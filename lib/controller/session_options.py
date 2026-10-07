"""Owned normalized input for persistence, distinct from runtime policies."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True, init=False)
class SessionOptions:
    """An opaque value with copy-in/copy-out access, not a mutable mapping.

    Keep normalized Python types, unknown keys and absent fields intact. Runtime
    policies are intentionally lossy adapters and cannot reconstruct this input.
    Only SessionStore translates it to the historical JSON representation.

    The private payload is never returned or mutated after construction. Callers
    receive independent copies, and changing the save destination creates a new
    value. Neither targets nor live resources belong here. Omit all payload data
    from repr because it can include credentials, headers and request bodies.
    """

    _values: dict[str, Any] = field(repr=False)

    def __init__(self, values: Mapping[str, Any] | None = None) -> None:
        if values is None:
            values = {}
        if not isinstance(values, Mapping):
            raise TypeError("SessionOptions input must be a mapping")
        if "urls" in values:
            raise ValueError("Session targets belong in remaining_tasks, not options")
        object.__setattr__(self, "_values", deepcopy(dict(values)))

    @classmethod
    def from_options(cls, values: Mapping[str, Any]) -> SessionOptions:
        """Capture normalized CLI input, excluding the separately owned queue.

        This boundary intentionally projects out URLs; direct construction from
        already separated session data rejects a second target queue instead.
        Do not fill defaults or derive input from runtime configuration here.
        """
        return cls({key: value for key, value in values.items() if key != "urls"})

    def to_options(self) -> dict[str, Any]:
        """Return detached normalized data for CLI restoration or wire encoding."""
        return deepcopy(self._values)

    def with_session_file(self, path: str | None) -> SessionOptions:
        """Retain all prepared values while replacing only the save destination."""
        return SessionOptions({**self._values, "session_file": path})
