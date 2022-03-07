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

from lib.output.verbose import Output as _Output


class Output(_Output):
    def status_report(self, response, full_url, added_to_queue):
        super().status_report(response, True, added_to_queue)

    def last_path(self, *args):
        pass

    def new_directories(self, directories):
        pass

    def warning(self, reason, save=True):
        pass

    def header(self, message):
        pass

    def config(self, *args):
        pass

    def set_target(self, target):
        pass

    def output_file(self, file):
        pass

    def log_file(self, file):
        pass
