"""Local, isolated demonstration using the application's original backends.

Python 3.12, Node.js 22 and PostgreSQL 17 are required. No OS services or
scheduled tasks are installed. Only the dedicated .demo cluster is managed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
STATE = ROOT / ".demo"
CLUSTER = STATE / "postgres"
CONFIG = STATE / "runtime.json"
PORTS = {"portal": 8890, "notas": 8891, "colaboradores": 8892, "analises": 8888, "balanca": 8833}
MODULES = {"portal": "launcher_web", "notas": "app_notas", "colaboradores": "app_colaboradores", "analises": "analises"}
DB_PORT = 55439
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def python_exe() -> Path:
    return STATE / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(args, *, cwd=ROOT, env=None, **kwargs):
    # Capture stderr so a hidden Windows child cannot silently lose diagnostics.
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=env, stderr=kwargs.pop("stderr", subprocess.PIPE),
                            stdout=kwargs.pop("stdout", sys.stdout), creationflags=HIDDEN, **kwargs)
    if result.returncode:
        raise RuntimeError((result.stderr or b"Comando falhou; consulte .demo/logs.").decode("utf-8", errors="replace"))
    return result


def available(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def config() -> dict:
    if not CONFIG.exists():
        raise RuntimeError("Execute primeiro: python demo.py setup")
    settings = json.loads(CONFIG.read_text(encoding="utf-8"))
    if "integration_password" not in settings:
        settings["integration_password"] = secrets.token_urlsafe(24)
        CONFIG.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return settings


def database_url(settings: dict, module: str) -> str:
    assert module in {*PORTS, "tests"}
    return f"postgresql://oa_demo:{quote(settings['database_password'], safe='')}@127.0.0.1:{DB_PORT}/oa_demo_{module}"


def environment(settings: dict, module="balanca") -> dict:
    # Never inherit application targets, tokens, remote storage, or integration settings.
    env = {k: v for k, v in os.environ.items() if not k.startswith((
        "APP_", "PORTAL_", "LAUNCHER_", "BALANCA_", "AGRICOLA_", "ANALISES_",
        "POSTGRES_", "POST_HARVEST_", "DATABASE_", "PG", "JWT_", "UPLOAD_",
        "BACKUP_", "FLEET_", "ANALYSIS_", "PYTHONPATH", "GOOGLE_", "GEMINI_", "CANE_",
    ))}
    env.update({
        "PYTHONPATH": str(ROOT), "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8", "QT_QPA_PLATFORM": "offscreen",
        "PATH": str(Path(settings["node"]).parent) + os.pathsep + env.get("PATH", ""),
        "TEMP": str(STATE / "temp"), "TMP": str(STATE / "temp"),
        "OA_DEMO_TEMP_DIR": str(STATE / "temp"), "APP_BIND_HOST": "127.0.0.1",
        "PORTAL_SKIP_LOCAL_ENV": "1", "PORTAL_DATABASE_URL": database_url(settings, "portal"),
        "PORTAL_LOG_DIR": str(STATE / "logs" / "portal"), "PORTAL_BACKUP_DIR": str(STATE / "backups" / "portal"),
        "PORTAL_BACKUP_RETENTION_APPLY": "0", "LAUNCHER_AUTOSTART_APPS": "0", "LAUNCHER_OPEN_BROWSER": "0",
        "LAUNCHER_ADMIN_USER": "gestor@example.invalid", "LAUNCHER_ADMIN_PASSWORD": settings["login_password"],
        "LAUNCHER_WEB_PORT": "8890", "LAUNCHER_FRIENDLY_HOST": "127.0.0.1",
        "LAUNCHER_APP_BIND_HOST": "127.0.0.1", "PYTHON_EXE": str(python_exe()),
        "AGRICOLA_AUDIT_URL": "http://127.0.0.1:8890/api/audit/event",
        "AGRICOLA_LOGIN_URL": "http://127.0.0.1:8890/login.html",
        "AGRICOLA_PORTAL_SESSION_URL": "http://127.0.0.1:8890",
        "AGRICOLA_SESSION_COOKIE": "oa_demo_session",
        "APP_NOTAS_DB_ENGINE": "postgresql", "APP_NOTAS_DATABASE_URL": database_url(settings, "notas"),
        "APP_NOTAS_BACKUP_PATH": str(STATE / "backups" / "notas"),
        "APP_NOTAS_COLABORADORES_CONFIG_PATH": str(STATE / "colaboradores-reference.json"),
        "APP_NOTAS_BALANCA_API_URL": "http://127.0.0.1:8833",
        "APP_NOTAS_BALANCA_API_EMAIL": "integracao@example.invalid",
        "APP_NOTAS_BALANCA_API_PASSWORD": settings["integration_password"],
        "APP_COLAB_DB_ENGINE": "postgresql", "APP_COLAB_DATABASE_URL": database_url(settings, "colaboradores"),
        "APP_COLAB_STORAGE_ROOT": str(STATE / "colaboradores"),
        "APP_COLAB_BACKUP_DIR": str(STATE / "backups" / "colaboradores"),
        "ANALISES_DB_ENGINE": "postgresql", "ANALISES_DATABASE_URL": database_url(settings, "analises"),
        "DATABASE_PROVIDER": "postgres", "DATABASE_URL": database_url(settings, module),
        "POSTGRES_MIGRATION_URL": database_url(settings, "balanca"),
        "BALANCA_TEST_DATABASE_URL": database_url(settings, "tests"),
        "POSTGRES_BIN": settings["postgres_bin"],
        "JWT_SECRET": settings["jwt_secret"], "API_HOST": "127.0.0.1", "PORT": "8833",
        "UPLOAD_DIR": str(STATE / "uploads"), "ANALYSIS_ARCHIVE_DIR": str(STATE / "analysis-files"),
        "BACKUP_DIR": str(STATE / "backups" / "balanca"), "BALANCA_LOG_DIR": str(STATE / "logs" / "balanca"),
        "FLEET_BASE_FILE": str(STATE / "frotas-ficticias.xlsx"),
        "POST_HARVEST_WEBHOOK_URL": "", "POST_HARVEST_WEBHOOK_TOKEN": "",
        "CANE_PDF_ASSIST_PROVIDER": "none", "NODE_ENV": "production", "BALANCA_ALLOW_LOCAL_ACCESS": "0",
        "BALANCA_ALLOWED_ORIGINS": "http://127.0.0.1:8890",
    })
    return env


def pg_tool(settings: dict, name: str) -> Path:
    return Path(settings["postgres_bin"]) / (name + (".exe" if os.name == "nt" else ""))


def ensure_cluster(settings: dict):
    assert CLUSTER.resolve().is_relative_to(STATE.resolve()) and CLUSTER.name == "postgres"
    marker = CLUSTER / "oa-demo-cluster"
    if CLUSTER.exists() and not marker.exists():
        raise RuntimeError("Diretorio PostgreSQL existente sem marcador da demonstracao; nenhuma alteracao executada.")
    if not CLUSTER.exists():
        if not available(DB_PORT):
            raise RuntimeError(f"Porta {DB_PORT} ocupada; nao vou reutilizar outro PostgreSQL.")
        pwfile = STATE / "init-password.txt"
        pwfile.write_text(settings["database_password"], encoding="utf-8")
        try:
            run([pg_tool(settings, "initdb"), "-D", CLUSTER, "-U", "oa_demo", "--pwfile", pwfile,
                 "--auth-host=scram-sha-256", "--auth-local=scram-sha-256", "--encoding=UTF8", "--locale=C"],
                stdout=subprocess.DEVNULL)
            marker.write_text("operacoes-agricolas-demo-v1\n", encoding="utf-8")
        finally:
            pwfile.unlink(missing_ok=True)
    status = subprocess.run([str(pg_tool(settings, "pg_ctl")), "-D", str(CLUSTER), "status"],
                            capture_output=True, creationflags=HIDDEN)
    if status.returncode != 0:
        if not available(DB_PORT):
            raise RuntimeError(f"Porta {DB_PORT} ocupada por outro processo; inicializacao cancelada.")
        run([pg_tool(settings, "pg_ctl"), "-D", CLUSTER, "-l", STATE / "logs" / "postgres.log",
             "-o", f"-h 127.0.0.1 -p {DB_PORT}", "-w", "start"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def setup(skip_install=False):
    STATE.mkdir(exist_ok=True)
    for folder in ["temp", "logs", "uploads", "analysis-files", "backups", "colaboradores"]:
        (STATE / folder).mkdir(exist_ok=True)
    if not CONFIG.exists():
        node = os.environ.get("OA_DEMO_NODE") or shutil.which("node")
        pg_bin = os.environ.get("OA_DEMO_POSTGRES_BIN") or (r"C:\Program Files\PostgreSQL\17\bin" if os.name == "nt" else "/usr/lib/postgresql/17/bin")
        if not node or not (Path(pg_bin) / ("initdb.exe" if os.name == "nt" else "initdb")).exists():
            raise RuntimeError("Instale Node.js 22 e PostgreSQL 17; caminhos opcionais OA_DEMO_NODE / OA_DEMO_POSTGRES_BIN.")
        version = subprocess.check_output([node, "--version"], text=True).strip()
        if not version.startswith("v22."):
            raise RuntimeError(f"Node.js 22 necessario; encontrado {version}.")
        settings = {"node": node, "postgres_bin": pg_bin, "database_password": secrets.token_urlsafe(32),
                    "login_password": secrets.token_urlsafe(12), "jwt_secret": secrets.token_urlsafe(48)}
        CONFIG.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        CONFIG.chmod(0o600)
    settings = config()
    (STATE / "colaboradores-reference.json").write_text(json.dumps({
        "db_engine": "postgresql", "database_url": database_url(settings, "colaboradores")
    }), encoding="utf-8")
    if not skip_install:
        if not python_exe().exists():
            run([sys.executable, "-m", "venv", STATE / "venv"])
        run([python_exe(), "-m", "pip", "install", "-r", "requirements-demo.txt"])
        npm = Path(shutil.which("npm.cmd" if os.name == "nt" else "npm") or "npm")
        npm_cli = npm.parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        run([settings["node"], npm_cli, "ci", "--ignore-scripts"], cwd=ROOT / "balanca-audit", env=environment(settings))
        run([settings["node"], npm_cli, "run", "build"], cwd=ROOT / "balanca-audit", env=environment(settings))
    ensure_cluster(settings)
    # Bootstrap is executed inside the isolated virtual environment, not a global Python.
    run([python_exe(), __file__, "_create_databases"], env=environment(settings))
    for module in MODULES:
        run([python_exe(), __file__, "_init_module", "--module", module], env=environment(settings, module))
    run([settings["node"], "dist/postgresMigrationApply.js"], cwd=ROOT / "balanca-audit/apps/api", env=environment(settings))
    run([python_exe(), ROOT / "scripts/seed_demo.py"], env=environment(settings))
    run([settings["node"], ROOT / "scripts/seed_integration.mjs"], cwd=ROOT / "balanca-audit/apps/api", env=environment(settings))
    print("Demonstracao preparada. Execute: python demo.py start", flush=True)


def create_databases():
    import psycopg
    from psycopg import sql
    settings = config()
    # This one bootstrap connection targets the built-in postgres DB in our marked cluster.
    assert (CLUSTER / "oa-demo-cluster").exists()
    with psycopg.connect(host="127.0.0.1", port=DB_PORT, user="oa_demo",
                        password=settings["database_password"], dbname="postgres", autocommit=True) as conn:
        data_dir = Path(conn.execute("SHOW data_directory").fetchone()[0]).resolve()
        if data_dir != CLUSTER.resolve():
            raise RuntimeError("O PostgreSQL respondeu com outro diretorio; operacao cancelada.")
        for module in [*PORTS, "tests"]:
            name = f"oa_demo_{module}"
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone():
                conn.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8'").format(sql.Identifier(name)))


def init_module(module):
    sys.path.insert(0, str(ROOT / MODULES[module]))
    if module == "portal":
        from server import setup_auth_db
        setup_auth_db()
    elif module == "notas":
        from database import DB
        database = DB(seed_from_excel=False)
        database.close()
    elif module == "colaboradores":
        from funcoes_colaboradores import garantir_schema_banco
        garantir_schema_banco()
    elif module == "analises":
        from core.database import setup_main_database
        setup_main_database()


def start(open_browser=False):
    settings = config()
    ensure_cluster(settings)
    occupied = [port for port in PORTS.values() if not available(port)]
    if occupied:
        raise RuntimeError(f"Portas ocupadas {occupied}; nenhum servidor da demonstracao sera iniciado.")
    processes = []
    handles = []
    try:
        for module, folder in MODULES.items():
            command = [str(python_exe()), str(ROOT / folder / ("server.py" if module == "portal" else "web_app/server.py"))]
            if module != "portal":
                command += ["--host", "127.0.0.1", "--port", str(PORTS[module])]
            if module == "colaboradores":
                command += ["--no-browser"]
            log = (STATE / "logs" / f"{module}.log").open("a", encoding="utf-8")
            handles.append(log)
            processes.append(subprocess.Popen(command, cwd=ROOT / folder, env=environment(settings, module),
                                              stdout=log, stderr=log, creationflags=HIDDEN))
        log = (STATE / "logs/balanca.log").open("a", encoding="utf-8")
        handles.append(log)
        processes.append(subprocess.Popen([settings["node"], "dist/server.js"], cwd=ROOT / "balanca-audit/apps/api",
                                          env=environment(settings), stdout=log, stderr=log, creationflags=HIDDEN))
        for _ in range(90):
            failed = [p.pid for p in processes if p.poll() is not None]
            if failed:
                raise RuntimeError("Um modulo encerrou durante a inicializacao. Consulte .demo/logs.")
            if all(not available(port) for port in PORTS.values()):
                break
            time.sleep(1)
        else:
            raise RuntimeError("Tempo limite ao iniciar a demonstracao; consulte .demo/logs.")
        # Exercise the original authenticated master-data integration on demo data.
        run([python_exe(), "sync_balanca_cadastros.py", "--source", "api", "--no-backup"],
            cwd=ROOT / "app_notas", env=environment(settings, "notas"), stdout=subprocess.DEVNULL)
        print("Operacoes Agricolas: http://127.0.0.1:8890", flush=True)
        print("Credenciais locais: python demo.py credentials. Ctrl+C encerra os cinco servidores.", flush=True)
        if open_browser:
            import webbrowser
            webbrowser.open("http://127.0.0.1:8890")
        while all(p.poll() is None for p in processes):
            time.sleep(1)
        raise RuntimeError("Um modulo encerrou; os demais serao encerrados pelo controlador.")
    except KeyboardInterrupt:
        pass
    finally:
        for p in reversed(processes):
            if p.poll() is None:
                p.terminate()
        for p in processes:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        for handle in handles:
            handle.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["setup", "start", "test", "credentials", "stop-db", "_create_databases", "_init_module"])
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--module", choices=list(MODULES))
    args = parser.parse_args()
    if args.action == "setup": setup(args.skip_install)
    elif args.action == "start": start(args.open)
    elif args.action == "test": run([python_exe(), ROOT / "scripts/test_demo.py"], env=environment(config()), stderr=sys.stderr)
    elif args.action == "credentials": print("Usuario: gestor@example.invalid\nSenha: " + config()["login_password"])
    elif args.action == "_create_databases": create_databases()
    elif args.action == "_init_module": init_module(args.module)
    elif args.action == "stop-db":
        if not (CLUSTER / "oa-demo-cluster").exists(): raise RuntimeError("Cluster demonstrativo nao identificado.")
        run([pg_tool(config(), "pg_ctl"), "-D", CLUSTER, "-m", "fast", "-w", "stop"])


if __name__ == "__main__":
    main()
