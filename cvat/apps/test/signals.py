# Copyright (C) 2026 Muhammad Saeed
#
# SPDX-License-Identifier: MIT

"""
Change detection for annotation data.

CVAT writes annotations with ``bulk_create``, which does not emit ``post_save``.
Relying on the annotation models alone would therefore miss the main editing
path. What every path does have in common is ``JobAnnotation._set_updated_date``,
which calls ``Job.touch()`` and so does emit ``post_save`` on ``Job``. That is
the primary trigger here.

The model-level receivers stay as a safety net for the paths that write rows one
at a time (the admin site, management commands, direct ORM use in tests).
"""

from __future__ import annotations

from functools import lru_cache

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from cvat.apps.engine.models import Job, LabeledImage, LabeledShape, LabeledTrack

from .broadcast import publish_task_changed


@lru_cache(maxsize=2048)
def _task_id_of_job(job_id: int) -> int | None:
    """A job never moves between tasks, so this mapping is safe to cache."""
    return Job.objects.filter(id=job_id).values_list("segment__task_id", flat=True).first()


@receiver(post_save, sender=Job, dispatch_uid="test_analytics.job_saved")
def _on_job_saved(sender, instance: Job, **kwargs) -> None:
    publish_task_changed(_task_id_of_job(instance.id))


@receiver(post_delete, sender=Job, dispatch_uid="test_analytics.job_deleted")
def _on_job_deleted(sender, instance: Job, **kwargs) -> None:
    task_id = _task_id_of_job(instance.id)
    _task_id_of_job.cache_clear()
    publish_task_changed(task_id)


def _on_annotation_changed(sender, instance, **kwargs) -> None:
    # Every model connected below carries job_id directly, so this receiver
    # issues no query of its own beyond the cached job -> task lookup.
    # TrackedShape is deliberately not connected: it has no job_id, and any
    # change to a keyframe already touches the job through JobAnnotation.
    job_id = getattr(instance, "job_id", None)
    publish_task_changed(_task_id_of_job(job_id) if job_id else None)


for model in (LabeledImage, LabeledShape, LabeledTrack):
    post_save.connect(
        _on_annotation_changed,
        sender=model,
        dispatch_uid=f"test_analytics.{model.__name__}.saved",
    )
    post_delete.connect(
        _on_annotation_changed,
        sender=model,
        dispatch_uid=f"test_analytics.{model.__name__}.deleted",
    )
