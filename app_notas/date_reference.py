"""Allowed date columns for transport queries; harvest remains the default."""
DATE_REFERENCES = {"data_colheita": "Data de colheita", "data_plantio": "Data de plantio"}

def date_column(value="data_colheita"):
    if value not in DATE_REFERENCES:
        raise ValueError("Data de referencia invalida.")
    return value

def date_label(value="data_colheita"):
    return DATE_REFERENCES[date_column(value)]
