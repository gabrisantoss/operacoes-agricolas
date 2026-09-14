from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row, tuple_row

from app_config import DATABASE_URL, DB_ENGINE, SQLITE_PATH


DB_TIMEOUT = 30
DATABASE_ERROR_TYPES = (sqlite3.Error, psycopg.Error)
INTEGRITY_ERROR_TYPES = (sqlite3.IntegrityError, psycopg.IntegrityError)
DatabaseError = DATABASE_ERROR_TYPES
IntegrityError = INTEGRITY_ERROR_TYPES


class _DatabaseGate:
    def __init__(self):
        self._condition = threading.Condition()
        self._active_connections = 0
        self._maintenance = False

    def acquire_connection(self):
        with self._condition:
            while self._maintenance:
                self._condition.wait()
            self._active_connections += 1

        released = False

        def release():
            nonlocal released
            if released:
                return
            released = True
            with self._condition:
                self._active_connections -= 1
                self._condition.notify_all()

        return release

    @contextmanager
    def maintenance(self):
        with self._condition:
            while self._maintenance:
                self._condition.wait()
            self._maintenance = True
            while self._active_connections:
                self._condition.wait()
        try:
            yield
        finally:
            with self._condition:
                self._maintenance = False
                self._condition.notify_all()


_DATABASE_GATE = _DatabaseGate()


def database_quiescence():
    """Block new connections and wait until active app connections are closed."""
    return _DATABASE_GATE.maintenance()


def normalize_db_engine(value: str | None = None) -> str:
    engine = str(value or DB_ENGINE).strip().lower()
    if engine in {"postgres", "postgresql"}:
        return "postgresql"
    if engine == "sqlite":
        return "sqlite"
    raise ValueError(f"Engine de banco não suportada: {value}")


def infer_db_engine_from_target(db_target: str | None) -> str:
    target = str(db_target or "").strip().lower()
    if target.startswith(("postgresql://", "postgres://")):
        return "postgresql"
    return "sqlite"


def is_postgresql(engine: str | None = None) -> bool:
    return normalize_db_engine(engine) == "postgresql"


def is_sqlite(engine: str | None = None) -> bool:
    return normalize_db_engine(engine) == "sqlite"


def resolve_connection_target(
    db_target: str | None = None,
    db_engine: str | None = None,
) -> tuple[str, str]:
    if db_target not in (None, ""):
        target = str(db_target).strip()
        engine = normalize_db_engine(db_engine or infer_db_engine_from_target(target))
        return engine, target

    engine = normalize_db_engine(db_engine)
    target = DATABASE_URL if is_postgresql(engine) else SQLITE_PATH
    return engine, target


def translate_query(query: str, engine: str | None = None) -> str:
    if not is_postgresql(engine):
        return query

    translated: list[str] = []
    in_single = False
    in_double = False
    prev = ""
    for char in query:
        if char == "'" and not in_double and prev != "\\":
            in_single = not in_single
        elif char == '"' and not in_single and prev != "\\":
            in_double = not in_double

        if char == "?" and not in_single and not in_double:
            translated.append("%s")
        else:
            translated.append(char)
        prev = char
    return "".join(translated)


class CursorWrapper:
    def __init__(self, cursor: Any, engine: str):
        self._cursor = cursor
        self._engine = normalize_db_engine(engine)

    def execute(self, query: str, params: Iterable[Any] | None = None):
        if params is None:
            self._cursor.execute(translate_query(query, self._engine))
        else:
            self._cursor.execute(translate_query(query, self._engine), params)
        return self

    def executemany(self, query: str, params_seq: Iterable[Iterable[Any]]):
        self._cursor.executemany(translate_query(query, self._engine), params_seq)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size: int | None = None):
        if size is None:
            return self._cursor.fetchmany()
        return self._cursor.fetchmany(size)

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return getattr(self._cursor, "lastrowid", None)

    @property
    def description(self):
        return self._cursor.description

    def close(self) -> None:
        self._cursor.close()

    def __iter__(self):
        return iter(self._cursor)

    def __getattr__(self, item: str):
        return getattr(self._cursor, item)


class ConnectionWrapper:
    def __init__(self, connection: Any, engine: str, dict_rows: bool = False, release_gate=None):
        self._connection = connection
        self._engine = normalize_db_engine(engine)
        self._dict_rows = dict_rows
        self._release_gate = release_gate
        self._closed = False
        self.row_factory = sqlite3.Row if dict_rows else None

    @property
    def row_factory(self):
        return getattr(self, "_row_factory", None)

    @row_factory.setter
    def row_factory(self, value):
        self._row_factory = value
        self._dict_rows = value is not None
        if is_sqlite(self._engine):
            self._connection.row_factory = sqlite3.Row if self._dict_rows else None
        else:
            self._connection.row_factory = dict_row if self._dict_rows else tuple_row

    def cursor(self) -> CursorWrapper:
        return CursorWrapper(self._connection.cursor(), self._engine)

    def execute(self, query: str, params: Iterable[Any] | None = None):
        return self.cursor().execute(query, params)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._connection.close()
        finally:
            if self._release_gate:
                self._release_gate()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False

    def __getattr__(self, item: str):
        return getattr(self._connection, item)


def get_db_connection(
    dict_rows: bool = False,
    *,
    db_target: str | None = None,
    db_engine: str | None = None,
) -> ConnectionWrapper:
    release_gate = _DATABASE_GATE.acquire_connection()
    try:
        engine, target = resolve_connection_target(db_target=db_target, db_engine=db_engine)
        if is_postgresql(engine):
            from agricola_shared.demo_safety import assert_demo_database_target
            assert_demo_database_target(target)
            connection = psycopg.connect(target, row_factory=dict_row if dict_rows else tuple_row)
            return ConnectionWrapper(
                connection,
                engine=engine,
                dict_rows=dict_rows,
                release_gate=release_gate,
            )

        connection = sqlite3.connect(target, timeout=DB_TIMEOUT)
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.execute("PRAGMA wal_autocheckpoint = 1000")
        return ConnectionWrapper(
            connection,
            engine=engine,
            dict_rows=dict_rows,
            release_gate=release_gate,
        )
    except Exception:
        release_gate()
        raise
