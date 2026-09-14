"""Small tracked-file gate; human privacy review remains necessary."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
blocked = re.compile(r"(?:^|/)(?:\.demo|\.env|node_modules|uploads|backups|logs)(?:/|$)|\.(?:db|sqlite\d?|dump|backup|zip|exe|dll|pem|key|pdf|xlsx?|kml|kmz|shp|geojson)$", re.I)
token = re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY")
failures = []
for name in filter(None, files):
    path = ROOT / name
    if blocked.search(name):
        failures.append(f"Artefato de execucao ou privado: {name}")
    if path.is_file() and token.search(path.read_bytes()):
        failures.append(f"Possivel segredo: {name}")
if failures:
    raise SystemExit("\n".join(failures))
print("Arquivos versionados: nenhuma ocorrencia nas regras basicas de publicacao.")
