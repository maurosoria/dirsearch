import os
import sys

from lib.core.argument_parser import ArgumentParser
from lib.output.verbose_output import CLIOutput
from lib.output.silent_output import PrintOutput
from lib.controller.controller import LibController

from functools import wraps

def add_method(cls):
    def decorator(func):
        @wraps(func) 
        def wrapper(self, *args, **kwargs): 
            return func(*args, **kwargs)
        setattr(cls, func.__name__, wrapper)
        # Note we are not binding func, but wrapper which accepts self but does exactly the same as func
        return func # returning func means func can still be used normally
    return decorator



class DirFoundHandler:
    def __init__(self):
        self.dirs = []
    def add(self, path, reponse, full_url, added_to_queue):
        self.dirs.append( (path, reponse.status, reponse) )
        self.found_dir(path, reponse, full_url, added_to_queue)
    def found_dir(self, path, reponse, full_url, added_to_queue):
        pass
    def config_data(self, extensions, prefixes, suffixes, threads_count, dictionary, http_method):
        pass


class dirsearch(object):
    def __init__(self, dfh):

        self.script_path = os.path.dirname(os.path.realpath(__file__))
        self.dfh = dfh

    def run(self, args: list):

        args.insert(0, "__main__.py")

        orignal_argv = sys.argv # save current arguments
        
        sys.argv = args

        self.arguments = ArgumentParser(self.script_path) 

        sys.argv = orignal_argv # restore original arguments


        self.output = PrintOutput(self.arguments.color)
       


        self.controller = LibController(self.script_path, self.arguments, self.output, self.dfh)


