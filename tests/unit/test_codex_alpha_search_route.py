from fastapi.routing import APIRoute

from app.modules.proxy.api import codex_alpha_search, router, v1_router


def test_codex_alpha_search_route_is_post_only() -> None:
    routes = [
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/backend-api/codex/alpha/search"
    ]

    assert len(routes) == 1
    assert routes[0].methods == {"POST"}


def test_codex_search_aliases_share_handler_without_adding_slash_or_methods() -> None:
    for family, path in [(router, "/backend-api/codex/alpha/search"), (v1_router, "/v1/alpha/search")]:
        routes = [route for route in family.routes if isinstance(route, APIRoute) and route.path == path]
        assert len(routes) == 1
        assert routes[0].endpoint is codex_alpha_search
        assert routes[0].methods == {"POST"}
        assert not any(isinstance(route, APIRoute) and route.path == path + "/" for route in family.routes)
