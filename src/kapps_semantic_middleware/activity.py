"""Live activity feed for the middleware's machinery.

This module turns the middleware's internal logging stream into a live, browser-readable feed.
It is library-level and mode-agnostic: a controller and a monitor are the same library configured
differently (ADR 0022), so they inherit this feed from the same code with no flavour-specific
branching. That is the architectural claim the demo exists to make.

**What it shows:** wiring decisions, message traffic, registrations, heartbeats. **What it does not
show:** resource state. That is the monitor's job, and keeping the two apart is a decided boundary.
Mixing them would conflate the middleware's health with the device's status, making debugging
ambiguous.

**Why the stream is polled rather than pushed:** Log records arrive from two places — the event
loop, and worker threads (this codebase calls ``anyio.to_thread.run_sync`` for every graph write).
Pushing from the logging handler into an ``asyncio.Queue`` is not thread-safe and would require
capturing the running loop, which breaks when no loop is running (construction time, tests).
Instead, the handler appends to a thread-safe ``collections.deque``, and the SSE endpoint polls
that deque on a short sleep. This decouples the logging path (synchronous, multi-threaded) from
the serving path (asynchronous, single-threaded) without requiring loop introspection or
``call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, List

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse


@dataclass(frozen=True)
class ActivityRecord:
    """One entry in the activity feed.

    Immutable so that records handed to the SSE generator cannot be mutated by later logging
    activity. The ``seq`` field allows clients to request only what is new.
    """

    seq: int
    timestamp: float  # unix epoch seconds
    level: str  # "INFO", "WARNING", ...
    logger: str  # the record's logger name
    message: str  # already formatted


class ActivityFeed:
    """Thread-safe buffer for activity records.

    Holds a rolling window of records. Appends are protected by a lock because the logging
    handler runs in arbitrary threads; reads are protected for the same reason, though the
    SSE generator holds the lock only long enough to copy data out.
    """

    def __init__(self, capacity: int = 200) -> None:
        self._capacity = capacity
        self._deque: collections.deque[ActivityRecord] = collections.deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._seq = 0

    def append(
        self, *, timestamp: float, level: str, logger: str, message: str
    ) -> ActivityRecord:
        """Buffer one record, assigning its sequence number. Oldest is dropped when full.

        Numbering and insertion happen under **one** lock, together, and that is the whole
        point of this method taking fields rather than a finished record. Split them -- take a
        number in one critical section, insert in another -- and two threads interleave to
        leave the deque ordered ``[.., 6, 5]``. ``last_seq`` then reports 5, so the stream
        re-sends record 6 on every poll, forever. The race is reachable here rather than
        theoretical: this codebase logs from worker threads (``anyio.to_thread.run_sync``
        wraps every graph write) as well as from the event loop.
        """
        with self._lock:
            self._seq += 1
            record = ActivityRecord(
                seq=self._seq,
                timestamp=timestamp,
                level=level,
                logger=logger,
                message=message,
            )
            self._deque.append(record)
            return record

    def since(self, seq: int) -> List[ActivityRecord]:
        """Return records with ``.seq > seq``, oldest first.

        Called by the SSE generator. The lock is held only for the duration of the slice
        operation, not during the yield, so the event loop is not blocked.
        """
        with self._lock:
            return [r for r in self._deque if r.seq > seq]

    def snapshot(self) -> List[ActivityRecord]:
        """Return everything currently buffered.

        Used to seed a client connecting mid-run. Same locking discipline as ``since``.
        """
        with self._lock:
            return list(self._deque)

    @property
    def last_seq(self) -> int:
        """The highest sequence number **currently buffered**. Zero if empty.

        Not a resume token. Once eviction has begun this is still the newest record, but the
        oldest has moved forward under it -- so a consumer that stores this, goes away, and
        comes back asking for everything after it has no way to learn what fell out of the
        window meanwhile. Pair it with :attr:`oldest_seq` to detect that; the stream does.
        """
        with self._lock:
            if not self._deque:
                return 0
            return self._deque[-1].seq

    @property
    def oldest_seq(self) -> int:
        """The lowest sequence number still buffered. Zero if empty.

        A consumer that expected ``n`` and finds this greater than ``n`` has been outrun: the
        records between are gone. Exposed so that loss is reportable rather than invisible --
        a feed that quietly drops lines is worse than one that says it dropped them, because
        the viewer cannot tell "nothing happened" from "I missed it".
        """
        with self._lock:
            if not self._deque:
                return 0
            return self._deque[0].seq


class _ActivityHandler(logging.Handler):
    """Logging handler that pushes records into an ``ActivityFeed``.

    Attached to the package-root logger (``kapps_semantic_middleware``) to catch every child
    logger with one attach. The level is set on the handler, not the logger, so this feature
    does not change what every *other* handler in the host application sees.

    ``emit`` is wrapped in a try/except; on failure it calls ``self.handleError`` as the stdlib
    expects. It never raises into the logging system, which would risk deadlocking the caller.
    """

    def __init__(self, feed: ActivityFeed, level: int = logging.INFO) -> None:
        super().__init__(level)
        self._feed = feed

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Numbering belongs to the feed, under the same lock as the insertion -- see
            # `ActivityFeed.append`. A handler that took a number and then handed over a
            # finished record would reintroduce exactly the ordering race that method exists
            # to close.
            #
            # `getMessage` applies %-style formatting, and it happens here rather than at the
            # call site so the cost is only paid when this handler is attached.
            self._feed.append(
                timestamp=record.created,
                level=record.levelname,
                logger=record.name,
                message=record.getMessage(),
            )
        except Exception:
            self.handleError(record)


def enable_activity_feed(
    middleware: Any,
    *,
    capacity: int = 200,
    level: int = logging.INFO,
    logger_name: str = "kapps_semantic_middleware",
) -> ActivityFeed:
    """Enable the activity feed on a middleware instance.

    Builds an ``ActivityFeed``, attaches a logging handler to capture records, and mounts the
    HTTP routes on ``middleware.app``. Calling twice on the same middleware returns the existing
    feed without attaching a second handler.

    The feed is stored on the middleware as ``middleware.activity_feed`` so other components
    (tests, diagnostics) can inspect it directly.
    """
    # `getattr(..., None) is not None` rather than `hasattr`: a middleware that declares
    # `self.activity_feed = None` when the feature is off would otherwise satisfy `hasattr`
    # and be handed its own `None` back as a feed.
    existing = getattr(middleware, "activity_feed", None)
    if existing is not None:
        return existing

    feed = ActivityFeed(capacity=capacity)
    handler = _ActivityHandler(feed, level=level)

    # Attach to the package-root logger. This catches every child logger with one attach.
    target_logger = logging.getLogger(logger_name)
    target_logger.addHandler(handler)

    # The package logger is NOTSET by default, so its effective level comes from root -- which
    # is WARNING unless the host application configured logging. A handler cannot rescue a
    # record that was never emitted, so leaving the level alone makes this whole feature a
    # no-op in exactly the default case, and it fails *silently*: the page loads, the stream
    # connects, and nothing ever appears.
    #
    # So opting into the feed lowers this package's level far enough to produce the records it
    # was asked to show. That is a real, documented side effect rather than a free one: records
    # this package emits at INFO now also reach whatever handlers the host has on the root
    # logger. Widening only -- an application that has deliberately set a *more* verbose level
    # keeps it.
    if target_logger.level == logging.NOTSET or target_logger.level > level:
        target_logger.setLevel(level)

    router = APIRouter()

    @router.get("/activity")
    async def get_activity_page() -> HTMLResponse:
        # Self-contained HTML. No external fetches, no external CSS/JS.
        # The JS opens an EventSource to /activity/stream and appends lines to the log view.
        # Auto-scrolling is suppressed if the user has scrolled up to read history.
        html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Middleware Activity</title>
    <style>
        body { font-family: monospace; margin: 0; padding: 0; background: #f5f5f5; }
        header { background: #333; color: #fff; padding: 10px 20px; }
        header h1 { margin: 0; font-size: 1.2rem; }
        header p { margin: 5px 0 0; font-size: 0.9rem; opacity: 0.8; }
        #log { height: calc(100vh - 80px); overflow-y: auto; padding: 10px 20px; }
        .entry { padding: 4px 0; border-bottom: 1px solid #ddd; }
        .entry:last-child { border-bottom: none; }
        .time { color: #666; width: 90px; display: inline-block; }
        .level { font-weight: bold; width: 80px; display: inline-block; }
        .logger { color: #0066cc; width: 200px; display: inline-block; }
        .message { color: #333; }
        .WARNING .level { color: #996600; }
        .ERROR .level { color: #cc0000; }
        .WARNING { background: #fff8e1; }
        .ERROR { background: #ffebee; }
    </style>
</head>
<body>
    <header>
        <h1>Middleware Activity</h1>
        <p>Shows machinery: wiring, traffic, registrations. Not resource state.</p>
    </header>
    <div id="log"></div>
    <script>
        const log = document.getElementById('log');
        let lastSeq = 0;
        let isAtBottom = true;

        function appendRecord(record) {
            const div = document.createElement('div');
            div.className = 'entry ' + record.level;
            const date = new Date(record.timestamp * 1000);
            const timeStr = date.toLocaleTimeString();
            const loggerShort = record.logger.split('.').pop();
            div.innerHTML = '<span class="time">' + timeStr + '</span>' +
                            '<span class="level">' + record.level + '</span>' +
                            '<span class="logger">' + loggerShort + '</span>' +
                            '<span class="message">' + escapeHtml(record.message) + '</span>';
            log.appendChild(div);
            if (isAtBottom) {
                log.scrollTop = log.scrollHeight;
            }
        }

        function escapeHtml(text) {
            const map = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'};
            return text.replace(/[&<>"']/g, m => map[m]);
        }

        log.addEventListener('scroll', () => {
            isAtBottom = (log.scrollTop + log.clientHeight >= log.scrollHeight - 10);
        });

        const source = new EventSource('/activity/stream');
        source.onmessage = (event) => {
            const record = JSON.parse(event.data);
            appendRecord(record);
            lastSeq = record.seq;
        };
        source.onerror = () => {
            // Silent fail; browser will reconnect.
        };
    </script>
</body>
</html>
        """
        return HTMLResponse(html)

    @router.get("/activity/stream")
    async def get_activity_stream(request: Request) -> StreamingResponse:
        # SSE endpoint. Polls the feed rather than waiting on a queue because the logging
        # handler runs in worker threads where no asyncio loop is available. Pushing from
        # the handler would require call_soon_threadsafe and a captured loop, which breaks
        # at construction time. Polling is cheap and robust.
        async def generate() -> AsyncIterator[str]:
            last_yield = time.time()
            client_seq = 0

            # Seed with existing records so a viewer arriving mid-run does not see an empty page.
            for record in feed.snapshot():
                yield f"data: {json.dumps(record.__dict__)}\n\n"
                client_seq = record.seq
                last_yield = time.time()

            try:
                while True:
                    # Stop when the viewer goes away. uvicorn does cancel the task on
                    # disconnect, but relying on that alone leaks a polling loop per
                    # disconnect under any server that does not, and makes the endpoint
                    # untestable -- a client that stops reading otherwise hangs forever
                    # waiting for a generator that never ends.
                    if await request.is_disconnected():
                        return

                    # Report anything the ring buffer dropped before this client could be
                    # handed it. Unreachable at demo rates -- measured at ~0.4 records/sec
                    # against a 200-record window -- but a burst that outruns the window
                    # would otherwise take lines out of the feed with nothing to show for
                    # it, and a viewer cannot tell "nothing happened" from "I missed it".
                    oldest = feed.oldest_seq
                    if oldest > client_seq + 1:
                        dropped = oldest - client_seq - 1
                        yield (
                            "data: "
                            + json.dumps(
                                {
                                    "seq": oldest - 1,
                                    "timestamp": time.time(),
                                    "level": "WARNING",
                                    "logger": __name__,
                                    "message": (
                                        f"{dropped} record(s) dropped -- the feed produced "
                                        f"faster than this view could read it"
                                    ),
                                }
                            )
                            + "\n\n"
                        )
                        client_seq = oldest - 1
                        last_yield = time.time()

                    # Poll for new records.
                    new_records = feed.since(client_seq)
                    for record in new_records:
                        yield f"data: {json.dumps(record.__dict__)}\n\n"
                        client_seq = record.seq
                        last_yield = time.time()

                    # Keepalive every 15s of silence so proxies do not close the connection.
                    if time.time() - last_yield > 15:
                        yield ": keepalive\n\n"
                        last_yield = time.time()

                    await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                # Clean termination when the client disconnects or the server shuts down.
                raise

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    middleware.app.include_router(router)
    middleware.activity_feed = feed
    return feed
