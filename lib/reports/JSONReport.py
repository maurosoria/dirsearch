from lib.reports import *
import json

class JSONReport(BaseReport):
    def generate(self):
        headerName = "{0}://{1}:{2}/{3}".format(self.protocol, self.host, self.port, self.basePath)
        result = { headerName : [] }
        for status, path in self.pathList:
            result[headerName].append([status, path])

        return json.dumps(result, sort_keys=True, indent=4,)
