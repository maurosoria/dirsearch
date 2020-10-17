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

from lib.reports import *


class SimpleReport(TailableFileBaseReport):

    def generate(self):
        result = ""

        for path, _, _ in self.getPathIterator():

            result += "{0}://{1}:{2}/".format(self.protocol, self.host, self.port)
            result += (
                "{0}\n".format(path)
                if self.basePath == ""
                else "{0}/{1}\n".format(self.basePath, path)
            )

        return result
