from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from starlette.requests import ClientDisconnect

from app.modules.proxy import downstream_delivery as delivery
from app.modules.proxy._service import support
from tests.unit.test_websocket_transport_fallback import _bridge_payload, _bridge_service, _pre_submit_error


@pytest.fixture(autouse=True)
def _reset_transport_failure_marker():
    # A pre-submit bridge failure arms the process-wide websocket transport
    # failure marker; reset it per test, as test_websocket_transport_fallback does,
    # so test order cannot route a later bridge test into raw retry.
    support.clear_upstream_websocket_transport_failure()
    yield
    support.clear_upstream_websocket_transport_failure()


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("spec_version", ["2.0", "2.4"])
@pytest.mark.parametrize("exit_kind", ["cancel", "send-error", "cleanup-cancel", "cleanup-error"])
@pytest.mark.parametrize("terminal", [False, True])
async def test_response_owns_close_before_finish(monkeypatch, spec_version, exit_kind, terminal):
    entered = asyncio.Event()
    close_started = asyncio.Event()
    close_release = asyncio.Event()
    closes = []
    finishes = []
    frame = b"event: response.completed\ndata: {}\n\n" if terminal else b": keepalive\n\n"

    class Body:
        def __aiter__(self):
            return self

        async def __anext__(self):
            return frame

        async def aclose(self):
            closes.append("start")
            close_started.set()
            if exit_kind == "cleanup-cancel":
                await close_release.wait()
            if exit_kind == "cleanup-error":
                raise LookupError("cleanup fixture")
            closes.append("end")

    response = delivery.DeliveryTracedStreamingResponse(cast(Any, Body()), surface="responses")
    original_finish = response._finish

    def finish(**kwargs):
        finishes.append((list(closes), kwargs))
        original_finish(**kwargs)

    monkeypatch.setattr(response, "_finish", finish)
    body_sends = 0

    async def send(message):
        nonlocal body_sends
        if message["type"] != "http.response.body":
            return
        body_sends += 1
        if terminal and body_sends == 1:
            return
        entered.set()
        if exit_kind == "send-error":
            raise OSError("send fixture")
        await asyncio.Event().wait()

    async def receive():
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    task = asyncio.create_task(response({"type": "http", "asgi": {"spec_version": spec_version}}, receive, send))
    await asyncio.wait_for(entered.wait(), 2)
    if exit_kind != "send-error":
        task.cancel()
    if exit_kind == "cleanup-cancel":
        await asyncio.wait_for(close_started.wait(), 2)
        task.cancel()
        tick = asyncio.Event()
        asyncio.get_running_loop().call_soon(tick.set)
        await tick.wait()
        task.cancel()
        assert not finishes
        close_release.set()
    error = (
        LookupError
        if exit_kind == "cleanup-error"
        else (
            ClientDisconnect
            if exit_kind == "send-error" and spec_version == "2.4"
            else (OSError if exit_kind == "send-error" else asyncio.CancelledError)
        )
    )
    with pytest.raises(error):
        await asyncio.wait_for(task, 2)
    assert closes == (["start"] if exit_kind == "cleanup-error" else ["start", "end"])
    assert len(finishes) == 1 and finishes[0][0] == closes
    assert response._chunks == int(terminal)
    assert response._bytes == (len(frame) if terminal else 0)
    expected = (
        delivery.OUTCOME_TERMINAL_WRITTEN
        if terminal
        else (
            delivery.OUTCOME_EXCEPTION_BEFORE_TERMINAL
            if exit_kind in {"send-error", "cleanup-error"}
            else delivery.OUTCOME_CANCELLED_BEFORE_TERMINAL
        )
    )
    assert response.outcome == expected
    assert finishes[0][1] == {
        "exc_name": error.__name__ if exit_kind in {"send-error", "cleanup-error"} else None,
        "cancelled": exit_kind in {"cancel", "cleanup-cancel"},
    }


def _stream(service, reservation=None):
    return service._stream_http_bridge_or_retry(
        _bridge_payload(),
        {},
        codex_session_affinity=True,
        propagate_http_errors=True,
        openai_cache_affinity=False,
        api_key=None,
        api_key_reservation=reservation,
        suppress_text_done_events=False,
    )


@pytest.mark.parametrize("fallback", [False, True])
async def test_raw_bridge_forwarders_close_retained_child(monkeypatch, fallback):
    service = _bridge_service(monkeypatch, dashboard_transport="default" if fallback else "http")
    retained = []
    closed = []

    async def raw():
        try:
            yield "data: raw\n\n"
            await asyncio.Event().wait()
        finally:
            closed.append("raw")

    def retry(*args, **kwargs):
        assert kwargs["api_key_reservation"] is None
        child = raw()
        retained.append(child)
        return child

    async def bridge(*args, **kwargs):
        raise _pre_submit_error()
        yield "unreachable"

    monkeypatch.setattr(service, "_stream_with_retry", retry)
    monkeypatch.setattr(service, "_stream_via_http_bridge", bridge)
    stream = _stream(service)
    assert await anext(stream) == "data: raw\n\n"
    await stream.aclose()
    assert closed == ["raw"] and len(retained) == 1
    assert retained[0].ag_frame is None


async def test_bridge_child_cleanup_precedes_settlement_inspection(monkeypatch):
    service = _bridge_service(monkeypatch, dashboard_transport="default")
    order = []
    retained = []
    reservation = object()

    async def bridge(*args, **kwargs):
        lifecycle = support._DeferredAccountBackoffLifecycle(reservation=cast(Any, reservation))
        lifecycle.settlement_owned = True
        lifecycle.pending_backoffs["fixture"] = cast(Any, object())
        kwargs["deferred_account_backoff_tracker"].current_lifecycle = lifecycle
        try:
            yield "data: bridge\n\n"
            await asyncio.Event().wait()
        finally:
            order.append("child-settlement")
            lifecycle.settlement_confirmed = True

    def child(*args, **kwargs):
        gen = bridge(*args, **kwargs)
        retained.append(gen)
        return gen

    async def backoff(pending):
        assert list(pending) == ["fixture"]
        order.append("health")

    async def handoffs(*args, **kwargs):
        order.append("handoffs")

    monkeypatch.setattr(
        "app.modules.proxy._service.http_bridge.streaming._release_http_bridge_unanchored_handoffs_for_request",
        handoffs,
    )
    release = AsyncMock()
    monkeypatch.setattr(service, "_stream_via_http_bridge", child)
    monkeypatch.setattr(service, "_release_websocket_reservation", release)
    monkeypatch.setattr(service, "_drain_deferred_account_error_backoffs", backoff)
    stream = _stream(service, reservation)
    assert await anext(stream) == "data: bridge\n\n"
    await stream.aclose()
    assert order == ["child-settlement", "health", "handoffs"]
    assert retained[0].ag_frame is None
    release.assert_not_awaited()
