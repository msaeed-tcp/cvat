# Copyright (C) 2026 Muhammad Saeed
#
# SPDX-License-Identifier: MIT

import os

# Smallest interval between two recomputations pushed to one WebSocket client.
# Annotation editing produces bursts of database writes; without a debounce the
# server would recompute the aggregate for every single shape.
TEST_ANALYTICS_DEBOUNCE_SECONDS = float(os.getenv("CVAT_TEST_ANALYTICS_DEBOUNCE", 1.0))

# Smallest interval between two invalidation messages published by one worker
# process for one task. Protects Redis from bulk deletes, which emit one
# post_delete signal per row.
TEST_ANALYTICS_PUBLISH_THROTTLE_SECONDS = float(
    os.getenv("CVAT_TEST_ANALYTICS_PUBLISH_THROTTLE", 0.2)
)

# Application-level keepalive. Idle WebSocket connections are dropped by many
# reverse proxies after 60 s, so the server sends a frame well before that.
TEST_ANALYTICS_HEARTBEAT_SECONDS = float(os.getenv("CVAT_TEST_ANALYTICS_HEARTBEAT", 25.0))

# Upper bound on the number of frames expanded from a single track. Guards
# against a pathological task exhausting memory during interpolation.
TEST_ANALYTICS_MAX_TRACK_FRAMES = int(os.getenv("CVAT_TEST_ANALYTICS_MAX_TRACK_FRAMES", 1_000_000))
