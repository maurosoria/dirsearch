from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable

from lib.connection.response import BaseResponse
from lib.parse.url import clean_path
from lib.utils.common import replace_path
from lib.utils.diff import normalize_dynamic_content


RUNTIME_MATCH_STREAK_THRESHOLD = 8


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
