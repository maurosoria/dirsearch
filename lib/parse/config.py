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

import configparser
import json


class ConfigParser(configparser.ConfigParser):
    def safe_get(self, section, option, default=None, allowed=None):
        try:
            value = super().get(section, option)

            if allowed and value not in allowed:
                return default

            return value
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default

    def safe_getfloat(self, section, option, default=0, allowed=None):
        try:
            value = super().getfloat(section, option)

            if allowed and value not in allowed:
                return default

            return value
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default

    def safe_getboolean(self, section, option, default=False, allowed=None):
        try:
            value = super().getboolean(section, option)

            if allowed and value not in allowed:
                return default

            return value
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default

    def safe_getint(self, section, option, default=0, allowed=None):
        try:
            value = super().getint(section, option)

            if allowed and value not in allowed:
                return default

            return value
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default

    def safe_getlist(self, section, option, default=[], allowed=None):
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
