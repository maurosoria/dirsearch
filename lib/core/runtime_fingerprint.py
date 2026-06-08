from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable

from lib.connection.response import BaseResponse
from lib.parse.url import clean_path
from lib.utils.common import replace_path
from lib.utils.diff import normalize_dynamic_content


RUNTIME_MATCH_STREAK_THRESHOLD = 8


class DisabledRuntimeFilter:
    def __init__(self) -> None:
        self.recalibration_events: list[str] = []

    def add_fingerprints(self, fingerprints: set[tuple]) -> None:
        del fingerprints

    def is_filtered(self, response: BaseResponse) -> bool:
        del response
        return False

    def record_match(self, response: BaseResponse) -> None:
        del response

    def reset(self) -> None:
        return None


class PreflightRuntimeFilter:
    def __init__(self) -> None:
        self.fingerprints: set[tuple] = set()
        self.match_streak: list[BaseResponse] = []
        self.recalibration_events: list[str] = []

    def add_fingerprints(self, fingerprints: set[tuple]) -> None:
        self.fingerprints.update(fingerprints)

    def is_filtered(self, response: BaseResponse) -> bool:
        return response_fingerprint(response) in self.fingerprints

    def record_match(self, response: BaseResponse) -> None:
        self.match_streak.append(response)
        fingerprints, reason = repeated_match_recalibration(self.match_streak)
        if not fingerprints:
            return

        self.add_fingerprints(fingerprints)
        self.recalibration_events.append(reason or "repeated_match_fingerprint")
        self.reset()

    def reset(self) -> None:
        self.match_streak.clear()


RuntimeFilter = DisabledRuntimeFilter | PreflightRuntimeFilter


def build_runtime_filter(enabled: bool) -> RuntimeFilter:
    if enabled:
        return PreflightRuntimeFilter()

    return DisabledRuntimeFilter()


def response_fingerprint(response: BaseResponse) -> tuple:
    body = normalize_dynamic_content(response.text)
    path = clean_path(response.full_path).strip("/")
    redirect = clean_path(response.redirect)
    if path:
        body = _replace_reflected_path(body, path)
        redirect = _replace_reflected_path(redirect, path)
    return (
        response.status,
        response.type,
        redirect,
        len(body) // 64,
        hashlib.sha256(body[:4096].encode()).hexdigest(),
    )


def _replace_reflected_path(value: str, path: str) -> str:
    value = replace_path(value, path, "__PATH__")
    return value.replace(path, "__PATH__")


def repeated_match_recalibration(
    responses: Iterable[BaseResponse],
    *,
    threshold: int = RUNTIME_MATCH_STREAK_THRESHOLD,
) -> tuple[set[tuple], str | None]:
    fingerprints = [response_fingerprint(response) for response in responses]
    if len(fingerprints) < threshold:
        return set(), None

    most_common, count = Counter(fingerprints).most_common(1)[0]
    if count < threshold:
        return set(), None

    return {most_common}, "repeated_match_fingerprint"
