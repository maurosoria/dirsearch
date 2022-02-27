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

from lib.parse.url import join_path
from lib.utils.common import human_size
from lib.output.colors import set_color
from lib.output.verbose import Output as _Output


class Output(_Output):
    def status_report(self, response, full_url, added_to_queue):
        status = response.status
        content_length = human_size(response.length)
        url = join_path(self.url, response.full_path)
        message = f"{status} - {content_length.rjust(6, ' ')} - {url}"

        if status in (200, 201, 204):
            message = set_color(message, fore="green")
        elif status == 401:
            message = set_color(message, fore="yellow")
        elif status == 403:
            message = set_color(message, fore="blue")
        elif status in range(500, 600):
            message = set_color(message, fore="red")
        elif status in range(300, 400):
            message = set_color(message, fore="cyan")
        else:
            message = set_color(message, fore="magenta")

        if response.redirect:
            message += f"  ->  {response.redirect}"
        if added_to_queue:
            message += "     (Added to queue)"

        for redirect in response.history:
            message += f"\n-->  {redirect}"

        self.new_line(message)

    def last_path(self, *args):
        pass

    def warning(self, reason, save=True):
        pass

    def header(self, message):
        pass

    def config(self, *args):
        pass

    def set_target(self, target):
        self.target = target

    def output_file(self, target):
        pass

    def log_file(self, target):
        pass
