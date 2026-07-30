"""Activity feed tests for the middleware's machinery.

This module guards the live activity feed implementation against regressions that would break
the browser-readable log stream. The feed is the only window into the middleware's internal
wiring decisions, message traffic, registrations, and heartbeats — not resource state, which
belongs to the monitor. Keeping these apart is a decided boundary; mixing them would conflate
the middleware's health with the device's status, making debugging ambiguous.

**Why these tests exist:** The feed's thread-safety depends on numbering and insertion happening
under one lock. A refactor that split them — taking a sequence number in one critical section,
inserting in another — would allow two threads to interleave and leave the deque ordered
``[.., 6, 5]``, causing the stream to re-send record 6 on every poll forever. The concurrency
test pins this race.

**Critical hazard:** The SSE endpoint is an endless generator. TestClient runs it on a blocking
portal that waits for the generator to finish, so iterating through it hangs the test run
forever, even if you break and exit the with block. Tests drive the generator directly instead.
The HTML page at /activity is safe to fetch with TestClient.

No GraphDB, no broker, no network: these tests run entirely offline under ``pytest -m 'not live'``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from unittest import mock
import threading
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kapps_semantic_middleware.activity import (
    ActivityFeed,
    _ActivityHandler,
    enable_activity_feed,
)


@pytest.fixture(autouse=True)
def _snapshot_logger_state():
    """Snapshot and restore the package logger's handlers and level around each test.

    These tests attach handlers to the real ``kapps_semantic_middleware`` logger. Without
    cleanup, a handler leaked from one test would persist into others, corrupting their
    assertions about what reaches the feed. This fixture captures the logger's state before
    each test and restores it after, preventing cross-test contamination.
    """
    logger = logging.getLogger("kapps_semantic_middleware")
    original_level = logger.level
    original_handlers = list(logger.handlers)
    
    try:
        yield
    finally:
        current_handlers = list(logger.handlers)
        for handler in current_handlers:
            if handler not in original_handlers:
                logger.removeHandler(handler)
        logger.setLevel(original_level)


class _FakeMiddleware:
    """The whole surface `enable_activity_feed` touches: an app, and somewhere to put the feed.

    Module scope rather than nested in the fixture, because a test that enables the feed twice
    needs two independent instances. Constructing a real `SemanticMiddleware` would drag in a
    graph connection for no gain here.
    """

    def __init__(self) -> None:
        self.app = FastAPI()
        self.activity_feed = None


@pytest.fixture
def fake_middleware():
    """One fake middleware, for the tests that only need a single instance."""
    return _FakeMiddleware()


async def _drive_stream(mw: Any, n: int, timeout: float = 3.0) -> list[str]:
    """Drive the SSE generator directly, returning n chunks.

    **Critical:** Do NOT use TestClient for /activity/stream. The endpoint returns an
    endless StreamingResponse generator. TestClient runs it on a blocking portal that
    waits for the generator to finish, so iterating through it hangs the test run
    forever, even if you break and exit the with block.

    This helper bypasses TestClient entirely: it finds the route, calls the endpoint
    directly with a fake request that never disconnects, and pulls n chunks from the
    async iterator with a timeout.
    """
    route = next(r for r in mw.app.routes if getattr(r, "path", "") == "/activity/stream")

    class _NeverDisconnected:
        async def is_disconnected(self) -> bool:
            return False

    response = await route.endpoint(_NeverDisconnected())
    iterator = response.body_iterator.__aiter__()
    chunks = [await asyncio.wait_for(iterator.__anext__(), timeout) for _ in range(n)]
    await response.body_iterator.aclose()
    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# Buffer behaviour tests (ActivityFeed directly, no HTTP)
# ─────────────────────────────────────────────────────────────────────────────


def test_the_buffer_is_bounded():
    """The rolling window drops oldest records when capacity is exceeded.

    With capacity 3, appending 5 records leaves only the last 3 in the buffer.
    This prevents unbounded memory growth during long-running middleware sessions.
    """
    feed = ActivityFeed(capacity=3)
    
    for i in range(5):
        feed.append(timestamp=float(i), level="INFO", logger="test", message=f"msg{i}")
    
    records = feed.snapshot()
    assert len(records) == 3
    assert [r.message for r in records] == ["msg2", "msg3", "msg4"]


def test_sequence_numbers_survive_concurrent_appends():
    """Numbering and insertion happen under one lock, preventing interleaving races.

    If numbering occurred in one critical section and insertion in another, two threads
    could interleave to leave the deque ordered ``[.., 6, 5]``. The stream would then
    report last_seq as 5 and re-send record 6 on every poll indefinitely. This test
    spawns multiple threads appending simultaneously and verifies sequence numbers are
    strictly increasing in deque order with no duplicates.
    """
    feed = ActivityFeed(capacity=500)
    threads = []
    
    def append_many(start: int, count: int) -> None:
        for i in range(count):
            feed.append(timestamp=float(start + i), level="INFO", logger="test", message=f"msg{start + i}")
    
    for t in range(8):
        thread = threading.Thread(target=append_many, args=(t * 50, 50))
        threads.append(thread)
        thread.start()
    
    for thread in threads:
        thread.join()
    
    records = feed.snapshot()
    seqs = [r.seq for r in records]
    
    assert len(seqs) == len(set(seqs))
    assert seqs == sorted(seqs)


def test_since_returns_only_what_is_new():
    """since(last_seq) filters to records newer than the given sequence.

    After capturing the current state, appending one more record should return exactly
    that new record when querying since the previous last sequence number.
    """
    feed = ActivityFeed(capacity=10)
    
    feed.append(timestamp=1.0, level="INFO", logger="test", message="first")
    feed.append(timestamp=2.0, level="INFO", logger="test", message="second")
    
    last_seq = feed.last_seq
    assert feed.since(last_seq) == []
    
    feed.append(timestamp=3.0, level="INFO", logger="test", message="third")
    
    new_records = feed.since(last_seq)
    assert len(new_records) == 1
    assert new_records[0].message == "third"


# ─────────────────────────────────────────────────────────────────────────────
# Wiring tests (enable_activity_feed on fake middleware)
# ─────────────────────────────────────────────────────────────────────────────


def test_a_log_record_reaches_the_feed(fake_middleware):
    """Attaching at the package root catches child loggers with a single handler.

    Logging through kapps_semantic_middleware.connectors.mqtt_binding (a child logger)
    should land in the feed, confirming the one-attach-at-package-root design works.
    """
    enable_activity_feed(fake_middleware)
    
    child_logger = logging.getLogger("kapps_semantic_middleware.connectors.mqtt_binding")
    child_logger.info("test message from child")
    
    records = fake_middleware.activity_feed.snapshot()
    assert len(records) == 1
    assert records[0].message == "test message from child"
    assert records[0].logger == "kapps_semantic_middleware.connectors.mqtt_binding"


def test_enabling_lowers_the_package_logger_to_the_handler_level():
    """Enabling the feed lowers `kapps_semantic_middleware`'s level so records exist at all.

    The package logger is NOTSET by default, so its effective level is root's — WARNING unless
    the host application configured logging. A handler cannot rescue a record that was never
    emitted, so a version that touched only the handler's level left the feed permanently and
    *silently* empty in the default case: page loads, stream connects, nothing appears.

    The widening is the documented cost of opting in, and it widens only — an application that
    has already asked for something more verbose keeps it.
    """
    package_logger = logging.getLogger("kapps_semantic_middleware")
    package_logger.setLevel(logging.WARNING)

    middleware = _FakeMiddleware()
    enable_activity_feed(middleware)
    assert package_logger.level == logging.INFO

    # Widening only: a more verbose level already chosen by the host survives.
    other = _FakeMiddleware()
    package_logger.setLevel(logging.DEBUG)
    enable_activity_feed(other)
    assert package_logger.level == logging.DEBUG

def test_enabling_twice_does_not_attach_a_second_handler(fake_middleware):
    """Calling enable_activity_feed twice returns the existing feed without adding handlers.

    Multiple calls should be idempotent — same feed object back, exactly one handler
    attached to the package logger.
    """
    logger = logging.getLogger("kapps_semantic_middleware")
    original_handler_count = len(logger.handlers)
    
    feed1 = enable_activity_feed(fake_middleware)
    feed2 = enable_activity_feed(fake_middleware)
    
    assert feed1 is feed2
    assert len(logger.handlers) == original_handler_count + 1


def test_the_handler_never_raises_into_logging():
    """A handler that throws takes down whatever was logging — so this one swallows and reports.

    Driven against `_ActivityHandler.emit` directly rather than through `logger.info(...)`,
    and deliberately: pytest installs its own `LogCaptureHandler` whose `handleError` *re-raises*
    so bad log calls surface during tests. Going through the logging chain would therefore
    measure pytest's handler, not this one.
    """
    feed = ActivityFeed(capacity=4)
    handler = _ActivityHandler(feed)

    # "%d" against a string: the failure happens inside `record.getMessage()`.
    bad = logging.LogRecord(
        name="kapps_semantic_middleware.x",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="%d",
        args=("not-a-number",),
        exc_info=None,
    )

    with mock.patch.object(handler, "handleError") as handle_error:
        handler.emit(bad)  # must not raise

    assert handle_error.called, "a swallowed failure must still be reported to handleError"
    assert feed.snapshot() == [], "a record that could not be formatted must not be buffered"


# ─────────────────────────────────────────────────────────────────────────────
# HTTP surface tests
# ─────────────────────────────────────────────────────────────────────────────


def test_the_page_is_self_contained(fake_middleware):
    """The HTML page contains no external references that would break on isolated networks.

    GET /activity returns 200 with body containing no http:// or https:// URLs,
    no <script src= tags, and no <link rel="stylesheet"> tags. Everything must be
    inline so the page renders on a factory network without CDN access.
    """
    enable_activity_feed(fake_middleware)
    
    client = TestClient(fake_middleware.app)
    response = client.get("/activity")
    
    assert response.status_code == 200
    
    body = response.text
    assert "http://" not in body
    assert "https://" not in body
    assert '<script src=' not in body
    assert '<link rel="stylesheet"' not in body


@pytest.mark.asyncio
async def test_the_stream_replays_the_backlog(fake_middleware):
    """A viewer connecting mid-run sees existing records, not an empty page.

    Log two records before opening the stream, then drive the generator and verify
    both appear as data: lines with correct messages and ascending sequence numbers.
    """
    feed = enable_activity_feed(fake_middleware)
    
    feed.append(timestamp=1.0, level="INFO", logger="test", message="first")
    feed.append(timestamp=2.0, level="INFO", logger="test", message="second")
    
    chunks = await _drive_stream(fake_middleware, 2)
    
    assert len(chunks) == 2
    assert chunks[0].startswith("data: ")
    assert chunks[1].startswith("data: ")
    
    first = json.loads(chunks[0][6:])
    second = json.loads(chunks[1][6:])
    
    assert first["message"] == "first"
    assert second["message"] == "second"
    assert first["seq"] < second["seq"]


@pytest.mark.asyncio
async def test_the_stream_is_server_sent_events(fake_middleware):
    """The response uses SSE media type and disables caching.

    Verify media_type is text/event-stream and Cache-Control header is no-cache.
    """
    enable_activity_feed(fake_middleware)
    
    route = next(r for r in fake_middleware.app.routes if getattr(r, "path", "") == "/activity/stream")

    class _NeverDisconnected:
        async def is_disconnected(self) -> bool:
            return False

    response = await route.endpoint(_NeverDisconnected())
    
    assert response.media_type == "text/event-stream"
    assert response.headers.get("Cache-Control") == "no-cache"
    
    await response.body_iterator.aclose()


# ─────────────────────────────────────────────────────────────────────────────
# Opt-in and mode-independence tests (real SemanticMiddleware)
# ─────────────────────────────────────────────────────────────────────────────


def test_disabled_allocates_nothing():
    """A middleware built without activity_feed=True has no activity routes.

    This is the acceptance criterion for the off state: activity_feed is None
    and no route path contains 'activity'.
    """
    from kapps_semantic_middleware import SemanticMiddleware, Mode
    
    mw = SemanticMiddleware(mode=Mode.WATCHDOG, ogm=object(), activity_feed=False)
    
    assert mw.activity_feed is None
    
    route_paths = [getattr(r, "path", "") for r in mw.app.routes]
    assert not any("activity" in p for p in route_paths)


def test_the_feed_is_mounted_the_same_way_regardless_of_mode():
    """Controller and monitor inherit the feed from the same code path without flavour-specific branching.

    ADR 0022 establishes that controller and monitor are the same library configured
    differently. Build a middleware in Mode.WATCHDOG with activity_feed=True and
    verify the activity routes exist. The mode-independence is structural —
    enable_activity_feed takes no mode argument.
    """
    from kapps_semantic_middleware import SemanticMiddleware, Mode
    
    mw = SemanticMiddleware(mode=Mode.WATCHDOG, ogm=object(), activity_feed=True)
    
    assert mw.activity_feed is not None
    
    route_paths = [getattr(r, "path", "") for r in mw.app.routes]
    assert any("/activity" in p for p in route_paths)


# ─────────────────────────────────────────────────────────────────────────────
# Drop detection and disconnect handling tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_client_that_falls_behind_is_told_records_were_dropped(fake_middleware):
    """A feed that quietly loses lines is worse than one that admits it, because the viewer
    cannot distinguish 'nothing happened' from 'I missed it'. The stream detects when the
    ring buffer has evicted records the client hasn't seen yet, and emits a synthetic
    WARNING before continuing with normal records.
    """
    feed = enable_activity_feed(fake_middleware, capacity=5)
    
    # Seed with some records through the package logger.
    logger = logging.getLogger("kapps_semantic_middleware")
    for i in range(20):
        logger.info(f"pre_msg{i}")
    
    # Open the stream.
    route = next(r for r in fake_middleware.app.routes if getattr(r, "path", "") == "/activity/stream")
    
    class _StayConnected:
        async def is_disconnected(self) -> bool:
            return False
    
    response = await route.endpoint(_StayConnected())
    iterator = response.body_iterator.__aiter__()
    
    # Drain the initial seeding chunks.
    seed_chunks = []
    for _ in range(5):
        chunk = await asyncio.wait_for(iterator.__anext__(), timeout=2.0)
        seed_chunks.append(chunk)
    
    # Now append enough to force eviction of records the client hasn't consumed.
    for i in range(200):
        logger.info(f"post_msg{i}")
    
    # Poll for the drop warning and subsequent records.
    chunks = []
    found_warning = False
    warning_data = None
    for _ in range(20):
        chunk = await asyncio.wait_for(iterator.__anext__(), timeout=2.0)
        chunks.append(chunk)
        if chunk.startswith("data: "):
            data = json.loads(chunk[6:])
            if data.get("level") == "WARNING" and "dropped" in data.get("message", "").lower():
                found_warning = True
                warning_data = data
                break
    
    assert found_warning, "Expected a WARNING about dropped records"

    # The count is derived from where the buffer now starts, not hardcoded: the client had
    # consumed through seq 20 when it fell behind.
    expected_dropped = feed.oldest_seq - 20 - 1
    assert warning_data["message"].startswith(f"{expected_dropped} record(s) dropped")

    # The stream carries on afterwards rather than stalling on the gap. Pulled *after* the
    # warning was found -- the search loop above breaks on it, so `chunks` ends there and
    # looking inside it for what comes next can only ever fail.
    following = []
    for _ in range(3):
        chunk = await asyncio.wait_for(iterator.__anext__(), timeout=2.0)
        if chunk.startswith("data: "):
            following.append(json.loads(chunk[6:]))

    await response.body_iterator.aclose()

    assert following, "the stream stopped after reporting the gap instead of resuming"
    assert all(
        "dropped" not in record["message"].lower() for record in following
    ), "the gap was reported more than once; the client position did not advance past it"


@pytest.mark.asyncio
async def test_the_stream_stops_when_the_client_disconnects(fake_middleware):
    """The generator checks await request.is_disconnected() each poll and returns when true.
    Without that, a disconnected viewer leaves a polling loop running forever under any server
    that does not cancel the task, and the endpoint cannot be tested at all -- an endless
    generator hangs any client that stops reading.
    """
    feed = enable_activity_feed(fake_middleware)
    
    # Seed with some records.
    feed.append(timestamp=1.0, level="INFO", logger="test", message="first")
    feed.append(timestamp=2.0, level="INFO", logger="test", message="second")
    
    # Fake request that disconnects after a couple polls.
    call_count = [0]
    
    class _DisconnectsSoon:
        async def is_disconnected(self) -> bool:
            call_count[0] += 1
            return call_count[0] >= 3
    
    route = next(r for r in fake_middleware.app.routes if getattr(r, "path", "") == "/activity/stream")
    response = await route.endpoint(_DisconnectsSoon())
    
    # Drive with timeout -- should terminate on its own, not hang.
    chunks = []
    completed = False
    try:
        async with asyncio.timeout(5.0):
            async for chunk in response.body_iterator:
                chunks.append(chunk)
        completed = True
    except asyncio.TimeoutError:
        pass
    
    assert completed, "Stream did not terminate after client disconnected"
    
    # Backlog was delivered before stopping.
    data_chunks = [c for c in chunks if c.startswith("data: ") and not c.startswith("data: :")]
    messages = [json.loads(c[6:])["message"] for c in data_chunks if not json.loads(c[6:]).get("message", "").startswith(":")]
    assert "first" in messages
    assert "second" in messages
