from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, Security
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.core.auth.dependencies import validate_usage_api_key
from app.core.config.settings_cache import get_settings_cache
from app.core.exceptions import ProxyAuthError
from app.dependencies import LbSummaryContext, get_lb_summary_context
from app.modules.api_keys.service import ApiKeyData
from app.modules.lb_summary.schemas import LbSummary, Window


def denial(status: int, code: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code}}, headers={"Cache-Control": "no-store"})


class SummaryRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                response = await original(request)
            except ProxyAuthError:
                return denial(401, "invalid_api_key")
            except Exception:
                # Never return provider/DB exceptions or reflect credential/query values.
                return denial(500, "summary_unavailable")
            response.headers["Cache-Control"] = "no-store"
            return response

        return handle


router = APIRouter(prefix="/v1/lb", tags=["usage"], route_class=SummaryRoute)


@router.get("/summary", response_model=LbSummary, response_model_exclude_unset=True)
async def get_summary(
    request: Request,
    key: ApiKeyData = Security(validate_usage_api_key),
    context: LbSummaryContext = Depends(get_lb_summary_context),
) -> LbSummary | JSONResponse:
    if "lb_summary" not in {section.strip() for section in key.usage_sections.split(",")}:
        return denial(403, "lb_summary_not_allowed")
    params = request.query_params
    if set(params) - {"window"} or len(params.getlist("window")) > 1 or await request.body():
        return denial(400, "invalid_summary_query")
    raw_window = params.get("window", "24h")
    if raw_window not in ("1h", "24h", "7d"):
        return denial(400, "invalid_summary_query")
    window: Window = "1h" if raw_window == "1h" else "7d" if raw_window == "7d" else "24h"
    settings = await get_settings_cache().get()
    return await context.service.summary(key, window, not settings.hide_upstream_quota_from_api_keys)
