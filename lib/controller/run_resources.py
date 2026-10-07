"""Owned live handles for one controller lifecycle, never checkpoint data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop

    from ..connection.native import NativeRequester
    from ..connection.requester import AsyncRequester, Requester
    from ..core.logger import RunLogger
    from ..report.manager import ReportManager
    from ..report.response_store import BaseResponseStore
    from ..view.terminal import CLI


@dataclass(slots=True, eq=False, repr=False)
class RunResources:
    """Own handles that the controller creates and its components borrow.

    Bootstrap terminal/logging are required; later handles are attached during
    preparation. This is a single-use, synchronous lifecycle owner, not a
    service locator or an independently runnable task. Consumers receive only
    the handles they need. The controller must drain workers before closing;
    this object does not own worker cancellation or process signal handlers.
    """

    interface: CLI
    logger: RunLogger
    reporter: ReportManager | None = None
    requester: Requester | AsyncRequester | NativeRequester | None = None
    loop: AbstractEventLoop | None = None
    response_stores: tuple[BaseResponseStore, ...] = ()
    _reporter_finished: bool = field(default=False, init=False)
    _closed: bool = field(default=False, init=False)

    def replace_terminal(self, terminal: CLI) -> None:
        """Adopt a prepared terminal before closing the bootstrap handle."""
        previous = self.interface
        self.interface = terminal
        previous.close()

    def replace_logger(self, logger: RunLogger) -> None:
        """Keep the replacement owned even if closing bootstrap logging fails."""
        previous = self.logger
        self.logger = logger
        previous.close()

    def finish_reports(self) -> None:
        """Allow normal completion/quit to finish reports before final cleanup.

        A failing finish is not retried during unwinding: report writers may
        already have released their handles or partially emitted final output.
        """
        if self.reporter is None or self._reporter_finished:
            return
        try:
            self.reporter.finish()
        finally:
            self._reporter_finished = True

    def _close_requester(self) -> None:
        # A loop is owned only for the async requester. Sync/native requesters
        # close directly; no engine selection or optional-native import is needed.
        if self.requester is None:
            if self.loop is not None:
                self.loop.close()
            return
        if self.loop is None:
            self.requester.close()
            return
        try:
            self.loop.run_until_complete(self.requester.close())
        finally:
            self.loop.close()

    def _close_response_stores(self) -> None:
        for store in self.response_stores:
            try:
                store.close()
            except OSError as error:
                self.logger.exception(error)
                self.interface.error(
                    f"Couldn't close {store.name} response store at "
                    f"{store.destination}: {error}"
                )

    def close(self) -> None:
        """Attempt teardown once, including later phases when an earlier fails.

        Keep diagnostics alive until their borrowers close. As in the controller's
        original nested cleanup, an exception still propagates (a later exception
        can supersede it, with normal Python chaining). A second call does not
        retry failed releases; callers must not attach/reuse resources afterward.
        """
        if self._closed:
            return
        self._closed = True
        try:
            self.finish_reports()
        finally:
            try:
                self._close_requester()
            finally:
                try:
                    self._close_response_stores()
                finally:
                    try:
                        self.interface.close()
                    finally:
                        self.logger.close()
