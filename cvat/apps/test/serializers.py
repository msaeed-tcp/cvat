# Copyright (C) 2026 Muhammad Saeed
#
# SPDX-License-Identifier: MIT

"""
Serializers used for response validation and for the generated OpenAPI schema.

The payload is computed, not stored, so these are plain ``Serializer`` classes
rather than ``ModelSerializer`` ones.
"""

from rest_framework import serializers


class ClassStatisticsSerializer(serializers.Serializer):
    label_id = serializers.IntegerField()
    name = serializers.CharField()
    color = serializers.CharField(allow_blank=True)
    type = serializers.CharField(allow_blank=True)
    image_count = serializers.IntegerField(help_text="Distinct frames containing this label")
    annotation_count = serializers.IntegerField(help_text="Tags + shapes + tracks")
    shape_count = serializers.IntegerField()
    tag_count = serializers.IntegerField()
    track_count = serializers.IntegerField()


class ClassDistributionSerializer(serializers.Serializer):
    task_id = serializers.IntegerField()
    task_name = serializers.CharField()
    job_id = serializers.IntegerField(allow_null=True)
    total_frames = serializers.IntegerField()
    annotated_frames = serializers.IntegerField()
    total_annotations = serializers.IntegerField()
    classes = ClassStatisticsSerializer(many=True)
    generated_at = serializers.DateTimeField()


class ClassDistributionQuerySerializer(serializers.Serializer):
    task_id = serializers.IntegerField(min_value=1)
    job_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
