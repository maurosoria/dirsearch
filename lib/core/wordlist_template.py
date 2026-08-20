from __future__ import annotations

import itertools
import re
from collections.abc import Iterable, Iterator, Mapping
from datetime import date

from lib.core.settings import (
    BACKUP_EXTENSIONS,
    DB_ENGINES,
    EXTENSION_TAG,
    WORDLIST_CATEGORIES,
    WORDLIST_CATEGORY_DIR,
)
from lib.utils.file import FileUtils


TOKEN_RE = re.compile(r"%([A-Z0-9_:/-]+)%", re.IGNORECASE)


DEFAULT_PLACEHOLDERS: dict[str, tuple[str, ...]] = {
    "SUBJECT": (
        "user",
        "users",
        "account",
        "accounts",
        "profile",
        "article",
        "articles",
        "post",
        "posts",
        "product",
        "products",
        "order",
        "orders",
        "invoice",
        "invoices",
    ),
    "CRUD_OP": (
        "create",
        "read",
        "update",
        "delete",
        "list",
        "get",
        "add",
        "edit",
        "remove",
        "search",
    ),
    "AUTH_OP": (
        "login",
        "logout",
        "signin",
        "signout",
        "signup",
        "register",
        "reset",
        "forgot",
        "password",
        "oauth",
        "sso",
    ),
    "ADMIN_OP": (
        "admin",
        "dashboard",
        "panel",
        "manage",
        "settings",
        "users",
        "roles",
        "permissions",
    ),
    "ENV": ("dev", "development", "test", "stage", "staging", "prod", "production", "local"),
    "SEP": ("-", "_", ".", "/"),
    "DB": DB_ENGINES,
    "DB_ENGINE": DB_ENGINES,
    "BACKUP": BACKUP_EXTENSIONS,
    "BACKUP_EXT": BACKUP_EXTENSIONS,
    "API_VERSION": ("v1", "v2", "v3", "v4", "latest", "beta"),
}


def normalize_placeholders(
    placeholders: Mapping[str, Iterable[str] | str] | None,
) -> dict[str, tuple[str, ...]]:
    normalized: dict[str, tuple[str, ...]] = {}
    for key, values in (placeholders or {}).items():
        token = key.strip("%").upper()
        if isinstance(values, str):
            normalized[token] = (values,)
        else:
            normalized[token] = tuple(str(value) for value in values)
    return normalized


def expand_template_line(
    line: str,
    *,
    extensions: Iterable[str] = (),
    placeholders: Mapping[str, Iterable[str] | str] | None = None,
) -> Iterator[str]:
    values = _placeholder_values(extensions, placeholders)
    tokens: list[str] = []
    for token in TOKEN_RE.findall(line):
        normalized = token.upper()
        if normalized in tokens:
            continue
        if _resolve_token(normalized, values) is not None:
            tokens.append(normalized)

    if not tokens:
        yield line
        return

    expansions = [_resolve_token(token, values) for token in tokens]
    if any(expansion is None for expansion in expansions):
        yield line
        return
    if any(not expansion for expansion in expansions):
        return

    for combo in itertools.product(*expansions):
        rendered = line
        for token, value in zip(tokens, combo):
            rendered = re.sub(f"%{re.escape(token)}%", value, rendered, flags=re.IGNORECASE)
        yield rendered


def _placeholder_values(
    extensions: Iterable[str],
    placeholders: Mapping[str, Iterable[str] | str] | None,
) -> dict[str, tuple[str, ...]]:
    today = date.today()
    values = dict(DEFAULT_PLACEHOLDERS)
    values.update(
        {
            EXTENSION_TAG.strip("%").upper(): tuple(extensions),
            "YYYY": (today.strftime("%Y"),),
            "YY": (today.strftime("%y"),),
            "MM": (today.strftime("%m"),),
            "DD": (today.strftime("%d"),),
            "DATE": (today.isoformat(),),
            "DATE_COMPACT": (today.strftime("%Y%m%d"),),
        }
    )
    values.update(normalize_placeholders(placeholders))
    return values


def _resolve_token(token: str, values: Mapping[str, tuple[str, ...]]) -> tuple[str, ...] | None:
    if token.startswith("CATEGORY:"):
        return _load_category(token.split(":", 1)[1].lower())
    return values.get(token)


def _load_category(name: str) -> tuple[str, ...]:
    if not re.fullmatch(r"[a-z0-9_./-]+", name):
        return ()

    filename = WORDLIST_CATEGORIES.get(name)
    if filename:
        path = FileUtils.build_path(WORDLIST_CATEGORY_DIR, filename)
    else:
        path = FileUtils.build_path(WORDLIST_CATEGORY_DIR, f"{name}.txt")

    if not FileUtils.can_read(path):
        return ()

    return tuple(
        line.strip().lstrip("/")
        for line in FileUtils.get_lines(path)
        if line.strip() and not line.strip().startswith("#")
    )
