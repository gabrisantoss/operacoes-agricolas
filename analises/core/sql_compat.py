"""Small SQL fragments that differ between SQLite and PostgreSQL."""


def _is_postgres(engine: str) -> bool:
    return (engine or "").strip().lower() in {"postgres", "postgresql"}


def numeric_text_order_sql(column: str, engine: str) -> str:
    """Return a stable numeric-first ordering expression for a text column."""
    if _is_postgres(engine):
        return (
            f"NULLIF(regexp_replace(COALESCE({column}, ''), '[^0-9]', '', 'g'), '')::bigint "
            "NULLS LAST"
        )
    return f"CAST({column} AS INTEGER)"


def hhmm_minutes_sql(column: str, engine: str) -> str:
    """Convert HH:MM text into minutes without using SQLite-only functions on PG."""
    if _is_postgres(engine):
        return (
            f"CASE WHEN COALESCE({column}, '') ~ '^[0-9]+:[0-9]{{2}}$' "
            f"THEN split_part({column}, ':', 1)::integer * 60 "
            f"+ split_part({column}, ':', 2)::integer ELSE 0 END"
        )
    return (
        f"CASE WHEN {column} IS NULL OR INSTR({column}, ':') = 0 THEN 0 "
        f"ELSE CAST(SUBSTR({column}, 1, INSTR({column}, ':') - 1) AS INTEGER) * 60 "
        f"+ CAST(SUBSTR({column}, INSTR({column}, ':') + 1) AS INTEGER) END"
    )
