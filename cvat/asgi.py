# Copyright (C) 2018-2022 Intel Corporation
#
# SPDX-License-Identifier: MIT

"""
ASGI config for CVAT project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/3.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application
from django.core.handlers.asgi import ASGIHandler

import cvat.utils.remote_debugger as debug

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cvat.settings.development")

# The HTTP application also loads the app registry, so it has to be built
# before anything imports a model. Channels routing does exactly that, which is
# why the imports below sit under this line rather than at the top of the file.
http_application = get_asgi_application()


if debug.is_debugging_enabled():

    class DebuggerApp(ASGIHandler):
        """
        Support for VS code debugger
        """

        def __init__(self) -> None:
            super().__init__()
            self.__debugger = debug.RemoteDebugger()

        async def handle(self, *args, **kwargs):
            self.__debugger.attach_current_thread()
            return await super().handle(*args, **kwargs)

    http_application = DebuggerApp()


# pylint: disable=wrong-import-position
from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from cvat.apps.test.routing import websocket_urlpatterns  # noqa: E402

# WebSocket connections reuse the session cookie that the browser already holds,
# so AuthMiddlewareStack is enough to populate scope["user"].
# AllowedHostsOriginValidator rejects cross-site handshakes, which the browser's
# same-origin policy does not do for WebSockets on its own.
application = ProtocolTypeRouter(
    {
        "http": http_application,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
