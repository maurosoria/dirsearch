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

try:
    import cPickle as _pickle
except ModuleNotFoundError:
    import pickle as _pickle

from lib.core.exceptions import UnpicklingError

ALLOWED_PICKLE_CLASSES = (
    "collections.OrderedDict",
    "http.cookiejar.DefaultCookiePolicy",
    "requests.adapters.HTTPAdapter",
    "requests.cookies.RequestsCookieJar",
    "requests.sessions.Session",
    "requests.structures.CaseInsensitiveDict",
    "lib.connection.requester.Requester",
    "lib.connection.response.Response",
    "lib.connection.requester.Session",
    "lib.core.dictionary.Dictionary",
    "lib.core.report_manager.Report",
    "lib.core.report_manager.ReportManager",
    "lib.core.report_manager.Result",
    "lib.core.structures.AttributeDict",
    "lib.core.structures.CaseInsensitiveDict",
    "lib.output.verbose.Output",
    "lib.reports.csv_report.CSVReport",
    "lib.reports.html_report.HTMLReport",
    "lib.reports.json_report.JSONReport",
    "lib.reports.markdown_report.MarkdownReport",
    "lib.reports.plain_text_report.PlainTextReport",
    "lib.reports.simple_report.SimpleReport",
    "lib.reports.xml_report.XMLReport",
    "lib.reports.sqlite_report.SQLiteReport",
    "urllib3.util.retry.Retry",
)


# Reference: https://docs.python.org/3.4/library/pickle.html#restricting-globals
class RestrictedUnpickler(_pickle.Unpickler):
    def find_class(self, module, name):
        if f"{module}.{name}" in ALLOWED_PICKLE_CLASSES:
            return super().find_class(module, name)

        raise UnpicklingError()


def unpickle(*args, **kwargs):
    return RestrictedUnpickler(*args, **kwargs).load()


def pickle(obj, *args, **kwargs):
    return _pickle.Pickler(*args, **kwargs).dump(obj)
