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

blacklists = {}
options = {
    "urls": [],
    "urls_file": None,
    "stdin_urls": None,
    "cidr": None,
    "raw_file": None,
    "session_file": None,
    "config": None,
    "wordlists": [],
    "extensions": (),
    "force_extensions": False,
    "overwrite_extensions": False,
    "exclude_extensions": (),
    "remove_extensions": None,
    "prefixes": (),
    "suffixes": (),
    "uppercase": False,
    "lowercase": False,
    "capitalization": False,
    "thread_count": 25,
    "recursive": False,
    "deep_recursive": False,
    "force_recursive": False,
    "recursion_depth": 0,
    "recursion_status_codes": set(),
    "subdirs": [],
    "exclude_subdirs": [],
    "include_status_codes": set(),
    "exclude_status_codes": set(),
    "exclude_sizes": set(),
    "exclude_texts": None,
    "exclude_regex": None,
    "exclude_redirect": None,
    "exclude_response": None,
    "skip_on_status": set(),
    "minimum_response_size": 0,
    "maximum_response_size": 0,
    "maxtime": 0,
    "http_method": "GET",
    "data": None,
    "data_file": None,
    "nmap_report": None,
    "headers": {},
    "headers_file": None,
    "follow_redirects": False,
    "random_agents": False,
    "auth": None,
    "auth_type": None,
    "cert_file": None,
    "key_file": None,
    "user_agent": None,
    "cookie": None,
    "timeout": 10,
    "delay": 0.0,
    "proxies": [],
    "proxies_file": None,
    "proxy_auth": None,
    "replay_proxy": None,
    "tor": None,
    "scheme": None,
    "max_rate": 0,
    "max_retries": 1,
    "network_interface": None,
    "ip": None,
    "exit_on_error": False,
    "crawl": False,
    "full_url": False,
    "redirects_history": False,
    "color": True,
    "quiet": False,
    "output_file": None,
    "output_format": None,
    "log_file": None,
    "output_path": None,
    "autosave_report": True,
    "log_file_size": 0
}
