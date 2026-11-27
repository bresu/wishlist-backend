import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.database import connect
from app.main import app


class AdminAuthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = "a-long-passphrase-for-this-test"
        cls.password_hash = PasswordHasher().hash(cls.password)

    def test_login_csrf_logout_and_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("app.database.DATABASE_PATH", str(Path(directory) / "test.db")), patch.dict(os.environ, {"ADMIN_PASSWORD_HASH": self.password_hash}):
                with TestClient(app, base_url="https://testserver") as client:
                    assert client.get("/admin", follow_redirects=False).status_code == 303
                    assert client.post("/admin/login", data={"password": "wrong"}, follow_redirects=False).status_code == 401
                    res = client.post("/admin/login", data={"password": self.password}, follow_redirects=False)
                    assert res.status_code == 303, res.text
                    cookie = res.headers["set-cookie"]
                    for flag in ["Secure", "HttpOnly", "SameSite=strict", "Path=/"]:
                        assert flag.lower() in cookie.lower(), (flag,cookie)
                    assert "__Host-wishlist_session=" in cookie
                    raw_token = client.cookies.get("__Host-wishlist_session")
                    assert raw_token
                    db = connect()
                    row = db.execute("SELECT token_hash FROM admin_sessions").fetchone()
                    assert row["token_hash"] != raw_token
                    db.close()

                    page = client.get("/admin")
                    assert page.status_code == 200
                    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
                    assert client.post("/admin/logout", data={"csrf_token": "wrong"}, follow_redirects=False).status_code == 403
                    assert client.get("/admin").status_code == 200
                    assert client.post("/admin/logout", data={"csrf_token": csrf}, follow_redirects=False).status_code == 303
                    assert client.get("/admin", follow_redirects=False).status_code == 303
                    assert client.get("/health").status_code == 200

    def test_rate_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("app.database.DATABASE_PATH", str(Path(directory) / "test.db")), patch.dict(os.environ, {"ADMIN_PASSWORD_HASH": self.password_hash}):
                with TestClient(app, base_url="https://testserver") as client:
                    for i in range(5):
                        assert client.post("/admin/login", data={"password": "wrong"}).status_code == 401
                    assert client.post("/admin/login", data={"password": self.password}).status_code == 429
