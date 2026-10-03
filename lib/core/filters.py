# -*- coding: utf-8 -*-
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.

from __future__ import annotations

import re


NumericRange = tuple[int, int]
TimeFilter = tuple[str, float]
SIZE_UNITS = {
    "B": 1,
    "KB": 1024,
    "MB": 1024 ** 2,
    "GB": 1024 ** 3,
    "TB": 1024 ** 4,
    "PB": 1024 ** 5,
    "EB": 1024 ** 6,
    "ZB": 1024 ** 7,
    "YB": 1024 ** 8,
}
SIZE_RE = re.compile(r"^(\d+)\s*([KMGTPEZY]?B)?$", re.IGNORECASE)


def parse_numeric_ranges(value: str | None) -> tuple[NumericRange, ...]:
    if not value:
        return ()

    ranges = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue

        if "-" in token:
            start, end = token.split("-", 1)
            try:
                minimum, maximum = int(start), int(end)
            except ValueError as error:
                raise ValueError(f"Invalid numeric range: {token}") from error

            if minimum > maximum:
                raise ValueError(f"Invalid numeric range: {token}")

            ranges.append((minimum, maximum))
            continue

        try:
            number = int(token)
        except ValueError as error:
            raise ValueError(f"Invalid numeric value: {token}") from error

        ranges.append((number, number))

    return tuple(ranges)


def parse_time_filters(value: str | None) -> tuple[TimeFilter, ...]:
    if not value:
        return ()

    filters = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue

        operator = "="
        if token[0] in (">", "<"):
            operator, token = token[0], token[1:]

        try:
            filters.append((operator, float(token)))
        except ValueError as error:
            raise ValueError(f"Invalid time filter: {operator}{token}") from error

    return tuple(filters)


def parse_size(value: str | int | None) -> int:
    if value is None or value == "":
        return 0

    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"Invalid response size: {value}")
        return value

    token = value.strip()
    if not token:
        return 0

    match = SIZE_RE.fullmatch(token)
    if not match:
        raise ValueError(f"Invalid response size: {value}")

    number, unit = match.groups()
    multiplier = SIZE_UNITS[(unit or "B").upper()]
    return int(number) * multiplier


def parse_size_list(value: str | None) -> set[int]:
    if not value:
        return set()

    sizes = set()
    for token in value.split(","):
        token = token.strip()
        if token:
            sizes.add(parse_size(token))

    return sizes


def validate_regex(pattern: str | None, label: str) -> None:
    if not pattern:
        return

    try:
        re.compile(pattern)
    except re.error as error:
        raise ValueError(f"Invalid {label} regular expression: {error}") from error


def matches_numeric_ranges(value: int, ranges: tuple[NumericRange, ...]) -> bool:
    return any(minimum <= value <= maximum for minimum, maximum in ranges)


def matches_time_filters(elapsed: float, filters: tuple[TimeFilter, ...]) -> bool:
    milliseconds = elapsed * 1000

    for operator, value in filters:
        if operator == ">" and milliseconds > value:
            return True
        if operator == "<" and milliseconds < value:
            return True
        if operator == "=" and milliseconds == value:
            return True

    return False
