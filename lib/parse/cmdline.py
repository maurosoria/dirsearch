# -*- coding: utf-8 -*-
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#  Author: Mauro Soria

from optparse import OptionParser, OptionGroup


from lib.core.settings import (
    AUTHENTICATION_TYPES,
    OUTPUT_FORMATS,
    VERSION,
)
from lib.utils.common import get_config_file


def parse_arguments():
    usage = "Usage: %prog [-u|--url] target [-e|--extensions] extensions [options]"
    epilog = "See 'config.ini' for the example configuration file"
    parser = OptionParser(usage=usage, epilog=epilog, version=f"dirsearch v{VERSION}")

    # Mandatory arguments
    mandatory = OptionGroup(parser, "Mandatory")
    mandatory.add_option(
        "-u",
        "--url",
        action="append",
        dest="urls",
        metavar="URL",
        help="Target URL(s), can use multiple flags",
    )
    mandatory.add_option(
        "-l",
        "--urls-file",
        action="store",
        dest="urls_file",
        metavar="PATH",
        help="URL list file",
    )
    mandatory.add_option(
        "--stdin", action="store_true", dest="stdin_urls", help="Read URL(s) from STDIN"
    )
    mandatory.add_option("--cidr", action="store", dest="cidr", help="Target CIDR")
    mandatory.add_option(
        "--raw",
        action="store",
        dest="raw_file",
        metavar="PATH",
        help="Load raw HTTP request from file (use '--scheme' flag to set the scheme)",
    )
    mandatory.add_option(
        "--nmap-report",
        action="store",
        dest="nmap_report",
        metavar="PATH",
        help="Load targets from nmap report (Ensure the inclusion of the -sV flag during nmap scan for comprehensive results)",
    )
    mandatory.add_option(
        "-s", "--session", action="store", dest="session_file", help="Session file"
    )
    mandatory.add_option(
        "--config",
        action="store",
        dest="config",
        metavar="PATH",
        help="Path to configuration file (Default: 'DIRSEARCH_CONFIG' environment variable, otherwise 'config.ini')",
        default=get_config_file(),
    )

    # Dictionary Settings
    dictionary = OptionGroup(parser, "Dictionary Settings")
    dictionary.add_option(
        "-w",
        "--wordlists",
        action="store",
        dest="wordlists",
        help="Wordlist files or directories contain wordlists (separated by commas)",
    )
    dictionary.add_option(
        "-e",
        "--extensions",
        action="store",
        dest="extensions",
        help="Extension list separated by commas (e.g. php,asp)",
    )
    dictionary.add_option(
        "-f",
        "--force-extensions",
        action="store_true",
        dest="force_extensions",
        help="Add extensions to the end of every wordlist entry. By default dirsearch only replaces the %EXT% keyword with extensions",
    )
    dictionary.add_option(
        "-O",
        "--overwrite-extensions",
        action="store_true",
        dest="overwrite_extensions",
        help="Overwrite other extensions in the wordlist with your extensions (selected via `-e`)",
    )
    dictionary.add_option(
        "--exclude-extensions",
        action="store",
        dest="exclude_extensions",
        metavar="EXTENSIONS",
        help="Exclude extension list separated by commas (e.g. asp,jsp)",
    )
    dictionary.add_option(
        "--remove-extensions",
        action="store_true",
        dest="remove_extensions",
        help="Remove extensions in all paths (e.g. admin.php -> admin)",
    )
    dictionary.add_option(
        "--prefixes",
        action="store",
        dest="prefixes",
        help="Add custom prefixes to all wordlist entries (separated by commas)",
    )
    dictionary.add_option(
        "--suffixes",
        action="store",
        dest="suffixes",
        help="Add custom suffixes to all wordlist entries, ignore directories (separated by commas)",
    )
    dictionary.add_option(
        "-U",
        "--uppercase",
        action="store_true",
        dest="uppercase",
        help="Uppercase wordlist",
    )
    dictionary.add_option(
        "-L",
        "--lowercase",
        action="store_true",
        dest="lowercase",
        help="Lowercase wordlist",
    )
    dictionary.add_option(
        "-C",
        "--capital",
        action="store_true",
        dest="capitalization",
        help="Capital wordlist",
    )

    # Optional Settings
    general = OptionGroup(parser, "General Settings")
    general.add_option(
        "-t",
        "--threads",
        action="store",
        type="int",
        dest="thread_count",
        metavar="THREADS",
        help="Number of threads",
    )
    general.add_option(
        "-r",
        "--recursive",
        action="store_true",
        dest="recursive",
        help="Brute-force recursively",
    )
    general.add_option(
        "--deep-recursive",
        action="store_true",
        dest="deep_recursive",
        help="Perform recursive scan on every directory depth (e.g. api/users -> api/)",
    )
    general.add_option(
        "--force-recursive",
        action="store_true",
        dest="force_recursive",
        help="Do recursive brute-force for every found path, not only directories",
    )
    general.add_option(
        "-R",
        "--max-recursion-depth",
        action="store",
        type="int",
        dest="recursion_depth",
        metavar="DEPTH",
        help="Maximum recursion depth",
    )
    general.add_option(
        "--recursion-status",
        action="store",
        dest="recursion_status_codes",
        metavar="CODES",
        help="Valid status codes to perform recursive scan, support ranges (separated by commas)",
    )
    general.add_option(
        "--subdirs",
        action="store",
        dest="subdirs",
        metavar="SUBDIRS",
        help="Scan sub-directories of the given URL[s] (separated by commas)",
    )
    general.add_option(
        "--exclude-subdirs",
        action="store",
        dest="exclude_subdirs",
        metavar="SUBDIRS",
        help="Exclude the following subdirectories during recursive scan (separated by commas)",
    )
    general.add_option(
        "-i",
        "--include-status",
        action="store",
        dest="include_status_codes",
        metavar="CODES",
        help="Include status codes, separated by commas, support ranges (e.g. 200,300-399)",
    )
    general.add_option(
        "-x",
        "--exclude-status",
        action="store",
        dest="exclude_status_codes",
        metavar="CODES",
        help="Exclude status codes, separated by commas, support ranges (e.g. 301,500-599)",
    )
    general.add_option(
        "--exclude-sizes",
        action="store",
        dest="exclude_sizes",
        metavar="SIZES",
        help="Exclude responses by sizes, separated by commas (e.g. 0B,4KB)",
    )
    general.add_option(
        "--exclude-text",
        action="append",
        dest="exclude_texts",
        metavar="TEXTS",
        help="Exclude responses by text, can use multiple flags",
    )
    general.add_option(
        "--exclude-regex",
        action="store",
        dest="exclude_regex",
        metavar="REGEX",
        help="Exclude responses by regular expression",
    )
    general.add_option(
        "--exclude-redirect",
        action="store",
        dest="exclude_redirect",
        metavar="STRING",
        help="Exclude responses if this regex (or text) matches redirect URL (e.g. '/index.html')",
    )
    general.add_option(
        "--exclude-response",
        action="store",
        dest="exclude_response",
        metavar="PATH",
        help="Exclude responses similar to response of this page, path as input (e.g. 404.html)",
    )
    general.add_option(
        "--skip-on-status",
        action="store",
        dest="skip_on_status",
        metavar="CODES",
        help="Skip target whenever hit one of these status codes, separated by commas, support ranges",
    )
    general.add_option(
        "--min-response-size",
        action="store",
        type="int",
        dest="minimum_response_size",
        help="Minimum response length",
        metavar="LENGTH",
        default=0,
    )
    general.add_option(
        "--max-response-size",
        action="store",
        type="int",
        dest="maximum_response_size",
        help="Maximum response length",
        metavar="LENGTH",
        default=0,
    )
    general.add_option(
        "--max-time",
        action="store",
        type="int",
        dest="max_time",
        metavar="SECONDS",
        help="Maximum runtime for the scan",
    )
    general.add_option(
        "--exit-on-error",
        action="store_true",
        dest="exit_on_error",
        help="Exit whenever an error occurs",
    )

    # Request Settings
    request = OptionGroup(parser, "Request Settings")
    request.add_option(
        "-m",
        "--http-method",
        action="store",
        dest="http_method",
        metavar="METHOD",
        help="HTTP method (default: GET)",
    )
    request.add_option(
        "-d", "--data", action="store", dest="data", help="HTTP request data"
    )
    request.add_option(
        "--data-file",
        action="store",
        dest="data_file",
        metavar="PATH",
        help="File contains HTTP request data"
    )
    request.add_option(
        "-H",
        "--header",
        action="append",
        dest="headers",
        help="HTTP request header, can use multiple flags",
    )
    request.add_option(
        "--headers-file",
        dest="headers_file",
        metavar="PATH",
        help="File contains HTTP request headers",
    )
    request.add_option(
        "-F",
        "--follow-redirects",
        action="store_true",
        dest="follow_redirects",
        help="Follow HTTP redirects",
    )
    request.add_option(
        "--random-agent",
        action="store_true",
        dest="random_agents",
        help="Choose a random User-Agent for each request",
    )
    request.add_option(
        "--auth",
        action="store",
        dest="auth",
        metavar="CREDENTIAL",
        help="Authentication credential (e.g. user:password or bearer token)",
    )
    request.add_option(
        "--auth-type",
        action="store",
        dest="auth_type",
        metavar="TYPE",
        help=f"Authentication type ({', '.join(AUTHENTICATION_TYPES)})",
    )
    request.add_option(
        "--cert-file",
        action="store",
        dest="cert_file",
        metavar="PATH",
        help="File contains client-side certificate",
    )
    request.add_option(
        "--key-file",
        action="store",
        dest="key_file",
        metavar="PATH",
        help="File contains client-side certificate private key (unencrypted)",
    )
    request.add_option("--user-agent", action="store", dest="user_agent")
    request.add_option("--cookie", action="store", dest="cookie")

    # Connection Settings
    connection = OptionGroup(parser, "Connection Settings")
    connection.add_option(
        "--timeout",
        action="store",
        type="float",
        dest="timeout",
        help="Connection timeout",
    )
    connection.add_option(
        "--delay",
        action="store",
        type="float",
        dest="delay",
        help="Delay between requests",
    )
    connection.add_option(
        "-p",
        "--proxy",
        action="append",
        dest="proxies",
        metavar="PROXY",
        help="Proxy URL (HTTP/SOCKS), can use multiple flags",
    )
    connection.add_option(
        "--proxies-file",
        action="store",
        dest="proxies_file",
        metavar="PATH",
        help="File contains proxy servers",
    )
    connection.add_option(
        "--proxy-auth",
        action="store",
        dest="proxy_auth",
        metavar="CREDENTIAL",
        help="Proxy authentication credential",
    )
    connection.add_option(
        "--replay-proxy",
        action="store",
        dest="replay_proxy",
        metavar="PROXY",
        help="Proxy to replay with found paths",
    )
    connection.add_option(
        "--tor", action="store_true", dest="tor", help="Use Tor network as proxy"
    )
    connection.add_option(
        "--scheme",
        action="store",
        dest="scheme",
        metavar="SCHEME",
        help="Scheme for raw request or if there is no scheme in the URL (Default: auto-detect)",
    )
    connection.add_option(
        "--max-rate",
        action="store",
        type="int",
        dest="max_rate",
        metavar="RATE",
        help="Max requests per second",
    )
    connection.add_option(
        "--retries",
        action="store",
        type="int",
        dest="max_retries",
        metavar="RETRIES",
        help="Number of retries for failed requests",
    )
    connection.add_option("--ip", action="store", dest="ip", help="Server IP address")
    connection.add_option("--interface", action="store", dest="network_interface", help="Network interface to use")


    # Advanced Settings
    advanced = OptionGroup(parser, "Advanced Settings")
    advanced.add_option(
        "--crawl",
        action="store_true",
        dest="crawl",
        help="Crawl for new paths in responses"
    )

    # View Settings
    view = OptionGroup(parser, "View Settings")
    view.add_option(
        "--full-url",
        action="store_true",
        dest="full_url",
        help="Full URLs in the output (enabled automatically in quiet mode)",
    )
    view.add_option(
        "--redirects-history",
        action="store_true",
        dest="redirects_history",
        help="Show redirects history",
    )
    view.add_option(
        "--no-color", action="store_false", dest="color", help="No colored output"
    )
    view.add_option(
        "-q", "--quiet-mode", action="store_true", dest="quiet", help="Quiet mode"
    )

    # Output Settings
    output = OptionGroup(parser, "Output Settings")
    output.add_option(
        "-o",
        "--output",
        action="store",
        dest="output",
        metavar="PATH/URL",
        help="Output file or MySQL/PostgreSQL URL (Format: scheme://[username:password@]host[:port]/database-name)",
    )
    output.add_option(
        "--format",
        action="store",
        dest="output_format",
        metavar="FORMAT",
        help=f"Report format (Available: {','.join(OUTPUT_FORMATS)})",
    )
    output.add_option(
        "--log", action="store", dest="log_file", metavar="PATH", help="Log file"
    )

    parser.add_option_group(mandatory)
    parser.add_option_group(dictionary)
    parser.add_option_group(general)
    parser.add_option_group(request)
    parser.add_option_group(connection)
    parser.add_option_group(advanced)
    parser.add_option_group(view)
    parser.add_option_group(output)
    options, _ = parser.parse_args()

    return options
