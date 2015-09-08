# coding: utf8

from twisted.internet import defer
from twisted.web.client import getPage
from twisted.application.service import Service

import zope.interface

from twoost import health
from twoost.web import Resource
from twoost.conf import settings

import logging
logger = logging.getLogger(__name__)


class HealthResource(Resource):

    def __init__(self, app):
        self.app = app

    def render_GET(self):
        d = health.checkServicesHealth(self.app, timeout=10)
        return d.addCallback(health.formatServicesHealth)


@zope.interface.implementer(health.IHealthChecker)
class WebapiChecker(Service):

    name = "webchecker"

    @defer.inlineCallbacks
    def checkHealth(self):
        # check if at least one web worker is alive & show workerid
        workerid = yield getPage(settings.DEMOAPP_WEBAPI_SITE + "/workerid")
        defer.returnValue("worker %r" % workerid)
