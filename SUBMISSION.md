# Real-Time Class Distribution Analytics for CVAT

Evaluation task submission - Full Stack Web Developer, XIS.AI

Branch: `dev-test01`
Base: `cvat-ai/cvat` (version 2.76.1)

---

## 1. What Was Built

A new Django app, `cvat/apps/test`, answers one question for any CVAT task: for
every label, on how many distinct images does that label appear? A new page in
`cvat-ui` draws that answer as a ranked horizontal bar chart, and a WebSocket
keeps the chart in step with the annotations as they are drawn.

| Layer | Location |
| --- | --- |
| Django app | `cvat/apps/test/` |
| REST API | `GET /api/test/class-distribution/{task_id}` |
| WebSocket | `ws://<host>/ws/test/class-distribution/{task_id}/` |
| UI page | `cvat-ui/src/components/class-distribution/` |
| Route | `/tasks/:tid/class-distribution` |

---

## 2. Understanding of CVAT Architecture

### 2.1 Process Layout

CVAT runs as a set of containers coordinated by `docker-compose.yml`. Six of
them matter here:

- `cvat_server` runs Django behind `uvicorn`, which supervisord starts as an
  FCGI program on a Unix socket, with nginx in front of it
- `cvat_ui` serves the compiled React bundle; nginx routes `/api` and every
  other backend path to the same uvicorn socket
- `cvat_db` is PostgreSQL and holds every annotation row
- `cvat_redis_inmem` backs the RQ queues on logical database 0 and the Django
  cache on database 1
- `cvat_opa` evaluates the Rego policies that decide who may see what
- `cvat_worker_*` containers run the long jobs, such as import, export, and
  quality reports

The important consequence: annotations are written by several processes, and
none of them is the process that holds a browser's WebSocket connection. Any
real-time design has to cross a process boundary.

### 2.2 Annotation Data Model

`cvat/apps/engine/models.py` stores an annotation in one of three tables, all of
which descend from an abstract `Annotation` model carrying `job` and `label`:

- `LabeledImage` is a tag on one frame
- `LabeledShape` is a box, polygon, mask, or similar on one frame
- `LabeledTrack` spans a frame range and stores only its keyframes, in
  `TrackedShape`

A task owns segments, a segment owns a job, and a job owns annotations, so the
path from an annotation row to its task is `job__segment__task_id`. Labels hang
off the task, or off the project when the task belongs to one. Skeleton
elements are ordinary rows with a non-null `parent_id`.

### 2.3 Permissions

Every CVAT viewset declares an `iam_permission_class`. The `PolicyEnforcer`
permission builds a payload from the request, the organization, and the target
object, then asks Open Policy Agent for a decision. The app built here
introduces no resource of its own, so it reuses the existing `tasks/view`
decision instead of shipping another Rego policy.

---

## 3. Data Flow

### 3.1 Read Path

1. The page mounts and calls `GET /api/test/class-distribution/{task_id}`
2. `ClassDistributionViewSet` resolves the task and runs the OPA `tasks/view`
   check through `TaskPermission.create_scope_view`
3. `ClassDistributionCalculator` issues four read-only queries: labels, tags,
   shapes, and tracks with their keyframes
4. Frames are folded into one set per label, so a frame holding both a tag and a
   box of the same class counts once
5. The response renders and the chart paints

### 3.2 Write Path

1. An annotator draws a shape; the browser sends `PATCH /api/jobs/{id}/annotations`
2. `JobAnnotation` writes the rows with `bulk_create`, then calls
   `_set_updated_date`, which calls `Job.touch()`
3. `Job.touch()` saves the job, which emits `post_save`
4. The receiver in `cvat/apps/test/signals.py` publishes one small message to
   the Redis channel layer: a task id, nothing more
5. Every consumer subscribed to that task's group wakes up, waits out the
   debounce window, recomputes, and pushes a fresh snapshot
6. The chart re-renders

Publishing the id rather than the payload is deliberate. The aggregate is
computed once per connected viewer instead of once per write, and a task nobody
is watching costs a single Redis command.

---

## 4. API Design

### 4.1 Endpoints

```
GET /api/test/class-distribution?task_id=12[&job_id=34]
GET /api/test/class-distribution/12[?job_id=34]
```

Both forms return the same body. The path form suits a page that already knows
its task; the query form suits tooling that builds URLs from parameters.

### 4.2 Response

```json
{
  "task_id": 12,
  "task_name": "Street scenes",
  "job_id": null,
  "total_frames": 500,
  "annotated_frames": 312,
  "total_annotations": 1487,
  "classes": [
    {
      "label_id": 3,
      "name": "car",
      "color": "#ff6037",
      "type": "rectangle",
      "image_count": 210,
      "annotation_count": 812,
      "shape_count": 640,
      "tag_count": 0,
      "track_count": 172
    }
  ],
  "generated_at": "2026-09-19T09:41:22.104Z"
}
```

### 4.3 Design Decisions

- The resource is computed, not stored. No model and no migration ship with the
  app, so there is nothing to keep in sync and nothing to invalidate
- `image_count` and `annotation_count` are reported separately because they
  answer different questions. Dataset balance depends on how many images carry a
  class; labeling effort depends on how many objects were drawn
- The breakdown into `shape_count`, `tag_count`, and `track_count` stays in the
  payload so a reviewer can see where a number came from
- The endpoint follows CVAT conventions: a `DefaultRouter` with
  `trailing_slash=False`, the `application/vnd.cvat+json` renderer, and a
  `drf-spectacular` schema, so it appears in the generated OpenAPI document
- Errors reuse DRF exceptions, which CVAT's exception handler already formats:
  404 for a missing task, 403 for a task the caller may not view, and 400 for a
  job that belongs to a different task

### 4.4 Counting Rules

The aggregate has to be defensible, so the rules are explicit:

- A frame counts once per label no matter how many objects of that label it holds
- Skeleton elements are excluded, since the parent annotation already counts the frame
- A track counts every frame on which it is visible, including the interpolated
  frames between two keyframes, because those frames do show the object
- A track becomes visible on a keyframe marked `outside=False` and stops at the
  next keyframe marked `outside=True`, or at the end of the job segment

`ClassDistributionCalculator._expand_track` implements the last two rules and is
covered by the unit tests in `cvat/apps/test/tests/test_track_expansion.py`.

---

## 5. WebSocket Implementation

### 5.1 Stack

Django Channels 4.2 provides the ASGI routing and the consumer base class.
`channels-redis` provides the channel layer, pointed at the Redis instance CVAT
already runs, on logical database 2. Databases 0 and 1 are taken by RQ and the
Django cache.

Three pieces of existing infrastructure made this cheap:

- `cvat_server` already speaks ASGI through uvicorn, and `uvicorn[standard]`
  already bundles the `websockets` library
- `cvat/nginx.conf` already sets the `Upgrade` and `Connection` headers, so the
  handshake passes through the proxy untouched
- Redis is already deployed, monitored, and backed up

`cvat/asgi.py` now returns a `ProtocolTypeRouter`. HTTP keeps the previous
application, including the VS Code debugger wrapper. WebSocket traffic passes
through `AllowedHostsOriginValidator` and `AuthMiddlewareStack` before reaching
the router.

### 5.2 Protocol

Server frames:

| Type | Meaning |
| --- | --- |
| `snapshot` | Full payload, byte-identical to the REST response |
| `heartbeat` | Application-level keepalive, every 25 seconds |
| `pong` | Answer to a client `ping` |
| `error` | A `code` and a human-readable `detail` |

Client frames are `ping` and `refresh`.

Close codes carry the reason: 4400 for a malformed request, 4401 for an
unauthenticated session, 4403 for a task the caller may not view, and 4404 for a
task that does not exist. The client treats all four as final and stops retrying.

### 5.3 Authentication

The browser attaches the CVAT session cookie to a same-origin WebSocket
handshake on its own, so no token appears in the URL and no credential reaches
an access log. `AuthMiddlewareStack` turns that cookie into `scope["user"]`.

A WebSocket connection never passes through Django's middleware chain, so the
organization and privilege parts of the OPA payload are rebuilt in
`permissions.build_iam_context`. That function takes the organization from the
task itself rather than from a request header, which is stricter than the HTTP
path: a client cannot widen its own scope by choosing a different organization.

---

## 6. Stability

### 6.1 Server Side

- Every `group_send` is wrapped. A broken analytics stream must never roll back
  an annotator's work
- A failed recomputation sends an `error` frame and leaves the socket open, so
  one bad query does not end the session
- The heartbeat runs every 25 seconds, comfortably inside the 60-second idle
  timeout most reverse proxies apply
- `disconnect` cancels the heartbeat and refresh tasks and removes the channel
  from its group, so a closed tab leaves nothing behind
- Track expansion stops at a configurable frame budget, so one malformed task
  cannot exhaust memory

### 6.2 Client Side

- Reconnection uses exponential backoff from 1 second to 30 seconds, with
  jitter, so many open tabs do not reconnect in lockstep after an outage
- A silence watchdog closes the socket when nothing arrives for 60 seconds,
  which catches the half-open connection a laptop leaves behind after sleep
- After three failed attempts the page falls back to polling the REST endpoint
  every 15 seconds and keeps retrying the socket in the background
- The connection badge always states the truth: Live, Reconnecting, Refreshing
  every 15s, or Updates stopped
- Returning to a hidden tab triggers an immediate refetch and reconnect

### 6.3 UI Responsiveness

- The page paints from REST first, then the socket takes over, so the chart
  never waits on a handshake
- Chart and table components are memoized, and animation is capped at 250 ms
- The table view presents the same numbers for screen readers and for copying
- Direct value labels appear only while they stay readable; past twelve classes
  the tooltip and the table carry the exact numbers

---

## 7. Challenges and Solutions

**CVAT writes annotations in bulk, and `bulk_create` emits no `post_save`.**
Connecting receivers to the annotation models alone would have missed the main
editing path entirely. Every write path does, however, end at
`JobAnnotation._set_updated_date`, which calls `Job.touch()` and therefore does
emit `post_save` on `Job`. That became the primary trigger, with model-level
receivers kept as a safety net for the paths that write one row at a time.

**A bulk delete emits one `post_delete` per row.** Clearing a job's annotations
would have produced thousands of Redis publishes. A per-process throttle in
`broadcast.py` collapses those into one message per task per 200 milliseconds.

**Drawing ten boxes produces ten invalidations in a second.** Recomputing on
each one would have wasted queries and flooded the socket. The consumer collapses
a burst into a single recomputation with a one-second debounce that still
guarantees a final snapshot after the last change.

**Counting distinct frames per label cannot be done in one SQL aggregate.** The
frames come from three tables, and a frame holding both a tag and a box of the
same label must count once. The calculator pulls distinct pairs from each table
and folds them into one set per label in Python, which is four queries rather
than a correlated subquery per label.

**Tracks store keyframes, not frames.** A naive count would have credited a
100-frame track with one image. `_expand_track` reconstructs the visible ranges
from the keyframes and their `outside` flags, matching what an annotator sees on
the canvas.

**A WebSocket has no Django middleware, so the OPA payload was incomplete.**
Rather than loosen the check, `build_iam_context` reconstructs the privilege and
organization fields from the user and the task, and the consumer calls the same
`TaskPermission` the REST view uses.

**Channels 4.3 requires `asgiref>=3.9`, and CVAT resolves `asgiref` to 3.8.1.**
Bumping a core dependency for a feature branch invites unrelated breakage, so the
pins landed on `channels==4.2.2` and `channels-redis==4.2.1`, the newest pair
that installs cleanly against CVAT's existing lock file.

**The webpack dev server proxies `/api` but not `/ws`.** The handshake failed in
development while working in Docker. The proxy rule now matches `/ws/test/` and
sets `ws: true`, deliberately narrow so it cannot swallow the dev server's own
hot-reload socket at `/ws`.

**Closing a WebSocket before accepting it hides the close code.** The browser
reports a bare handshake failure, leaving the client unable to tell "not allowed"
from "server down", and those need opposite retry behavior. The consumer accepts
first, sends an `error` frame, and then closes with a specific code.

---

## 8. Files Changed

New:

```
cvat/apps/test/{__init__,apps,analytics,broadcast,consumers,
                default_settings,permissions,routing,serializers,
                signals,urls,views}.py
cvat/apps/test/tests/test_track_expansion.py
cvat-ui/src/components/class-distribution/{api.ts,use-class-distribution.ts,
                class-distribution-page.tsx,class-distribution-chart.tsx,
                class-distribution-table.tsx,styles.scss,index.ts}
```

Modified:

```
cvat/asgi.py                                    ProtocolTypeRouter
cvat/urls.py                                    mounts the app's API
cvat/settings/base.py                           INSTALLED_APPS, ASGI_APPLICATION, CHANNEL_LAYERS
cvat/requirements/base.in, base.txt             channels, channels-redis
cvat-ui/src/components/cvat-app.tsx             route
cvat-ui/src/components/tasks-page/actions-menu-items.tsx   menu entry
cvat-ui/webpack.config.js                       dev-server WebSocket proxy
```

---

## 9. Running It Locally

```bash
git clone https://github.com/<your-account>/cvat.git
cd cvat
git checkout dev-test01

docker compose -f docker-compose.yml -f docker-compose.dev.yml build
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
docker exec -it cvat_server python3 manage.py createsuperuser
```

Open `http://localhost:8080`, create a task with a few labels, upload images,
and annotate. The page sits behind the task's action menu, under Class
distribution, or at `/tasks/<id>/class-distribution` directly.

To watch it update live, open the page in one browser tab and the annotation
view in another. Drawing a shape updates the chart within about a second.

Front-end development against the Docker backend:

```bash
yarn --frozen-lockfile
yarn run start:cvat-ui
```

Tests that need no database and no OPA server:

```bash
docker exec -it cvat_server python3 manage.py test cvat.apps.test.tests.test_track_expansion
```

After changing the API, regenerate the OpenAPI document so CI stays green:

```bash
docker exec -it cvat_server python3 manage.py spectacular --file cvat/schema.yml
```

---

## 10. Known Limits and Next Steps

- The aggregate is computed on every request. A task with hundreds of thousands
  of tracked shapes will feel it. The natural next step is a cached snapshot in
  Redis, invalidated by the same signal that already drives the socket
- Statistics cover tasks. Project-level and job-level rollups would reuse the
  same calculator with a wider scope
- The app reuses the `tasks/view` policy. A dedicated Rego rule would allow
  finer control, such as granting analytics to a reviewer who cannot open the
  annotations themselves
- The chart paints each bar in the label's own color, which annotators chose.
  A palette check would be needed before using these colors in print or for
  colorblind-safe reporting
