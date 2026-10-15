from __future__ import annotations

import pytest

from app.modules.proxy._service.streaming.helpers import _is_account_neutral_request_rejection

pytestmark = pytest.mark.unit

MESSAGE = "X-OpenAI-Internal-Codex-Responses-Lite requires `parallel_tool_calls` to be false."


@pytest.mark.parametrize("status", [None, 400, 401, 403, 429, 500])
@pytest.mark.parametrize(
    "code,message",
    [
        ("unsupported_value", MESSAGE),
        ("upstream_error", MESSAGE),
        ("unsupported_value", "An unrelated unsupported value."),
        ("unsupported_value", None),
    ],
)
def test_lite_validation_neutrality_is_narrow(status, code, message) -> None:
    assert _is_account_neutral_request_rejection(code=code, http_status=status, message=message) is (
        status in {None, 400} and code == "unsupported_value" and message == MESSAGE
    )
