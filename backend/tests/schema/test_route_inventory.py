from collections.abc import Callable
from typing import Any

import pytest
from fastapi.routing import APIRoute

from app.auth.dependencies import (
    get_authenticated_user,
    get_booking_scope,
    get_patient_scope,
    get_provider_scope,
    get_staff_member,
    get_verified_patient,
)
from app.main import app

#: Dependencies that resolve a caller and constrain what they may reach. A PHI route must
#: sit behind one of these; reading the database any other way is unscoped by definition.
_SCOPE_GUARDS: set[Callable[..., Any]] = {
    get_patient_scope,
    get_booking_scope,
    get_provider_scope,
}

#: Routes that are deliberately reachable without a scope, each with the reason. Anything
#: not listed here must be guarded, so adding a PHI route without a scope fails this test
#: rather than shipping.
_UNGUARDED: dict[tuple[str, str], str] = {
    ("GET", "/health"): "liveness probe; reports reachability only, no patient data",
    ("POST", "/identity/verify"): "the identity check itself; it is what creates a scope",
    ("GET", "/identity/status"): "returns a single boolean; says nothing about the record",
    ("GET", "/s/{token}"): "public share link; the token is the credential and is audited",
}


def _dependencies(route: APIRoute) -> set[Any]:
    """Collect every dependency callable a route resolves, at any depth.

    Args:
        route: The route to inspect.

    Returns:
        The dependency callables.
    """
    found: set[Any] = set()
    pending = list(route.dependant.dependencies)
    while pending:
        dependency = pending.pop()
        if dependency.call is not None:
            found.add(dependency.call)
        pending.extend(dependency.dependencies)
    return found


def _routes() -> list[APIRoute]:
    """Return every API route the application serves, however deeply nested.

    `include_router` wraps its routes in a container in this version of FastAPI rather than
    flattening them into `app.routes`, so a shallow scan finds only the docs endpoints —
    and a scan that found nothing would let this whole file pass while checking nothing.

    Returns:
        Every `APIRoute` reachable from the application.
    """
    found: list[APIRoute] = []
    pending: list[Any] = list(app.routes)
    while pending:
        route = pending.pop()
        if isinstance(route, APIRoute):
            found.append(route)
            continue
        # `_IncludedRouter` keeps its routes on `original_router`; a plain Mount uses
        # `routes`. Both are followed so neither shape can hide an endpoint.
        nested = getattr(route, "original_router", None)
        pending.extend(getattr(nested, "routes", []) if nested else getattr(route, "routes", []))
    return found


def test_the_route_scan_actually_finds_routes() -> None:
    """Every other test in this file passes trivially if the scan returns nothing, which is
    exactly what happened when FastAPI changed how included routers are stored. This is the
    canary: it fails loudly rather than letting the suite go quietly green and blind.
    """
    paths = {route.path for route in _routes()}

    assert len(paths) > 20, f"route scan found only {len(paths)} paths; the traversal is broken"
    # A few load-bearing endpoints by name, so a scan that finds *some* routes but misses
    # whole routers is caught too.
    assert {"/studies", "/reports", "/appointments", "/provider/availability"} <= paths


def test_every_route_is_either_scoped_or_listed_as_deliberately_open() -> None:
    """The guarantee this whole build rests on is that patient data is unreachable without
    a scope. A new endpoint that forgets `get_patient_scope` would not fail any existing
    test — it would simply be an unguarded hole. This makes forgetting a build failure.
    """
    unguarded: list[str] = []
    for route in _routes():
        for method in sorted(route.methods or set()):
            if (method, route.path) in _UNGUARDED:
                continue
            if not (_dependencies(route) & _SCOPE_GUARDS):
                unguarded.append(f"{method} {route.path}")

    assert unguarded == [], (
        "These routes reach the application without a scope dependency. Add one, or if the "
        f"route genuinely exposes no patient data, list it in _UNGUARDED with a reason: {unguarded}"
    )


def test_the_deliberately_open_list_has_no_stale_entries() -> None:
    """An exemption for a route that no longer exists is an exemption nobody is checking —
    and the name could later be reused by a route that does serve patient data."""
    live = {
        (method, route.path) for route in _routes() for method in sorted(route.methods or set())
    }
    stale = [f"{method} {path}" for method, path in _UNGUARDED if (method, path) not in live]

    assert stale == [], f"_UNGUARDED lists routes that no longer exist: {stale}"


@pytest.mark.parametrize(
    "guard", [get_patient_scope, get_booking_scope], ids=["patient_scope", "booking_scope"]
)
def test_patient_scopes_are_built_only_behind_the_identity_check(guard: Any) -> None:
    """A valid login is not enough to reach protected health information — the ID and
    date-of-birth check is the second factor (Core #2). If a scope could be constructed
    without it, every patient route would silently lose that factor.
    """
    route = next(candidate for candidate in _routes() if guard in _dependencies(candidate))

    assert get_verified_patient in _dependencies(route)


def test_provider_routes_resolve_their_provider_from_the_staff_record() -> None:
    """A clinician must not be able to act for a colleague by changing a parameter. The
    provider is read from the caller's own staff row, so this asserts the staff lookup is
    actually in the chain rather than trusting a request field.
    """
    provider_routes = [route for route in _routes() if get_provider_scope in _dependencies(route)]

    assert provider_routes, "expected at least one provider-scoped route"
    for route in provider_routes:
        dependencies = _dependencies(route)
        assert get_staff_member in dependencies, route.path
        assert get_authenticated_user in dependencies, route.path
