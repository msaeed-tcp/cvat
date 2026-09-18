# Copyright (C) 2026 Muhammad Saeed
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .analytics import collect_class_distribution
from .permissions import get_viewable_task
from .serializers import ClassDistributionQuerySerializer, ClassDistributionSerializer


@extend_schema(tags=["test"])
class ClassDistributionViewSet(viewsets.ViewSet):
    """
    Read-only, computed-on-demand class statistics for a task.

    Permission handling is explicit here. The default ``PolicyEnforcer`` maps a
    viewset to its own Rego policy; this app has no policy of its own and
    delegates to ``tasks/view`` instead, so the enforcer is replaced by
    ``IsAuthenticated`` plus a check inside ``get_viewable_task``.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ClassDistributionSerializer
    lookup_value_regex = r"\d+"

    @extend_schema(
        summary="Class-wise image counts for a task",
        parameters=[
            OpenApiParameter(
                "task_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Task to aggregate",
            ),
            OpenApiParameter(
                "job_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Narrow the aggregate to a single job of that task",
            ),
        ],
        responses={"200": ClassDistributionSerializer},
    )
    def list(self, request):
        query = ClassDistributionQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        return self._respond(
            request,
            task_id=query.validated_data["task_id"],
            job_id=query.validated_data.get("job_id"),
        )

    @extend_schema(
        summary="Class-wise image counts for a task, addressed by path",
        parameters=[
            OpenApiParameter(
                "job_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Narrow the aggregate to a single job of that task",
            ),
        ],
        responses={
            "200": ClassDistributionSerializer,
            "404": OpenApiResponse(description="The task does not exist"),
        },
    )
    def retrieve(self, request, pk=None):
        job_id = request.query_params.get("job_id")
        if job_id is not None:
            try:
                job_id = int(job_id)
            except (TypeError, ValueError):
                raise ValidationError({"job_id": "Must be an integer"})

        return self._respond(request, task_id=int(pk), job_id=job_id)

    # -- internals -------------------------------------------------------

    def _respond(self, request, *, task_id: int, job_id: int | None):
        task = get_viewable_task(request, task_id)

        if job_id is not None and not task.segment_set.filter(job__id=job_id).exists():
            raise ValidationError({"job_id": f"Job {job_id} does not belong to task {task_id}"})

        payload = collect_class_distribution(task, job_id=job_id)
        return Response(payload, status=status.HTTP_200_OK)
