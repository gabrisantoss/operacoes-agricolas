OPERATIONAL_FLEET_TYPES = ("COLHEDORA", "TRANSBORDO")


def normalize_fleet_name(frota):
    return (frota or "").upper()


def fleet_matches_type(frota, fleet_type):
    return fleet_type.upper() in normalize_fleet_name(frota)


def is_colhedora(frota):
    return fleet_matches_type(frota, "COLHEDORA")


def is_transbordo(frota):
    return fleet_matches_type(frota, "TRANSBORDO")


def is_operational_fleet(frota):
    frota_normalizada = normalize_fleet_name(frota)
    return any(tipo in frota_normalizada for tipo in OPERATIONAL_FLEET_TYPES)


def fleet_type_sql(fleet_type, column="Frota"):
    return f"UPPER(COALESCE({column}, '')) LIKE '%{fleet_type.upper()}%'"


def operational_fleet_sql(column="Frota"):
    return "(" + " OR ".join(
        fleet_type_sql(tipo, column)
        for tipo in OPERATIONAL_FLEET_TYPES
    ) + ")"
