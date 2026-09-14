from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


LAUNCHER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAUNCHER))
os.environ.setdefault("PORTAL_SKIP_LOCAL_ENV", "1")

import server  # noqa: E402


class ProfileUpdateTest(unittest.TestCase):
    def setUp(self) -> None:
        with server.LOGIN_LOCK:
            server.LOGIN_ATTEMPTS.clear()
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT,
                provider TEXT NOT NULL DEFAULT 'local',
                role TEXT NOT NULL DEFAULT 'user',
                status TEXT NOT NULL DEFAULT 'approved',
                created_at INTEGER NOT NULL,
                approved_at INTEGER,
                approved_by INTEGER
            );
            CREATE TABLE sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );
            """
        )
        with patch.object(server, "PASSWORD_ITERATIONS", 1_000):
            password_hash = server.hash_password("senha-atual", salt="a" * 32, iterations=2_000)
        self.conn.execute(
            """
            INSERT INTO users (
                id, name, email, password_hash, provider, role, status,
                created_at, approved_at, approved_by
            ) VALUES (1, 'Maria Souza', 'maria@example.invalid', ?, 'local', 'user', 'approved', 1, 1, NULL)
            """,
            (password_hash,),
        )
        self.conn.executemany(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, 1, 1, 9999999999)",
            [("current-token",), ("other-token",)],
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        with server.LOGIN_LOCK:
            server.LOGIN_ATTEMPTS.clear()

    def user(self) -> dict:
        row = self.conn.execute("SELECT * FROM users WHERE id = 1").fetchone()
        return server.user_public(row)

    def handler(self, payload: dict) -> server.LauncherHandler:
        handler = object.__new__(server.LauncherHandler)
        handler.headers = {"Cookie": f"{server.SESSION_COOKIE}=current-token"}
        handler.client_address = ("127.0.0.1", 12345)
        handler.require_user = MagicMock(return_value=self.user())
        handler.read_json_body = MagicMock(return_value=payload)
        handler.audit = MagicMock()
        handler.send_json = MagicMock()
        return handler

    def update(self, payload: dict) -> server.LauncherHandler:
        handler = self.handler(payload)
        with (
            patch.object(server, "PASSWORD_ITERATIONS", 1_000),
            patch.object(server, "auth_conn", return_value=self.conn),
        ):
            handler.update_own_profile()
        return handler

    def test_updates_and_normalizes_display_name(self) -> None:
        handler = self.update({"name": "  Maria   da   Silva  "})

        row = self.conn.execute("SELECT name FROM users WHERE id = 1").fetchone()
        self.assertEqual("Maria da Silva", row["name"])
        response = handler.send_json.call_args.args[0]
        self.assertTrue(response["ok"])
        self.assertEqual("Maria da Silva", response["user"]["name"])
        self.assertEqual("PROFILE_UPDATED", handler.audit.call_args.args[1])
        self.assertEqual(
            {"nameChanged": True, "passwordChanged": False},
            handler.audit.call_args.kwargs["details"],
        )

    def test_changes_password_preserves_hash_cost_and_revokes_other_sessions(self) -> None:
        handler = self.update(
            {
                "name": "Maria Souza",
                "currentPassword": "senha-atual",
                "newPassword": "senha-nova",
            }
        )

        row = self.conn.execute("SELECT password_hash FROM users WHERE id = 1").fetchone()
        self.assertTrue(server.verify_password(row["password_hash"], "senha-nova"))
        self.assertFalse(server.verify_password(row["password_hash"], "senha-atual"))
        self.assertEqual(2_000, server.password_hash_iterations(row["password_hash"]))
        tokens = [item["token"] for item in self.conn.execute("SELECT token FROM sessions ORDER BY token")]
        self.assertEqual(["current-token"], tokens)
        details = handler.audit.call_args.kwargs["details"]
        self.assertEqual({"nameChanged": False, "passwordChanged": True}, details)
        self.assertNotIn("senha-atual", repr(handler.audit.call_args))
        self.assertNotIn("senha-nova", repr(handler.audit.call_args))

    def test_wrong_current_password_keeps_profile_unchanged(self) -> None:
        before = self.conn.execute("SELECT name, password_hash FROM users WHERE id = 1").fetchone()
        handler = self.update(
            {
                "name": "Nome que nao deve salvar",
                "currentPassword": "senha-incorreta",
                "newPassword": "senha-nova",
            }
        )

        after = self.conn.execute("SELECT name, password_hash FROM users WHERE id = 1").fetchone()
        self.assertEqual(dict(before), dict(after))
        self.assertEqual(2, self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
        response, status = handler.send_json.call_args.args
        self.assertFalse(response["ok"])
        self.assertEqual(400, status)
        self.assertEqual("PROFILE_UPDATE_DENIED", handler.audit.call_args.args[1])
        self.assertIs(self.conn, handler.audit.call_args.kwargs["connection"])

    def test_repeated_password_attempts_are_rate_limited_before_hash_check(self) -> None:
        handler = self.handler(
            {
                "name": "Maria Souza",
                "currentPassword": "tentativa",
                "newPassword": "senha-nova",
            }
        )
        with (
            patch.object(server, "auth_conn", return_value=self.conn),
            patch.object(server, "login_retry_after", return_value=45),
            patch.object(server, "verify_password") as verify,
        ):
            handler.update_own_profile()

        verify.assert_not_called()
        response, status = handler.send_json.call_args.args
        self.assertFalse(response["ok"])
        self.assertEqual(429, status)
        self.assertEqual(45, handler.audit.call_args.kwargs["details"]["retryAfterSeconds"])

    def test_profile_and_audit_are_atomic(self) -> None:
        before = self.conn.execute("SELECT name, password_hash FROM users WHERE id = 1").fetchone()
        handler = self.handler(
            {
                "name": "Nome transacional",
                "currentPassword": "senha-atual",
                "newPassword": "senha-nova",
            }
        )
        handler.audit.side_effect = RuntimeError("audit unavailable")

        with (
            patch.object(server, "PASSWORD_ITERATIONS", 1_000),
            patch.object(server, "auth_conn", return_value=self.conn),
            self.assertRaises(RuntimeError),
        ):
            handler.update_own_profile()

        after = self.conn.execute("SELECT name, password_hash FROM users WHERE id = 1").fetchone()
        self.assertEqual(dict(before), dict(after))
        self.assertEqual(2, self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
        handler.send_json.assert_not_called()

    def test_rejects_privileged_fields(self) -> None:
        handler = self.update({"name": "Maria Souza", "email": "outra@example.invalid", "role": "admin"})

        response, status = handler.send_json.call_args.args
        self.assertFalse(response["ok"])
        self.assertEqual(400, status)
        self.assertEqual("maria@example.invalid", self.conn.execute("SELECT email FROM users WHERE id = 1").fetchone()[0])
        handler.audit.assert_not_called()

    def test_integrated_account_cannot_create_local_password(self) -> None:
        self.conn.execute("UPDATE users SET provider = 'google', password_hash = NULL WHERE id = 1")
        self.conn.commit()
        handler = self.update(
            {
                "name": "Novo Nome",
                "currentPassword": "senha-atual",
                "newPassword": "senha-nova",
            }
        )

        response, status = handler.send_json.call_args.args
        self.assertFalse(response["ok"])
        self.assertEqual(400, status)
        self.assertEqual("Maria Souza", self.conn.execute("SELECT name FROM users WHERE id = 1").fetchone()[0])

    def test_invalid_name_is_rejected_without_database_write(self) -> None:
        handler = self.update({"name": "  x  "})

        response, status = handler.send_json.call_args.args
        self.assertFalse(response["ok"])
        self.assertEqual(400, status)
        self.assertEqual("Maria Souza", self.conn.execute("SELECT name FROM users WHERE id = 1").fetchone()[0])
        handler.audit.assert_not_called()

    def test_unauthenticated_request_stops_before_reading_payload(self) -> None:
        handler = object.__new__(server.LauncherHandler)
        handler.require_user = MagicMock(return_value=None)
        handler.read_json_body = MagicMock()

        handler.update_own_profile()

        handler.read_json_body.assert_not_called()

    def test_route_delegates_to_authenticated_profile_handler(self) -> None:
        handler = object.__new__(server.LauncherHandler)
        handler.path = "/api/profile"
        handler.reject_untrusted_api_origin = MagicMock(return_value=False)
        handler.update_own_profile = MagicMock()

        handler.handle_post()

        handler.update_own_profile.assert_called_once_with()


if __name__ == "__main__":
    unittest.main(verbosity=2)
