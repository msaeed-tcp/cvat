# Copyright (C) 2026 Muhammad Saeed
#
# SPDX-License-Identifier: MIT

from django.apps import AppConfig


class TestAnalyticsConfig(AppConfig):
    """
    Application config for the evaluation app.

    The app is intentionally named ``test`` (as required by the task
    specification). Its label is ``test_analytics`` so that it never collides
    with Django's own test tooling or with a future core app.
    """

    name = "cvat.apps.test"
    label = "test_analytics"
    verbose_name = "Class distribution analytics"

    def ready(self) -> None:
        from django.conf import settings

        from . import default_settings

        for key in dir(default_settings):
            if key.isupper() and not hasattr(settings, key):
                setattr(settings, key, getattr(default_settings, key))

        # Registers the annotation-change listeners that feed the WebSocket layer.
        from . import signals  # noqa: F401  pylint: disable=unused-import
