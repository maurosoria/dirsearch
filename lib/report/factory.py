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

import hashlib
import json
import os
import sqlite3
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass

from lib.core.decorators import locked
from lib.core.exceptions import (
    CannotConnectException,
    FileExistsException,
    InvalidURLException,
)
from lib.core.settings import DEFAULT_ENCODING
from lib.utils import safe_xml
from lib.utils.file import FileUtils


REPORT_PARSE_ERRORS = (
    OSError,
    ValueError,
    KeyError,
    IndexError,
    TypeError,
    safe_xml.ParseError,
    safe_xml.UnsafeXML,
)

SQL_CONNECTION_ERRORS = (
    OSError,
    ValueError,
    ImportError,
    sqlite3.DatabaseError,
    InvalidURLException,
)


class BaseReport(ABC):
    def __init__(self):
        self._operation_lock = threading.Lock()

    @abstractmethod
    def initiate(self):
        raise NotImplementedError

    @abstractmethod
    def save(self, result):
        raise NotImplementedError

    def flush(self):
        pass


class FileReportMixin:
    _newline = None

    def initiate(self, file):
        FileUtils.create_dir(FileUtils.parent(file))
        if FileUtils.exists(file) and not FileUtils.is_empty(file):
            self.validate(file)
        else:
            self.write(file, self.new())

    def validate(self, file):
        try:
            self.parse(file)
        except REPORT_PARSE_ERRORS as error:
            raise FileExistsException(f"Output file {file} already exists") from error

    def parse(self, file):
        with open(file, "r", encoding=DEFAULT_ENCODING) as file_handle:
            return file_handle.read()

    def _atomic_writer(self, file):
        return FileUtils.atomic_write_private_text(
            file,
            encoding=DEFAULT_ENCODING,
            newline=self._newline,
        )

    def write(self, file, data):
        with self._atomic_writer(file) as fh:
            fh.write(data)

    def append(self, file, data):
        FileUtils.append_private_text(
            file,
            data,
            encoding=DEFAULT_ENCODING,
            newline=self._newline,
        )

    def finish(self):
        pass


@dataclass
class _StructuredReportState:
    journal_base_hash: str
    journal_entries: int = 0
    applied_entries: int = 0


class StructuredFileReportMixin(FileReportMixin):
    """Persist entries in a journal and compact them into one final snapshot."""

    _journal_version = 1

    def __init__(self):
        super().__init__()
        self._report_states: dict[str, _StructuredReportState] = {}

    @staticmethod
    def journal_path(file):
        parent = FileUtils.parent(file)
        name = f".{os.path.basename(file)}.dirsearch-journal"
        return os.path.join(parent, name)

    def _state_for_journal(self, data):
        return data

    def _new_state(self):
        return self.new()

    def _state_hash(self, data):
        serialized = json.dumps(
            self._state_for_journal(data),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode(DEFAULT_ENCODING)
        return hashlib.sha256(serialized).hexdigest()

    def _apply_entry(self, data, entry):
        raise NotImplementedError

    def _journal_record(self, record):
        return json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ) + "\n"

    def _write_journal_header(self, file, state):
        journal = self.journal_path(file)
        header = {
            "base": state.journal_base_hash,
            "format": self.__format__,
            "kind": "header",
            "version": self._journal_version,
        }
        with FileUtils.atomic_write_private_text(
            journal,
            encoding=DEFAULT_ENCODING,
        ) as file_handle:
            file_handle.write(self._journal_record(header))

    def _append_journal_record(self, file, state, record):
        journal = self.journal_path(file)
        if not FileUtils.exists(journal):
            if state.journal_entries or state.applied_entries:
                raise OSError(f"Structured report journal disappeared: {journal}")
            self._write_journal_header(file, state)

        FileUtils.append_private_text(
            journal,
            self._journal_record(record),
            encoding=DEFAULT_ENCODING,
        )

    def _read_journal(self, file, data):
        journal = self.journal_path(file)
        with open(journal, encoding=DEFAULT_ENCODING) as file_handle:
            records = [json.loads(line) for line in file_handle if line.strip()]

        if not records or not isinstance(records[0], dict):
            raise ValueError(f"Invalid structured report journal: {journal}")

        header = records[0]
        if set(header) != {"base", "format", "kind", "version"} or header != {
            "base": header.get("base"),
            "format": self.__format__,
            "kind": "header",
            "version": self._journal_version,
        }:
            raise ValueError(f"Invalid structured report journal: {journal}")

        base_hash = header["base"]
        if not isinstance(base_hash, str):
            raise ValueError(f"Invalid structured report journal: {journal}")
        entries = []
        commits = []
        for record in records[1:]:
            if not isinstance(record, dict):
                raise ValueError(f"Invalid structured report journal: {journal}")
            kind = record.get("kind")
            if kind == "result" and set(record) == {"entry", "kind"}:
                entries.append(record["entry"])
            elif kind == "commit" and set(record) == {
                "entries",
                "kind",
                "report",
            }:
                entry_count = record["entries"]
                if type(entry_count) is not int or not 0 <= entry_count <= len(entries):
                    raise ValueError(f"Invalid structured report journal: {journal}")
                if not isinstance(record["report"], str):
                    raise ValueError(f"Invalid structured report journal: {journal}")
                commits.append((entry_count, record["report"]))
            else:
                raise ValueError(f"Invalid structured report journal: {journal}")

        current_hash = self._state_hash(data)
        if current_hash == base_hash:
            applied_entries = 0
        else:
            matching_commits = [
                entry_count
                for entry_count, report_hash in commits
                if report_hash == current_hash
            ]
            if not matching_commits:
                raise ValueError(
                    f"Structured report and journal are inconsistent: {file}"
                )
            applied_entries = max(matching_commits)

        for entry in entries[applied_entries:]:
            self._apply_entry(data, entry)

        return _StructuredReportState(
            journal_base_hash=base_hash,
            journal_entries=len(entries),
            applied_entries=applied_entries,
        )

    @locked
    def initiate(self, file):
        if file in self._report_states:
            return

        FileUtils.create_dir(FileUtils.parent(file))
        try:
            if FileUtils.exists(file) and not FileUtils.is_empty(file):
                data = self.parse(file)
            else:
                data = self._new_state()
                self.write(file, data)

            state = _StructuredReportState(
                journal_base_hash=self._state_hash(data),
            )
            journal = self.journal_path(file)
            if FileUtils.exists(journal):
                state = self._read_journal(file, data)
                if state.applied_entries == state.journal_entries:
                    try:
                        FileUtils.remove(journal)
                    except OSError:
                        pass
                    else:
                        state.journal_base_hash = self._state_hash(data)
                        state.journal_entries = 0
                        state.applied_entries = 0
        except REPORT_PARSE_ERRORS as error:
            raise FileExistsException(f"Output file {file} already exists") from error

        self._report_states[file] = state

    def save_entry(self, file, entry):
        try:
            state = self._report_states[file]
        except KeyError as error:
            raise RuntimeError(f"Report was not initiated: {file}") from error

        self._append_journal_record(
            file,
            state,
            {"entry": entry, "kind": "result"},
        )
        state.journal_entries += 1

    def _compact(self, file, state):
        journal = self.journal_path(file)
        if not FileUtils.exists(journal):
            if state.journal_entries or state.applied_entries:
                raise OSError(f"Structured report journal disappeared: {journal}")
            return

        data = self.parse(file)
        recovered = self._read_journal(file, data)
        state.journal_base_hash = recovered.journal_base_hash
        state.journal_entries = recovered.journal_entries
        state.applied_entries = recovered.applied_entries

        if state.journal_entries == state.applied_entries:
            try:
                FileUtils.remove(journal)
            except OSError:
                return
            state.journal_base_hash = self._state_hash(data)
            state.journal_entries = 0
            state.applied_entries = 0
            return

        report_hash = self._state_hash(data)
        self._append_journal_record(
            file,
            state,
            {
                "entries": state.journal_entries,
                "kind": "commit",
                "report": report_hash,
            },
        )
        self.write(file, data)
        state.applied_entries = state.journal_entries

        try:
            FileUtils.remove(journal)
        except OSError:
            return

        state.journal_base_hash = report_hash
        state.journal_entries = 0
        state.applied_entries = 0

    @locked
    def flush(self):
        first_error = None
        for file, state in self._report_states.items():
            try:
                self._compact(file, state)
            except BaseException as error:
                if first_error is None:
                    first_error = error

        if first_error is not None:
            raise first_error

    finish = flush


class SQLReportMixin:
    # Reuse the connection
    _conn = None
    _conn_database = None

    def get_connection(self, database):
        # Reuse the old connection
        if not self._reuse:
            return self.connect(database)

        if self._conn is not None and self._conn_database != database:
            self._close_connection()

        if self._conn is None:
            self._conn = self.connect(database)
            self._conn_database = database

        return self._conn

    def _commit(self, conn):
        conn.commit()

    def _after_save(self, conn):
        self._commit(conn)

    def _close_connection(self):
        conn = self._conn
        if conn is None:
            return

        try:
            self._commit(conn)
        finally:
            try:
                conn.close()
            finally:
                self._conn = None
                self._conn_database = None

    def get_create_table_query(self, table):
        return (f'''CREATE TABLE IF NOT EXISTS "{table}" (
            time TIMESTAMP,
            url TEXT,
            status_code INTEGER,
            content_length INTEGER,
            content_type TEXT,
            redirect TEXT
        );''',)

    def get_insert_table_query(self, table, values):
        return (f'''INSERT INTO "{table}" (time, url, status_code, content_length, content_type, redirect)
                    VALUES
                    (%s, %s, %s, %s, %s, %s);''', values)

    def initiate(self, database, table):
        try:
            conn = self.get_connection(database)
        except SQL_CONNECTION_ERRORS as e:
            raise CannotConnectException(f"Cannot connect to the SQL database: {str(e)}") from e

        cursor = conn.cursor()

        cursor.execute(*self.get_create_table_query(table))
        self._commit(conn)

        if not self._reuse:
            conn.close()

    @locked
    def save(self, database, table, result):
        conn = self.get_connection(database)
        cursor = conn.cursor()

        cursor.execute(
            *self.get_insert_table_query(
                table,
                (
                    result.datetime,
                    result.url,
                    result.status,
                    result.length,
                    result.type,
                    result.redirect,
                ),
            )
        )
        self._after_save(conn)

        if not self._reuse:
            conn.close()

    @locked
    def flush(self):
        if self._conn is not None:
            self._commit(self._conn)

    @locked
    def finish(self):
        self._close_connection()
