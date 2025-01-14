# -*- coding: utf-8 -*-
#########################################################################
#
# Copyright (C) 2017 OSGeo
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################

import logging
import pytz
import hashlib
import types

from datetime import datetime
from django.conf import settings
from geonode.monitoring.models import Service, Host
from geonode.monitoring.utils import MonitoringHandler
from django.http import HttpResponse


FILTER_URLS = (settings.MEDIA_URL,
               settings.STATIC_URL,
               '/gs/',
               '/api/',
               '/security/',
               '/lang.js',
               '/jsi18n/',
               '/h_keywords_api',
               '/admin/jsi18n/',)


class MonitoringMiddleware(object):

    def __init__(self):
        self.setup_logging()

    def setup_logging(self):
        self.log = logging.getLogger('{}.catcher'.format(__name__))
        self.log.propagate = False
        self.log.setLevel(logging.DEBUG)
        self.log.handlers = []
        self.service = self.get_service()
        self.handler = MonitoringHandler(self.service)
        self.handler.setLevel(logging.DEBUG)
        self.log.addHandler(self.handler)

    def get_service(self):
        hname = getattr(settings, 'MONITORING_HOST_NAME', None) or 'localhost'
        sname = getattr(settings, 'MONITORING_SERVICE_NAME', None) or 'geonode'
        try:
            host = Host.objects.get(name=hname)
        except Host.DoesNotExist:
            host = None
        if host:
            try:
                service = Service.objects.get(host=host, name=sname)
                return service
            except Service.DoesNotExist:
                service = None

    @staticmethod
    def should_process(request):
        current = request.path

        for skip_url in settings.MONITORING_SKIP_PATHS:
            if isinstance(skip_url, types.StringTypes):
                if current.startswith(skip_url):
                    return False
            elif hasattr(skip_url, 'match'):
                if skip_url.match(current):
                    return False
        return True

    @staticmethod
    def register_event(request, event_type, resource_type, resource_name):
        m = getattr(request, '_monitoring', None)
        if not m:
            return
        events = m['events']
        events.append((event_type, resource_type, resource_name,))

    def register_request(self, request, response):
        if self.service:
            self.log.debug('request', extra={'request': request, 'response': response})

    def register_exception(self, request, exception):
        if self.service:
            response = HttpResponse('')
            self.log.debug('request', exc_info=exception, extra={'request': request, 'response': response})

    def process_view(self, request, view_func, view_args, view_kwargs):
        m = request.resolver_match
        if m.namespace in ('admin', 'monitoring',):
            request._monitoring = None
            del request._monitoring

    def process_request(self, request):
        if not self.should_process(request):
            return
        utc = pytz.utc
        now = datetime.utcnow().replace(tzinfo=utc)

        # enforce session create
        if not request.session.session_key:
            request.session.create()

        meta = {'started': now,
                'resources': {},
                'events': [],
                'finished': None,
                }

        if settings.USER_ANALYTICS_ENABLED:
            meta.update({
                'user_identifier': hashlib.sha256(request.session.session_key or '').hexdigest(),
                'user_username': request.user.username if request.user.is_authenticated() else None
            })

        request._monitoring = meta

        def register_event(event_type, resource_type, name):
            self.register_event(request, event_type, resource_type, name)

        request.register_event = register_event

    def process_response(self, request, response):
        m = getattr(request, '_monitoring', None)
        if m is None:
            return response
        utc = pytz.utc
        now = datetime.utcnow().replace(tzinfo=utc)
        m['finished'] = now
        self.register_request(request, response)
        return response

    def process_exception(self, request, exception):
        m = getattr(request, '_monitoring', None)
        if m is None:
            return
        utc = pytz.utc
        now = datetime.utcnow().replace(tzinfo=utc)
        m['finished'] = now
        self.register_exception(request, exception)
