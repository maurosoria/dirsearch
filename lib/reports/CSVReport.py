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
#  Author: Timo Goosen

from lib.reports import *
from lib.utils.FileUtils import *


class CSVReport(BaseReport):

    def generate(self):
        result = ''
        for path, status, contentLength in self.pathList:
            result += '{0},'.format(status)
#            result += '{0}'.format(FileUtils.sizeHuman(contentLength).rjust(6, ','))
            result += '{0},'.format(FileUtils.sizeHuman(contentLength))
            result += '{0},'.format(self.host)  # site
            result += ('{0}\n'.format(path) if self.basePath is '' else '{0}/{1}\n'.format(self.basePath, path))
        return result


# Output will look like this
# 302,26KB,pw.mail.ru,index.php

# We don't add any heading to the CSV but you could adapt the code to do that if you want it to.
# statuscode,contentlength,host,file_or_dir_name
