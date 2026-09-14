from __future__ import annotations

import re
import sqlite3
import atexit
import os
import queue
import threading
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import psycopg


class CompatRow:
    def __init__(self, columns: Sequence[str], values: Sequence[Any]):
        self._columns = list(columns)
        self._values = tuple(values)
        self._index = {name: index for index, name in enumerate(self._columns)}

    def keys(self) -> list[str]:
        return list(self._columns)

    def values(self) -> tuple[Any, ...]:
        return self._values

    def items(self):
        return [(key, self[key]) for key in self._columns]

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except (KeyError, IndexError):
            return default

    def __getitem__(self, key: int | slice | str) -> Any:
        if isinstance(key, (int, slice)):
            return self._values[key]
        return self._values[self._index[key]]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __contains__(self, key: object) -> bool:
        return key in self._index

    def __repr__(self) -> str:
        values = ", ".join(f"{key}={self[key]!r}" for key in self._columns)
        return f"CompatRow({values})"


class CompatCursor:
    def __init__(self, connection: "CompatConnection"):
        self.connection = connection
        self._cursor = connection.raw.cursor()
        self._rows: list[Any] | None = None
        self._row_index = 0
        self._description = None
        self._rowcount = -1
        self.lastrowid: Any = None

    @property
    def description(self):
        return self._description if self._description is not None else self._cursor.description

    @property
    def rowcount(self) -> int:
        return self._rowcount if self._rows is not None else self._cursor.rowcount

    def execute(self, query: str, params: Iterable[Any] | None = None):
        self.lastrowid = None
        self._rows = None
        self._row_index = 0
        handled = self._execute_special(query, tuple(params or ()))
        if handled:
            return self

        translated = translate_sql(query)
        translated, returning_id = self.connection.maybe_add_returning_id(translated)
        self._cursor.execute(translated, tuple(params or ()))
        self._description = self._cursor.description
        self._rowcount = self._cursor.rowcount

        if returning_id:
            row = self._cursor.fetchone()
            self.lastrowid = row[0] if row else None
            self._rows = []
            self._description = None
        return self

    def executemany(self, query: str, params_seq: Iterable[Iterable[Any]]):
        self.lastrowid = None
        self._rows = None
        self._row_index = 0
        translated = translate_sql(query)
        self._cursor.executemany(translated, [tuple(params) for params in params_seq])
        self._description = self._cursor.description
        self._rowcount = self._cursor.rowcount
        return self

    def executescript(self, script: str):
        self.connection.executescript(script)
        self._set_rows([], [])
        return self

    def fetchone(self):
        if self._rows is not None:
            if self._row_index >= len(self._rows):
                return None
            row = self._rows[self._row_index]
            self._row_index += 1
            return row
        row = self._cursor.fetchone()
        return self.connection.wrap_row(self._cursor.description, row)

    def fetchall(self):
        if self._rows is not None:
            rows = self._rows[self._row_index :]
            self._row_index = len(self._rows)
            return rows
        rows = self._cursor.fetchall()
        return [self.connection.wrap_row(self._cursor.description, row) for row in rows]

    def fetchmany(self, size: int | None = None):
        if size is None:
            size = 1
        if self._rows is not None:
            end = min(self._row_index + size, len(self._rows))
            rows = self._rows[self._row_index : end]
            self._row_index = end
            return rows
        rows = self._cursor.fetchmany(size)
        return [self.connection.wrap_row(self._cursor.description, row) for row in rows]

    def close(self) -> None:
        self._cursor.close()

    def __iter__(self):
        return iter(self.fetchall())

    def _set_rows(self, columns: Sequence[str], values: Sequence[Sequence[Any]]) -> None:
        self._description = [(column,) for column in columns]
        self._rows = [self.connection.make_row(columns, value) for value in values]
        self._rowcount = len(self._rows)

    def _execute_special(self, query: str, params: Sequence[Any]) -> bool:
        normalized = normalize_sql(query)
        if not normalized:
            self._set_rows([], [])
            return True

        pragma = re.match(r"PRAGMA\s+([A-Za-z_]+)(?:\(([^)]*)\))?", normalized, re.IGNORECASE)
        if pragma:
            name = pragma.group(1).lower()
            argument = (pragma.group(2) or "").strip().strip("'\"")
            if name == "table_info":
                rows = self.connection.table_info(argument)
                self._set_rows(["cid", "name", "type", "notnull", "dflt_value", "pk"], rows)
            elif name in {"quick_check", "integrity_check"}:
                self._set_rows([name], [("ok",)])
            elif name == "journal_mode":
                self._set_rows(["journal_mode"], [("postgresql",)])
            else:
                self._set_rows([], [])
            return True

        if re.search(r"FROM\s+sqlite_master", normalized, re.IGNORECASE):
            self._execute_sqlite_master_query(normalized, params)
            return True

        return False

    def _execute_sqlite_master_query(self, query: str, params: Sequence[Any]) -> None:
        table_name = str(params[0]) if params else ""
        if "COUNT(*)" in query.upper():
            count = self.connection.count_tables()
            self._set_rows(["COUNT(*)"], [(count,)])
            return
        if "AND name = ?" in query or "AND name=?" in query:
            rows = [(table_name,)] if table_name and self.connection.table_exists(table_name) else []
            self._set_rows(["name"], rows)
            return
        rows = [(name,) for name in self.connection.list_tables()]
        self._set_rows(["name"], rows)


class _ConnectionPool:
    def __init__(self, database_url: str, max_size: int):
        self.database_url = database_url
        self.max_size = max(1, max_size)
        self._available: queue.LifoQueue = queue.LifoQueue()
        self._created = 0
        self._lock = threading.Lock()

    def _discard(self, connection) -> None:
        try:
            connection.close()
        except Exception:
            pass
        finally:
            with self._lock:
                self._created = max(0, self._created - 1)

    def _is_usable(self, connection) -> bool:
        if connection.closed:
            self._discard(connection)
            return False
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            connection.rollback()
            return True
        except Exception:
            self._discard(connection)
            return False

    def acquire(self):
        wait_seconds = float(os.environ.get("AGRICOLA_PG_POOL_WAIT_SECONDS", "10"))
        while True:
            try:
                connection = self._available.get_nowait()
            except queue.Empty:
                connection = None

            if connection is not None:
                if self._is_usable(connection):
                    return connection
                continue

            create_new = False
            with self._lock:
                if self._created < self.max_size:
                    self._created += 1
                    create_new = True
            if create_new:
                try:
                    return psycopg.connect(self.database_url)
                except Exception:
                    with self._lock:
                        self._created = max(0, self._created - 1)
                    raise

            connection = self._available.get(timeout=wait_seconds)
            if self._is_usable(connection):
                return connection

    def release(self, connection) -> None:
        try:
            if connection.closed:
                with self._lock:
                    self._created = max(0, self._created - 1)
                return
            try:
                connection.rollback()
            except Exception:
                connection.close()
                with self._lock:
                    self._created = max(0, self._created - 1)
                return
            self._available.put_nowait(connection)
        except Exception:
            try:
                connection.close()
            finally:
                with self._lock:
                    self._created = max(0, self._created - 1)

    def close_all(self) -> None:
        while True:
            try:
                connection = self._available.get_nowait()
            except queue.Empty:
                return
            try:
                connection.close()
            except Exception:
                pass
            finally:
                with self._lock:
                    self._created = max(0, self._created - 1)


_POOLS: dict[str, _ConnectionPool] = {}
_POOLS_LOCK = threading.Lock()


def _pool_for(database_url: str) -> _ConnectionPool:
    max_size = int(os.environ.get("AGRICOLA_PG_POOL_MAX", "8"))
    with _POOLS_LOCK:
        pool = _POOLS.get(database_url)
        if pool is None:
            pool = _ConnectionPool(database_url, max_size)
            _POOLS[database_url] = pool
        return pool


def close_all_pools() -> None:
    with _POOLS_LOCK:
        pools = list(_POOLS.values())
        _POOLS.clear()
    for pool in pools:
        pool.close_all()


atexit.register(close_all_pools)


class CompatConnection:
    def __init__(self, database_url: str, *, use_pool: bool = True):
        self._pool = _pool_for(database_url) if use_pool else None
        self.raw = self._pool.acquire() if self._pool else psycopg.connect(database_url)
        self._row_factory = None
        self._dict_rows = False
        self._id_column_cache: dict[str, bool] = {}
        self._closed = False

    @property
    def row_factory(self):
        return self._row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._row_factory = value
        self._dict_rows = value is not None

    def cursor(self) -> CompatCursor:
        return CompatCursor(self)

    def execute(self, query: str, params: Iterable[Any] | None = None) -> CompatCursor:
        return self.cursor().execute(query, params)

    def executemany(self, query: str, params_seq: Iterable[Iterable[Any]]) -> CompatCursor:
        return self.cursor().executemany(query, params_seq)

    def executescript(self, script: str) -> None:
        for statement in split_sql_script(script):
            if not statement.strip():
                continue
            if re.search(r"CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?sqlite_sequence\b", statement, re.IGNORECASE):
                continue
            self.execute(statement)

    def commit(self) -> None:
        self.raw.commit()

    def rollback(self) -> None:
        self.raw.rollback()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._pool:
            self._pool.release(self.raw)
        else:
            self.raw.close()

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

    def make_row(self, columns: Sequence[str], values: Sequence[Any]):
        if self._dict_rows:
            return CompatRow(columns, values)
        return tuple(values)

    def wrap_row(self, description, row):
        if row is None:
            return None
        columns = [item.name if hasattr(item, "name") else item[0] for item in (description or [])]
        return self.make_row(columns, row)

    def table_exists(self, table_name: str) -> bool:
        lookup_name = table_name.lower()
        with self.raw.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = %s
                """,
                (lookup_name,),
            )
            return cursor.fetchone() is not None

    def list_tables(self) -> list[str]:
        with self.raw.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            )
            return [row[0] for row in cursor.fetchall()]

    def count_tables(self) -> int:
        return len(self.list_tables())

    def table_info(self, table_name: str) -> list[tuple[Any, ...]]:
        lookup_name = table_name.lower()
        with self.raw.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                ORDER BY ordinal_position
                """,
                (lookup_name,),
            )
            columns = cursor.fetchall()
            cursor.execute(
                """
                SELECT a.attname
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = %s::regclass
                  AND i.indisprimary
                ORDER BY array_position(i.indkey, a.attnum)
                """,
                (lookup_name,),
            )
            pk_columns = {row[0]: index + 1 for index, row in enumerate(cursor.fetchall())}
        result = []
        for index, (name, data_type, nullable, default) in enumerate(columns):
            result.append((index, name, data_type, 0 if nullable == "YES" else 1, default, pk_columns.get(name, 0)))
        return result

    def maybe_add_returning_id(self, sql: str) -> tuple[str, bool]:
        if re.search(r"\bRETURNING\b", sql, re.IGNORECASE) or re.search(r"\bON\s+CONFLICT\s+DO\s+NOTHING\b", sql, re.IGNORECASE):
            return sql, False
        match = re.match(r"\s*INSERT\s+INTO\s+\"?([A-Za-z_][A-Za-z0-9_]*)\"?\b", sql, re.IGNORECASE)
        if not match:
            return sql, False
        table_name = match.group(1)
        if not self.has_id_column(table_name):
            return sql, False
        return f"{sql.rstrip().rstrip(';')} RETURNING id", True

    def has_id_column(self, table_name: str) -> bool:
        lookup_name = table_name.lower()
        cached = self._id_column_cache.get(lookup_name)
        if cached is not None:
            return cached
        with self.raw.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                  AND column_name = 'id'
                """,
                (lookup_name,),
            )
            exists = cursor.fetchone() is not None
        self._id_column_cache[lookup_name] = exists
        return exists


def connect(database_url: str, *, row_factory: Any = sqlite3.Row, use_pool: bool | None = None) -> CompatConnection:
    from .demo_safety import assert_demo_database_target
    assert_demo_database_target(database_url)
    if use_pool is None:
        use_pool = os.environ.get("AGRICOLA_PG_POOL_ENABLED", "1") != "0"
    conn = CompatConnection(database_url, use_pool=use_pool)
    conn.row_factory = row_factory
    return conn


def connect_sqlite(sqlite_path: str | Path, *, timeout: float = 30, row_factory: Any = sqlite3.Row):
    conn = sqlite3.connect(str(sqlite_path), timeout=timeout)
    conn.row_factory = row_factory
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA wal_autocheckpoint = 1000")
    return conn


def translate_sql(query: str) -> str:
    sql = normalize_sql(query)
    sql = re.sub(r"\bCOLLATE\s+NOCASE\b", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bLIKE\b", "ILIKE", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bIFNULL\s*\(", "COALESCE(", sql, flags=re.IGNORECASE)
    sql = translate_group_concat(sql)
    sql = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "BIGSERIAL PRIMARY KEY", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bAUTOINCREMENT\b", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bDATETIME\b", "TIMESTAMP", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bBLOB\b", "BYTEA", sql, flags=re.IGNORECASE)
    sql = re.sub(
        r"\bTEXT(\s+(?:NOT\s+NULL\s+)?)DEFAULT\s+CURRENT_TIMESTAMP\b",
        r"TEXT\1DEFAULT (CURRENT_TIMESTAMP::text)",
        sql,
        flags=re.IGNORECASE,
    )
    sql = translate_placeholders(sql)

    if re.match(r"\s*INSERT\s+INTO\b", sql, re.IGNORECASE) and "ON CONFLICT" not in sql.upper():
        original = normalize_sql(query)
        if re.match(r"\s*INSERT\s+OR\s+IGNORE\s+INTO\b", original, re.IGNORECASE):
            sql = f"{sql.rstrip().rstrip(';')} ON CONFLICT DO NOTHING"
    return sql


def normalize_sql(query: str) -> str:
    return str(query or "").strip().rstrip(";")


def _split_top_level_args(inner: str) -> list[str]:
    args: list[str] = []
    current: list[str] = []
    depth = 0
    in_single = False
    previous = ""
    for char in inner:
        if char == "'" and previous != "\\":
            in_single = not in_single
        if not in_single:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == "," and depth == 0:
                args.append("".join(current))
                current = []
                previous = char
                continue
        current.append(char)
        previous = char
    if current:
        args.append("".join(current))
    return args


def translate_group_concat(sql: str) -> str:
    """Converte GROUP_CONCAT(expr[, sep]) do SQLite para string_agg do PostgreSQL.

    Usa correspondencia de parenteses balanceada para suportar expressoes
    aninhadas como GROUP_CONCAT(DISTINCT NULLIF(TRIM(col), '')).
    """
    pattern = re.compile(r"\bGROUP_CONCAT\s*\(", re.IGNORECASE)
    while True:
        match = pattern.search(sql)
        if not match:
            return sql

        open_idx = match.end() - 1
        depth = 0
        in_single = False
        previous = ""
        close_idx = -1
        for index in range(open_idx, len(sql)):
            char = sql[index]
            if char == "'" and previous != "\\":
                in_single = not in_single
            elif not in_single:
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        close_idx = index
                        break
            previous = char

        if close_idx == -1:
            return sql  # parenteses desbalanceado: deixa como esta

        inner = sql[open_idx + 1 : close_idx]
        distinct = ""
        stripped = inner.lstrip()
        if re.match(r"DISTINCT\b", stripped, re.IGNORECASE):
            distinct = "DISTINCT "
            inner = stripped[len("DISTINCT"):]

        args = _split_top_level_args(inner)
        expr = args[0].strip() if args else inner.strip()
        separator = args[1].strip() if len(args) > 1 else "','"

        replacement = f"string_agg({distinct}({expr})::text, {separator})"
        sql = sql[: match.start()] + replacement + sql[close_idx + 1 :]


def translate_placeholders(sql: str) -> str:
    result: list[str] = []
    in_single = False
    in_double = False
    previous = ""
    for char in sql:
        if char == "'" and not in_double and previous != "\\":
            in_single = not in_single
        elif char == '"' and not in_single and previous != "\\":
            in_double = not in_double
        if char == "?" and not in_single and not in_double:
            result.append("%s")
        elif char == "%":
            # psycopg processes percent markers even in SQL strings and with
            # an empty parameter tuple. Preserve LIKE wildcards and modulo.
            result.append("%%")
        else:
            result.append(char)
        previous = char
    return "".join(result)


def split_sql_script(script: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    previous = ""
    for char in script:
        if char == "'" and not in_double and previous != "\\":
            in_single = not in_single
        elif char == '"' and not in_single and previous != "\\":
            in_double = not in_double
        if char == ";" and not in_single and not in_double:
            statements.append("".join(current))
            current = []
        else:
            current.append(char)
        previous = char
    if current:
        statements.append("".join(current))
    return statements
