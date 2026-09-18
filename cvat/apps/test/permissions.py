# Copyright (C) 2026 Muhammad Saeed
#
# SPDX-License-Identifier: MIT

"""
Access control for the class-distribution endpoints.

The app introduces no resource of its own: it only reports numbers derived from
a task the caller already has access to. So instead of writing a new Rego
policy, both the REST view and the WebSocket consumer reuse CVAT's existing
``tasks/view`` decision from Open Policy Agent. One source of truth, and a user
who loses access to a task loses access to its analytics at the same moment.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.exceptions import NotFound, PermissionDenied

from cvat.apps.engine.models import Task
from cvat.apps.engine.permissions import TaskPermission
from cvat.apps.organizations.models import Membership

TASK_SELECT_RELATED = ("organization", "data", "project")


def get_task_or_404(task_id: int) -> Task:
    try:
        return Task.objects.select_related(*TASK_SELECT_RELATED).get(id=task_id)
    except Task.DoesNotExist:
        raise NotFound(f"Task {task_id} does not exist")


def get_viewable_task(request, task_id: int) -> Task:
    """Resolve a task for an HTTP request, enforcing ``tasks/view``."""
    task = get_task_or_404(task_id)

    permission = TaskPermission.create_scope_view(request, task)
    if not permission.check_access().allow:
        raise PermissionDenied("You do not have permission to view this task")

    return task


def build_iam_context(user, task: Task) -> dict:
    """
    Assemble the OPA input that ``ContextMiddleware`` would normally build.

    A WebSocket connection never passes through Django's middleware chain, so
    the organization and privilege parts of the policy input have to be
    reconstructed here. The organization is taken from the task itself rather
    than from a query parameter, which is stricter than the HTTP path: a client
    cannot widen its own scope by choosing a different ``X-Organization``.
    """
    role_priority = {role: priority for priority, role in enumerate(settings.IAM_ROLES)}
    groups = sorted(
        user.groups.filter(name__in=list(role_priority.keys())),
        key=lambda group: role_priority[group.name],
    )
    privilege = groups[0].name if groups else None

    organization = task.organization
    membership = (
        Membership.objects.filter(organization=organization, user=user, is_active=True).first()
        if organization
        else None
    )

    return {
        "user_id": user.id,
        "group_name": privilege,
        "org_specified": organization is not None,
        "org_id": getattr(organization, "id", None),
        "org_slug": getattr(organization, "slug", None),
        "org_owner_id": organization.owner_id if organization else None,
        "org_role": getattr(membership, "role", None),
    }


def user_can_view_task(user, task: Task) -> bool:
    """Synchronous permission check used by the WebSocket consumer."""
    if user is None or not user.is_authenticated:
        return False

    permission = TaskPermission(
        **build_iam_context(user, task),
        obj=task,
        scope=TaskPermission.Scopes.VIEW,
    )
    return permission.check_access().allow
