from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.openai import host_models


def test_image_host_prefers_image_capable_current_model(monkeypatch) -> None:
    registry = SimpleNamespace(
        plan_types_for_model=lambda model: {"gpt-5.6-sol"} if model == "gpt-5.6-sol" else set(),
        is_suppressed_model=lambda model: False,
    )
    monkeypatch.setattr(host_models, "get_model_registry", lambda: registry)

    assert host_models.resolve_image_host_model() == "gpt-5.6-sol"


def test_image_host_falls_back_when_preferred_model_is_unavailable(monkeypatch) -> None:
    registry = SimpleNamespace(
        plan_types_for_model=lambda model: {"available"} if model == "gpt-6-astra" else set(),
        is_suppressed_model=lambda model: False,
    )
    monkeypatch.setattr(host_models, "get_model_registry", lambda: registry)

    assert host_models.resolve_image_host_model() == "gpt-6-astra"


@pytest.mark.parametrize(
    "visible, suppressed, expected",
    [
        ({"gpt-5.6-sol", "gpt-6-astra", "gpt-5.6-luna", "gpt-5.5"}, set(), "gpt-5.6-sol"),
        ({"gpt-5.6-sol", "gpt-6-astra"}, {"gpt-5.6-sol"}, "gpt-6-astra"),
        ({"gpt-5.6-luna", "gpt-5.5"}, set(), "gpt-5.6-luna"),
        ({"gpt-5.5"}, set(), "gpt-5.5"),
        (set(), set(), "gpt-5.6-sol"),
        (
            {"gpt-5.6-sol", "gpt-6-astra", "gpt-5.6-luna", "gpt-5.5"},
            {"gpt-5.6-sol", "gpt-6-astra", "gpt-5.6-luna", "gpt-5.5"},
            "gpt-5.6-sol",
        ),
    ],
)
def test_image_host_visibility_and_suppression(monkeypatch, visible, suppressed, expected) -> None:
    registry = SimpleNamespace(
        plan_types_for_model=lambda model: {"plus"} if model in visible else set(),
        is_suppressed_model=lambda model: model in suppressed,
    )
    monkeypatch.setattr(host_models, "get_model_registry", lambda: registry)

    assert host_models.resolve_image_host_model() == expected


def test_image_host_preference_keeps_default_account_probe_order(monkeypatch) -> None:
    registry = SimpleNamespace(
        plan_types_for_model=lambda model: {"plus"},
        is_suppressed_model=lambda model: False,
    )
    monkeypatch.setattr(host_models, "get_model_registry", lambda: registry)

    assert host_models.resolve_image_host_model() == "gpt-5.6-sol"
    assert host_models.resolve_default_host_model() == "gpt-5.6-luna"
