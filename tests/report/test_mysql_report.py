import sys
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from lib.core.settings import DB_CONNECTION_TIMEOUT
from lib.report.mysql_report import MySQLReport


@contextmanager
def fake_mysql_connector():
    connection = SimpleNamespace(sql_mode=None)
    connect = Mock(return_value=connection)

    mysql = ModuleType("mysql")
    connector = ModuleType("mysql.connector")
    constants = ModuleType("mysql.connector.constants")
    connector.connect = connect
    connector.Error = Exception
    constants.SQLMode = SimpleNamespace(ANSI_QUOTES="ANSI_QUOTES")
    mysql.connector = connector

    with patch.dict(
        sys.modules,
        {
            "mysql": mysql,
            "mysql.connector": connector,
            "mysql.connector.constants": constants,
        },
    ):
        yield connect, connection


class TestMySQLReportURLParsing(TestCase):
    def test_percent_decodes_connection_components(self):
        with fake_mysql_connector() as (connect, connection):
            result = MySQLReport().connect(
                "mysql://us%40er:p%40ss%3Aword@db.example:3307/"
                "report%2Farchive"
            )

        connect.assert_called_once_with(
            host="db.example",
            port=3307,
            user="us@er",
            password="p@ss:word",
            database="report/archive",
            connection_timeout=DB_CONNECTION_TIMEOUT,
        )
        self.assertIs(result, connection)
        self.assertEqual(connection.sql_mode, ["ANSI_QUOTES"])

    def test_literal_plus_is_not_decoded_as_space(self):
        with fake_mysql_connector() as (connect, _):
            MySQLReport().connect(
                "mysql://user+tag:pass+word@db.example/report+archive"
            )

        connect.assert_called_once_with(
            host="db.example",
            port=3306,
            user="user+tag",
            password="pass+word",
            database="report+archive",
            connection_timeout=DB_CONNECTION_TIMEOUT,
        )

    def test_missing_credentials_remain_none(self):
        with fake_mysql_connector() as (connect, _):
            MySQLReport().connect("mysql://db.example/report")

        connect.assert_called_once_with(
            host="db.example",
            port=3306,
            user=None,
            password=None,
            database="report",
            connection_timeout=DB_CONNECTION_TIMEOUT,
        )
