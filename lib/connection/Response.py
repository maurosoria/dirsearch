class Response:
    def __init__(self, status, reason, headers, body):
        self.status = status
        self.reason = reason
        self.headers = headers
        self.body = body


    def __str__(self):
        return self.body


    def __int__(self):
        return self.status


    def __eq__(self, other):
        return (self.status == other.status) and (self.body == other.body)