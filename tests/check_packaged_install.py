import ast
import importlib.metadata
import os
import subprocess
import sys
import tempfile
from io import StringIO
from pathlib import Path


def read_source_version() -> str:
    source = Path(__file__).resolve().parents[1] / "lib" / "core" / "settings.py"
    module = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "VERSION":
                    value = ast.literal_eval(node.value)
                    if isinstance(value, str):
                        return value
    raise RuntimeError("Unable to locate VERSION in lib/core/settings.py")


def main() -> None:
    temp_dir = tempfile.mkdtemp(prefix="dirsearch-install-check-")
    os.chdir(temp_dir)

    from dirsearch import (
        DirsearchFuzzer,
        FuzzerConfig,
        FuzzerResult,
        Wordlist,
        WordlistLimitError,
        WordlistState,
        WordlistTemplate,
    )
    from dirsearch.lib.core import settings
    from dirsearch.lib.controller.session import SessionStore
    from dirsearch.lib.controller.session_snapshot import RunCheckpoint, SessionSnapshot
    from dirsearch.lib.core.discovery_config import DiscoveryConfig
    from dirsearch.lib.core.execution_config import ExecutionConfig, ScanEngine
    from dirsearch.lib.core.filter_config import FilterConfig
    from dirsearch.lib.core.filter_state import FilterState
    from dirsearch.lib.core.log_config import LogConfig
    from dirsearch.lib.core.logger import RunLogger
    from dirsearch.lib.core.request_config import RequestConfig
    from dirsearch.lib.core.report_config import ReportConfig
    from dirsearch.lib.core.result_config import ResultConfig
    from dirsearch.lib.core.scan_run_state import ScanRunState
    from dirsearch.lib.core.target_config import TargetConfig
    from dirsearch.lib.core.target_progress import TargetProgress
    from dirsearch.lib.core.task_checkpoint import DictionaryCheckpoint, TaskCheckpoint
    from dirsearch.lib.core.terminal_config import TerminalConfig
    from dirsearch.lib.core.wordlist_config import WordlistConfig
    from dirsearch.lib.report.directory_response_store import DirectoryResponseStore
    from dirsearch.lib.report.jsonl_response_store import JsonlResponseStore
    from dirsearch.lib.report.response_store import (
        BaseResponseStore,
        create_response_stores,
    )
    from dirsearch.lib.view.terminal import create_terminal

    expected_version = read_source_version()
    installed_version = importlib.metadata.version("dirsearch")
    assert installed_version == expected_version, (installed_version, expected_version)
    assert DirsearchFuzzer
    assert FuzzerConfig
    assert FuzzerResult
    assert Wordlist
    assert WordlistLimitError
    assert WordlistState
    assert WordlistTemplate
    snapshot = SessionSnapshot(
        run=RunCheckpoint(0),
        task=TaskCheckpoint(DictionaryCheckpoint((), 0)),
        options={"urls": [], "data": b"\x80\r\n"},
    )
    session_path = str(Path(temp_dir, "checkpoint"))
    store = SessionStore()
    store.save(snapshot, session_path)
    restored = store.load(session_path)
    assert isinstance(restored, SessionSnapshot)
    assert isinstance(restored.run, RunCheckpoint)
    assert isinstance(restored.task, TaskCheckpoint)
    assert isinstance(restored.task.dictionary, DictionaryCheckpoint)
    assert restored == snapshot
    assert WordlistConfig(extensions=["html"]).extensions == ("html",)
    assert ExecutionConfig(engine=ScanEngine.NATIVE).engine is ScanEngine.NATIVE
    assert ExecutionConfig(skip_on_status=[429]).skip_on_status == frozenset({429})
    assert RequestConfig(method="POST").method == "POST"
    assert TargetConfig(default_scheme="https").default_scheme == "https"
    pending_directories = ["current/", "next/"]
    target_progress = TargetProgress(directories=pending_directories)
    pending_directories.clear()
    assert target_progress.directories == ["current/", "next/"]
    assert TerminalConfig(extensions=["html"]).extensions == ("html",)
    output = StringIO()
    terminal = create_terminal(TerminalConfig(color=False), stream=output)
    try:
        terminal.header("installed terminal")
        assert terminal.buffer == "installed terminal\n"
        assert output.getvalue() == "installed terminal\n"
    finally:
        terminal.close()
    assert not output.closed
    log_path = Path(temp_dir, "run.log")
    logger = RunLogger(LogConfig(str(log_path), proxy_auth="user:private/value"))
    try:
        logger.info("installed logger user:private/value@proxy.example.test")
    finally:
        logger.close()
    assert not logger.handlers
    assert "installed logger <redacted>@proxy.example.test" in log_path.read_text()
    assert ReportConfig(formats=["json"]).formats == ("json",)
    assert DiscoveryConfig(subdirs=[""]).subdirs == ("",)
    assert FilterConfig(include_status_codes={200}).native_options()["include_status_codes"] == [200]
    assert FilterState().scanners == {"default": {}, "prefixes": {}, "suffixes": {}}
    run_state = ScanRunState(["http://example.test/", "http://next.test/"])
    assert run_state.activate_next() == "http://example.test/"
    assert run_state.pending_count == 1
    assert run_state.snapshot_targets() == ["http://example.test/", "http://next.test/"]
    run_state.finish_active()
    run_state.jobs_processed = 3
    run_state.prepare_targets(["http://resumed.test/"])
    assert run_state.jobs_processed == 3
    assert run_state.snapshot_targets() == ["http://resumed.test/"]
    assert issubclass(DirectoryResponseStore, BaseResponseStore), (
        DirectoryResponseStore.__mro__
    )
    assert issubclass(JsonlResponseStore, BaseResponseStore), (
        JsonlResponseStore.__mro__
    )

    result_config = ResultConfig(
        response_directory=os.path.join(temp_dir, "responses"),
        response_jsonl_file=os.path.join(temp_dir, "responses.jsonl"),
    )
    assert result_config.capture_full_body
    stores = create_response_stores(
        result_config.response_directory,
        result_config.response_jsonl_file,
    )
    try:
        assert all(isinstance(store, BaseResponseStore) for store in stores)
    finally:
        for store in stores:
            store.close()

    package_root = Path(settings.__file__).resolve().parents[2]
    assert (package_root / "config.ini").is_file()
    assert (package_root / "db" / "categories" / "aggressive.txt").is_file()
    assert (package_root / "db" / "categories" / "common.txt").is_file()
    assert (package_root / "db" / "templates" / "crud.txt").is_file()
    subprocess.run(
        [sys.executable, "-m", "dirsearch", "--version"],
        cwd=temp_dir,
        check=True,
    )


if __name__ == "__main__":
    main()
