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


# Remove parameters and fragment from the URL
def clean_path(path):
    return path.split('?')[0].split('#')[0]


def parse_full_path(url):
    if url.startswith('/') and not url.startswith("//"):
        return url
    elif "//" not in url:
        return '/' + url

    return '/' + '/'.join(url.split('/')[3:])


def parse_path(url):
    return clean_path(parse_full_path(url))


def join_path(*components):
    result = ''

    for component in [*components]:
        if not component:
            continue

        if result:
            if result.endswith('/'):
                result = result[:-1]
            if not component.startswith('/'):
                result += '/'

        result += component

    return result
