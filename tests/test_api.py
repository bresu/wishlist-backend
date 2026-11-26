
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import connect
from app.main import app


class WishlistAPITest(unittest.TestCase):
    def test_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "app.database.DATABASE_PATH",
                str(Path(directory) / "test.db"),
            ):
                with TestClient(app) as client:
                    assert client.get("/gifts").json() == []

                    db = connect()
                    db.execute(
                        "INSERT INTO gifts (title) VALUES (?)",
                        ("Testbuch",),
                    )
                    db.commit()
                    db.close()

                    assert client.get("/gifts").json()[0]["reserved"] is False

                    response = client.post(
                        "/gifts/1/claim",
                        json={"name": "Max"},
                    )
                    assert response.status_code == 201

                    assert client.get("/gifts").json()[0]["reserved"] is True

                    assert client.post(
                        "/gifts/1/claim",
                        json={"name": "Lisa"},
                    ).status_code == 409

                    assert client.post(
                        "/gifts/999/claim",
                        json={"name": "Lisa"},
                    ).status_code == 404

                    assert client.post(
                        "/gifts/1/claim",
                        json={"name": "   "},
                    ).status_code == 422

                    assert "Max" not in str(client.get("/gifts").json())
