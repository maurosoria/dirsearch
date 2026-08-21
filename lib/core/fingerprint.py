from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from ipaddress import ip_address, ip_network
from typing import Any


class Strength(IntEnum):
    """Intrinsic, curator-assigned strength of a single fingerprint signal.

    Strength is a property of the *signal*, decided once by a human with a
    single yes/no question, not a tuned probability:

    * ``DEFINITIVE`` - emitted by exactly one provider (e.g. ``cf-ray``,
      ``x-amz-cf-id``); conclusive on its own.
    * ``STRONG`` - a vendor name in an otherwise shared field (``server`` /
      ``via`` values, TLS issuer, branded error text); identifying but
      spoofable or shared, so it needs corroboration to be conclusive.
    * ``WEAK`` - generic or shared-infrastructure evidence (IP range, CNAME
      suffix, generic cache headers, generic block phrases); only corroborating.
    """

    WEAK = 1
    STRONG = 2
    DEFINITIVE = 3


class Confidence(IntEnum):
    """Discrete, rule-derived certainty that the detected provider is correct.

    The value is an ordinal rank used only for comparison and promotion; there
    is no arithmetic and no calibratable threshold anywhere. See
    :func:`_certainty_for` for the exact rules that produce it.
    """

    NONE = 0
    BEHAVIORAL_ONLY = 1  # runtime denial observed, but no provider identified
    POSSIBLE = 2
    LIKELY = 3
    CONFIRMED = 4


# Display-only float projection of ``Confidence``. Kept so the preflight summary
# string and any legacy caller that prints a number keep working unchanged; it
# is exposed read-only through ``FingerprintResult.confidence``. Nothing may
# branch on it - read ``certainty`` instead. Slated for removal once every
# caller asserts the enum.
_CONFIDENCE_DISPLAY = {
    Confidence.NONE: 0.0,
    Confidence.BEHAVIORAL_ONLY: 0.4,
    Confidence.POSSIBLE: 0.5,
    Confidence.LIKELY: 0.75,
    Confidence.CONFIRMED: 0.95,
}


@dataclass(frozen=True)
class FingerprintMatch:
    provider: str
    category: str
    technique: str
    signal: str
    strength: Strength


@dataclass(frozen=True)
class FingerprintResult:
    provider: str | None = None
    category: str | None = None
    certainty: Confidence = Confidence.NONE
    reason: str = ""
    signals: tuple[str, ...] = ()
    headers_seen: Mapping[str, str] = field(default_factory=dict)
    behavior_tags: tuple[str, ...] = ()
    matches: tuple[FingerprintMatch, ...] = ()

    @property
    def confidence(self) -> float:
        """Display-only float view of :attr:`certainty` (see ``_CONFIDENCE_DISPLAY``).

        Provided for backwards compatibility with callers that print a numeric
        confidence. Do not branch on this value; use :attr:`certainty`.
        """
        return _CONFIDENCE_DISPLAY.get(self.certainty, 0.0)


# Higher = preferred when two providers are otherwise tied during selection.
CATEGORY_PREFERENCE = {
    "waf": 3,
    "cdn": 2,
    "common": 1,
}

# Techniques observed directly on the HTTP response (vs. inferred from DNS/IP).
# A provider backed by any of these outranks one known only by network range.
HTTP_TECHNIQUES = frozenset({"header", "cookie", "body_marker", "tls_cert"})

# Runtime denial tags that mean "the target actively blocked the probe". These
# mirror the strong denial reasons produced by preflight.denial_behavior_tags();
# the set is kept local so this leaf module never imports the opt-in preflight
# engine. A provider is never created from these alone.
DENIAL_BEHAVIOR_TAGS = frozenset({
    "waf_rate_limit",
    "waf_challenge",
    "waf_5xx_denial",
    "waf_connection_denial",
})

# The subset strong enough to upgrade an already-identified provider by exactly
# one certainty tier. Generic noise (e.g. scanner_false_positive_burst, bare
# 5xx/connection drops) must not inflate certainty, so it is excluded.
PROMOTING_BEHAVIOR_TAGS = frozenset({"waf_challenge", "waf_rate_limit"})


WEAK, STRONG, DEFINITIVE = Strength.WEAK, Strength.STRONG, Strength.DEFINITIVE

# Each signal carries a discrete Strength (see the Strength docstring), not a
# tuned float. Read each row as: "if this signal is present, how conclusive is
# it on its own?". DEFINITIVE = unique to this provider; STRONG = vendor name in
# a shared/spoofable field; WEAK = generic.
HTTP_SIGNATURES = (
    {
        "provider": "cloudflare",
        "category": "waf",
        "headers": (
            ("cf-ray", "", DEFINITIVE),
            ("cf-cache-status", "", STRONG),
            ("cf-mitigated", "", DEFINITIVE),
            ("cf-chl-out", "", DEFINITIVE),
            ("server", "cloudflare", STRONG),
        ),
        "cookies": (("__cf_bm", STRONG), ("_cfuvid", STRONG), ("cf_clearance", DEFINITIVE)),
        "body_markers": (
            ("checking your browser", WEAK),
            ("cloudflare ray id", STRONG),
            ("cf-browser-verification", STRONG),
        ),
        "tls_cert": (("cloudflare", STRONG),),
    },
    {
        "provider": "akamai",
        "category": "cdn",
        "headers": (
            ("akamai-grn", "", DEFINITIVE),
            ("aka-global-request-id-uxtime", "", DEFINITIVE),
            ("x-akamai-transformed", "", DEFINITIVE),
            ("server-timing", "ak_p", STRONG),
            ("server", "akamai", STRONG),
        ),
        "cookies": (("_abck", STRONG), ("ak_bmsc", STRONG), ("bm_sz", STRONG)),
        "body_markers": (("reference #", WEAK), ("akamai", STRONG)),
        "tls_cert": (("akamai", STRONG),),
    },
    {
        "provider": "fastly",
        "category": "cdn",
        "headers": (
            ("fastly-debug-digest", "", DEFINITIVE),
            ("x-served-by", "cache-", WEAK),
            ("x-cache-hits", "", WEAK),
            ("x-timer", "", WEAK),
            ("server", "fastly", STRONG),
            ("via", "fastly", STRONG),
        ),
        "body_markers": (("fastly error", STRONG),),
        "tls_cert": (("fastly", STRONG),),
    },
    {
        "provider": "cloudfront",
        "category": "cdn",
        "headers": (
            ("x-amz-cf-id", "", DEFINITIVE),
            ("x-amz-cf-pop", "", DEFINITIVE),
            ("x-cache", "cloudfront", STRONG),
            ("via", "cloudfront", STRONG),
            ("server", "cloudfront", STRONG),
        ),
        "body_markers": (("generated by cloudfront", STRONG),),
        "tls_cert": (("amazon", WEAK), ("aws", WEAK)),
    },
    {
        "provider": "aws_waf",
        "category": "waf",
        "headers": (
            ("x-amzn-waf-action", "", DEFINITIVE),
            ("x-amzn-requestid", "", WEAK),
        ),
        # "request blocked" intentionally omitted: it is a generic denial phrase,
        # not an AWS WAF signal, and x-amzn-requestid is emitted by every AWS
        # service - together they must not corroborate to a confident verdict.
        "body_markers": (("aws waf", STRONG),),
    },
    {
        "provider": "incapsula",
        "category": "waf",
        "headers": (
            ("x-iinfo", "", DEFINITIVE),
            ("x-cdn", "incapsula", STRONG),
            ("x-ic-request-id", "", DEFINITIVE),
            ("x-incap-client-ip", "", DEFINITIVE),
            ("server", "incapsula", STRONG),
            ("server", "imperva", STRONG),
        ),
        "cookies": (("incap_ses", STRONG), ("visid_incap", STRONG)),
        "body_markers": (
            ("request unsuccessful. incapsula", STRONG),
            ("powered by imperva", STRONG),
            ("incident id", WEAK),
        ),
        "tls_cert": (("imperva", STRONG), ("incapsula", STRONG)),
    },
    {
        "provider": "sucuri",
        "category": "waf",
        "headers": (
            ("x-sucuri-id", "", DEFINITIVE),
            ("x-sucuri-cache", "", STRONG),
            ("x-sucuri-block", "", DEFINITIVE),
            ("server", "sucuri", STRONG),
        ),
        "body_markers": (("sucuri website firewall", STRONG), ("access denied - sucuri", STRONG)),
        "tls_cert": (("sucuri", STRONG),),
    },
    {
        "provider": "datadome",
        "category": "waf",
        "headers": (
            ("x-datadome", "", DEFINITIVE),
            ("datadome", "", DEFINITIVE),
        ),
        "cookies": (("datadome", STRONG),),
        # Bare brand word in body text is corroborating only (it appears in
        # prose); the cookie/headers carry the conclusive evidence.
        "body_markers": (("datadome", WEAK),),
    },
    {
        "provider": "f5_bigip",
        "category": "waf",
        "headers": (
            ("x-wa-info", "", STRONG),
            ("x-f5", "", STRONG),
            ("server", "big-ip", STRONG),
            ("server", "bigip", STRONG),
        ),
        "cookies": (("bigipserver", STRONG), ("f5avrbbbbbbbbbbbb", STRONG)),
        "body_markers": (("the requested url was rejected", WEAK),),
    },
    {
        "provider": "barracuda",
        "category": "waf",
        "headers": (
            ("x-barracuda", "", DEFINITIVE),
            ("server", "barracuda", STRONG),
        ),
        "cookies": (("barra_counter_session", STRONG), ("bni_", WEAK)),
        "body_markers": (("barracuda web application firewall", STRONG),),
        "tls_cert": (("barracuda", STRONG),),
    },
    {
        "provider": "cloudbric",
        "category": "waf",
        "headers": (("x-cloudbric", "", DEFINITIVE),),
        "cookies": (("cloudbric", STRONG),),
        "body_markers": (("cloudbric", STRONG),),
        "tls_cert": (("cloudbric", STRONG),),
    },
    {
        "provider": "azure_front_door",
        "category": "cdn",
        "headers": (
            ("x-azure-ref", "", DEFINITIVE),
            ("x-fd-int-roxy-purgeid", "", DEFINITIVE),
        ),
        "tls_cert": (("microsoft azure", WEAK), ("azure", WEAK)),
    },
)


def fingerprint_headers(
    headers: Mapping[str, str] | Iterable[tuple[str, str]],
    *,
    dataset: Mapping[str, Any] | None = None,
    behavior_tags: Iterable[str] = (),
) -> FingerprintResult:
    return fingerprint_response(headers, dataset=dataset, behavior_tags=behavior_tags)


def fingerprint_response(
    headers: Mapping[str, str] | Iterable[tuple[str, str]],
    *,
    body: str | bytes = "",
    dns_cnames: Iterable[str] = (),
    resolved_ips: Iterable[str] = (),
    tls_cert: Mapping[str, Any] | Iterable[str] | str | None = None,
    dataset: Mapping[str, Any] | None = None,
    behavior_tags: Iterable[str] = (),
) -> FingerprintResult:
    normalized = _normalize_headers(headers)
    behavior_tags = tuple(behavior_tags)  # materialize once: it is read twice below
    matches = []
    matches.extend(_match_http_signatures(normalized, body, tls_cert))
    matches.extend(_match_cname_suffixes(dns_cnames, dataset))
    matches.extend(_match_ip_cidrs(resolved_ips, dataset))
    matches = _dedupe_matches(matches)
    provider, category, certainty, reason = _select_primary_match(matches, behavior_tags)

    return FingerprintResult(
        provider=provider,
        category=category,
        certainty=certainty,
        reason=reason,
        signals=tuple(dict.fromkeys(match.signal for match in matches)),
        headers_seen=normalized,
        behavior_tags=tuple(dict.fromkeys(behavior_tags)),
        matches=tuple(matches),
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
    matches: list[FingerprintMatch] = []

    for fingerprint in fingerprints:
        headers.update(fingerprint.headers_seen)
        signals.extend(fingerprint.signals)
        tags.extend(fingerprint.behavior_tags)
        matches.extend(fingerprint.matches)
        if (
            fingerprint.provider
            and not fingerprint.matches
            and fingerprint.certainty >= Confidence.POSSIBLE
        ):
            matches.append(
                FingerprintMatch(
                    fingerprint.provider,
                    fingerprint.category or "common",
                    "legacy",
                    f"legacy:{fingerprint.provider}",
                    _certainty_to_strength(fingerprint.certainty),
                )
            )

    matches = _dedupe_matches(matches)
    provider, category, certainty, reason = _select_primary_match(matches, tags)

    return FingerprintResult(
        provider=provider,
        category=category,
        certainty=certainty,
        reason=reason,
        signals=tuple(dict.fromkeys(signals + [match.signal for match in matches])),
        headers_seen=headers,
        behavior_tags=tuple(dict.fromkeys(tags)),
        matches=tuple(matches),
    )


def _match_http_signatures(
    headers: Mapping[str, str],
    body: str | bytes,
    tls_cert: Mapping[str, Any] | Iterable[str] | str | None,
) -> list[FingerprintMatch]:
    matches: list[FingerprintMatch] = []
    lowered_headers = {name: value.lower() for name, value in headers.items()}
    cookie_source = "; ".join(
        value for name, value in lowered_headers.items() if name in ("set-cookie", "cookie")
    )
    body_text = _normalize_text(body[:4096] if isinstance(body, bytes) else str(body)[:4096])
    tls_text = _normalize_tls_cert_text(tls_cert)

    for signature in HTTP_SIGNATURES:
        provider = str(signature["provider"])
        category = str(signature["category"])
        for name, value_pattern, strength in signature.get("headers", ()):
            value = lowered_headers.get(name)
            if value is None:
                continue
            if value_pattern and str(value_pattern).lower() not in value:
                continue
            matches.append(
                FingerprintMatch(provider, category, "header", f"header:{name}", strength)
            )

        for marker, strength in signature.get("cookies", ()):
            marker = str(marker).lower()
            if marker in cookie_source:
                matches.append(
                    FingerprintMatch(provider, category, "cookie", f"cookie:{marker}", strength)
                )

        for marker, strength in signature.get("body_markers", ()):
            marker = str(marker).lower()
            if marker in body_text:
                matches.append(
                    FingerprintMatch(
                        provider, category, "body_marker", f"body_marker:{marker}", strength
                    )
                )

        for marker, strength in signature.get("tls_cert", ()):
            marker = str(marker).lower()
            if marker in tls_text:
                matches.append(
                    FingerprintMatch(
                        provider, category, "tls_cert", f"tls_cert:{marker}", strength
                    )
                )

    return matches


def _match_cname_suffixes(
    cnames: Iterable[str],
    dataset: Mapping[str, Any] | None,
) -> list[FingerprintMatch]:
    suffixes = _cname_suffixes(dataset)
    if not suffixes:
        return []

    matches: list[FingerprintMatch] = []
    for cname in cnames:
        normalized = _normalize_hostname(cname)
        if not normalized:
            continue
        for provider, suffix in suffixes:
            if normalized == suffix or normalized.endswith(f".{suffix}"):
                matches.append(
                    FingerprintMatch(
                        provider, "common", "cname_suffix", f"cname_suffix:{suffix}", WEAK
                    )
                )
    return matches


def _match_ip_cidrs(
    ips: Iterable[str],
    dataset: Mapping[str, Any] | None,
) -> list[FingerprintMatch]:
    networks = _cidr_networks(dataset)
    matches: list[FingerprintMatch] = []
    for raw_ip in ips:
        try:
            address = ip_address(str(raw_ip))
        except ValueError:
            continue

        for category in ("cdn", "waf"):
            for provider, provider_networks in networks.get(category, {}).items():
                for network in provider_networks:
                    if address in network:
                        matches.append(
                            FingerprintMatch(
                                provider,
                                category,
                                "ip_cidr",
                                f"ip_cidr:{network.with_prefixlen}",
                                WEAK,
                            )
                        )
                        break
    return matches


def _certainty_for(matches: Iterable[FingerprintMatch]) -> Confidence:
    """Map a single provider's matches to a discrete certainty via fixed rules.

    Corroboration counts *distinct techniques* (header/cookie/body/tls/cname/ip),
    not raw signals, so five Cloudflare headers do not masquerade as independent
    evidence; duplicate-technique hits collapse to their strongest member.

        any DEFINITIVE technique          -> CONFIRMED
        >= 2 STRONG techniques            -> CONFIRMED   (independent corroboration)
        exactly 1 STRONG technique        -> LIKELY
        >= 2 WEAK techniques              -> LIKELY
        exactly 1 WEAK technique          -> POSSIBLE
    """
    strongest_by_technique: dict[str, Strength] = {}
    for match in matches:
        current = strongest_by_technique.get(match.technique)
        if current is None or match.strength > current:
            strongest_by_technique[match.technique] = match.strength

    if not strongest_by_technique:
        return Confidence.NONE

    best = max(strongest_by_technique.values())
    if best == Strength.DEFINITIVE:
        return Confidence.CONFIRMED
    if best == Strength.STRONG:
        strong_techniques = sum(1 for s in strongest_by_technique.values() if s == Strength.STRONG)
        return Confidence.CONFIRMED if strong_techniques >= 2 else Confidence.LIKELY
    # Only WEAK techniques remain.
    return Confidence.LIKELY if len(strongest_by_technique) >= 2 else Confidence.POSSIBLE


def _promote_certainty(certainty: Confidence, behavior_tags: Iterable[str]) -> Confidence:
    """Raise an identified provider's certainty by one tier on active denial.

    A genuine runtime block (waf_challenge / waf_rate_limit) corroborates the
    static signal, so it bumps the verdict up exactly one tier, capped at
    CONFIRMED. It can never create a provider or jump more than one tier, so it
    cannot fabricate CONFIRMED out of WEAK-only evidence.
    """
    if certainty >= Confidence.CONFIRMED:
        return certainty
    if any(tag in PROMOTING_BEHAVIOR_TAGS for tag in behavior_tags):
        return Confidence(min(int(Confidence.CONFIRMED), int(certainty) + 1))
    return certainty


def _select_primary_match(
    matches: Iterable[FingerprintMatch],
    behavior_tags: Iterable[str] = (),
) -> tuple[str | None, str | None, Confidence, str]:
    matches = tuple(matches)
    behavior_tags = tuple(behavior_tags)
    if not matches:
        if any(tag in DENIAL_BEHAVIOR_TAGS for tag in behavior_tags):
            return None, None, Confidence.BEHAVIORAL_ONLY, _behavioral_reason(behavior_tags)
        return None, None, Confidence.NONE, ""

    by_provider: dict[str, list[FingerprintMatch]] = defaultdict(list)
    for match in matches:
        by_provider[match.provider].append(match)

    def provider_rank(provider: str) -> tuple[int, int, int, int, str]:
        provider_matches = by_provider[provider]
        return (
            int(_certainty_for(provider_matches)),
            int(any(match.technique in HTTP_TECHNIQUES for match in provider_matches)),
            len({match.technique for match in provider_matches}),
            CATEGORY_PREFERENCE.get(_best_category(provider_matches) or "", 0),
            provider,
        )

    provider = max(by_provider, key=provider_rank)
    chosen = by_provider[provider]
    category = _best_category(chosen)
    raw_certainty = _certainty_for(chosen)
    certainty = _promote_certainty(raw_certainty, behavior_tags)
    return provider, category, certainty, _explain(chosen, raw_certainty, certainty)


def _best_category(matches: Iterable[FingerprintMatch]) -> str | None:
    strongest_by_category: dict[str, Strength] = {}
    for match in matches:
        current = strongest_by_category.get(match.category)
        if current is None or match.strength > current:
            strongest_by_category[match.category] = match.strength
    if not strongest_by_category:
        return None
    return max(
        strongest_by_category,
        key=lambda category: (
            strongest_by_category[category],
            CATEGORY_PREFERENCE.get(category, 0),
            category,
        ),
    )


def _explain(
    matches: Iterable[FingerprintMatch],
    raw_certainty: Confidence,
    certainty: Confidence,
) -> str:
    matches = tuple(matches)
    strongest = max(matches, key=lambda match: (match.strength, match.signal))
    techniques = {match.technique for match in matches}
    reason = f"{strongest.strength.name.lower()} signal {strongest.signal}"
    extra = len(techniques) - 1
    if extra > 0:
        reason += f" + {extra} corroborating technique{'s' if extra > 1 else ''}"
    if certainty > raw_certainty:
        reason += " + runtime denial behavior"
    return reason


def _behavioral_reason(behavior_tags: Iterable[str]) -> str:
    denial = [tag for tag in behavior_tags if tag in DENIAL_BEHAVIOR_TAGS]
    return "runtime denial behavior: " + ", ".join(dict.fromkeys(denial))


def _certainty_to_strength(certainty: Confidence) -> Strength:
    if certainty >= Confidence.CONFIRMED:
        return Strength.DEFINITIVE
    if certainty >= Confidence.LIKELY:
        return Strength.STRONG
    return Strength.WEAK


def _dedupe_matches(matches: Iterable[FingerprintMatch]) -> list[FingerprintMatch]:
    deduped: dict[tuple[str, str, str, str], FingerprintMatch] = {}
    for match in matches:
        key = (match.provider, match.category, match.technique, match.signal)
        current = deduped.get(key)
        if current is None or match.strength > current.strength:
            deduped[key] = match
    return list(deduped.values())


def _normalize_headers(headers: Mapping[str, str] | Iterable[tuple[str, str]]) -> dict[str, str]:
    if hasattr(headers, "items"):
        pairs = headers.items()
    else:
        pairs = headers

    return {str(key).lower(): str(value) for key, value in pairs}


def _normalize_text(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore").lower()
    return str(value).lower()


def _normalize_tls_cert_text(tls_cert: Mapping[str, Any] | Iterable[str] | str | None) -> str:
    if tls_cert is None:
        return ""
    if isinstance(tls_cert, str):
        return tls_cert.lower()
    if isinstance(tls_cert, Mapping):
        values: list[str] = []
        for value in tls_cert.values():
            if isinstance(value, (list, tuple, set)):
                values.extend(str(item) for item in value)
            else:
                values.append(str(value))
        return " ".join(values).lower()
    return " ".join(str(value) for value in tls_cert).lower()


def _normalize_hostname(hostname: str) -> str:
    return str(hostname).strip().lower().rstrip(".")


def _dataset_categories(dataset: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not dataset:
        return {}

    categories = dataset.get("categories", {})
    if isinstance(categories, Mapping):
        return categories

    return {}


def _cname_suffixes(dataset: Mapping[str, Any] | None) -> tuple[tuple[str, str], ...]:
    common = _dataset_categories(dataset).get("common", {})
    if not isinstance(common, Mapping):
        return ()

    suffixes: list[tuple[str, str]] = []
    for provider, values in common.items():
        if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
            continue
        for value in values:
            suffix = _normalize_hostname(value)
            if suffix:
                suffixes.append((str(provider).lower(), suffix))
    return tuple(suffixes)


def _cidr_networks(dataset: Mapping[str, Any] | None) -> dict[str, dict[str, tuple[Any, ...]]]:
    categories = _dataset_categories(dataset)
    compiled: dict[str, dict[str, tuple[Any, ...]]] = {"cdn": {}, "waf": {}}
    for category in ("cdn", "waf"):
        providers = categories.get(category, {})
        if not isinstance(providers, Mapping):
            continue
        for provider, cidrs in providers.items():
            if not isinstance(cidrs, Iterable) or isinstance(cidrs, (str, bytes)):
                continue
            networks = []
            for cidr in cidrs:
                try:
                    networks.append(ip_network(str(cidr), strict=False))
                except ValueError:
                    continue
            compiled[category][str(provider).lower()] = tuple(networks)
    return compiled
