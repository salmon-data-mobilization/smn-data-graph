"""Shared helper for documented stubs (internal)."""

from __future__ import annotations


def not_yet(name: str, owner_note: str = "") -> NotImplementedError:
    """The error every stub raises: names the function and points at INTERFACES.md."""
    msg = (f"salmongraph.{name} is a documented stub; see salmongraph/INTERFACES.md and the "
           "docstring for its contract")
    if owner_note:
        msg += f" ({owner_note})"
    return NotImplementedError(msg)
