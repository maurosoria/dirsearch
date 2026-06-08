from __future__ import annotations

import asyncio
import hashlib
import time
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from lib.connection.dns import DNSResolution, resolve_host_records
from lib.core.data import options
from lib.core.dictionary import Dictionary
from lib.core.exceptions import RequestException
from lib.core.fingerprint import FingerprintResult, fingerprint_response, merge_fingerprints
from lib.core.settings import DEFAULT_TEST_PREFIXES, DEFAULT_TEST_SUFFIXES, WILDCARD_TEST_POINT_MARKER
from lib.parse.url import clean_path
from lib.utils.diff import normalize_dynamic_content
from lib.utils.random import rand_stealth_word

if TYPE_CHECKING:
    from lib.connection.requester import AsyncRequester, Requester
    from lib.connection.response import BaseResponse
    from lib.core.scanner import BaseScanner


PREFLIGHT_MATCH_STREAK_THRESHOLD = 8
PREFLIGHT_STEALTH_SAMPLE_COUNT = 4
PREFLIGHT_WORDLIST_SAMPLE_COUNT = 4
PREFLIGHT_SUSTAINED_DENIAL_COUNT = 2

WAF_DENIAL_STATUS_CODES = {403, 429}
WAF_BODY_MARKERS = (
    "access denied",
    "arkose",
    "captcha",
    "checking your browser",
    "datadome",
    "hcaptcha",
    "please enable cookies",
    "rate limit",
    "recaptcha",
    "request blocked",
    "temporarily blocked",
    "too many requests",
)
WAF_HEADER_NAMES = (
    "cf-chl-out",
    "cf-mitigated",
    "datadome",
    "x-datadome",
    "x-distil",
    "x-sucuri-block",
)
WAF_HEADER_VALUE_MARKERS = (
    "_abck",
    "_cfuvid",
    "ak_bmsc",
    "arkose",
    "bm_sz",
    "bot management",
    "captcha",
    "challenge",
    "cf_clearance",
    "datadome",
    "hcaptcha",
    "recaptcha",
)


@dataclass(frozen=True)
class PreflightProfile:
    name: str
    thread_count: int
    delay: float
    max_rate: int = 0


@dataclass(frozen=True)
class PreflightObservation:
    profile: PreflightProfile
    path: str
    expected_missing: bool
    status: int
    scanner_decisions: tuple[str, ...]
    matched: bool
    fingerprint: FingerprintResult
    runtime_fingerprint: tuple
    timestamp: float = 0.0
    elapsed: float = 0.0
    redirect: str = ""
    content_type: str = ""
    length: int = 0
    denial_reason: str | None = None


@dataclass
class PreflightResult:
    enabled: bool
    applied_profile: PreflightProfile
    original_profile: PreflightProfile
    observations: list[PreflightObservation] = field(default_factory=list)
    fingerprint: FingerprintResult = field(default_factory=FingerprintResult)
    behavior_tags: list[str] = field(default_factory=list)
    recalibrations: list[str] = field(default_factory=list)
    runtime_fingerprints: set[tuple] = field(default_factory=set)
    max_rate_supported: bool = True

    @property
    def adjusted(self) -> bool:
        return (
            self.applied_profile.thread_count != self.original_profile.thread_count
            or self.applied_profile.delay != self.original_profile.delay
            or self.applied_profile.max_rate != self.original_profile.max_rate
        )

    def summary(self) -> str:
        provider = self.fingerprint.provider or "unknown"
        category = self.fingerprint.category or "unknown"
        max_rate = (
            str(self.applied_profile.max_rate)
            if self.applied_profile.max_rate > 0
            else "unlimited"
        )
        if not self.max_rate_supported and self.applied_profile.max_rate > 0:
            max_rate += " recommended-not-applied"
        return (
            f"preflight provider={provider} category={category} "
            f"confidence={self.fingerprint.confidence:.2f} "
            f"threads={self.applied_profile.thread_count} delay={self.applied_profile.delay:g}s "
            f"max-rate={max_rate}"
        )


@dataclass(frozen=True)
class PreflightSample:
    path: str
    expected_missing: bool


def build_preflight_profiles(
    thread_count: int,
    delay: float,
    max_rate: int = 0,
) -> tuple[PreflightProfile, ...]:
    thread_count = max(1, int(thread_count))
    delay = max(0.0, float(delay))
    max_rate = max(0, int(max_rate))
    balanced_threads = max(1, thread_count // 2)
    slow_threads = max(1, thread_count // 4)
    candidates = (
        PreflightProfile("current", thread_count, delay, max_rate),
        PreflightProfile("rate-limited", thread_count, delay, max_rate or thread_count),
        PreflightProfile(
            "balanced",
            balanced_threads,
            max(delay, 0.05),
            max(1, min(max_rate or balanced_threads, balanced_threads)),
        ),
        PreflightProfile(
            "slow",
            slow_threads,
            max(delay, 0.15),
            max(1, min(max_rate or slow_threads, slow_threads)),
        ),
        PreflightProfile("conservative", 1, max(delay, 0.30), 1),
    )
    unique: list[PreflightProfile] = []
    seen = set()
    for profile in candidates:
        key = (profile.thread_count, profile.delay, profile.max_rate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(profile)
    return tuple(unique)


def sample_preflight_paths(
    dictionary: Dictionary | Iterable[str],
    *,
    base_path: str = "",
    extensions: Iterable[str] = (),
) -> tuple[PreflightSample, ...]:
    omitted = set()
    samples: list[PreflightSample] = []
    extensions = tuple(extensions)

    for index in range(PREFLIGHT_STEALTH_SAMPLE_COUNT):
        word = rand_stealth_word(omit=omitted)
        omitted.add(word)
        if index == 1:
            word = f".{word}"
        elif index == 2:
            word = f"{word}~"
        elif index == 3 and extensions:
            word = f"{word}.{extensions[0]}"
        samples.append(PreflightSample(base_path + word, True))

    for path in list(dictionary)[:PREFLIGHT_WORDLIST_SAMPLE_COUNT]:
        samples.append(PreflightSample(base_path + str(path).lstrip("/"), False))

    return tuple(samples)


def scanner_decisions(scanners: dict[str, dict[str, BaseScanner]], path: str, response: BaseResponse) -> tuple[str, ...]:
    decisions: list[str] = []
    cleaned = clean_path(path)
    for prefix, scanner in scanners["prefixes"].items():
        if cleaned.startswith(prefix):
            decisions.append(f"{scanner.context}:{scanner.classify(path, response)}")
    for suffix, scanner in scanners["suffixes"].items():
        if cleaned.endswith(suffix):
            decisions.append(f"{scanner.context}:{scanner.classify(path, response)}")
    for scanner in scanners["default"].values():
        decisions.append(f"{scanner.context}:{scanner.classify(path, response)}")
    return tuple(decisions)


def response_matches_scanners(decisions: tuple[str, ...]) -> bool:
    return bool(decisions) and all(not decision.endswith(":wildcard") for decision in decisions)


def response_fingerprint(response: BaseResponse) -> tuple:
    body = normalize_dynamic_content(response.text)
    path = clean_path(response.full_path).strip("/")
    redirect = clean_path(response.redirect)
    if path:
        body = body.replace(path, "__PATH__")
        redirect = redirect.replace(path, "__PATH__")
    return (
        response.status,
        response.type,
        redirect,
        len(body) // 64,
        hashlib.sha256(body[:4096].encode()).hexdigest(),
    )


def response_denial_reason(response: BaseResponse) -> str | None:
    if response.status in WAF_DENIAL_STATUS_CODES:
        return f"status_{response.status}"

    headers = _normalized_headers(response.headers)
    for name in WAF_HEADER_NAMES:
        if name in headers:
            return f"waf_header:{name}"

    for name, value in headers.items():
        if any(marker in value for marker in WAF_HEADER_VALUE_MARKERS):
            return f"waf_header:{name}"

    body = response.text[:4096].lower()
    for marker in WAF_BODY_MARKERS:
        if marker in body:
            return f"waf_body:{marker}"

    return None


def _normalized_headers(headers: Iterable[tuple[str, str]]) -> dict[str, str]:
    return {str(key).lower(): str(value).lower() for key, value in headers.items()}


def _error_observation(
    profile: PreflightProfile,
    sample: PreflightSample,
    error: RequestException,
    *,
    start_time: float,
) -> PreflightObservation:
    message = str(error) or error.__class__.__name__
    return PreflightObservation(
        profile=profile,
        path=sample.path,
        expected_missing=sample.expected_missing,
        status=0,
        scanner_decisions=(),
        matched=False,
        fingerprint=FingerprintResult(behavior_tags=("request_error",)),
        runtime_fingerprint=("error", message),
        timestamp=time.monotonic() - start_time,
        denial_reason=f"request_error:{message}",
    )


def _response_observation(
    profile: PreflightProfile,
    sample: PreflightSample,
    response: BaseResponse,
    scanners: dict[str, dict[str, BaseScanner]],
    *,
    dns_resolution: DNSResolution = DNSResolution(),
    start_time: float,
) -> PreflightObservation:
    decisions = scanner_decisions(scanners, sample.path, response)
    return PreflightObservation(
        profile=profile,
        path=sample.path,
        expected_missing=sample.expected_missing,
        status=response.status,
        scanner_decisions=decisions,
        matched=response_matches_scanners(decisions),
        fingerprint=fingerprint_response(
            response.headers,
            body=response.text,
            dns_cnames=dns_resolution.cnames,
            resolved_ips=dns_resolution.ips,
            tls_cert=getattr(response, "tls_cert", None),
        ),
        runtime_fingerprint=response_fingerprint(response),
        timestamp=time.monotonic() - start_time,
        elapsed=response.elapsed,
        redirect=response.redirect,
        content_type=response.type,
        length=response.length,
        denial_reason=response_denial_reason(response),
    )


def finalize_profile_observations(
    observations: Iterable[PreflightObservation],
) -> list[PreflightObservation]:
    observations = list(observations)
    observations = _mark_sustained_5xx(observations)
    return _mark_missing_response_shifts(observations)


def _mark_sustained_5xx(
    observations: list[PreflightObservation],
) -> list[PreflightObservation]:
    status_counts = Counter(
        observation.status
        for observation in observations
        if 500 <= observation.status <= 599
    )
    sustained_statuses = {
        status
        for status, count in status_counts.items()
        if count >= PREFLIGHT_SUSTAINED_DENIAL_COUNT
    }
    if not sustained_statuses:
        return observations

    return [
        replace(observation, denial_reason=f"status_{observation.status}")
        if observation.status in sustained_statuses and not observation.denial_reason
        else observation
        for observation in observations
    ]


def _mark_missing_response_shifts(
    observations: list[PreflightObservation],
) -> list[PreflightObservation]:
    missing = [
        observation
        for observation in observations
        if observation.expected_missing
        and observation.status > 0
        and not observation.denial_reason
    ]
    if len(missing) < PREFLIGHT_SUSTAINED_DENIAL_COUNT:
        return observations

    fingerprint_counts = Counter(observation.runtime_fingerprint for observation in missing)
    if len(fingerprint_counts) <= 1:
        return observations

    baseline, baseline_count = fingerprint_counts.most_common(1)[0]
    shifted = {
        fingerprint
        for fingerprint, count in fingerprint_counts.items()
        if fingerprint != baseline and count >= PREFLIGHT_SUSTAINED_DENIAL_COUNT
    }
    if not shifted and baseline_count > 1:
        return observations

    return [
        replace(observation, denial_reason="response_fingerprint_shift")
        if observation.expected_missing
        and observation.status > 0
        and not observation.denial_reason
        and observation.runtime_fingerprint in shifted
        else observation
        for observation in observations
    ]


def denial_behavior_tags(observations: Iterable[PreflightObservation]) -> tuple[str, ...]:
    tags = []
    for observation in observations:
        reason = observation.denial_reason or ""
        if reason.startswith("status_429"):
            tags.append("waf_rate_limit")
        elif reason.startswith("status_403") or reason.startswith(("waf_", "response_")):
            tags.append("waf_challenge")
        elif reason.startswith("status_5"):
            tags.append("waf_5xx_denial")
        elif reason.startswith("request_error"):
            tags.append("waf_connection_denial")
    return tuple(dict.fromkeys(tags))


def _profile_is_clean(observations: Iterable[PreflightObservation]) -> bool:
    observations = tuple(observations)
    return not any(
        observation.expected_missing and observation.matched
        for observation in observations
    ) and not any(observation.denial_reason for observation in observations)


def _original_preflight_profile() -> PreflightProfile:
    return PreflightProfile(
        "original",
        max(1, int(options["thread_count"])),
        max(0.0, float(options["delay"])),
        max(0, int(options["max_rate"])),
    )


def _preflight_profiles(original_profile: PreflightProfile) -> tuple[PreflightProfile, ...]:
    return build_preflight_profiles(
        original_profile.thread_count,
        original_profile.delay,
        original_profile.max_rate,
    )


def _apply_observations_to_result(
    result: PreflightResult,
    profile: PreflightProfile,
    observations: list[PreflightObservation],
) -> None:
    result.observations.extend(observations)
    suspicious = [
        observation
        for observation in observations
        if observation.expected_missing and observation.matched
    ]
    if not suspicious:
        result.applied_profile = profile
    if suspicious:
        result.behavior_tags.append("scanner_false_positive_burst")
    for observation in suspicious:
        result.runtime_fingerprints.add(observation.runtime_fingerprint)
    denied = [observation for observation in observations if observation.denial_reason]
    result.behavior_tags.extend(denial_behavior_tags(denied))
    for observation in denied:
        result.runtime_fingerprints.add(observation.runtime_fingerprint)


def _finalize_preflight_result(
    result: PreflightResult,
    fingerprints: Iterable[FingerprintResult],
) -> PreflightResult:
    result.fingerprint = merge_fingerprints(
        fingerprints,
        behavior_tags=result.behavior_tags,
    )
    return result


class PreflightScanner:
    def __init__(self, requester: Requester, dictionary: Dictionary, base_path: str = "") -> None:
        self.requester = requester
        self.dictionary = dictionary
        self.base_path = base_path
        self.dns_resolution = preflight_dns_resolution(getattr(requester, "_url", ""))
        self._samples: tuple[PreflightSample, ...] | None = None
        self._scanners: dict[str, dict[str, BaseScanner]] | None = None

    @property
    def samples(self) -> tuple[PreflightSample, ...]:
        if self._samples is None:
            self._samples = sample_preflight_paths(
                self.dictionary,
                base_path=self.base_path,
                extensions=options["extensions"],
            )
        return self._samples

    @property
    def scanners(self) -> dict[str, dict[str, BaseScanner]]:
        if self._scanners is None:
            self._scanners = self._build_scanners()
        return self._scanners

    def scan_profile(self, profile: PreflightProfile) -> list[PreflightObservation]:
        original_threads = options["thread_count"]
        original_delay = options["delay"]
        original_max_rate = options["max_rate"]
        options["thread_count"] = profile.thread_count
        options["delay"] = profile.delay
        options["max_rate"] = profile.max_rate
        if hasattr(self.requester, "_rate"):
            self.requester._rate = 0
        start_time = time.monotonic()

        def probe(sample: PreflightSample) -> PreflightObservation:
            try:
                response = self.requester.request(sample.path)
            except RequestException as error:
                return _error_observation(profile, sample, error, start_time=start_time)
            if profile.delay:
                time.sleep(profile.delay)
            return _response_observation(
                profile,
                sample,
                response,
                self.scanners,
                dns_resolution=self.dns_resolution,
                start_time=start_time,
            )

        try:
            with ThreadPoolExecutor(max_workers=profile.thread_count) as executor:
                return finalize_profile_observations(executor.map(probe, self.samples))
        finally:
            options["thread_count"] = original_threads
            options["delay"] = original_delay
            options["max_rate"] = original_max_rate

    def _build_scanners(self) -> dict[str, dict[str, BaseScanner]]:
        from lib.core.scanner import Scanner

        scanners: dict[str, dict[str, BaseScanner]] = {
            "default": {},
            "prefixes": {},
            "suffixes": {},
        }
        scanners["default"]["random"] = Scanner(
            self.requester,
            path=self.base_path + WILDCARD_TEST_POINT_MARKER,
        )
        if options["exclude_response"]:
            scanners["default"]["custom"] = Scanner(
                self.requester,
                tested=scanners,
                path=options["exclude_response"],
            )
        for prefix in set(options["prefixes"] + DEFAULT_TEST_PREFIXES):
            scanners["prefixes"][prefix] = Scanner(
                self.requester,
                tested=scanners,
                path=f"{self.base_path}{prefix}{WILDCARD_TEST_POINT_MARKER}",
                context=f"/{self.base_path}{prefix}***",
            )
        for suffix in set(options["suffixes"] + DEFAULT_TEST_SUFFIXES):
            scanners["suffixes"][suffix] = Scanner(
                self.requester,
                tested=scanners,
                path=f"{self.base_path}{WILDCARD_TEST_POINT_MARKER}{suffix}",
                context=f"/{self.base_path}***{suffix}",
            )
        for extension in options["extensions"]:
            key = "." + extension
            if key not in scanners["suffixes"]:
                scanners["suffixes"][key] = Scanner(
                    self.requester,
                    tested=scanners,
                    path=f"{self.base_path}{WILDCARD_TEST_POINT_MARKER}.{extension}",
                    context=f"/{self.base_path}***.{extension}",
                )
        return scanners


class NativePreflightScanner(PreflightScanner):
    def __init__(self, requester: Requester, dictionary: Dictionary, base_path: str = "") -> None:
        super().__init__(requester, dictionary, base_path=base_path)
        from lib.connection.native import NativeHTTPBackend

        self.native_backend = NativeHTTPBackend()

    def scan_profile(self, profile: PreflightProfile) -> list[PreflightObservation]:
        observations: list[PreflightObservation] = []
        original_threads = options["thread_count"]
        original_delay = options["delay"]
        original_max_rate = options["max_rate"]
        options["thread_count"] = profile.thread_count
        options["delay"] = profile.delay
        options["max_rate"] = profile.max_rate
        start_time = time.monotonic()
        try:
            paths = [sample.path for sample in self.samples]
            by_path = {sample.path: sample for sample in self.samples}
            for path, response, error in self.native_backend.scan(
                self.requester._url,
                paths,
                getattr(self.requester, "_query", ""),
                apply_filters=False,
            ):
                if error is not None or response is None:
                    observations.append(
                        _error_observation(
                            profile,
                            by_path[path],
                            error or RequestException("Native preflight request failed"),
                            start_time=start_time,
                        )
                    )
                    continue
                sample = by_path[path]
                observations.append(
                    _response_observation(
                        profile,
                        sample,
                        response,
                        self.scanners,
                        dns_resolution=self.dns_resolution,
                        start_time=start_time,
                    )
                )
        finally:
            options["thread_count"] = original_threads
            options["delay"] = original_delay
            options["max_rate"] = original_max_rate
        return finalize_profile_observations(observations)


class SyncPreflightCalibrator:
    scanner_class = PreflightScanner

    def __init__(self, requester: Requester, dictionary: Dictionary, base_path: str = "") -> None:
        self.scanner = self.scanner_class(
            requester,
            dictionary,
            base_path=base_path,
        )
        self.original_profile = _original_preflight_profile()

    def run(self) -> PreflightResult:
        profiles = _preflight_profiles(self.original_profile)
        result = PreflightResult(
            enabled=True,
            applied_profile=profiles[-1],
            original_profile=self.original_profile,
        )

        fingerprints: list[FingerprintResult] = []
        for profile in profiles:
            observations = self.scanner.scan_profile(profile)
            fingerprints.extend(observation.fingerprint for observation in observations)
            _apply_observations_to_result(result, profile, observations)
            if result.applied_profile == profile and _profile_is_clean(observations):
                break

        return _finalize_preflight_result(result, fingerprints)


class NativePreflightCalibrator(SyncPreflightCalibrator):
    scanner_class = NativePreflightScanner

    def __init__(self, requester: Requester, dictionary: Dictionary, base_path: str = "") -> None:
        super().__init__(requester, dictionary, base_path=base_path)


class AsyncPreflightScanner:
    def __init__(self, requester: AsyncRequester, dictionary: Dictionary, base_path: str = "") -> None:
        self.requester = requester
        self.dictionary = dictionary
        self.base_path = base_path
        self.dns_resolution = preflight_dns_resolution(getattr(requester, "_url", ""))
        self._samples: tuple[PreflightSample, ...] | None = None
        self._scanners: dict[str, dict[str, BaseScanner]] | None = None

    @property
    def samples(self) -> tuple[PreflightSample, ...]:
        if self._samples is None:
            self._samples = sample_preflight_paths(
                self.dictionary,
                base_path=self.base_path,
                extensions=options["extensions"],
            )
        return self._samples

    async def scanners(self) -> dict[str, dict[str, BaseScanner]]:
        if self._scanners is None:
            self._scanners = await self._build_scanners()
        return self._scanners

    async def _build_scanners(self) -> dict[str, dict[str, BaseScanner]]:
        from lib.core.scanner import AsyncScanner

        scanners: dict[str, dict[str, BaseScanner]] = {
            "default": {},
            "prefixes": {},
            "suffixes": {},
        }
        scanners["default"]["random"] = await AsyncScanner.create(
            self.requester,
            path=self.base_path + WILDCARD_TEST_POINT_MARKER,
        )
        if options["exclude_response"]:
            scanners["default"]["custom"] = await AsyncScanner.create(
                self.requester,
                tested=scanners,
                path=options["exclude_response"],
            )
        for prefix in set(options["prefixes"] + DEFAULT_TEST_PREFIXES):
            scanners["prefixes"][prefix] = await AsyncScanner.create(
                self.requester,
                tested=scanners,
                path=f"{self.base_path}{prefix}{WILDCARD_TEST_POINT_MARKER}",
                context=f"/{self.base_path}{prefix}***",
            )
        for suffix in set(options["suffixes"] + DEFAULT_TEST_SUFFIXES):
            scanners["suffixes"][suffix] = await AsyncScanner.create(
                self.requester,
                tested=scanners,
                path=f"{self.base_path}{WILDCARD_TEST_POINT_MARKER}{suffix}",
                context=f"/{self.base_path}***{suffix}",
            )
        for extension in options["extensions"]:
            key = "." + extension
            if key not in scanners["suffixes"]:
                scanners["suffixes"][key] = await AsyncScanner.create(
                    self.requester,
                    tested=scanners,
                    path=f"{self.base_path}{WILDCARD_TEST_POINT_MARKER}.{extension}",
                    context=f"/{self.base_path}***.{extension}",
                )
        return scanners

    async def scan_profile(self, profile: PreflightProfile) -> list[PreflightObservation]:
        observations: list[PreflightObservation] = []
        original_threads = options["thread_count"]
        original_delay = options["delay"]
        original_max_rate = options["max_rate"]
        options["thread_count"] = profile.thread_count
        options["delay"] = profile.delay
        options["max_rate"] = profile.max_rate
        if hasattr(self.requester, "_rate"):
            self.requester._rate = 0
        start_time = time.monotonic()
        semaphore = asyncio.Semaphore(profile.thread_count)
        scanners = await self.scanners()

        async def probe(sample: PreflightSample) -> PreflightObservation:
            async with semaphore:
                try:
                    response = await self.requester.request(sample.path)
                except RequestException as error:
                    return _error_observation(profile, sample, error, start_time=start_time)
                if profile.delay:
                    await asyncio.sleep(profile.delay)
                return _response_observation(
                    profile,
                    sample,
                    response,
                    scanners,
                    dns_resolution=self.dns_resolution,
                    start_time=start_time,
                )

        try:
            observations = finalize_profile_observations(
                await asyncio.gather(*(probe(sample) for sample in self.samples))
            )
        finally:
            options["thread_count"] = original_threads
            options["delay"] = original_delay
            options["max_rate"] = original_max_rate
        return observations


class AsyncPreflightCalibrator:
    scanner_class = AsyncPreflightScanner

    def __init__(self, requester: AsyncRequester, dictionary: Dictionary, base_path: str = "") -> None:
        self.scanner = self.scanner_class(
            requester,
            dictionary,
            base_path=base_path,
        )
        self.original_profile = _original_preflight_profile()

    async def run(self) -> PreflightResult:
        profiles = _preflight_profiles(self.original_profile)
        result = PreflightResult(
            enabled=True,
            applied_profile=profiles[-1],
            original_profile=self.original_profile,
        )
        fingerprints: list[FingerprintResult] = []
        for profile in profiles:
            observations = await self.scanner.scan_profile(profile)
            fingerprints.extend(observation.fingerprint for observation in observations)
            _apply_observations_to_result(result, profile, observations)
            if result.applied_profile == profile and _profile_is_clean(observations):
                break
        return _finalize_preflight_result(result, fingerprints)


def repeated_match_recalibration(responses: Iterable[BaseResponse]) -> tuple[set[tuple], str | None]:
    fingerprints = [response_fingerprint(response) for response in responses]
    if len(fingerprints) < PREFLIGHT_MATCH_STREAK_THRESHOLD:
        return set(), None
    most_common, count = Counter(fingerprints).most_common(1)[0]
    if count < PREFLIGHT_MATCH_STREAK_THRESHOLD:
        return set(), None
    return {most_common}, "repeated_match_fingerprint"


def preflight_dns_resolution(base_url: str) -> DNSResolution:
    parsed = urlparse(base_url)
    try:
        return resolve_host_records(
            parsed.hostname,
            timeout=options.get("timeout"),
            explicit_ip=options.get("ip"),
        )
    except Exception:
        return DNSResolution()
