#!/usr/bin/env python
import os
import sys
from lib.controller import *

class Program:
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
    REVISION = 1
    PROGRAM_BANNER = \
    r"""         _ _            _____                  _     
      __| (_)_ __ ___  |___ /    __ _ _ __ ___| |__  
     / _` | | '__/ __|   |_ \   / _` | '__/ __| '_ \ 
    | (_| | | |  \__ \  ___) | | (_| | | | (__| | | |
     \__,_|_|_|  |___/ |____/   \__,_|_|  \___|_| |_|
                                                     
    """
    main = Program()