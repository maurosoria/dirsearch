# -*- coding: utf-8 -*-
"""FastMCP server for AI-driven dirsearch scans."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Union

from lib.core.settings import (
    MCP_DEFAULT_HOST,
    MCP_DEFAULT_PATH,
    MCP_DEFAULT_PORT,
    MCP_DEFAULT_TRANSPORT,
)

try:
    from fastmcp import FastMCP
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
except ImportError:  # pragma: no cover - exercised when optional dependency is absent
    FastMCP = None  # type: ignore[assignment]
    StaticTokenVerifier = None


BLOCKED_VALUE_FLAGS = {
    "-o",
    "--output-file",
    "-O",
    "--output-formats",
    "--mysql-url",
    "--postgres-url",
    "--log",
    "-s",
    "--session",
    "--session-id",
    "--sessions-dir",
    "--config",
}
BLOCKED_SHORT_VALUE_FLAGS = {"-o", "-O", "-s"}
BLOCKED_BOOL_FLAGS = {
    "--stdin",
    "--list-sessions",
}
# Use MCP_DEFAULT_* from lib.core.settings
DEFAULT_SUBPROCESS_GRACE_SECONDS = 30


class MCPConfigurationError(RuntimeError):
    pass


def repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _normalize_wordlists(wordlists: Optional[Union[str, List[str]]]) -> Optional[str]:
    if not wordlists:
        return None
    if isinstance(wordlists, str):
        return wordlists
    return ",".join(wordlists)


def _has_flag(args: Sequence[str], flag: str) -> bool:
    prefix = f"{flag}="
    return any(arg == flag or arg.startswith(prefix) for arg in args)


def sanitize_cli_args(args: Sequence[str]) -> List[str]:
    """Remove CLI flags that would interfere with MCP-managed output/lifecycle."""
    sanitized: List[str] = []
    skip_next = False

    for arg in args:
        if skip_next:
            skip_next = False
            continue

        if arg in BLOCKED_BOOL_FLAGS:
            continue

        if arg in BLOCKED_VALUE_FLAGS:
            skip_next = True
            continue

        if any(arg.startswith(f"{flag}=") for flag in BLOCKED_VALUE_FLAGS):
            continue

        if any(arg.startswith(flag) and arg != flag for flag in BLOCKED_SHORT_VALUE_FLAGS):
            continue

        sanitized.append(arg)

    return sanitized


def build_cli_args(
    url: str,
    wordlists: Optional[Union[str, List[str]]] = None,
    extensions: str = "",
    threads: int = 10,
    recursive: bool = False,
    include_status: Optional[str] = None,
    exclude_status: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 7.5,
    max_time: int = 60,
) -> List[str]:
    if not url:
        raise ValueError("url is required")
    if threads < 1:
        raise ValueError("threads must be greater than zero")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    if max_time < 1:
        raise ValueError("max_time must be greater than zero")

    args = [
        "-u",
        url,
        "--threads",
        str(threads),
        "--timeout",
        str(timeout),
        "--max-time",
        str(max_time),
    ]

    normalized_wordlists = _normalize_wordlists(wordlists)
    if normalized_wordlists:
        args.extend(["-w", normalized_wordlists])

    if extensions is not None:
        args.extend(["-e", extensions])

    if recursive:
        args.append("--recursive")

    if include_status:
        args.extend(["--include-status", include_status])

    if exclude_status:
        args.extend(["--exclude-status", exclude_status])

    for name, value in (headers or {}).items():
        args.extend(["-H", f"{name}: {value}"])

    return args


def build_command(cli_args: Sequence[str], output_file: str, default_max_time: int = 60) -> List[str]:
    sanitized_args = sanitize_cli_args(cli_args)
    command = [sys.executable, os.path.join(repo_root(), "dirsearch.py"), *sanitized_args]

    if not _has_flag(sanitized_args, "--max-time"):
        command.extend(["--max-time", str(default_max_time)])

    command.extend(["--no-color", "--quiet-mode", "-O", "json", "-o", output_file])
    return command


def run_dirsearch(cli_args: Sequence[str], max_time: int = 60) -> Dict[str, Any]:
    if max_time < 1:
        raise ValueError("max_time must be greater than zero")

    fd, output_file = tempfile.mkstemp(prefix="dirsearch-mcp-", suffix=".json")
    os.close(fd)
    os.unlink(output_file)

    command = build_command(cli_args, output_file, default_max_time=max_time)
    try:
        try:
            proc = subprocess.run(
                command,
                cwd=repo_root(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=max_time + DEFAULT_SUBPROCESS_GRACE_SECONDS,
            )
        except subprocess.TimeoutExpired as e:
            stdout = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = e.stderr.decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
            return {
                "ok": False,
                "returncode": None,
                "report": None,
                "stdout": stdout[-4000:],
                "stderr": stderr[-4000:],
                "error": "dirsearch subprocess timed out",
            }

        report = None
        if os.path.exists(output_file):
            with open(output_file, encoding="utf-8") as fh:
                report = json.load(fh)

        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "report": report,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
        }
    finally:
        try:
            os.remove(output_file)
        except OSError:
            pass


def create_mcp(auth_token: Optional[str] = None):
    if FastMCP is None:
        raise MCPConfigurationError(
            "FastMCP is not installed. Install it with 'pip install fastmcp'."
        )

    auth = None
    if auth_token and StaticTokenVerifier is not None:
        auth = StaticTokenVerifier(
            tokens={
                auth_token: {
                    "client_id": "dirsearch-mcp-client",
                    "scopes": ["read", "write"],
                }
            },
            required_scopes=["read"],
        )

    kwargs: Dict[str, Any] = {"auth": auth}

    server = FastMCP("dirsearch", **kwargs)

    @server.tool
    def dirsearch_scan(
        url: str,
        wordlists: Optional[Union[str, List[str]]] = None,
        extensions: str = "",
        threads: int = 10,
        recursive: bool = False,
        include_status: Optional[str] = None,
        exclude_status: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 7.5,
        max_time: int = 60,
    ) -> Dict[str, Any]:
        """Run dirsearch with common structured options and return its JSON report."""
        cli_args = build_cli_args(
            url=url,
            wordlists=wordlists,
            extensions=extensions,
            threads=threads,
            recursive=recursive,
            include_status=include_status,
            exclude_status=exclude_status,
            headers=headers,
            timeout=timeout,
            max_time=max_time,
        )
        return run_dirsearch(cli_args, max_time=max_time)

    @server.tool
    def dirsearch_scan_cli(args: List[str], max_time: int = 60) -> Dict[str, Any]:
        """Run dirsearch with raw CLI arguments while MCP manages JSON output safely."""
        return run_dirsearch(args, max_time=max_time)

    return server


mcp = create_mcp() if FastMCP is not None else None


def parse_mcp_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run dirsearch as a FastMCP server")
    parser.add_argument("--mcp", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--mcp-transport",
        choices=("stdio", "http"),
        default=MCP_DEFAULT_TRANSPORT,
        help="MCP transport to use (default: {0})".format(MCP_DEFAULT_TRANSPORT),
    )
    parser.add_argument("--mcp-host", default=MCP_DEFAULT_HOST, help="HTTP MCP bind host")
    parser.add_argument("--mcp-port", type=int, default=MCP_DEFAULT_PORT, help="HTTP MCP bind port")
    parser.add_argument("--mcp-path", default=MCP_DEFAULT_PATH, help="HTTP MCP endpoint path")
    parser.add_argument(
        "--mcp-token",
        nargs="?",
        const="",
        default=None,
        help="Enable bearer token auth (auto-generates if flag provided without value)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_mcp_args(argv)
    auth_token = None

    if args.mcp_token is not None:
        auth_token = args.mcp_token.strip() if args.mcp_token else secrets.token_urlsafe(32)
        sys.stderr.write(f"MCP auth token: {auth_token}\n")

    server = create_mcp(auth_token)

    if args.mcp_transport == "http":
        server.run(
            transport="http",
            host=args.mcp_host,
            port=args.mcp_port,
            path=args.mcp_path,
            show_banner=False,
        )
    else:
        server.run(show_banner=False)


if __name__ == "__main__":
    main()
