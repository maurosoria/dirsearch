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

import os
import sys
from lib.core import ArgumentParser
from lib.controller import *
from lib.output import *
from lib.utils import FileUtils


class Program(object):
    def __init__(self, script_path, save_path):
        self.arguments = ArgumentParser(script_path)
        self.output = CLIOutput()
        log_path = os.path.join(save_path, 'logs')
        if not FileUtils.exists(log_path):
            FileUtils.createDirectory(log_path)
        self.controller = Controller(script_path, save_path, self.arguments, self.output)

def run_as_command():
    if sys.version_info < (3, 0):
        sys.stdout.write("Sorry, dirsearch requires Python 3.x\n")
        sys.exit(1)

    main = Program(os.path.dirname(os.path.dirname(__file__)), './')
