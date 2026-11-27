import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import connect
from app.main import app


class PublicWishlistTest(unittest.TestCase):
    def test_public_page_and_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('app.database.DATABASE_PATH', str(Path(directory) / 'test.db')):
                with TestClient(app) as client:
                    page = client.get('/wishlist')
                    assert page.status_code == 200
                    assert 'Dein Name' in page.text
                    assert "fetch('/gifts')" in page.text
                    assert 'Wunsch speichern' not in page.text
                    assert 'Wunsch löschen' not in page.text
                    assert 'Bearbeiten' not in page.text
                    assert 'Reservierung freigeben' not in page.text
                    db = connect()
                    db.execute('INSERT INTO gifts (title, description) VALUES (?, ?)', ('Buch', '**Cool**'))
                    db.commit()
                    db.close()
                    gifts = client.get('/gifts').json()
                    assert len(gifts) == 1
                    assert '<strong>Cool</strong>' in gifts[0]['description_html']
                    assert gifts[0]['reserved'] is False
                    assert client.post('/gifts/1/claim', json={'name':'Anna'}).status_code == 201
                    assert client.post('/gifts/1/claim', json={'name':'Max'}).status_code == 409
                    gifts = client.get('/gifts').json()
                    assert gifts[0]['reserved'] is True
                    assert 'Anna' not in str(gifts)
