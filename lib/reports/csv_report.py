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

from lib.reports import FileBaseReport


class CSVReport(FileBaseReport):
    def generate_header(self):
        if self.header_written is False:
            self.header_written = True
            return "URL,Status,Size,Redirection\n"
        else:
            return ""

    def generate(self):
        result = self.generate_header()
        insecure_chars = ("+", "-", "=", "@")

        for entry in self.entries:
            for e in entry.results:
                if (entry.protocol, entry.host, entry.port, entry.base_path, e.path) not in self.written_entries:
                    path = e.path
                    status = e.status
                    content_length = e.get_content_length()
                    redirect = e.response.redirect

                    result += "{0}://{1}:{2}/{3}{4},".format(entry.protocol, entry.host, entry.port, entry.base_path, path)
                    result += "{0},".format(status)
                    result += "{0},".format(content_length)
                    if redirect:
                        # Preventing CSV injection. More info: https://www.exploit-db.com/exploits/49370
                        if redirect.startswith(insecure_chars):
                            redirect = "'" + redirect

                        redirect = redirect.replace("\"", "\"\"")
                        result += "\"{0}\"".format(redirect)

                    result += "\n"
                    self.written_entries.append((entry.protocol, entry.host, entry.port, entry.base_path, e.path))

        return result
