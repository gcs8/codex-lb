from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.db.models import ApiKey
from app.modules.api_keys.service import (
    ApiKeyValidationError,
    _get_usage_sections_with_default,
    _normalize_usage_sections,
)
from app.modules.lb_summary.schemas import CacheSummary, QuotaSummary, RequestSummary

pytestmark = pytest.mark.unit


def test_lb_summary_opt_in_does_not_expand_defaults():
    assert _normalize_usage_sections(None) == "upstream_limits,account_pool_usage"
    assert _get_usage_sections_with_default(ApiKey(usage_sections=None)) == "upstream_limits,account_pool_usage"
    assert _normalize_usage_sections("lb_summary,lb_summary") == "lb_summary"
    assert _normalize_usage_sections("upstream_limits, lb_summary") == "upstream_limits,lb_summary"
    with pytest.raises(ApiKeyValidationError):
        _normalize_usage_sections("lb_summary,private-extension")


def test_closed_envelopes_reject_extensions_and_nonfinite_values():
    values = dict(total=0, success=0, error=0, cancelled=0, unknown=0, errors_by_code={})
    with pytest.raises(ValidationError):
        RequestSummary.model_validate({**values, "prompt": "private"})
    with pytest.raises(ValidationError):
        CacheSummary(
            input_tokens=0, cached_input_tokens=0, hit_ratio=float("nan"), measured_requests=0, unknown_requests=0
        )
    with pytest.raises(ValidationError):
        QuotaSummary(
            known_accounts=0,
            used_percent_mean=float("inf"),
            reset_at_earliest=None,
            reset_at_latest=None,
            recorded_at_oldest=None,
            recorded_at_newest=None,
        )
