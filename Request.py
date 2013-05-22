import httplib, urlparse, socket, urllib

class RequestException(Exception):
    pass

class Response:
    def __init__(self, status, reason, body):
        self.status = status
        self.reason = reason
        self.body = body

class Requester:
    headers = {
        'User-agent' : 'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/28.0.1468.0 Safari/537.36',
        'Accept-Language': 'en-us',
        'Accept-Encoding': 'identity',
        'Keep-Alive': '300',
        'Connection': 'keep-alive',
        'Cache-Control': 'max-age=0',
    }

    def __init__(self, url, cookie = "", useragent = "", maxRetries = 5):
        #if no backslash, append one    
        if url[len(url) - 1] != '/':
            url = url + '/'

        #if not protocol specified, set http by default
        parsed = urlparse.urlparse(url)
        if(parsed.scheme == ''):
            parsed = urlparse.urlparse('http://' + url)
        self.protocol = parsed.scheme
        if (self.protocol != 'http') and (self.protocol != 'https'): 
            self.protocol = 'http'
        
        basePath = parsed.path
        self.basePath = basePath

        #Parse port number
        self.host = parsed.netloc.split(':')[0]
        self.ip = socket.gethostbyname(self.host)
        self.headers['Host'] = self.host
        self.maxRetries = maxRetries

        try:
            self.port = parsed.netloc.split(':')[1]
        except IndexError:
            self.port = None

        #Set cookie and user-agent headers
        if cookie != "":
            self.setHeader("Cookie", cookie)
        if useragent != "":
            self.setHeader("User-agent", useragent)

        
    def setHeader(self, header, content):
        self.headers[header] = content

    def getConnection(self):
        connection = None
        if (self.protocol == 'https'):
            return httplib.HTTPSConnection(self.ip, port = self.port)
        else:
            return httplib.HTTPConnection(self.ip, port = self.port)

    def request(self, path, method="GET", params=""):
        i = 0
        while i <= self.maxRetries:
            try:
                conn = self.getConnection()
                conn.request(method, self.basePath + path, urllib.urlencode(params), self.headers)
                response = conn.getresponse()
                result = Response(response.status, response.reason, response.read())
                break
            except socket.error:
                continue
            except httplib.BadStatusLine:
                return Response(0, "", "")
            finally:
                i = i + 1
        if(i > self.maxRetries):
            raise RequestException({"message" : "There was a problem in the request to: {0}".format(path)})
        conn.close()
        return result