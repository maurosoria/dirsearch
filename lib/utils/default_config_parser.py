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


class DefaultConfigParser(configparser.ConfigParser):
    def __init__(self):
        configparser.ConfigParser.__init__(self)

    def safe_get(self, section, option, default, allowed=None):
        try:
            result = configparser.ConfigParser.get(self, section, option)
            if allowed is not None:
                return result if result in allowed else default
            else:
                return result
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default

    def safe_getfloat(self, section, option, default, allowed=None):
        try:
            result = configparser.ConfigParser.getfloat(self, section, option)
            if allowed is not None:
                return result if result in allowed else default
            else:
                return result
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default

    def safe_getboolean(self, section, option, default, allowed=None):
        try:
            result = configparser.ConfigParser.getboolean(self, section, option)
            if allowed is not None:
                return result if result in allowed else default
            else:
                return result
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default

    def safe_getint(self, section, option, default, allowed=None):
        try:
            result = configparser.ConfigParser.getint(self, section, option)
            if allowed is not None:
                return result if result in allowed else default
            else:
                return result
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default
