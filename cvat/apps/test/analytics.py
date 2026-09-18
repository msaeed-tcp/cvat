# Copyright (C) 2026 Muhammad Saeed
#
# SPDX-License-Identifier: MIT

"""
Class-wise image statistics for a CVAT task.

The aggregate answers one question: *for every label of a task, on how many
distinct images does that label appear?* CVAT stores an annotation in one of
three shapes, and all three have to be folded into the same answer:

``LabeledImage``
    A tag attached to one frame.
``LabeledShape``
    A box, polygon, mask and so on, attached to one frame.
``LabeledTrack``
    An object that spans a frame range. The database holds only the keyframes
    (``TrackedShape``); every frame between two keyframes is interpolated at
    read time and still counts as an appearance.

Skeleton elements (rows with a non-null ``parent_id``) are deliberately
excluded: they belong to their parent annotation and would double-count the
image.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from django.conf import settings
from django.db.models import Q

from cvat.apps.engine.models import (
    Job,
    LabeledImage,
    LabeledShape,
    LabeledTrack,
    Task,
    TrackedShape,
)


@dataclass
class ClassStatistics:
    """Per-label counters for one task."""

    label_id: int
    name: str
    color: str
    type: str
    image_count: int = 0
    shape_count: int = 0
    tag_count: int = 0
    track_count: int = 0

    @property
    def annotation_count(self) -> int:
        return self.shape_count + self.tag_count + self.track_count

    def as_dict(self) -> dict:
        return {
            "label_id": self.label_id,
            "name": self.name,
            "color": self.color,
            "type": self.type,
            "image_count": self.image_count,
            "annotation_count": self.annotation_count,
            "shape_count": self.shape_count,
            "tag_count": self.tag_count,
            "track_count": self.track_count,
        }


class ClassDistributionCalculator:
    """
    Builds the class-wise image count for a task, optionally narrowed to a
    single job.

    The calculator issues four read-only queries and does the set arithmetic in
    Python. Counting distinct frames per label cannot be done in one SQL
    aggregate because the frames come from three different tables, and a frame
    holding both a tag and a box of the same label must be counted once.
    """

    def __init__(self, task: Task, *, job_id: int | None = None) -> None:
        self._task = task
        self._job_id = job_id
        self._max_track_frames = settings.TEST_ANALYTICS_MAX_TRACK_FRAMES

    # -- public API ------------------------------------------------------

    def compute(self) -> dict:
        labels = {
            label.id: ClassStatistics(
                label_id=label.id,
                name=label.name,
                color=label.color,
                type=label.type,
            )
            for label in self._task.get_labels()
        }

        frames_by_label: dict[int, set[int]] = defaultdict(set)

        self._collect_tags(labels, frames_by_label)
        self._collect_shapes(labels, frames_by_label)
        self._collect_tracks(labels, frames_by_label)

        annotated_frames: set[int] = set()
        for label_id, frames in frames_by_label.items():
            annotated_frames |= frames
            if label_id in labels:
                labels[label_id].image_count = len(frames)

        rows = sorted(
            (row.as_dict() for row in labels.values()),
            key=lambda row: (-row["image_count"], row["name"]),
        )

        return {
            "task_id": self._task.id,
            "task_name": self._task.name,
            "job_id": self._job_id,
            "total_frames": self._total_frames(),
            "annotated_frames": len(annotated_frames),
            "total_annotations": sum(row["annotation_count"] for row in rows),
            "classes": rows,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # -- collectors ------------------------------------------------------

    def _scope(self, prefix: str) -> Q:
        """Restrict a queryset to the task, or to one job inside the task."""
        if self._job_id is not None:
            return Q(**{f"{prefix}_id": self._job_id})
        return Q(**{f"{prefix}__segment__task_id": self._task.id})

    def _collect_tags(
        self, labels: dict[int, ClassStatistics], frames_by_label: dict[int, set[int]]
    ) -> None:
        rows = LabeledImage.objects.filter(self._scope("job")).values_list("label_id", "frame")
        for label_id, frame in rows.iterator():
            frames_by_label[label_id].add(frame)
            if label_id in labels:
                labels[label_id].tag_count += 1

    def _collect_shapes(
        self, labels: dict[int, ClassStatistics], frames_by_label: dict[int, set[int]]
    ) -> None:
        rows = LabeledShape.objects.filter(self._scope("job"), parent__isnull=True).values_list(
            "label_id", "frame"
        )
        for label_id, frame in rows.iterator():
            frames_by_label[label_id].add(frame)
            if label_id in labels:
                labels[label_id].shape_count += 1

    def _collect_tracks(
        self, labels: dict[int, ClassStatistics], frames_by_label: dict[int, set[int]]
    ) -> None:
        tracks = list(
            LabeledTrack.objects.filter(self._scope("job"), parent__isnull=True).values_list(
                "id", "label_id", "job_id"
            )
        )
        if not tracks:
            return

        for _, label_id, _ in tracks:
            if label_id in labels:
                labels[label_id].track_count += 1

        stop_frames = self._segment_stop_frames()

        keyframes: dict[int, list[tuple[int, bool]]] = defaultdict(list)
        shape_rows = (
            TrackedShape.objects.filter(track_id__in=[track[0] for track in tracks])
            .values_list("track_id", "frame", "outside")
            .order_by("track_id", "frame")
        )
        for track_id, frame, outside in shape_rows.iterator():
            keyframes[track_id].append((frame, outside))

        budget = self._max_track_frames
        for track_id, label_id, job_id in tracks:
            stop_frame = stop_frames.get(job_id, 0)
            for frame in self._expand_track(keyframes.get(track_id, ()), stop_frame):
                budget -= 1
                if budget < 0:
                    # Hard stop. The numbers reported so far stay valid lower
                    # bounds; the guard exists so one malformed task cannot
                    # take the process down.
                    return
                frames_by_label[label_id].add(frame)

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _expand_track(keyframes, stop_frame: int):
        """
        Turn a track's keyframes into the frames on which the object is visible.

        A track becomes visible on a keyframe with ``outside=False`` and stays
        visible - through interpolation - until the next keyframe that marks it
        ``outside``, or until the end of the job segment.
        """
        visible_from: int | None = None

        for frame, outside in keyframes:
            if outside:
                if visible_from is not None:
                    yield from range(visible_from, frame)
                    visible_from = None
            elif visible_from is None:
                visible_from = frame

        if visible_from is not None:
            yield from range(visible_from, stop_frame + 1)

    def _segment_stop_frames(self) -> dict[int, int]:
        jobs = Job.objects.filter(segment__task_id=self._task.id)
        if self._job_id is not None:
            jobs = jobs.filter(id=self._job_id)
        return dict(jobs.values_list("id", "segment__stop_frame"))

    def _total_frames(self) -> int:
        if self._job_id is not None:
            stop_frames = self._segment_stop_frames()
            job = Job.objects.filter(id=self._job_id).values("segment__start_frame").first()
            if not job:
                return 0
            return stop_frames.get(self._job_id, 0) - job["segment__start_frame"] + 1

        data = self._task.data
        return data.size if data else 0


def collect_class_distribution(task: Task, *, job_id: int | None = None) -> dict:
    """Convenience wrapper used by the REST view and the WebSocket consumer."""
    return ClassDistributionCalculator(task, job_id=job_id).compute()
