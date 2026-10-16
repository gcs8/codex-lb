from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import AsyncGeneratorType
from typing import Any, cast

import pytest

from app.core.utils.shared_future import wait_on_shared_future
from app.core.utils.sse import inject_sse_keepalives
from app.modules.proxy import api

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("wrapper", ["public", "reasoning", "errors", "proxy-errors", "first", "items", "first-task"])
async def test_consumer_close_reaches_suspended_owner(wrapper: str) -> None:
    closed = asyncio.Event()

    async def owner() -> AsyncIterator[str]:
        try:
            yield 'data: {"type":"response.created","response":{"id":"resp_owner","status":"in_progress"}}\n\n'
            await asyncio.Event().wait()
        finally:
            closed.set()

    source = owner()
    if wrapper == "public":
        stream = api._normalize_public_responses_stream(source)
    elif wrapper == "reasoning":
        stream = api._normalize_reasoning_summary_stream(source)
    elif wrapper == "errors":
        stream = api._stream_response_error_events(source, owns_reservation=False, reservation=None)
    elif wrapper == "proxy-errors":
        stream = api._stream_proxy_errors_as_response_failed(source)
    elif wrapper == "first":
        first = await anext(source)
        stream = api._prepend_first(first, source)
    elif wrapper == "items":
        first = await anext(source)
        stream = api._prepend_items([first], source)
    else:
        task = asyncio.create_task(api._read_first_stream_item(source))
        stream = api._prepend_first_task(task, source)
    await asyncio.wait_for(anext(stream), timeout=2)
    await asyncio.wait_for(cast(Any, stream).aclose(), timeout=2)
    assert closed.is_set()


async def test_close_defers_repeated_cancellation_and_does_not_orphan_cleanup() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    class Source:
        async def aclose(self) -> None:
            started.set()
            await release.wait()
            finished.set()

    task = asyncio.create_task(api._close_responses_stream_best_effort(cast(Any, Source()), action="fixture"))
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    task.cancel()
    assert not finished.is_set()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)
    assert finished.is_set()


async def test_startup_guard_stops_active_read_before_closing_inner_stream(monkeypatch) -> None:
    reading = asyncio.Event()
    exited = asyncio.Event()
    keepalive = asyncio.Event()

    async def owner() -> AsyncIterator[str]:
        try:
            reading.set()
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            exited.set()

    source = owner()
    # Advance the injector to its heartbeat yield using a causal timeout seam,
    # not a wall-clock sleep. Its owned next task still drives the source.
    first_wait = True

    async def heartbeat_wait(shared, *, timeout=None, **kwargs):
        nonlocal first_wait
        if first_wait:
            first_wait = False
            await asyncio.wait_for(reading.wait(), timeout=2)
            raise TimeoutError
        return await wait_on_shared_future(shared, timeout=timeout, **kwargs)

    import app.core.utils.sse as sse

    monkeypatch.setattr(sse, "wait_on_shared_future", heartbeat_wait)
    injected = inject_sse_keepalives(source, 10, on_keepalive=keepalive.set)
    cleanup = api._ResponsesReservationCleanup(
        owns_reservation=False, reservation=None, scheduler=None, request_id="fixture"
    )
    guarded = api._guard_responses_startup_handoff(
        injected,
        startup_task=None,
        streams_to_close=(source,),
        reservation_cleanup=cleanup,
        responses_service_cleanup_ready_event=asyncio.Event(),
        responses_owner_forward_dispatched_event=asyncio.Event(),
        responses_owner_forward_rejected_event=asyncio.Event(),
    )
    assert await asyncio.wait_for(anext(guarded), timeout=2) == sse.SSE_KEEPALIVE_FRAME
    assert keepalive.is_set()
    assert reading.is_set()
    assert not exited.is_set()
    await asyncio.wait_for(cast(Any, guarded).aclose(), timeout=2)
    assert exited.is_set()
    # No concurrent aclose RuntimeError was swallowed, and no read survived.
    assert cast(Any, source).ag_frame is None
    assert cast(Any, injected).ag_frame is None


@pytest.mark.parametrize("started", [False, True])
async def test_heartbeat_takes_inner_ownership_only_when_iteration_starts(started: bool) -> None:
    closes = []

    class Source:
        def __aiter__(self):
            return self

        async def __anext__(self):
            return "data: fixture\n\n"

        async def aclose(self):
            closes.append("inner")

    heartbeat = api._prepend_initial_sse_heartbeat(cast(Any, Source()), ": heartbeat\n\n")
    assert await anext(heartbeat) == ": heartbeat\n\n"
    if started:
        assert await anext(heartbeat) == "data: fixture\n\n"
    assert isinstance(heartbeat, AsyncGeneratorType)
    await heartbeat.aclose()
    assert closes == (["inner"] if started else [])


@pytest.mark.parametrize("pending_probe", [False, True])
async def test_guard_drains_all_fallbacks_and_reservation_after_repeated_cancel(pending_probe: bool) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    probe_started = asyncio.Event()
    closed = []

    class Outer:
        def __aiter__(self):
            return self

        async def __anext__(self):
            return ": heartbeat\n\n"

        async def aclose(self):
            entered.set()
            await release.wait()
            closed.append("outer")

    class Original:
        async def aclose(self):
            closed.append("original")

    class Cleanup:
        async def release(self, *, action):
            closed.append("reservation")

    async def probe():
        probe_started.set()
        await asyncio.Event().wait()
        return "unreachable"

    startup = asyncio.create_task(probe()) if pending_probe else None
    if startup is not None:
        await probe_started.wait()
    guarded = api._guard_responses_startup_handoff(
        cast(Any, Outer()),
        startup_task=startup,
        streams_to_close=(cast(Any, Original()),),
        reservation_cleanup=cast(Any, Cleanup()),
        responses_service_cleanup_ready_event=asyncio.Event(),
        responses_owner_forward_dispatched_event=asyncio.Event(),
        responses_owner_forward_rejected_event=asyncio.Event(),
    )
    assert await anext(guarded) == ": heartbeat\n\n"
    assert isinstance(guarded, AsyncGeneratorType)
    close_task = asyncio.create_task(guarded.aclose())
    await asyncio.wait_for(entered.wait(), timeout=2)
    close_task.cancel()
    tick = asyncio.Event()
    asyncio.get_running_loop().call_soon(tick.set)
    await tick.wait()
    close_task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(close_task, timeout=2)
    assert closed == ["outer", "original", "reservation"]
    if startup is not None:
        assert startup.cancelled()
    assert guarded.ag_frame is None


@pytest.mark.parametrize("failure_type", [RuntimeError, asyncio.CancelledError])
async def test_unknown_failure_and_cancellation_remain_unchanged(failure_type: type[BaseException]) -> None:
    failure = failure_type("fixture failure")
    closed = asyncio.Event()

    async def owner() -> AsyncIterator[str]:
        try:
            raise failure
            yield "unreachable"
        finally:
            closed.set()

    stream = api._normalize_public_responses_stream(
        api._stream_response_error_events(owner(), owns_reservation=False, reservation=None)
    )
    with pytest.raises(failure_type) as caught:
        await anext(stream)
    assert caught.value is failure
    assert closed.is_set()
