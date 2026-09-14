import os
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle # Adicionado ParagraphStyle aqui
from reportlab.lib import colors
from reportlab.lib.units import cm
import matplotlib.pyplot as plt
import io
from datetime import datetime
from core.config import DatabaseConfig
from core.date_utils import sql_date_expr

DB_NAME = DatabaseConfig.DB_PATH

def create_connection():
    """Estabelece uma conexão com o banco de dados."""
    conn = None
    try:
        conn = DatabaseConfig.get_connection()
    except Exception as e:
        print(f"Erro ao conectar ao banco de dados: {e}")
    return conn

def build_filters(data_inicial=None, data_final=None, frente=None, turno=None, fazenda=None):
    """Constrói a cláusula WHERE da consulta e os parâmetros de forma segura."""
    where_clause = " WHERE 1=1"
    params = []

    if data_inicial:
        try:
            date_for_comparison = datetime.strptime(data_inicial, "%d/%m/%Y").strftime("%Y-%m-%d")
            where_clause += f" AND {sql_date_expr('Data')} >= ?"
            params.append(date_for_comparison)
        except (ValueError, TypeError):
            print(f"Aviso: Data inicial inválida '{data_inicial}' será ignorada na consulta.")

    if data_final:
        try:
            date_for_comparison = datetime.strptime(data_final, "%d/%m/%Y").strftime("%Y-%m-%d")
            where_clause += f" AND {sql_date_expr('Data')} <= ?"
            params.append(date_for_comparison)
        except (ValueError, TypeError):
            print(f"Aviso: Data final inválida '{data_final}' será ignorada na consulta.")

    if frente:
        where_clause += " AND Frente LIKE ?"
        params.append(f"%{frente}%")
    if turno:
        where_clause += " AND Turno = ?"
        params.append(turno)
    if fazenda:
        where_clause += " AND Fazenda LIKE ?"
        params.append(f"%{fazenda}%")

    return where_clause, params

def _build_unique_pdf_path(output_path, base_name):
    """Evita sobrescrever relatórios existentes."""
    counter = 1
    file_path = os.path.join(output_path, f"{base_name}.pdf")
    while os.path.exists(file_path):
        file_path = os.path.join(output_path, f"{base_name}_{counter}.pdf")
        counter += 1
    return file_path


def _format_period_label(data_inicial=None, data_final=None):
    """Monta um rótulo amigável do período filtrado."""
    if data_inicial and data_final:
        return f"{data_inicial} a {data_final}"
    if data_inicial:
        return f"a partir de {data_inicial}"
    if data_final:
        return f"até {data_final}"
    return "todo o período disponível"


def get_colheita_data(data_inicial=None, data_final=None, frente=None, turno=None, fazenda=None):
    """Busca dados de detalhamento da colheita com filtros."""
    conn = create_connection()
    if conn is None: return []
    cursor = conn.cursor()

    where_clause, params = build_filters(data_inicial, data_final, frente, turno, fazenda)

    query = """
        SELECT Data, Frente, Turno, Fazenda, Area_Colhida, Produtividade, Viagens
        FROM COLHEITA_MECANIZADA
    """ + where_clause + """
        ORDER BY
            {date_expr} DESC,
            Frente,
            Turno
    """.format(date_expr=sql_date_expr("Data"))

    try:
        cursor.execute(query, params)
        registros = cursor.fetchall()
    except Exception as e:
        print(f"Erro na consulta get_colheita_data: {e}")
        registros = []
    finally:
        conn.close()
    return registros

def get_productivity_by_frente_for_date(data_inicial=None, data_final=None, frente=None, turno=None, fazenda=None):
    """Agrega a produção estimada por frente para um período e filtros."""
    conn = create_connection()
    if conn is None: return {}
    cursor = conn.cursor()

    where_clause, params = build_filters(data_inicial, data_final, frente, turno, fazenda)

    query = """
        SELECT Frente, SUM(COALESCE(Area_Colhida, 0) * COALESCE(Produtividade, 0))
        FROM COLHEITA_MECANIZADA
    """ + where_clause + """
        GROUP BY Frente
        ORDER BY SUM(COALESCE(Area_Colhida, 0) * COALESCE(Produtividade, 0)) DESC
    """

    try:
        cursor.execute(query, params)
        results = cursor.fetchall()
    except Exception as e:
        print(f"Erro na consulta get_productivity: {e}")
        results = []
    finally:
        conn.close()
    return {row[0]: row[1] for row in results}


def generate_bar_chart(data, title, ylabel):
    """Gera um gráfico de barras simples, como no modelo."""
    if not data: return None

    frentes = list(data.keys())
    values = list(data.values())

    plt.style.use('default')
    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(frentes, values, color='green')

    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_xlabel("Frente", fontsize=12)
    ax.set_title(title, fontsize=14, weight='bold')
    ax.grid(axis='y', linestyle='--', alpha=0.7)

    for bar in bars:
        height = bar.get_height()
        ax.annotate(f'{height:.2f}',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3), textcoords="offset points",
                    ha='center', va='bottom', fontsize=9)

    plt.tight_layout()
    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', dpi=200)
    plt.close(fig)
    img_buffer.seek(0)
    return Image(img_buffer, width=18*cm, height=9*cm)


def _build_harvest_detail_table(registros, styles):
    if "TableParagraph" not in styles.byName:
        styles.add(ParagraphStyle(
            name="TableParagraph",
            parent=styles["Normal"],
            fontSize=8.5,
            leading=10,
            alignment=1,
        ))
    if "TableHeader" not in styles.byName:
        styles.add(ParagraphStyle(
            name="TableHeader",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=8,
            alignment=1,
        ))

    header = [
        "Data",
        "Frente",
        "Turno",
        "Fazenda",
        "Area<br/>colhida (ha)",
        "Produtividade<br/>(ton/ha)",
        "Viagens",
    ]
    dados_tabela = [[Paragraph(titulo, styles["TableHeader"]) for titulo in header]]
    for row in registros:
        data_db, frente_val, turno_val, fazenda_val, area, prod, viagens = row
        try:
            data_display = datetime.strptime(data_db, "%d-%m-%Y").strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            data_display = data_db
        area_str = f"{area:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if area else "0,00"
        prod_str = f"{prod:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if prod else "0,00"
        viagens_str = str(viagens) if viagens is not None else "0"
        dados_tabela.append([
            data_display,
            frente_val,
            turno_val,
            Paragraph(str(fazenda_val or "-"), styles["TableParagraph"]),
            area_str,
            prod_str,
            viagens_str,
        ])

    # A largura total permanece em 17 cm, dentro da area util do A4.
    tabela = Table(
        dados_tabela,
        colWidths=[2.0*cm, 1.3*cm, 1.3*cm, 5.7*cm, 2.5*cm, 3.0*cm, 1.2*cm],
        repeatRows=1,
    )
    tabela.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, 0), 4),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
        ('FONTSIZE', (0, 1), (-1, -1), 8.5),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    return tabela

def gerar_relatorio_colheita(data_inicial=None, data_final=None, frente=None, turno=None, fazenda=None, output_path='.'):
    """Gera um relatório PDF da colheita mecanizada, replicando o modelo fornecido."""
    try:
        os.makedirs(output_path, exist_ok=True)

        period_label = _format_period_label(data_inicial, data_final)
        base_period = "periodo_completo"
        if data_inicial and data_final:
            base_period = f"{data_inicial.replace('/', '-')}_a_{data_final.replace('/', '-')}"
        elif data_inicial:
            base_period = f"a_partir_de_{data_inicial.replace('/', '-')}"
        elif data_final:
            base_period = f"ate_{data_final.replace('/', '-')}"

        nome_pdf_base = f"Relatorio_Colheita_{base_period}"
        if frente: nome_pdf_base += f"_Frente_{''.join(filter(str.isalnum, frente))}"
        if turno: nome_pdf_base += f"_Turno_{''.join(filter(str.isalnum, turno))}"
        if fazenda: nome_pdf_base += f"_Fazenda_{''.join(filter(str.isalnum, fazenda))}"

        nome_arquivo_final = _build_unique_pdf_path(output_path, nome_pdf_base)

        doc = SimpleDocTemplate(nome_arquivo_final, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm, leftMargin=2*cm, rightMargin=2*cm)
        elementos = []
        styles = getSampleStyleSheet()
        styles['Title'].alignment = 1

        elementos.append(Paragraph("RELATÓRIO DE COLHEITA MECANIZADA", styles['Title']))
        elementos.append(Spacer(1, 0.4*cm))

        filtros = [f"Período: {period_label}"]
        if frente: filtros.append(f"Frente: {frente}")
        if turno: filtros.append(f"Turno: {turno}")
        if fazenda: filtros.append(f"Fazenda: {fazenda}")
        elementos.append(Paragraph(f"Filtros Aplicados: {', '.join(filtros)}", styles['Normal']))
        elementos.append(Spacer(1, 1*cm))

        elementos.append(Paragraph(f"Resumo do período: {period_label}", styles['h2']))
        elementos.append(Spacer(1, 0.5*cm))

        productivity_data = get_productivity_by_frente_for_date(data_inicial, data_final, frente, turno, fazenda)

        if productivity_data:
            chart_title = f"Produção Estimada por Frente ({period_label})"
            graph = generate_bar_chart(productivity_data, chart_title, "Produção Estimada (ton)")
            if graph:
                elementos.append(graph)
        else:
            elementos.append(Paragraph("Nenhum dado de produtividade para gerar gráfico.", styles['Normal']))
        elementos.append(Spacer(1, 1*cm))

        elementos.append(Paragraph(f"Detalhamento dos registros de {period_label}:", styles['h2']))
        elementos.append(Spacer(1, 0.5*cm))

        registros = get_colheita_data(data_inicial, data_final, frente, turno, fazenda)
        if registros:
            elementos.append(_build_harvest_detail_table(registros, styles))
        else:
            elementos.append(Paragraph("Nenhum registro encontrado para os filtros aplicados.", styles['Normal']))

        doc.build(elementos)
        print(f"Relatorio de Colheita gerado com sucesso: {nome_arquivo_final}")
        return nome_arquivo_final

    except Exception as e:
        # O console Windows pode usar cp1252. Evite simbolos fora dessa pagina
        # para que o log nao mascare a excecao original com UnicodeEncodeError.
        print(f"Falha ao gerar PDF de Colheita: {e}")
        raise e
