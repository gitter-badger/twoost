# coding: utf-8

from __future__ import print_function, division, absolute_import

import os

import twisted
from twisted.internet import reactor
from twisted.application.service import Application
from twisted.internet import endpoints
from twisted.application import internet

from . import log, geninit
from .conf import settings
from ._misc import ignore_errors, subdict, mkdir_p

import logging
logger = logging.getLogger(__name__)


__all__ = [
    'attach_service',
    'build_dbs',
    'build_amqps',
    'build_web',
    'build_timer',
    'build_manhole',
    'build_rpc_proxies',
    'build_server',
    'build_memcache',
    'AppWorker',
]


# -- common

def attach_service(app, s):
    logger.info("attach service %s to application", s)
    s.setServiceParent(app)
    return s


def build_timer(app, step, callback, stop_on_error=False):
    if not stop_on_error:
        callback = ignore_errors(callback)
    return attach_service(app, internet.TimerService(step, callback))


# -- generic server & client

def build_server(app, factory, endpoint):
    logger.debug("serve %s on %s", factory, endpoint)
    ept = endpoints.serverFromString(reactor, endpoint)
    ss = internet.StreamServerEndpointService(ept, factory)
    return attach_service(app, ss)


class _StreamClientEndpointService(internet._VolatileDataService):

    _connection = None

    def __init__(self, client_factory, endpoint):
        self.client_factory = client_factory
        self.endpoint = self.endpoint

    def startService(self):
        internet._VolatileDataService.startService(self)
        self._connection = self._getConnection()

    def stopService(self):
        internet._VolatileDataService.stopService(self)
        if self._connection is not None:
            self._connection.disconnect()
            del self._connection

    def _getConnection(self):
        return self.endpoint.connect(self.client_factory)


def build_client(app, client_factory, endpoint):
    logger.debug("connect %s to %s", client_factory, endpoint)
    ept = endpoints.clientFromString(reactor, endpoint)
    ss = _StreamClientEndpointService(ept, client_factory)
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

    return attach_service(app, amqp.AMQPService(d))


def build_web(app, site_or_restree, prefix=None, endpoint=None, add_meta=True):
    from twoost import web
    logger.debug("build web service")
    endpoint = endpoint or settings.WEB_ENDPOINT
    site = web.buildSite(site_or_restree, prefix, add_meta=add_meta)
    return build_server(app, site, endpoint)


def build_rpc_proxies(app, active_proxies=None):
    from twoost import rpcproxy
    proxies = settings.RPC_PROXIES
    logger.debug("build rpc proxies")
    return attach_service(app, rpcproxy.RPCProxyService(subdict(proxies, active_proxies)))


def build_manhole(app, namespace=None):

    if not settings.DEBUG:
        logger.debug("don't create manhole server - production mode")
        return

    from twoost.manhole import AnonymousShellFactory
    from twisted.application.internet import UNIXServer

    socket_file = settings.MANHOLE_SOCKET
    mkdir_p(os.path.dirname(socket_file))

    namespace = dict(namespace or {})
    if not namespace:
        namespace.update({
            'twisted': twisted,
            'app': app,
            'settings': settings,
        })
    f = AnonymousShellFactory(namespace)

    logger.info("serve shell on %r socket", socket_file)

    # only '0600' mode allowed here!
    ss = UNIXServer(address=socket_file, factory=f, mode=0600, wantPID=1)

    return attach_service(app, ss)


def build_memcache(app, active_servers=None):
    from twoost import memcache
    servers = settings.MEMCACHE_SERVERS
    logger.debug("build memcache service, connections %s", servers)
    return attach_service(app, memcache.MemCacheService(subdict(servers, active_servers)))


# --- integration with 'geninit'

class AppWorker(geninit.Worker):

    log_dir = settings.LOG_DIR
    pid_dir = settings.PID_DIR

    def init_app(self, app, workerid):
        raise NotImplementedError

    def init_logging(self, workerid):
        log.setup_logging()

    def init_settings(self, workerid):
        # note: here we can't modify 'LOG_DIR' & 'PID_DIR'
        # appname used by `log`, `email` etc
        settings.add_config({
            'APPNAME': self.appname,
            'WORKERID': workerid,
        })

    def create_app(self, workerid):

        self.init_settings(workerid)
        self.init_logging(workerid)

        app = Application(workerid)
        self.init_app(app, workerid)
        return app
