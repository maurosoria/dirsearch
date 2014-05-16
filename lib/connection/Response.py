# -*- coding: utf-8 -*-


class Response(object):

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
        return self.status == other.status and self.body == other.body

    def __cmp__(self, other):
        return cmp(self.body, other.body)

    def __len__(self):
        return len(self.body)

    def __hash__(self):
        return hash(self.body)

    @property
    def pretty(self):
        try:
            from BeautifulSoup import BeautifulSoup
        except ImportError:
            raise Exception('BeautifulSoup must be installed to get pretty HTML =(')
        html = BeautifulSoup(self.body)
        return html.prettify()


