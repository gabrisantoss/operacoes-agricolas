"""Run the retained suites against isolated, disposable test databases."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import demo


def main():
    settings = demo.config()
    demo.ensure_cluster(settings)
    failures = []
    for module, folder in demo.MODULES.items():
        env = demo.environment(settings, module)
        env.update(QT_QPA_PLATFORM="offscreen", APP_NOTAS_DB_ENGINE="sqlite",
                   APP_COLAB_DB_ENGINE="sqlite", ANALISES_DB_ENGINE="sqlite",
                   APP_COLAB_SQLITE_PATH=str(demo.STATE / "temp/colab-unittest.db"))
        print(f"\n=== Python: {module} ===", flush=True)
        # Qt test modules own QApplication and native widgets. A process per file
        # prevents C++ wrapper lifetimes leaking between otherwise independent suites.
        patterns = [p.name for p in sorted((ROOT / folder / "tests").glob("test_*.py"))]
        if module == "portal":
            patterns.append("validate_portal_foundation.py")
        for pattern in patterns:
            result = subprocess.run([str(demo.python_exe()), "-m", "unittest", "discover", "-s", "tests", "-p", pattern, "-v"],
                                    cwd=ROOT / folder, env=env)
            if result.returncode:
                failures.append(f"{module}/{pattern}")
    api = ROOT / "balanca-audit/apps/api"
    env = demo.environment(settings)
    env["NODE_ENV"] = "test"
    tests = sorted(str(p.relative_to(api)) for p in (api / "src").rglob("*.test.ts"))
    print("\n=== TypeScript / PostgreSQL ===", flush=True)
    result = subprocess.run([settings["node"], str(ROOT / "balanca-audit/node_modules/tsx/dist/cli.mjs"),
                             "--test", *tests], cwd=api, env=env)
    if result.returncode:
        failures.append("api")
    if failures:
        raise SystemExit("Falhas: " + ", ".join(failures))
    print("Todas as suites passaram.")


if __name__ == "__main__":
    main()
