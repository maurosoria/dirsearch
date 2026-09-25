#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path | None = None) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def clean_wheel_dir(wheel_dir: Path) -> None:
    wheel_dir.mkdir(parents=True, exist_ok=True)
    for wheel in wheel_dir.glob("*.whl"):
        wheel.unlink()


def resolve_python(value: str) -> Path:
    candidate = Path(value)
    if candidate.exists() or len(candidate.parts) > 1:
        return candidate.absolute()

    resolved = shutil.which(value)
    if resolved:
        return Path(resolved).absolute()

    return candidate


def read_native_version(manifest: Path) -> str:
    cargo = tomllib.loads(manifest.read_text(encoding="utf-8"))
    return cargo["package"]["version"]


def install_native_wheel(python: Path, wheel: Path, expected_version: str) -> None:
    # Reinstall even when the version matches: reused build environments may
    # otherwise keep an older binary and package it into release artifacts.
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--force-reinstall",
            "--no-deps",
            str(wheel),
        ]
    )
    verification = (
        "import dirsearch_native; "
        f"expected = {expected_version!r}; "
        "actual = getattr(dirsearch_native, '__version__', None); "
        "assert actual == expected, "
        "f'native extension version mismatch: expected {expected}, found {actual}'"
    )
    run([str(python), "-c", verification])


def build_native(args: argparse.Namespace) -> Path:
    python = resolve_python(args.python)
    manifest = Path(args.manifest_path).resolve()
    wheel_dir = Path(args.out).resolve()
    clean_wheel_dir(wheel_dir)

    command = [
        str(python),
        "-m",
        "maturin",
        "build",
        "--release",
        "--locked",
        "--manifest-path",
        str(manifest),
        "--out",
        str(wheel_dir),
    ]
    if args.target_dir:
        command.extend(["--target-dir", str(Path(args.target_dir).resolve())])

    run(command, cwd=PROJECT_ROOT)

    wheels = sorted(wheel_dir.glob("*.whl"))
    if len(wheels) != 1:
        names = ", ".join(wheel.name for wheel in wheels) or "none"
        raise RuntimeError(f"Expected exactly one native wheel in {wheel_dir}; found {names}")

    return wheels[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and install dirsearch_native")
    parser.add_argument("--python", default=sys.executable, help="Python executable to install into")
    parser.add_argument(
        "--manifest-path",
        default=PROJECT_ROOT / "native" / "Cargo.toml",
        type=Path,
        help="Path to native/Cargo.toml",
    )
    parser.add_argument(
        "--out",
        default=PROJECT_ROOT / "dist" / "native-wheels",
        type=Path,
        help="Directory for the built native wheel",
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        help="Optional Cargo target directory, useful for read-only source trees",
    )
    parser.add_argument(
        "--keep-target",
        action="store_true",
        help="Keep the Cargo target directory after a successful build",
    )
    args = parser.parse_args()

    wheel = build_native(args)
    python = resolve_python(args.python)
    expected_version = read_native_version(Path(args.manifest_path).resolve())
    install_native_wheel(python, wheel, expected_version)

    if not args.keep_target:
        target_dir = Path(args.target_dir).resolve() if args.target_dir else PROJECT_ROOT / "native" / "target"
        shutil.rmtree(target_dir, ignore_errors=True)

    print(f"Native wheel installed: {wheel}", flush=True)


if __name__ == "__main__":
    main()
