from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import demo  # noqa: E402


def find_npm_cli() -> Path | None:
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        return None
    cli = Path(npm).resolve().parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    return cli if cli.exists() else None


class NpmInstallArgsTest(unittest.TestCase):
    def test_setup_install_keeps_build_dependencies(self) -> None:
        args = demo.npm_install_args("npm-cli.js")

        self.assertEqual(args[:2], ["npm-cli.js", "ci"])
        self.assertIn("--include=dev", args)
        self.assertIn("--ignore-scripts", args)

    def test_npm_ci_installs_dev_dependencies_under_runtime_environment(self) -> None:
        node = os.environ.get("OA_DEMO_NODE") or shutil.which("node")
        npm_cli = find_npm_cli()
        if not node or not npm_cli:
            self.skipTest("Node.js/npm indisponiveis")

        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            tool = project / "build-tool"
            tool.mkdir()
            (tool / "package.json").write_text(json.dumps({"name": "build-tool", "version": "1.0.0"}), encoding="utf-8")
            (project / "package.json").write_text(json.dumps({
                "name": "setup-fixture", "version": "1.0.0", "private": True,
                "devDependencies": {"build-tool": "file:./build-tool"},
            }), encoding="utf-8")
            env = {**os.environ, "npm_config_cache": str(project / ".npm-cache"),
                   "npm_config_audit": "false", "npm_config_fund": "false"}
            subprocess.run([node, str(npm_cli), "install", "--package-lock-only", "--offline"],
                           cwd=project, env=env, check=True, capture_output=True)

            # Same NODE_ENV that demo.environment() hands to the setup install.
            env["NODE_ENV"] = "production"
            subprocess.run([node, *demo.npm_install_args(str(npm_cli)), "--offline"],
                           cwd=project, env=env, check=True, capture_output=True)

            self.assertTrue((project / "node_modules" / "build-tool" / "package.json").exists())


if __name__ == "__main__":
    unittest.main()
