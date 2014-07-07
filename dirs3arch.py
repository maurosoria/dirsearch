#!/usr/bin/env python
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


import os
from lib.controller import *

class Program(object):
    def __init__(self):
        self.script_path = (os.path.dirname(os.path.realpath(__file__)))
        self.arguments = ArgumentsParser(self.script_path)
        self.output = Output()
        self.output.printHeader(PROGRAM_BANNER)
        self.output.printHeader("version {0}.{1}.{2}\n".format(MAYOR_VERSION, MINOR_VERSION, REVISION))
        self.controller = Controller(self.script_path, self.arguments, self.output)


if __name__ == '__main__':
    MAYOR_VERSION = 0
    MINOR_VERSION = 2
    REVISION = 3
    PROGRAM_BANNER = \
    r"""         _ _            _____                  _     
      __| (_)_ __ ___  |___ /    __ _ _ __ ___| |__  
     / _` | | '__/ __|   |_ \   / _` | '__/ __| '_ \ 
    | (_| | | |  \__ \  ___) | | (_| | | | (__| | | |
     \__,_|_|_|  |___/ |____/   \__,_|_|  \___|_| |_|
                                                     
    """
    main = Program()