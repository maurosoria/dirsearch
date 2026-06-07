from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FingerprintResult:
    provider: str | None = None
    confidence: float = 0.0
    signals: tuple[str, ...] = ()
    headers_seen: Mapping[str, str] = field(default_factory=dict)
    behavior_tags: tuple[str, ...] = ()


HEADER_SIGNATURES = {
    "cloudflare": (
        ("cf-ray", ""),
        ("cf-cache-status", ""),
        ("server", "cloudflare"),
    ),
    "akamai": (
        ("akamai-grn", ""),
        ("aka-global-request-id-uxtime", ""),
        ("x-akamai-transformed", ""),
        ("server-timing", "ak_p"),
        ("server", "akamai"),
    ),
}


def fingerprint_headers(
    headers: Mapping[str, str] | Iterable[tuple[str, str]],
    *,
    behavior_tags: Iterable[str] = (),
) -> FingerprintResult:
    normalized = _normalize_headers(headers)
    signals: list[str] = []
    provider_scores: Counter[str] = Counter()

    for provider, signatures in HEADER_SIGNATURES.items():
        for name, value_pattern in signatures:
            value = normalized.get(name)
            if value is None:
                continue
            if value_pattern and value_pattern not in value.lower():
                continue
            provider_scores[provider] += 1
            signals.append(f"header:{name}")

    provider = None
    confidence = 0.0
    if provider_scores:
        provider, score = provider_scores.most_common(1)[0]
        confidence = min(1.0, score / 3)

    tags = tuple(dict.fromkeys(behavior_tags))
    if tags and confidence < 0.4:
        confidence = 0.4

    return FingerprintResult(
        provider=provider,
        confidence=confidence,
        signals=tuple(dict.fromkeys(signals)),
        headers_seen=normalized,
        behavior_tags=tags,
    )


def merge_fingerprints(
    fingerprints: Iterable[FingerprintResult],
    *,
    behavior_tags: Iterable[str] = (),
) -> FingerprintResult:
    fingerprints = tuple(fingerprints)
    headers: dict[str, str] = {}
    signals: list[str] = []
    tags: list[str] = list(behavior_tags)
    provider_scores: Counter[str] = Counter()

    for fingerprint in fingerprints:
        headers.update(fingerprint.headers_seen)
        signals.extend(fingerprint.signals)
        tags.extend(fingerprint.behavior_tags)
        if fingerprint.provider:
            provider_scores[fingerprint.provider] += max(1, int(fingerprint.confidence * 3))

    provider = None
    confidence = 0.0
    if provider_scores:
        provider, score = provider_scores.most_common(1)[0]
        confidence = min(1.0, score / 3)
    elif tags:
        confidence = 0.4

    return FingerprintResult(
        provider=provider,
        confidence=confidence,
        signals=tuple(dict.fromkeys(signals)),
        headers_seen=headers,
        behavior_tags=tuple(dict.fromkeys(tags)),
    )


def _normalize_headers(headers: Mapping[str, str] | Iterable[tuple[str, str]]) -> dict[str, str]:
    if isinstance(headers, Mapping):
        pairs = headers.items()
    else:
        pairs = headers

    return {str(key).lower(): str(value) for key, value in pairs}
