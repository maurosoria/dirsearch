from lib.reports import *

class ListReport(BaseReport):
    def generate(self):
        result = ""
        for status, path in self.pathList:
            result += "{0}://{1}:{2}/".format(self.protocol, self.host, self.port)
            result += "{0}\n".format(path) if self.basePath is "" else "{0}/{1}\n".format(self.basePath, path)

        return result
