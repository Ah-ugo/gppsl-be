"""Ordered signing rules."""
from __future__ import annotations

from typing import Any


def signing_turn(signers: list[dict[str, Any]], user_id: str) -> bool:
    """True only when `user_id` is a pending signer and every earlier signer has signed."""
    mine = next((s for s in signers if str(s.get("user_id")) == str(user_id)), None)
    if mine is None or mine.get("status") != "pending":
        return False
    return all(
        s.get("status") == "signed" for s in signers if int(s.get("order", 0)) < int(mine.get("order", 0))
    )


def next_signer(signers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The signer who must act next, or None when everyone has signed."""
    pending = [s for s in signers if s.get("status") == "pending"]
    return min(pending, key=lambda s: int(s.get("order", 0))) if pending else None


def request_status(signers: list[dict[str, Any]]) -> str:
    """'Signed' when all signed, otherwise 'Awaiting signature'."""
    return "Signed" if signers and all(s.get("status") == "signed" for s in signers) else "Awaiting signature"
