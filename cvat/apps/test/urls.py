# Copyright (C) 2026 Muhammad Saeed
#
# SPDX-License-Identifier: MIT

from django.urls import include, path
from rest_framework import routers

from cvat.apps.test import views

router = routers.DefaultRouter(trailing_slash=False)
router.register(
    "class-distribution",
    views.ClassDistributionViewSet,
    basename="class_distribution",
)

urlpatterns = [
    path("test/", include(router.urls)),
]
