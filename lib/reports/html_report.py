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

import time
import sys
import os
from mako.template import Template

from lib.reports import *


class HTMLReport(FileBaseReport):
    def generate(self):
        metadata = {"info": {"args": ' '.join(sys.argv), "time": time.ctime()}, "results": []}
        template_file= os.path.dirname(os.path.realpath(__file__)) + '/templates/html_report_template.html'
        mytemplate = Template(filename=template_file)

        return mytemplate.render(info=metadata, entries=self.entries)

    def save(self):
        self.file.seek(0)
        self.file.truncate(0)
        self.file.flush()
        self.file.writelines(self.generate())
        self.file.flush()
