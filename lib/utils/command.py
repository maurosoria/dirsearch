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
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#  Author: Mauro Soria

from collections.abc import Sequence


REDACTED_VALUE = "<redacted>"

SENSITIVE_OPTIONS = frozenset(
    {
        "-d",
        "--data",
        "-H",
        "--header",
        "--auth",
        "--cookie",
        "-p",
        "--proxy",
        "--proxy-auth",
        "--replay-proxy",
        "--mysql-url",
        "--postgres-url",
    }
)

SENSITIVE_SHORT_OPTIONS = ("-d", "-H", "-p")

TARGET_OPTIONS = frozenset({"-u", "--url"})

SHORT_FLAG_OPTIONS = frozenset(
    {"-a", "-C", "-f", "-F", "-h", "-L", "-q", "-r", "-U", "-v"}
)


def _matches_option(option: str, candidates: frozenset[str]) -> bool:
    if option in candidates:
        return True
    return option.startswith("--") and any(
        candidate.startswith(option)
        for candidate in candidates
        if candidate.startswith("--")
    )


def _redact_value(option: str, value: str) -> str:
    if _matches_option(option, SENSITIVE_OPTIONS):
        return REDACTED_VALUE
    if _matches_option(option, TARGET_OPTIONS) and "@" in value:
        return REDACTED_VALUE
    return value


def _find_short_value_option(argument: str) -> tuple[str, int] | None:
    if not argument.startswith("-") or argument.startswith("--"):
        return None

    for index, character in enumerate(argument[1:], 1):
        option = f"-{character}"
        if option in SENSITIVE_SHORT_OPTIONS + ("-u",):
            return option, index + 1
        if option not in SHORT_FLAG_OPTIONS:
            return None
    return None


def redact_command(arguments: Sequence[str]) -> str:
    """Format command metadata without persisting credential-bearing values."""
    redacted = []
    index = 0

    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            redacted.extend(arguments[index:])
            break

        option, separator, value = argument.partition("=")
        if separator and option.startswith("--"):
            redacted.append(f"{option}={_redact_value(option, value)}")
            index += 1
            continue

        if _matches_option(argument, SENSITIVE_OPTIONS | TARGET_OPTIONS):
            redacted.append(argument)
            if index + 1 < len(arguments):
                redacted.append(_redact_value(argument, arguments[index + 1]))
                index += 2
            else:
                index += 1
            continue

        short_value_option = _find_short_value_option(argument)
        if short_value_option:
            short_option, value_index = short_value_option
            attached_value = argument[value_index:]
            if attached_value:
                redacted.append(
                    argument[:value_index]
                    + _redact_value(short_option, attached_value)
                )
            else:
                redacted.append(argument)
                if index + 1 < len(arguments):
                    redacted.append(
                        _redact_value(short_option, arguments[index + 1])
                    )
                    index += 1
        else:
            redacted.append(argument)
        index += 1

    return " ".join(redacted)
