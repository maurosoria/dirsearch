#!/usr/bin/env python
from optparse import OptionParser, OptionGroup
from Fuzzer import *
from Request import *
from FuzzerDictionary import *
from Output import *

class Program:
    def __init__(self):
        usage = "Usage: %prog [-u|--url] target [-e|--extensions] extensions [options]"
        parser = OptionParser(usage)
        
        # Mandatory arguments
        mandatory = OptionGroup(parser, 'Mandatory')
        mandatory.add_option("-u", "--url", help="URL target", action="store", type="string", dest="url", default=None)
        mandatory.add_option("-e", "--extensions", help="Extensions list separated by comma (Example: php, asp)", \
            action="store", dest="extensions", default=None)

        # Optional Settings
        settings = OptionGroup(parser, 'Optional Settings')
        settings.add_option("-t", "--threads", help="Number of Threads", action="store", type="int", \
            dest="threadsCount", default=10)
        settings.add_option("-x", "--exclude-500", help="Exclude Internal Server Error Status (500)", action="store_true", \
            dest="exclude500", default=False)
        settings.add_option("--cookie", "--cookie", action="store", type="string", dest="cookie", default="")
        settings.add_option("--user-agent", "--user-agent", action="store", type="string", dest="useragent", \
            default="")
        settings.add_option("-w", "--wordlist", action="store", dest="wordlist", default="db/dicc.txt")
        settings.add_option("-l", "--lowercase", action="store_true", dest="lowercase", default="False")
        settings.add_option("--ignore-response-status", "--ignore-response-status", action="store", type="string", dest="ignoreResponseStatus", default="")

        parser.add_option_group(mandatory)
        parser.add_option_group(settings)
        (options, arguments) = parser.parse_args()
        if options.url == None:
            print("Url target is missing")
            exit(0)
        if options.extensions == None:
            print("No extension specified. You must specify at least one extension")
            exit(0)
        try:
            with open(options.wordlist): pass
        except IOError:
            print ("Invalid wordlist file")
            exit(0)
        self.url = options.url
        self.extensions = [extension.strip() for extension in options.extensions.split(",")]
        self.useragent = options.useragent
        self.cookie = options.cookie
        self.threadsCount = options.threadsCount
        self.exclude500 = options.exclude500
        self.wordlist = options.wordlist
        self.lowercase = options.lowercase


    def run(self):
        output = Output()
        output.printHeader(programBanner)
        output.printHeader("version 0.2\n")
        output.printWarning("- Searching in: {0}".format(self.url))
        output.printWarning("- For extensions: {0}".format(', '.join(self.extensions)))
        output.printWarning("- Number of Threads: {0}\n".format(self.threadsCount))
        requester = Requester(self.url, self.cookie, self.useragent)
        dictionary = FuzzerDictionary(self.wordlist, self.extensions, self.lowercase)
        
        fuzzer = Fuzzer(requester, dictionary, output, threads = self.threadsCount, \
            excludeInternalServerError = self.exclude500)
        try:
            fuzzer.start()
            fuzzer.wait()
        except KeyboardInterrupt:
            output.printError("\nCanceled by the user")
            exit(0)
        output.printWarning("\nTask Completed")

if __name__ == '__main__':
    programBanner = \
    r"""         _ _            _____                  _     
      __| (_)_ __ ___  |___ /    __ _ _ __ ___| |__  
     / _` | | '__/ __|   |_ \   / _` | '__/ __| '_ \ 
    | (_| | | |  \__ \  ___) | | (_| | | | (__| | | |
     \__,_|_|_|  |___/ |____/   \__,_|_|  \___|_| |_|
                                                     
    """
    main = Program()
    main.run()