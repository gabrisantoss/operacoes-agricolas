from datetime import datetime


class ValidationError(ValueError):
    """Erro de validação exibível para o usuário."""


def normalize_whitespace(value):
    return " ".join((value or "").split())


def normalize_optional_time(value):
    cleaned_value = (value or "").strip().replace("_", "")
    if cleaned_value in {"", ":"}:
        return ""

    try:
        datetime.strptime(cleaned_value, "%H:%M")
    except ValueError as exc:
        raise ValidationError("As horas devem estar no formato HH:MM.") from exc

    return cleaned_value


def normalize_occurrence_payload(raw_data):
    data_display = normalize_whitespace(raw_data.get("data"))
    if not data_display:
        raise ValidationError("O campo 'Data' é obrigatório.")

    data_obj = None
    for date_format in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            data_obj = datetime.strptime(data_display, date_format)
            break
        except ValueError:
            continue
    if data_obj is None:
        raise ValidationError("A data deve estar no formato DD/MM/AAAA.")

    turno = normalize_whitespace(raw_data.get("turno"))
    if turno not in {"1", "2"}:
        raise ValidationError("Selecione um turno válido.")

    frente = normalize_whitespace(raw_data.get("frente"))
    if not frente:
        raise ValidationError("O campo 'Frente' é obrigatório.")
    if not frente.isdigit():
        raise ValidationError("A frente deve conter apenas números inteiros.")

    frente = str(int(frente))
    if frente == "0":
        raise ValidationError("A frente deve ser maior que zero.")

    frota = normalize_whitespace(raw_data.get("frota")).upper()
    if not frota:
        raise ValidationError("O campo 'Frota' é obrigatório.")

    motivo = normalize_whitespace(raw_data.get("motivo"))
    if not motivo:
        raise ValidationError("O campo 'Motivo da Ocorrência' é obrigatório.")

    parou_hora = normalize_optional_time(raw_data.get("parou_hora"))
    voltou_hora = normalize_optional_time(raw_data.get("voltou_hora"))
    em_andamento = bool(raw_data.get("em_andamento"))

    if em_andamento and not parou_hora:
        raise ValidationError("A 'Hora que Parou' é obrigatória para parada em andamento.")

    if em_andamento and voltou_hora:
        raise ValidationError("Limpe a 'Hora que Voltou' antes de marcar a parada como em andamento.")

    if voltou_hora and not parou_hora:
        raise ValidationError("Informe a 'Hora que Parou' antes da 'Hora que Voltou'.")

    if parou_hora and not voltou_hora and not em_andamento:
        raise ValidationError("A 'Hora que Voltou' é obrigatória para parada finalizada.")

    return {
        "data_display": data_display,
        "data_db": data_obj.strftime("%d-%m-%Y"),
        "turno": turno,
        "frente": frente,
        "fundo": normalize_whitespace(raw_data.get("fundo")),
        "chove": normalize_whitespace(raw_data.get("chove")) or "NÃO",
        "incendio": normalize_whitespace(raw_data.get("incendio")) or "NÃO",
        "frota": frota,
        "motivo": motivo,
        "parou_hora": parou_hora,
        "voltou_hora": voltou_hora,
        "em_andamento": em_andamento,
    }


def normalize_web_occurrence_payload(raw_data):
    """Map the web API contract onto the same validator used by the desktop UI."""
    status = normalize_whitespace(raw_data.get("status")) or "Finalizada"
    if status not in {"Finalizada", "Em Andamento"}:
        raise ValidationError("Selecione um status válido.")

    normalized = normalize_occurrence_payload(
        {
            "data": raw_data.get("data"),
            "turno": raw_data.get("turno"),
            "frente": raw_data.get("frente"),
            "fundo": raw_data.get("fundo_agricola", raw_data.get("fundo")),
            "chove": raw_data.get("chuva", raw_data.get("chove")),
            "incendio": raw_data.get("incendio"),
            "frota": raw_data.get("frota"),
            "motivo": raw_data.get("motivo"),
            "parou_hora": raw_data.get("parou_hora"),
            "voltou_hora": raw_data.get("voltou_hora"),
            "em_andamento": status == "Em Andamento",
        }
    )
    normalized["status"] = status
    return normalized


def build_finalized_occurrence_metrics(data_display, parou_hora, voltou_hora, calculator):
    if not parou_hora:
        return None, None

    total_parado, eficiencia = calculator(
        data_display, parou_hora, data_display, voltou_hora
    )
    return total_parado, round(float(eficiencia), 2)
