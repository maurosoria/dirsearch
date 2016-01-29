#!/usr/bin/env python3
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

import sys
if sys.version_info < (3, 0):
    sys.stdout.write("Sorry, dirsearch requires Python 3.x\n")
    sys.exit(1)

from lib.core import ArgumentParser
from lib.controller import *
from lib.output import *

class Program(object):
    def __init__(self):
        self.script_path = (os.path.dirname(os.path.realpath(__file__)))
        self.arguments = ArgumentParser(self.script_path)
        self.output = CLIOutput()        
        self.controller = Controller(self.script_path, self.arguments, self.output)


if __name__ == '__main__':
    #from pympler.tracker import SummaryTracker
    #tracker = SummaryTracker()
    main = Program()
    #tracker.print_diff()