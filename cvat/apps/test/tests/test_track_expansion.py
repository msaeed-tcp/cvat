# Copyright (C) 2026 Muhammad Saeed
#
# SPDX-License-Identifier: MIT

"""
Unit tests for track interpolation.

These touch no database and no OPA server, so they run with:

    python manage.py test cvat.apps.test.tests.test_track_expansion
"""

from django.test import SimpleTestCase

from cvat.apps.test.analytics import ClassDistributionCalculator

expand = ClassDistributionCalculator._expand_track


class TrackExpansionTest(SimpleTestCase):
    def test_no_keyframes_yields_nothing(self):
        self.assertEqual(list(expand([], stop_frame=10)), [])

    def test_single_visible_keyframe_runs_to_end_of_segment(self):
        self.assertEqual(list(expand([(3, False)], stop_frame=6)), [3, 4, 5, 6])

    def test_outside_keyframe_closes_the_interval(self):
        self.assertEqual(list(expand([(2, False), (5, True)], stop_frame=9)), [2, 3, 4])

    def test_interpolated_frames_between_two_visible_keyframes_count(self):
        frames = list(expand([(0, False), (4, False), (6, True)], stop_frame=20))
        self.assertEqual(frames, [0, 1, 2, 3, 4, 5])

    def test_track_can_reappear_after_being_outside(self):
        frames = list(expand([(0, False), (2, True), (5, False), (7, True)], stop_frame=20))
        self.assertEqual(frames, [0, 1, 5, 6])

    def test_track_starting_outside_contributes_nothing_until_it_appears(self):
        frames = list(expand([(0, True), (3, False)], stop_frame=4))
        self.assertEqual(frames, [3, 4])
