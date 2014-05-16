# -*- coding: utf-8 -*-
import os
import os.path


class FileUtils(object):

    def __init__(self, *pathComponents):
        path = None
        if pathComponents:
            path = os.path.join(*pathComponents)
        else:
            path = ''
        self.path = os.path.abspath(path)

    @staticmethod
    def isValid(fileName):
        raise NotImplementedError

    @staticmethod
    def exists(fileName):
        raise NotImplementedError

    @staticmethod
    def canRead(fileName):
        raise NotImplementedError

    @staticmethod
    def canWrite(fileName):
        raise NotImplementedError

    @staticmethod
    def read(fileName):
        raise NotImplementedError


