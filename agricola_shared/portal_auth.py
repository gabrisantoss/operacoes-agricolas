from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen


def read_portal_session(
    cookie_header: str | None,
    *,
    portal_url: str | None = None,
    timeout: float = 2.0,
) -> dict | None:
    cookie = str(cookie_header or "").strip()
    if not cookie:
        return None

    base_url = (portal_url or os.environ.get("AGRICOLA_PORTAL_SESSION_URL") or "http://127.0.0.1:8890").rstrip("/")
    request = Request(
        f"{base_url}/api/session",
        headers={"Cookie": cookie, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        return None

    if not payload.get("authenticated"):
        return None
    user = payload.get("user")
    return dict(user) if isinstance(user, dict) else None


@dataclass(frozen=True)
class PortalAccessDecision:
    allowed: bool
    reason: str


def evaluate_portal_access(user: dict | None, *, maintenance_mode: bool = False) -> PortalAccessDecision:
    """Apply the minimum module-side access policy.

    Every normal request requires an authenticated portal user. Maintenance mode
    additionally restricts the module to portal administrators.
    """

    if not user:
        return PortalAccessDecision(False, "authentication_required")
    if maintenance_mode and str(user.get("role") or "").strip().lower() != "admin":
        return PortalAccessDecision(False, "maintenance_admin_required")
    return PortalAccessDecision(True, "allowed")


def resolve_path_within_root(root: str | Path, stored_path: str | Path | None) -> Path | None:
    """Resolve a stored path while confining it to one explicit storage root."""

    if stored_path in (None, ""):
        return None
    storage_root = Path(root).expanduser().resolve()
    raw = Path(str(stored_path)).expanduser()
    candidate = raw.resolve() if raw.is_absolute() else (storage_root / raw).resolve()
    try:
        candidate.relative_to(storage_root)
    except ValueError:
        return None
    return candidate
