"""Prepared policies for one run, separate from input, resources and progress."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from .discovery_config import DiscoveryConfig
from .execution_config import ExecutionConfig
from .filter_config import FilterConfig
from .log_config import LogConfig
from .report_config import ReportConfig
from .request_config import RequestConfig
from .result_config import ResultConfig
from .target_config import TargetConfig
from .terminal_config import TerminalConfig
from .wordlist_config import WordlistConfig


@dataclass(frozen=True, slots=True)
class RunConfig:
    """An aggregate for composition, not a service locator or a checkpoint.

    Each consumer still receives its narrow policy, never this whole object.
    Defaults support explicit component composition; production uses normalized
    input through ``from_options`` after raw parsing or session restoration.
    Resources, task input, metadata, learned filters and progress stay outside.
    Omit the aggregate's values from repr because policies can contain secrets.
    """

    wordlist: WordlistConfig = field(default_factory=WordlistConfig, repr=False)
    request: RequestConfig = field(default_factory=RequestConfig, repr=False)
    filters: FilterConfig = field(default_factory=FilterConfig, repr=False)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig, repr=False)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig, repr=False)
    reports: ReportConfig = field(default_factory=ReportConfig, repr=False)
    target: TargetConfig = field(default_factory=TargetConfig, repr=False)
    terminal: TerminalConfig = field(default_factory=TerminalConfig, repr=False)
    logging: LogConfig = field(default_factory=LogConfig, repr=False)
    results: ResultConfig = field(default_factory=ResultConfig, repr=False)

    @classmethod
    def from_options(cls, values: Mapping[str, Any]) -> RunConfig:
        """Build policies without global reads, file access or live resources.

        Parsing/normalization stays at the CLI/session boundary. Resolve engine
        selection first, so an invalid pair cannot reach resource construction.
        Blacklist files are loaded separately at the existing run-start boundary.
        """
        execution = ExecutionConfig.from_options(values)
        results = ResultConfig.from_options(values)
        request = replace(
            RequestConfig.from_options(values),
            capture_full_body=results.capture_full_body,
        )
        return cls(
            wordlist=WordlistConfig.from_options(values), request=request,
            filters=FilterConfig.from_options(values),
            discovery=DiscoveryConfig.from_options(values), execution=execution,
            reports=ReportConfig.from_options(values),
            target=TargetConfig.from_options(values),
            terminal=TerminalConfig.from_options(values),
            logging=LogConfig.from_options(values), results=results,
        )

    def with_blacklists(self, blacklists: Mapping[int, Iterable[str]]) -> RunConfig:
        """Attach detached blacklist data before workers start, retaining peers.

        Loading belongs to the controller. This pure replacement does not read
        files, reread options or mutate the policy already used by resources.
        """
        return replace(self, filters=replace(self.filters, blacklists=blacklists))
