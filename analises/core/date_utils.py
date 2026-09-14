from datetime import datetime


DB_DATE_FORMAT = "%d-%m-%Y"
DISPLAY_DATE_FORMAT = "%d/%m/%Y"


def parse_date(value):
    for fmt in (DB_DATE_FORMAT, DISPLAY_DATE_FORMAT, "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt)
        except (TypeError, ValueError):
            pass
    return None


def normalize_date_for_db(value):
    parsed = parse_date(value)
    return parsed.strftime(DB_DATE_FORMAT) if parsed else value


def format_date_for_display(value):
    parsed = parse_date(value)
    return parsed.strftime(DISPLAY_DATE_FORMAT) if parsed else str(value or "")


def sortable_date(value, fallback="9999-12-31"):
    parsed = parse_date(value)
    return parsed.strftime("%Y-%m-%d") if parsed else fallback


def sql_date_expr(column="Data"):
    legacy_date = (
        f"SUBSTR({column}, 7, 4) || '-' || "
        f"SUBSTR({column}, 4, 2) || '-' || SUBSTR({column}, 1, 2)"
    )
    return (
        "(CASE "
        f"WHEN SUBSTR({column}, 5, 1) = '-' AND SUBSTR({column}, 8, 1) = '-' "
        f"THEN SUBSTR({column}, 1, 10) "
        f"ELSE {legacy_date} END)"
    )
