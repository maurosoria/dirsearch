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

from __future__ import annotations

import configparser
import json


class ConfigParser(configparser.ConfigParser):
    def safe_get(
        self,
        section: str,
        option: str,
        default: str | None = None,
        allowed: tuple[str, ...] | None = None,
    ) -> str | None:
        try:
            value = super().get(section, option)

            if allowed and value not in allowed:
                return default

            return value
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default

    def safe_getfloat(
        self,
        section: str,
        option: str,
        default: float = 0.0,
        allowed: tuple[float, ...] | None = None,
    ) -> float:
        try:
            value = super().getfloat(section, option)

            if allowed and value not in allowed:
                return default

            return value
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default

    def safe_getboolean(
        self,
        section: str,
        option: str,
        default: bool = False,
        allowed: tuple[bool, ...] | None = None,
    ) -> bool:
        try:
            value = super().getboolean(section, option)

            if allowed and value not in allowed:
                return default

            return value
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default

    def safe_getint(
        self,
        section: str,
        option: str,
        default: int = 0,
        allowed: tuple[int, ...] | None = None,
    ) -> int:
        try:
            value = super().getint(section, option)

            if allowed and value not in allowed:
                return default

            return value
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default

    def safe_getlist(
        self,
        section: str,
        option: str,
        default: list[str] = [],
        allowed: tuple[str, ...] | None = None,
    ) -> list[str]:
        try:
            try:
                value = json.loads(super().get(section, option))
            except json.decoder.JSONDecodeError:
                value = [super().get(section, option)]

            if allowed and set(value) - set(allowed):
                return default

            return value
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default
