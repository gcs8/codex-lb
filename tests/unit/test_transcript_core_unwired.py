from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, HttpBridgeOperationRecord
from app.modules.proxy.durable_bridge_coordinator import DurableBridgeSessionCoordinator

_TRANSCRIPT_FIELDS = (
    "transcript_version",
    "response_output_items_json",
    "response_output_items_complete",
    "response_replay_input_json",
    "response_replay_input_complete",
    "response_replay_input_turn_count",
)


def test_transcript_helpers_and_columns_have_no_runtime_consumers() -> None:
    app_root = Path(__file__).resolve().parents[2] / "app"
    for path in app_root.rglob("*.py"):
        relative = path.relative_to(app_root).as_posix()
        if relative in {"db/models.py", "modules/proxy/complete_transcript.py"} or relative.startswith(
            "db/alembic/versions/"
        ):
            continue
        source = path.read_text(encoding="utf-8")
        assert "complete_transcript" not in source, relative
        assert all(field not in source for field in _TRANSCRIPT_FIELDS), relative

    helper = ast.parse((app_root / "modules/proxy/complete_transcript.py").read_text(encoding="utf-8"))
    imports = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(helper)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imports <= {"__future__", "json", "collections.abc", "typing", "app.core.types"}
    assert not any(isinstance(node, (ast.AsyncFunctionDef, ast.Await)) for node in ast.walk(helper))


@pytest.mark.asyncio
@pytest.mark.parametrize("spool_kind", ["rows", "chunks"])
async def test_existing_operation_consumer_leaves_transcript_core_empty(spool_kind: str) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        coordinator = DurableBridgeSessionCoordinator(factory)
        claimed = await coordinator.claim_live_session(
            session_key_kind="session_header",
            session_key_value="fixture-transcript-unwired",
            api_key_id=None,
            instance_id="fixture-instance",
            owner_process_epoch="fixture-process",
            lease_ttl_seconds=120.0,
            account_id="fixture-account",
            model="fixture-model",
            service_tier=None,
            latest_turn_state=None,
            latest_response_id=None,
            allow_takeover=True,
        )
        operation = await coordinator.record_operation(
            operation_id="fixture-operation",
            session_id=claimed.session_id,
            instance_id="fixture-instance",
            owner_epoch=claimed.owner_epoch,
            request_fingerprint="fixture-fingerprint",
            account_id="fixture-account",
            model="fixture-model",
            parent_response_id=None,
            request_text='{"input":"fixture user text"}',
        )
        assert operation is not None
        event = 'data: {"type":"response.completed","response":{"id":"fixture-response","output":[]}}\n\n'
        append = (
            coordinator.append_terminal_operation_event
            if spool_kind == "rows"
            else coordinator.append_terminal_operation_chunk
        )
        assert await append(
            operation_id="fixture-operation",
            session_id=claimed.session_id,
            instance_id="fixture-instance",
            owner_epoch=claimed.owner_epoch,
            event_text=event,
            max_bytes=65536,
            state="completed",
            response_id="fixture-response",
        )
        assert await coordinator.get_operation_events(operation_id="fixture-operation") == [event]
        snapshot = await coordinator.get_operation(operation_id="fixture-operation")
        assert snapshot is not None
        assert snapshot.state == "completed"
        assert snapshot.response_id == "fixture-response"
        assert not set(_TRANSCRIPT_FIELDS).intersection(field.name for field in dataclasses.fields(snapshot))
        async with factory() as session:
            stored = await session.get(HttpBridgeOperationRecord, "fixture-operation")
            assert stored is not None
            assert tuple(getattr(stored, field) for field in _TRANSCRIPT_FIELDS) == (0, None, False, None, False, 0)
            assert stored.request_text == '{"input":"fixture user text"}'
    finally:
        await engine.dispose()
