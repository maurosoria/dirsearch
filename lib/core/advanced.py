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

import re

from lib.utils import FileUtils


class Signatures(object):
    def __init__(self, signatures):
        self.signatures = signatures
        pass

    def check(self, httpmethod, resp):
        signatures = []

        for signature in self.signatures:
            for object in signature:
                if not isinstance(signature[object], (list, dict)):
                    signature[object] = [signature[object]]

            if "status" in signature and resp.status not in signature["status"]:
                continue

            if "method" in signature and httpmethod not in [
                method.lower() for method in signature["method"]
            ]:
                continue

            if "path" in signature:
                if "regex" in signature["path"] and not any(
                    [
                        re.match(path, resp.path) for path in signature["path"]["regex"]
                    ]
                ):
                    continue

                elif "regex" not in signature["path"] and signature["path"][0] not in resp.path:
                    continue

            if "headers" in signature:
                match = False

                if "regex" in signature["headers"]:
                    headers = signature["headers"]["regex"]
                else:
                    headers = signature["headers"]

                for header in headers:
                    # Original: 'Key: Value'
                    #
                    # ['Key', ' Value']
                    header = header.split(":")
                    # ['key', ' Value']
                    header[0] = header[0].lower()
                    # ['key', 'Value']
                    if header[1].startswith(" "):
                        header[1] = header[1][1:]
                    # 'key:Value'
                    header = ":".join(header)

                    for h in list(resp.response.headers.items()):
                        if "regex" in signature["headers"] and re.match(
                            # {'Key': 'Value'} => 'key:Value'
                            header, ":".join([h[0].lower(), h[1]])
                        ):
                            match = True
                            break

                        elif "regex" not in signature["headers"] and header in ":".join(
                            # {'Key': 'Value'} => 'key:Value'
                            [h[0].lower(), h[1]]
                        ):
                            match = True
                            break

                    if match:
                        break

                if not match:
                    continue

            if "body" in signature:
                if "regex" in signature["body"] and not re.match(
                    signature["body"]["regex"][0], resp.response.body
                ):
                    continue

                elif "regex" not in signature["body"] and signature["body"][0] not in resp.response.body:
                    continue

            try:
                signatures.append(signature["name"][0])
            except Exception:
                # Consequence when you forgot to add the 'name' object
                pass

        return signatures
