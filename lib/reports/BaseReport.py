class BaseReport(object):
    def __init__(self, host, port, protocol, basePath, output):
        self.output = output
        self.port = port
        self.host = host
        self.protocol = protocol
        self.basePath = basePath
        if self.basePath.endswith('/'):
            self.basePath = self.basePath[:-1]
        if self.basePath.startswith('/'):
            self.basePath = self.basePath[1:]
        self.pathList = []
        self.open()


    def addPath(self, status, path):
        self.pathList.append((status, path))


    def open(self):
        self.file = open(self.output, 'w+')


    def save(self):
        self.file.writelines(self.generate())


    def close(self):
        self.file.close()


    def generate(self): raise NotImplementedError