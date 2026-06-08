import json
from pathlib import Path
from unittest import TestCase


class TestNativeInstallPackaging(TestCase):
    def test_entrypoints_include_native_builder(self):
        self.assertIn(
            'dirsearch-build-native = "dirsearch.lib.core.native_builder:main"',
            Path("pyproject.toml").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "dirsearch-build-native=dirsearch.lib.core.native_builder:main",
            Path("setup.py").read_text(encoding="utf-8"),
        )

    def test_package_data_includes_native_sources(self):
        setup_py = Path("setup.py").read_text(encoding="utf-8")

        self.assertIn('*package_files(package_root / "native")', setup_py)
        self.assertIn('"target"', setup_py)

    def test_package_data_includes_fingerprint_dataset(self):
        setup_py = Path("setup.py").read_text(encoding="utf-8")
        pyinstaller_spec = Path("pyinstaller/dirsearch.spec").read_text(encoding="utf-8")

        self.assertTrue(Path("db/fingerprints/cdn_waf.json").is_file())
        self.assertTrue(Path("db/fingerprints/cdncheck.LICENSE").is_file())
        self.assertIn('*package_files(package_root / "db")', setup_py)
        self.assertIn("(os.path.join(PROJECT_ROOT, 'db'), 'db')", pyinstaller_spec)

    def test_fingerprint_dataset_metadata_excludes_cloud(self):
        data = json.loads(Path("db/fingerprints/cdn_waf.json").read_text(encoding="utf-8"))

        self.assertEqual(set(data["categories"]), {"cdn", "waf", "common"})
        self.assertNotIn("cloud", data["categories"])
        self.assertEqual(data["metadata"]["license"], "MIT")
        self.assertEqual(
            data["metadata"]["source_commit"],
            "1e2f9d0d95dd144f274a10ad911fc33e7f7a5562",
        )

    def test_install_docs_use_native_builder_flow(self):
        docs = Path("docs/installation.md").read_text(encoding="utf-8")

        self.assertIn("dirsearch-build-native", docs)
        self.assertIn("python3.14-dev", docs)
        self.assertIn("python3.14-devel", docs)
        self.assertNotIn("maturin develop", docs)
