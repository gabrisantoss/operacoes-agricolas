import math
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from core.config import DatabaseConfig


MAX_EXCEL_ROWS = 1_048_576
DATA_ROWS_PER_SHEET = MAX_EXCEL_ROWS - 1
INVALID_SHEET_CHARS = re.compile(r"[\[\]\:\*\?\/\\]")


def _quote_sqlite_identifier(value):
    return '"' + str(value).replace('"', '""') + '"'


def _escape_xml_attribute(value):
    return escape(str(value), {'"': '&quot;'})


def export_database_to_excel(output_path=None):
    """
    Exporta todas as tabelas de usuario do SQLite para um arquivo .xlsx.
    Usa apenas a biblioteca padrao para nao exigir dependencias extras.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(output_path or f"backup_banco_operacional_{timestamp}.xlsx")
    if output_path.suffix.lower() != ".xlsx":
        output_path = output_path.with_suffix(".xlsx")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    db_path = Path(DatabaseConfig.DB_PATH)
    conn = DatabaseConfig.get_connection()
    try:
        tables = _list_user_tables(conn)
        table_infos = [_table_info(conn, table) for table in tables]
        sheets = _build_sheet_plan(table_infos)

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            _write_static_parts(archive, sheets)
            _write_summary_sheet(archive, db_path, table_infos)

            for sheet in sheets[1:]:
                _write_table_sheet(
                    archive=archive,
                    conn=conn,
                    sheet_path=sheet["path"],
                    table=sheet["table"],
                    columns=sheet["columns"],
                    order_columns=sheet["order_columns"],
                    offset=sheet["offset"],
                    limit=sheet["limit"],
                )

        return str(output_path.resolve())
    finally:
        conn.close()


def _list_user_tables(conn):
    cursor = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    )
    return [row[0] for row in cursor.fetchall()]


def _table_info(conn, table):
    quoted_table = _quote_sqlite_identifier(table)
    column_rows = conn.execute(f"PRAGMA table_info({quoted_table})").fetchall()
    columns = [row[1] for row in column_rows]
    primary_key = [
        row[1]
        for row in sorted(column_rows, key=lambda item: int(item[5] or 0))
        if int(row[5] or 0) > 0
    ]
    row_count = conn.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()[0]
    return {
        "table": table,
        "columns": columns,
        "order_columns": primary_key or columns,
        "row_count": row_count,
    }


def _build_sheet_plan(table_infos):
    sheets = [
        {
            "name": "Resumo",
            "path": "xl/worksheets/sheet1.xml",
        }
    ]
    used_names = {"Resumo"}
    sheet_index = 2

    for info in table_infos:
        parts = max(1, (info["row_count"] + DATA_ROWS_PER_SHEET - 1) // DATA_ROWS_PER_SHEET)
        for part in range(parts):
            suffix = f"_{part + 1}" if parts > 1 else ""
            name = _unique_sheet_name(f"{info['table']}{suffix}", used_names)
            used_names.add(name)
            sheets.append(
                {
                    "name": name,
                    "path": f"xl/worksheets/sheet{sheet_index}.xml",
                    "table": info["table"],
                    "columns": info["columns"],
                    "order_columns": info["order_columns"],
                    "offset": part * DATA_ROWS_PER_SHEET,
                    "limit": DATA_ROWS_PER_SHEET,
                }
            )
            sheet_index += 1

    return sheets


def _unique_sheet_name(name, used_names):
    cleaned = INVALID_SHEET_CHARS.sub("_", name).strip("'") or "Tabela"
    cleaned = cleaned[:31]
    normalized_used_names = {str(used_name).casefold() for used_name in used_names}
    if cleaned.casefold() not in normalized_used_names:
        return cleaned

    counter = 2
    while True:
        suffix = f"_{counter}"
        candidate = f"{cleaned[:31 - len(suffix)]}{suffix}"
        if candidate.casefold() not in normalized_used_names:
            return candidate
        counter += 1


def _write_static_parts(archive, sheets):
    archive.writestr("[Content_Types].xml", _content_types_xml(sheets))
    archive.writestr("_rels/.rels", _root_rels_xml())
    archive.writestr("docProps/core.xml", _core_props_xml())
    archive.writestr("docProps/app.xml", _app_props_xml(len(sheets)))
    archive.writestr("xl/workbook.xml", _workbook_xml(sheets))
    archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml(sheets))
    archive.writestr("xl/styles.xml", _styles_xml())


def _write_summary_sheet(archive, db_path, table_infos):
    rows = [
        ["Arquivo gerado em", datetime.now().strftime("%d/%m/%Y %H:%M:%S")],
        ["Banco de dados", str(db_path.resolve())],
        [],
        ["Tabela", "Registros", "Colunas"],
    ]
    for info in table_infos:
        rows.append([info["table"], info["row_count"], ", ".join(info["columns"])])

    with archive.open("xl/worksheets/sheet1.xml", "w") as sheet:
        _write_sheet_start(sheet, freeze_header=False)
        for row_index, row in enumerate(rows, start=1):
            _write_row(sheet, row_index, row, header=(row_index == 4))
        _write_sheet_end(sheet)


def _write_table_sheet(archive, conn, sheet_path, table, columns, order_columns, offset, limit):
    with archive.open(sheet_path, "w") as sheet:
        _write_sheet_start(sheet, freeze_header=True)
        _write_row(sheet, 1, columns, header=True)

        order_sql = ", ".join(_quote_sqlite_identifier(column) for column in order_columns)
        order_clause = f" ORDER BY {order_sql}" if order_sql else ""
        query = f"SELECT * FROM {_quote_sqlite_identifier(table)}{order_clause} LIMIT ? OFFSET ?"
        cursor = conn.execute(query, (limit, offset))
        row_index = 2
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            for row in rows:
                _write_row(sheet, row_index, row)
                row_index += 1

        if columns and row_index > 2:
            last_col = _column_name(len(columns))
            sheet.write(f'<autoFilter ref="A1:{last_col}{row_index - 1}"/>'.encode("utf-8"))
        _write_sheet_end(sheet)


def _write_sheet_start(sheet, freeze_header):
    sheet.write(
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        b'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        b'<sheetViews><sheetView workbookViewId="0">'
    )
    if freeze_header:
        sheet.write(b'<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>')
    sheet.write(b'</sheetView></sheetViews><sheetFormatPr defaultRowHeight="15"/><sheetData>')


def _write_sheet_end(sheet):
    sheet.write(b'</sheetData><pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/></worksheet>')


def _write_row(sheet, row_index, values, header=False):
    sheet.write(f'<row r="{row_index}">'.encode("utf-8"))
    for col_index, value in enumerate(values, start=1):
        if value is None:
            continue
        ref = f"{_column_name(col_index)}{row_index}"
        style = ' s="1"' if header else ""
        sheet.write(_cell_xml(ref, value, style).encode("utf-8"))
    sheet.write(b"</row>")


def _cell_xml(ref, value, style):
    if isinstance(value, bool):
        return f'<c r="{ref}"{style} t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, float) and not math.isfinite(value):
        text = _clean_excel_text(str(value))
        return f'<c r="{ref}"{style} t="inlineStr"><is><t>{escape(text)}</t></is></c>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"{style}><v>{value}</v></c>'

    text = _clean_excel_text(str(value))
    return f'<c r="{ref}"{style} t="inlineStr"><is><t>{escape(text)}</t></is></c>'


def _clean_excel_text(value):
    return "".join(ch for ch in value if ch in "\t\n\r" or ord(ch) >= 32)


def _column_name(index):
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _content_types_xml(sheets):
    sheet_overrides = "".join(
        f'<Override PartName="/{sheet["path"]}" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for sheet in sheets
    )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  {sheet_overrides}
</Types>'''


def _root_rels_xml():
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''


def _workbook_xml(sheets):
    sheet_xml = "".join(
        f'<sheet name="{_escape_xml_attribute(sheet["name"])}" sheetId="{index}" r:id="rId{index}"/>'
        for index, sheet in enumerate(sheets, start=1)
    )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>{sheet_xml}</sheets>
</workbook>'''


def _workbook_rels_xml(sheets):
    sheet_rels = "".join(
        f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
        for index, _ in enumerate(sheets, start=1)
    )
    styles_id = len(sheets) + 1
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {sheet_rels}
  <Relationship Id="rId{styles_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''


def _styles_xml():
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><name val="Calibri"/></font>
  </fonts>
  <fills count="2">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
  </fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="2">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''


def _core_props_xml():
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Backup Banco Operacional</dc:title>
  <dc:creator>Operacoes Agricolas</dc:creator>
  <dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{created}</dcterms:modified>
</cp:coreProperties>'''


def _app_props_xml(sheet_count):
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Operacoes Agricolas Analises</Application>
  <DocSecurity>0</DocSecurity>
  <ScaleCrop>false</ScaleCrop>
  <HeadingPairs>
    <vt:vector size="2" baseType="variant">
      <vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant>
      <vt:variant><vt:i4>{sheet_count}</vt:i4></vt:variant>
    </vt:vector>
  </HeadingPairs>
</Properties>'''
