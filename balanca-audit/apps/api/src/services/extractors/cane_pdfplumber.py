import sys
import json
import re
import pdfplumber

def parse_decimal(s):
    try:
        s = s.replace(".", "").replace(",", ".")
        return float(s)
    except:
        return None

def extract_pdf(file_path):
    result = {
        "reportDate": None,
        "periodStart": None,
        "periodEnd": None,
        "totalNetWeight": None,
        "totalTrips": None,
        "rows": []
    }

    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text(layout=True)
                if not text:
                    text = page.extract_text()
                if not text:
                    continue

                # Try to parse Report Date
                if not result["reportDate"]:
                    m = re.search(r'Data\s*:\s*(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{2,4})', text, re.IGNORECASE)
                    if m:
                        result["reportDate"] = f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"

                # Try to parse Period
                if not result["periodStart"]:
                    m = re.search(r'PER[IÍ]ODO\s+(\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4})\s+A\s+(\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4})', text, re.IGNORECASE)
                    if m:
                        def to_iso(ds):
                            parts = ds.replace(" ", "").split("/")
                            return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                        result["periodStart"] = to_iso(m.group(1))
                        result["periodEnd"] = to_iso(m.group(2))

                # Try to parse Total Geral
                if not result["totalNetWeight"]:
                    m = re.search(r'TOTAL\s+GERAL\s+(?P<weight>\d{1,3}(?:\.\d{3})*,\d{3}|\d+,\d{3})\s*(?P<trips>\d+)(?:\s|$)', text, re.IGNORECASE)
                    if m:
                        result["totalNetWeight"] = parse_decimal(m.group("weight"))
                        result["totalTrips"] = int(m.group("trips"))

                lines = text.split('\n')
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    # Row regex:
                    # Left part: (Origem)\s+(Fornecedor)\s+(Nome Fornecedor e Fazenda)
                    # Right part: (Talhao)\s+(Distancia opcional)\s+(Area opcional)\s+(Peso Líquido)\s+(Viagens)

                    # Pattern for right part: Talhao (numbers + optional letter), Weight (xxx.xxx,xxx), Trips (integer)
                    right_match = re.search(r'(?P<field>\d+[A-Za-z0-9./-]*)\s+(?:(?P<km>\d+(?:[,.]\d+)?)\s+)?(?:(?P<area>\d+(?:[,.]\d+)?)\s+)?(?P<cane>\d{1,3}(?:\.\d{3})*,\d{3}|\d+,\d{3})\s*(?P<trips>\d+)\s*$', line)

                    if right_match:
                        left_part = line[:right_match.start()].strip()

                        # Match Origin and Supplier
                        left_match = re.match(r'^(\d+)\s+(\d+)\s+(.+)$', left_part)
                        if not left_match:
                            left_match = re.match(r'^(\d{3})(\d{2,4})\s+(.+)$', left_part)

                        if left_match:
                            origin_code = left_match.group(1)
                            supplier_code = left_match.group(2)
                            description = left_match.group(3).strip()

                            parts = [p.strip() for p in re.split(r'\s{2,}', description) if p.strip()]
                            farm = parts[-1] if len(parts) > 1 else description

                            net_weight = parse_decimal(right_match.group("cane"))
                            trip_count = int(right_match.group("trips"))
                            field = right_match.group("field")

                            if net_weight is not None:
                                result["rows"].append({
                                    "originCode": origin_code,
                                    "supplierCode": supplier_code,
                                    "farm": farm,
                                    "field": field,
                                    "netWeight": net_weight,
                                    "tripCount": trip_count
                                })

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(result))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No file path provided"}))
        sys.exit(1)

    extract_pdf(sys.argv[1])
