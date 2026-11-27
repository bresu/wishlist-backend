import os
import re
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from PIL import Image

from app.database import connect
from app.main import app


class AdminGiftsTest(unittest.TestCase):
    def test_create_and_list_gifts_with_image(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "test.db")
            uploads = Path(directory) / "uploads"
            password = "my-test-password-long"
            with patch("app.database.DATABASE_PATH", db_path), patch.dict(
                os.environ,
                {"ADMIN_PASSWORD_HASH": PasswordHasher().hash(password), "UPLOAD_DIR": str(uploads)},
            ):
                with TestClient(app, base_url="https://testserver") as client:
                    assert client.get("/admin", follow_redirects=False).status_code == 303
                    assert client.post("/admin/gifts", data={"title": "Nope", "csrf_token": "wrong"}).status_code == 401
                    response = client.post("/admin/login", data={"password": password}, follow_redirects=False)
                    assert response.status_code == 303
                    page = client.get("/admin")
                    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
                    assert client.post("/admin/gifts", data={"title": "Nope", "csrf_token": "wrong"}).status_code == 403
                    assert client.post("/admin/gifts", data={"title": "   ", "csrf_token": csrf}).status_code == 422
                    assert client.post("/admin/gifts", data={"title": "Kaputt", "csrf_token": csrf}, files={"image": ("bad.jpg", b"not an image", "image/jpeg")}).status_code == 422
                    assert client.get("/gifts").json() == []

                    picture = BytesIO()
                    Image.new("RGB", (40, 20), (240, 40, 60)).save(picture, "PNG")
                    result = client.post("/admin/gifts", data={
                        "title": "  <script>alert(1)</script>  ",
                        "description": "**Fett** und [Link](https://example.com) <script>alert(1)</script>",
                        "csrf_token": csrf,
                    }, files={"image": ("buch.png", picture.getvalue(), "image/png")}, follow_redirects=False)
                    assert result.status_code == 303, result.text
                    gifts = client.get("/gifts").json()
                    assert "<strong>Fett</strong>" in gifts[0]["description_html"]
                    assert "<script>" not in gifts[0]["description_html"]
                    assert "&lt;script&gt;" in gifts[0]["description_html"]
                    assert "<strong>Fett</strong>" in client.get("/admin").text
                    assert "id=\"drop-overlay\"" in client.get("/admin").text
                    assert "id=\"photo-preview\"" in client.get("/admin").text
                    assert len(gifts) == 1
                    assert gifts[0]["title"] == "<script>alert(1)</script>"
                    assert not gifts[0]["reserved"]
                    filename = gifts[0]["image"]
                    assert filename.endswith(".webp")
                    assert (uploads / filename).exists()
                    with Image.open(uploads / filename) as stored:
                        assert stored.format == "WEBP"
                    assert client.get(f"/images/{filename}").status_code == 200
                    assert client.get("/images/../test.db").status_code != 200
                    assert "&lt;script&gt;" in client.get("/admin").text
                    assert "<script>alert(1)</script>" not in client.get("/admin").text
                    db = connect()
                    assert db.execute("SELECT count(*) FROM gifts").fetchone()[0] == 1
                    db.close()

                    assert client.post("/admin/gifts", data={
                        "title": "Ohne Foto", "csrf_token": csrf
                    }, follow_redirects=False).status_code == 303
                    assert len(client.get("/gifts").json()) == 2
