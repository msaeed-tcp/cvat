# Copyright (C) 2026 Muhammad Saeed
#
# SPDX-License-Identifier: MIT

from django.urls import re_path

from .consumers import ClassDistributionConsumer

websocket_urlpatterns = [
    re_path(
        r"^ws/test/class-distribution/(?P<task_id>\d+)/?$",
        ClassDistributionConsumer.as_asgi(),
    ),
]
