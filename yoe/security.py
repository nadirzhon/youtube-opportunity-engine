"""
Security (Phase 8) — API-key auth + simple RBAC, as a FastAPI dependency.

Least-privilege by default: publishing/build routes can require a role. Keys and
roles come from the environment (never hard-coded). When no keys are configured
the API is open in local/dev mode — production sets YOE_API_KEYS to lock it.

  YOE_API_KEYS="viewerkey:viewer,adminkey:admin"
Requests send `X-API-Key: <key>`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

ROLE_RANK = {"viewer": 1, "editor": 2, "admin": 3}


@dataclass(frozen=True)
class Principal:
    key: str
    role: str

    def can(self, required: str) -> bool:
        return ROLE_RANK.get(self.role, 0) >= ROLE_RANK.get(required, 99)


def _load_keys() -> dict[str, str]:
    raw = os.environ.get("YOE_API_KEYS", "").strip()
    keys: dict[str, str] = {}
    for pair in raw.split(","):
        if ":" in pair:
            k, role = pair.split(":", 1)
            keys[k.strip()] = role.strip()
    return keys


def authenticate(api_key: str | None) -> Principal:
    """Return the caller's principal. Open (admin) when no keys are configured."""
    keys = _load_keys()
    if not keys:
        return Principal("dev", "admin")          # local/dev mode: unlocked
    if not api_key or api_key not in keys:
        raise PermissionError("missing or invalid API key")
    return Principal(api_key, keys[api_key])


def require(principal: Principal, role: str) -> None:
    if not principal.can(role):
        raise PermissionError(f"role '{role}' required (have '{principal.role}')")
