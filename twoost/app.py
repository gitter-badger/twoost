# coding: utf-8

from __future__ import print_function, division, absolute_import

import os
import stat

from twisted.internet import endpoints, defer, reactor, task
from twisted.application import internet, service

from twoost import log, geninit, _misc
from twoost.conf import settings
from twoost._misc import subdict, mkdir_p, overwritable_property

import logging
logger = logging.getLogger(__name__)


__all__ = [
    'attach_service',
    'react_app',
    'build_timer',
    'build_dbs',
    'build_web',
    'build_amqps',
    'build_rpcps',
    'build_memcache',
    'build_manhole',
    'build_health',
    'build_server',
    'build_client',
    'AppWorker',
]


# -- common

def attach_service(parent, child, name=None):
    logger.info("attach service %s to parent %s", child, parent)
    if name:
        child.setName(name)
    child.setServiceParent(parent)
    return child


def react_app(app, main, argv=()):

    @defer.inlineCallbacks
    def appless_main(reactor):
        yield defer.maybeDeferred(service.IService(app).startService)
        try:
            yield defer.maybeDeferred(main, *argv)
        finally:
            yield defer.maybeDeferred(service.IService(app).stopService)

    task.react(appless_main)


def build_timer(app, when, callback, name=None):

    if isinstance(when, (list, tuple)):
        assert len(when) == 5
        when = " ".join(map(str, when))

    try:
        interval = float(when)
    except (TypeError, ValueError):
        interval = None

    from twoost import cron
    logger.debug("build timer %r, callback %r", when, callback)

    if interval is not None:
        return attach_service(app, cron.IntervalTimerService(interval, callback), name)
    else:
        return attach_service(app, cron.CrontabTimerService(when, callback), name)


# -- generic server & client

def build_server(app, factory, endpoint, name=None):
    logger.debug("serve %s on %s", factory, endpoint)
    ept = endpoints.serverFromString(reactor, endpoint)
    ss = internet.StreamServerEndpointService(ept, factory)
    return attach_service(app, ss, name)


def build_client(app, client_factory, endpoint, params=None):
    from twoost import pclient
    logger.debug("connect %s to %s", client_factory, endpoint)
    ept = endpoints.clientFromString(reactor, endpoint)
    ss = pclient.PersistentClientService(ept, client_factory, **(params or {}))
    return attach_service(app, ss)


# -- twoost components

def build_dbs(app, active_databases=None):
    from twoost import dbpool
    logger.debug("build dbpool service")
    dbs = dbpool.DatabaseService(subdict(settings.DATABASES, active_databases))
    return attach_service(app, dbs)


def build_amqps(app, active_connections=None):

    from twoost import amqp
    connections = settings.AMQP_CONNECTIONS
    schemas = settings.AMQP_SCHEMAS
    logger.debug("build amqps service, connections %s", active_connections)

    d = subdict(connections, active_connections)
    for conn, params in d.items():
        d[conn] = dict(params)
        if conn in schemas:
            d[conn]['schema'] = schemas[conn]

    return attach_service(app, amqp.AMQPCollectionService(d))


def build_web(app, site, prefix=None, endpoint=None):
    from twoost import web
    logger.debug("build web service")
    endpoint = endpoint or settings.WEB_ENDPOINT
    if endpoint.startswith("unix:"):
        filename = endpoint[5:]
        mkdir_p(os.path.dirname(filename))
    site = web.buildSite(site, prefix)
    return build_server(app, site, endpoint, 'web')


def build_rpcps(app, active_proxies=None):
    from twoost import rpcproxy
    proxies = subdict(settings.RPC_PROXIES, active_proxies)
    logger.debug("build rpc proxies")
    return attach_service(app, rpcproxy.RPCProxiesCollectionService(proxies))


def build_manhole(app, namespace=None, add_defaults=True):

    if not settings.DEBUG:
        logger.debug("don't create manhole server - production mode")
        return

    import twisted
    import twoost

    from twoost.manhole import ManholeService, ServiceScanner

    workerid = app.workerid
    socket_file = os.path.join(settings.MANHOLE_SOCKET_DIR, workerid)
    mkdir_p(os.path.dirname(socket_file))

    namespace = dict(namespace or {})
    if add_defaults:
        namespace.update({
            'app': app,
            'ss': ServiceScanner(app),
            'twoost': twoost,
            'twisted': twisted,
            'settings': settings,
            'workerid': workerid,
        })

    logger.info("serve shell on %r socket", socket_file)
    return attach_service(app, ManholeService(socket_file, namespace), "manhole")


def build_health(app):

    from twoost.health import HealthCheckService

    mode = settings.HEALTHCHECK_SOCKET_MODE
    workerid = app.workerid
    socket_file = os.path.join(settings.HEALTHCHECK_SOCKET_DIR, workerid)
    mkdir_p(os.path.dirname(socket_file))

    logger.debug("serve health checker on %r socket", socket_file)
    return attach_service(app, HealthCheckService(socket_file, app, mode=mode, wantPID=1))


def build_memcache(app, active_servers=None):
    from twoost import memcache
    servers = settings.MEMCACHE_SERVERS
    logger.debug("build memcache service, connections %s", servers)
    return attach_service(app, memcache.MemCacheCollectionService(subdict(servers, active_servers)))


# --- integration with 'geninit'

def _get_service(app, name):
    try:
        return service.IServiceCollection(app).getServiceNamed('manhole')
    except KeyError:
        return


class AppWorker(geninit.Worker):

    healthcheck_timeout = 20

    @overwritable_property
    def log_dir(self):
        return settings.LOG_DIR

    @overwritable_property
    def pid_dir(self):
        return settings.PID_DIR

    @overwritable_property
    def workers(self):
        return settings.WORKERS_COUNT.get(self.appname, 1)

    def init_logging(self):
        log.setup_logging(self.appname)

    def main(self, args=None):
        self.init_settings()
        return geninit.Worker.main(self, args)

    def create_app(self, workerid):
        app = service.Application(workerid)
        app.workerid = workerid
        self._preinit_app(app, workerid)
        self.init_app(app, workerid)
        self._postinit_app(app, workerid)
        return app

    def _preinit_app(self, app, workerid):
        self.init_settings()
        self.init_logging()

    def _postinit_app(self, app, workerid):
        self._maybe_build_manhole(app)
        self._maybe_build_health(app)

    def _maybe_build_health(self, app):
        if not _get_service(app, 'health'):
            build_health(app)

    def _maybe_build_manhole(self, app):
        if not _get_service(app, 'manhole'):
            build_manhole(app)

    def read_worker_health(self, workerid, timeout=10):
        from twoost.health import parseServicesHealth
        self.init_settings()
        sp = os.path.join(settings.HEALTHCHECK_SOCKET_DIR, workerid)
        body = _misc.slurp_unix_socket(sp, timeout=timeout)
        return parseServicesHealth(body)

    def run_worker_manhole(self, workerid, **kwargs):

        from twoost.conf import settings
        from twoost.manhole import exec_manhole_client

        self.init_settings()
        socket_file = os.path.join(settings.MANHOLE_SOCKET_DIR, workerid)

        if not os.path.exists(socket_file):
            self.log_info("socket file %s does not exists", socket_file)
            return False
        elif not stat.S_ISSOCK(os.stat(socket_file).st_mode):
            self.log_info("file %s is not an unix socket", socket_file)
            return False
        else:
            exec_manhole_client(socket_file)

    def init_settings(self):
        raise NotImplementedError

    def init_app(self, app, workerid):
        raise NotImplementedError
