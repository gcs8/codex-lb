from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from websockets.asyncio.server import serve

from app.core.clients import native_egress
from app.core.clients.native_egress import (
    NativeEgressRequest,
    NativeEgressTransportError,
    NativeWebSocketRequest,
    SubprocessNativeEgressClient,
)
from app.core.clients.proxy_websocket import NativeUpstreamWebSocket

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def helper():
    binary = os.environ.get("CODEX_LB_NATIVE_EGRESS_TEST_BINARY")
    assert binary and Path(binary).is_file(), "qualification requires an actual compiled native helper"
    client = SubprocessNativeEgressClient(Path(binary))
    try:
        yield client
    finally:
        process = client._process
        await client.aclose()
        assert not client._streams
        assert client._reader_task is None
        if process is not None:
            assert process.returncode is not None
            assert not Path(f"/proc/{process.pid}").exists()


def _request(url: str, *, interpret: bool = False) -> NativeWebSocketRequest:
    return NativeWebSocketRequest(
        url=url,
        headers={},
        connect_timeout_seconds=5,
        max_message_bytes=16 * 1024 * 1024,
        ping_interval_seconds=None,
        interpret_responses=interpret,
    )


@pytest.mark.parametrize("count", [64, 65, 129])
@pytest.mark.parametrize("kind", ["text", "binary", "responses"])
async def test_native_burst_preserves_data_and_send_progress(helper, monkeypatch, count, kind):
    commands = []
    send = helper._send_command

    async def record(process, generation, command):
        commands.append(command)
        await send(process, generation, command)

    monkeypatch.setattr(helper, "_send_command", record)
    frames: list[str | bytes] = []
    for index in range(count):
        if kind == "binary":
            frames.append(f"caf\N{LATIN SMALL LETTER E WITH ACUTE}:{index}".encode())
        elif kind == "responses":
            frames.append(
                json.dumps(
                    {
                        "type": "response.output_text.delta",
                        "response_id": "burst-owner",
                        "sequence_number": index,
                        "delta": f"caf\N{LATIN SMALL LETTER E WITH ACUTE}:{index}",
                    },
                    ensure_ascii=False,
                )
            )
        else:
            frames.append(f"caf\N{LATIN SMALL LETTER E WITH ACUTE}:{index}")

    full = asyncio.Event()
    produced = asyncio.Event()
    read_barrier = asyncio.Event()
    command_received = asyncio.Event()
    enqueue = native_egress.NativeEgressWebSocket._queue_message

    def observe(socket, message):
        enqueue(socket, message)
        if socket._messages.qsize() == 64:
            full.set()

    monkeypatch.setattr(native_egress.NativeEgressWebSocket, "_queue_message", observe)

    async def origin(websocket: Any) -> None:
        assert await websocket.recv() == "start"
        for frame in frames:
            await websocket.send(frame)
        produced.set()
        # A pong proves the real native reader passed every preceding frame,
        # not merely that the server queued the fixture. At 129, native bounded
        # buffering may legitimately stop upstream reads until the app drains.
        if count <= 65:
            pong = await websocket.ping(b"native-read-barrier")
            await pong
            read_barrier.set()
        assert await websocket.recv() == "command-while-full"
        command_received.set()
        await websocket.wait_closed()

    async with serve(origin, "127.0.0.1", 0, ping_interval=None) as server:
        port = server.sockets[0].getsockname()[1]
        socket = await helper.websocket(_request(f"ws://127.0.0.1:{port}/burst", interpret=kind == "responses"))
        public = NativeUpstreamWebSocket(socket)
        try:
            async with asyncio.timeout(5):
                await public.send_text("start")
                await produced.wait()
                await full.wait()
                if count <= 65:
                    barrier = asyncio.create_task(read_barrier.wait())
                    try:
                        await asyncio.wait({barrier, socket._pump_task}, return_when=asyncio.FIRST_COMPLETED)
                        assert not socket._pump_task.done(), "valid small burst aborted the native data pump"
                        await barrier
                    finally:
                        barrier.cancel()
                        await asyncio.gather(barrier, return_exceptions=True)
                await public.send_text("command-while-full")
                await command_received.wait()
                assert socket._messages.maxsize == 64
                assert not socket._completed
                for index, frame in enumerate(frames):
                    message = await public.receive()
                    assert message.kind == ("binary" if kind == "binary" else "text")
                    assert (message.data if kind == "binary" else message.text) == frame
                    if kind == "responses":
                        assert message.responses_interpreted
                        assert message.payload == json.loads(frame)
                        assert message.routing is not None
                        assert message.routing.payload_response_id == "burst-owner"
                        assert message.routing.sequence_number == index
                assert not socket._pending
                assert sum(command["type"] == "websocket_consumed" for command in commands) == count
        finally:
            await public.close()
            assert socket._pump_task.done()


async def _wait_full(socket) -> None:
    async with asyncio.timeout(5):
        while socket._messages.qsize() < 64:
            assert not socket._pump_task.done()
            await asyncio.sleep(0.001)


@pytest.mark.parametrize("ending", ["close", "cancel", "stdin-eof"])
async def test_full_window_lifecycle_is_bounded(helper, ending):
    produced = asyncio.Event()

    async def origin(websocket: Any) -> None:
        try:
            for index in range(129):
                await websocket.send(str(index))
            produced.set()
            await websocket.wait_closed()
        except Exception:
            if not produced.is_set():
                raise

    async with serve(origin, "127.0.0.1", 0, ping_interval=None) as server:
        socket = await helper.websocket(_request(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/full"))
        try:
            await produced.wait()
            await _wait_full(socket)
            process = helper._process
            assert process is not None
            stat = Path(f"/proc/{process.pid}/stat")
            before = sum(map(int, stat.read_text().split()[13:15]))
            await asyncio.sleep(0.1)
            after = sum(map(int, stat.read_text().split()[13:15]))
            assert after - before < 10, "full native receive window must sleep, not spin"
            async with asyncio.timeout(5):
                if ending == "close":
                    await socket.close()
                    assert socket._terminal_failure is not None
                    assert socket._terminal_failure.failure_phase != "consumer_backpressure"
                elif ending == "cancel":
                    await helper._send_command(
                        process, socket._generation, {"type": "cancel", "request_id": socket._request_id}
                    )
                    await socket._pump_task
                    assert socket._terminal_failure.failure_phase == "cancelled"
                else:
                    process.stdin.close()
                    await process.wait()
                    await socket._pump_task
                    assert process.returncode == 0
                    assert not Path(f"/proc/{process.pid}").exists()
                assert socket._pump_task.done()
                assert not socket._pending
                assert socket._request_id not in helper._streams
        finally:
            await socket.close()


async def test_peer_close_preserves_full_window_data_and_control_frames(helper):
    peer_closed = asyncio.Event()

    async def origin(websocket: Any) -> None:
        for index in range(65):
            await websocket.send(str(index))
        pong = await websocket.ping(b"full-window-control")
        await pong
        await websocket.close(code=1000, reason="done")
        peer_closed.set()

    async with serve(origin, "127.0.0.1", 0, ping_interval=None) as server:
        socket = await helper.websocket(_request(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/peer"))
        try:
            async with asyncio.timeout(5):
                await _wait_full(socket)
                await peer_closed.wait()
                assert not socket._pump_task.done()
                assert socket._messages.qsize() == 64
                # Wire shutdown must not depend on credits, and an attempted
                # send must settle without discarding the retained receive FIFO.
                with pytest.raises(NativeEgressTransportError, match="native websocket is closed") as rejected:
                    await socket.send_text("after-peer-close")
                assert rejected.value.failure_phase == "websocket_send"
                assert socket._terminal_failure is None
                process = helper._process
                assert process is not None
                stat = Path(f"/proc/{process.pid}/stat")
                before = sum(map(int, stat.read_text().split()[13:15]))
                await asyncio.sleep(0.1)
                after = sum(map(int, stat.read_text().split()[13:15]))
                assert after - before < 10, "closed transport with retained data must sleep, not spin"
                assert [(await socket.receive()).text for _ in range(65)] == [str(i) for i in range(65)]
                message = await socket.receive()
                assert (message.kind, message.close_code, message.close_reason) == ("close", 1000, "done")
                await socket._pump_task
        finally:
            await socket.close()


@pytest.mark.parametrize("kind", ["text", "binary", "responses"])
async def test_native_byte_overflow_is_explicit_and_isolates_siblings(helper, kind):
    text = "x" * (2 * 1024 * 1024)
    if kind == "responses":
        text = json.dumps({"type": "response.output_text.delta", "delta": "x" * (512 * 1024)})
    frame = text.encode() if kind == "binary" else text

    async def origin(websocket: Any) -> None:
        if websocket.request.path == "/echo":
            async for message in websocket:
                await websocket.send(message)
        else:
            try:
                for _ in range(40):
                    await websocket.send(frame)
                await websocket.wait_closed()
            except Exception:
                pass  # Expected retirement of this overflowed exchange.

    async def http(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async with (
        serve(origin, "127.0.0.1", 0, ping_interval=None) as server,
        await asyncio.start_server(http, "127.0.0.1", 0) as http_server,
    ):
        base = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        socket = await helper.websocket(_request(base + "/overflow", interpret=kind == "responses"))
        sibling = await helper.websocket(_request(base + "/echo"))
        process = helper._process
        try:
            async with asyncio.timeout(10):
                await socket._pump_task
                assert isinstance(socket._terminal_failure, NativeEgressTransportError)
                assert socket._terminal_failure.failure_phase == "consumer_backpressure"
                assert "32 MiB" in str(socket._terminal_failure)
                assert socket._messages.qsize() <= 64
                assert socket._request_id not in helper._streams
                await sibling.send_text("sibling-survives")
                assert (await sibling.receive()).text == "sibling-survives"
                response = await helper.request(
                    NativeEgressRequest(
                        method="GET", url=f"http://127.0.0.1:{http_server.sockets[0].getsockname()[1]}/", headers={}
                    )
                )
                assert b"".join([part async for part in response.iter_bytes()]) == b"ok"
                assert helper._process is process
                assert process.returncode is None
        finally:
            await socket.close()
            await sibling.close()


async def test_old_helper_optional_capability_stays_compatible(monkeypatch):
    binary = Path(os.environ["ISSUE2594_OLD_HELPER"])
    client = SubprocessNativeEgressClient(binary)
    commands = []
    send = client._send_command

    async def observe(process, generation, command):
        commands.append(command)
        await send(process, generation, command)

    monkeypatch.setattr(client, "_send_command", observe)

    async def origin(websocket: Any):
        await websocket.send(await websocket.recv())
        await websocket.wait_closed()

    try:
        async with serve(origin, "127.0.0.1", 0, ping_interval=None) as server:
            socket = await client.websocket(_request(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/old"))
            try:
                assert "websocket_receive_window_v1" not in client._capabilities
                await socket.send_text("old-helper")
                assert (await socket.receive()).text == "old-helper"
                assert "receive_backpressure" not in commands[0]
                assert not any(command["type"] == "websocket_consumed" for command in commands)
                assert socket._terminal_failure is None
            finally:
                await socket.close()
                assert isinstance(socket._terminal_failure, NativeEgressTransportError)
                assert (str(socket._terminal_failure), socket._terminal_failure.failure_phase) in {
                    ("native websocket closed", "websocket_receive"),
                    ("native websocket was closed locally", "cancelled"),
                }
                assert socket._pump_task.done()
                assert not socket._pending
                assert socket._request_id not in client._streams
    finally:
        process = client._process
        await client.aclose()
        assert process is not None and process.returncode is not None
        assert not client._streams and client._reader_task is None
        assert not Path(f"/proc/{process.pid}").exists()


async def test_native_message_limit_remains_16_mib(helper):
    release = asyncio.Event()
    size = 16 * 1024 * 1024

    async def origin(websocket: Any) -> None:
        await websocket.send("x" * size)
        await release.wait()
        try:
            await websocket.send("x" * (size + 1))
            await websocket.wait_closed()
        except Exception:
            pass  # Expected native message-limit retirement.

    async with serve(origin, "127.0.0.1", 0, ping_interval=None) as server:
        socket = await helper.websocket(_request(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/limit"))
        try:
            async with asyncio.timeout(10):
                message = await socket.receive()
                assert message.kind == "text" and message.text == "x" * size
                release.set()
                await socket._pump_task
                assert isinstance(socket._terminal_failure, NativeEgressTransportError)
                assert socket._terminal_failure.failure_phase == "protocol"
        finally:
            release.set()
            await socket.close()


async def test_unearned_receipt_fails_only_its_exchange(helper):
    async def origin(websocket: Any) -> None:
        async for message in websocket:
            await websocket.send(message)

    async with serve(origin, "127.0.0.1", 0, ping_interval=None) as server:
        base = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        socket = await helper.websocket(_request(base + "/invalid"))
        sibling = await helper.websocket(_request(base + "/sibling"))
        try:
            async with asyncio.timeout(5):
                await helper._send_command(
                    helper._process,
                    socket._generation,
                    {"type": "websocket_consumed", "request_id": socket._request_id},
                )
                await socket._pump_task
                assert isinstance(socket._terminal_failure, NativeEgressTransportError)
                assert socket._terminal_failure.failure_phase == "protocol"
                await sibling.send_text("alive")
                assert (await sibling.receive()).text == "alive"
        finally:
            await socket.close()
            await sibling.close()
