import ast
import importlib.metadata
import os
import subprocess
import sys
import tempfile
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
    from dirsearch.lib.core.discovery_config import DiscoveryConfig
    from dirsearch.lib.core.filter_config import FilterConfig
    from dirsearch.lib.core.filter_state import FilterState
    from dirsearch.lib.core.request_config import RequestConfig
    from dirsearch.lib.report.directory_response_store import DirectoryResponseStore
    from dirsearch.lib.report.jsonl_response_store import JsonlResponseStore
    from dirsearch.lib.report.response_store import (
        BaseResponseStore,
        create_response_stores,
    )

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
    assert RequestConfig(method="POST").method == "POST"
    assert DiscoveryConfig(subdirs=[""]).subdirs == ("",)
    assert FilterConfig(include_status_codes={200}).native_options()["include_status_codes"] == [200]
    assert FilterState().scanners == {"default": {}, "prefixes": {}, "suffixes": {}}
    assert issubclass(DirectoryResponseStore, BaseResponseStore), (
        DirectoryResponseStore.__mro__
    )
    assert issubclass(JsonlResponseStore, BaseResponseStore), (
        JsonlResponseStore.__mro__
    )

    stores = create_response_stores(
        os.path.join(temp_dir, "responses"),
        os.path.join(temp_dir, "responses.jsonl"),
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
