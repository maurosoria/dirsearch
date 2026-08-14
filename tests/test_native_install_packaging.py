import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.build_native import resolve_python


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

        self.assertIn('*package_files(ROOT / "native")', setup_py)
        self.assertIn('"target"', setup_py)

    def test_setup_uses_standard_package_dir_mapping(self):
        setup_py = Path("setup.py").read_text(encoding="utf-8")

        self.assertIn('"dirsearch": "."', setup_py)
        self.assertIn('"dirsearch.lib": "lib"', setup_py)
        self.assertNotIn("tempfile.mkdtemp", setup_py)
        self.assertNotIn("shutil.copytree", setup_py)
        self.assertNotIn("os.chdir", setup_py)

    def test_ntlm_auth_is_not_a_direct_dependency(self):
        requirement_files = (
            Path("requirements.txt"),
            Path("requirements/runtime.txt"),
        )

        for path in requirement_files:
            with self.subTest(path=str(path)):
                self.assertNotIn(
                    "ntlm-auth",
                    path.read_text(encoding="utf-8"),
                )
        self.assertNotIn(
            "ntlm_auth",
            Path("pyinstaller/dirsearch.spec").read_text(encoding="utf-8"),
        )

    def test_macos_pyinstaller_omits_mysql_vendor_openssl(self):
        pyinstaller_spec = Path("pyinstaller/dirsearch.spec").read_text(
            encoding="utf-8"
        )

        self.assertIn('if sys.platform == "darwin":', pyinstaller_spec)
        self.assertIn('startswith("mysql/vendor/")', pyinstaller_spec)
        self.assertIn('startswith("_mysql_connector")', pyinstaller_spec)

    def test_portable_workflow_uses_github_token(self):
        workflow = Path(".github/workflows/portable-builds.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("GITHUB_TOKEN: ${{ github.token }}", workflow)

    def test_install_docs_use_native_builder_flow(self):
        docs = Path("docs/installation.md").read_text(encoding="utf-8")

        self.assertIn("dirsearch-build-native", docs)
        self.assertIn("python3.14-dev", docs)
        self.assertIn("python3.14-devel", docs)
        self.assertNotIn("maturin develop", docs)

    def test_pyinstaller_native_build_uses_selected_python(self):
        build_script = Path("pyinstaller/build.sh").read_text(encoding="utf-8")

        self.assertIn('${VIRTUAL_ENV:-}', build_script)
        self.assertIn('"$PYTHON_CMD" scripts/build_native.py --python "$PYTHON_CMD"', build_script)

    def test_native_builder_preserves_python_symlink(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            target = temp_path / "python-real"
            link = temp_path / "python"
            target.touch()
            try:
                os.symlink(target, link)
            except (AttributeError, NotImplementedError, OSError) as error:
                self.skipTest(f"Python symlink unavailable: {error}")

            self.assertEqual(resolve_python(str(link)), link.absolute())
