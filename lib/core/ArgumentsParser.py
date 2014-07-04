from optparse import OptionParser, OptionGroup
from lib.utils.FileUtils import File
import os

class ArgumentsParser(object):
    def __init__(self, script_path):
        usage = "Usage: %prog [-u|--url] target [-e|--extensions] extensions [options]"
        parser = OptionParser(usage)
        self.script_path = script_path
        # Mandatory arguments
        mandatory = OptionGroup(parser, 'Mandatory')
        mandatory.add_option("-u", "--url", help="URL target", action="store", type="string", dest="url", default=None)
        mandatory.add_option("-e", "--extensions", help="Extensions list separated by comma (Example: php, asp)", \
            action="store", dest="extensions", default=None)


        # Connection settings
        connection = OptionGroup(parser, 'Connection Settings')
        connection.add_option("--timeout", "--timeout", action="store", dest="timeout", type="int", default=30, help="Connection timeout")
        connection.add_option("--ip", "--ip", action="store", dest="ip", default=None, help="Destination IP (instead of resolving domain, use this ip)")
        connection.add_option("--http-proxy", "--http-proxy", action="store", dest="httpProxy", type="string", default=None, help="Http Proxy (example: localhost:8080")
        connection.add_option("--max-retries", "--max-retries", action="store", dest="maxRetries", type="int", default=5)

        # Dictionary settings
        dictionary = OptionGroup(parser, 'Dictionary Settings')
        dictionary.add_option("-w", "--wordlist", action="store", dest="wordlist", default=("{1}{0}db{0}dicc.txt".format(os.path.sep, self.script_path)))
        dictionary.add_option("-l", "--lowercase", action="store_true", dest="lowercase", default="False")

        # Optional Settings
        general = OptionGroup(parser, 'General Settings')
        general.add_option("-r", "--recursive", help="Bruteforce recursively", action="store_true", \
            dest="recursive", default=False)
        general.add_option("-t", "--threads", help="Number of Threads", action="store", type="int", \
            dest="threadsCount", default=10)
        general.add_option("-x", "--exclude-status", help="Exclude status code, separated by comma (example: 301, 500)", action="store", \
            dest="excludeStatusCodes", default=[])
        general.add_option("--cookie", "--cookie", action="store", type="string", dest="cookie", default=None)
        general.add_option("--user-agent", "--user-agent", action="store", type="string", dest="useragent", \
            default=None)
        general.add_option("--no-follow-redirects", "--no-follow-redirects", action="store_true", dest="followRedirects", default=False)
        

        #settings.add_option("--ignore-response-status", "--ignore-response-status", action="store", type="string", dest="ignoreResponseStatus", default="")

        # Reports Settings
        reports = OptionGroup(parser, 'Reports')
        reports.add_option("-o", "--output", action="store", dest="outputFile", default=None)
        reports.add_option("--json-output", "--json-output", action="store", dest="jsonOutputFile", default=None)
        

        parser.add_option_group(mandatory)
        parser.add_option_group(dictionary)
        parser.add_option_group(general)
        parser.add_option_group(connection)
        parser.add_option_group(reports)
        (options, arguments) = parser.parse_args()
        if options.url == None:
            print("Url target is missing")
            exit(0)
        if options.extensions == None:
            print("No extension specified. You must specify at least one extension")
            exit(0)
        
        with File(options.wordlist) as wordlist:
            if not wordlist.exists():
                print ("The wordlist file does not exists")
                exit(0)
            if not wordlist.isValid():
                print ("The wordlist is invalid")
                exit(0)
            if not wordlist.canRead():
                print ("The wordlist cannot be read")
                exit(0)
        if options.httpProxy is not None:
            if options.httpProxy.startswith("http://"):
                self.proxy = options.httpProxy
            else:
                self.proxy = "http://{0}".format(options.httpProxy) 
        else:
            self.proxy = None
        self.url = options.url
        self.extensions = [extension.strip() for extension in options.extensions.split(",")]
        self.useragent = options.useragent
        self.cookie = options.cookie
        self.threadsCount = options.threadsCount
        self.excludeStatusCodes = [int(excludeStatusCode.strip()) for excludeStatusCode in options.excludeStatusCodes.split(",")]
        self.wordlist = options.wordlist
        self.lowercase = options.lowercase
        self.outputFile = options.outputFile
        self.jsonOutputFile = options.jsonOutputFile
        self.timeout = options.timeout
        self.ip = options.ip
        self.maxRetries = options.maxRetries
        self.recursive = options.recursive
        self.redirect = not options.followRedirects