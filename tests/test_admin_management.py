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


def png(color):
    out = BytesIO()
    Image.new('RGB', (32, 24), color).save(out, 'PNG')
    return out.getvalue()


class AdminManagementTest(unittest.TestCase):
    def test_edit_release_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('app.database.DATABASE_PATH', str(Path(tmp) / 'wishlist.db')), patch.dict(
                os.environ, {'ADMIN_PASSWORD_HASH': PasswordHasher().hash('long-admin-test-password'),
                             'UPLOAD_DIR': str(Path(tmp) / 'uploads')},
            ):
                with TestClient(app, base_url='https://testserver') as client:
                    response = client.post('/admin/login', data={'password': 'long-admin-test-password'}, follow_redirects=False)
                    self.assertEqual(response.status_code, 303)
                    page = client.get('/admin')
                    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
                    self.assertIn('Wunsch hinzufügen', page.text)

                    resp = client.post('/admin/gifts', data={'csrf_token': csrf,
                        'title': 'Altes Buch', 'description': '**gut**'},
                        files={'image': ('first.png', png('red'), 'image/png')}, follow_redirects=False)
                    self.assertEqual(resp.status_code, 303)
                    gift = client.get('/gifts').json()[0]
                    gift_id = gift['id']
                    first_image = gift['image']
                    self.assertTrue((Path(tmp) / 'uploads' / first_image).exists())

                    claimed = client.post(f'/gifts/{gift_id}/claim', json={'name': 'Max Mustermann'})
                    self.assertEqual(claimed.status_code, 201)
                    self.assertIn('Max Mustermann', client.get('/admin').text)
                    self.assertNotIn('Max Mustermann', str(client.get('/gifts').json()))
                    self.assertIn('Reservierung freigeben', client.get('/admin').text)

                    bad = client.post(f'/admin/gifts/{gift_id}/release', data={'csrf_token': 'bad'})
                    self.assertEqual(bad.status_code, 403)
                    self.assertTrue(client.get('/gifts').json()[0]['reserved'])
                    released = client.post(f'/admin/gifts/{gift_id}/release', data={'csrf_token': csrf}, follow_redirects=False)
                    self.assertEqual(released.status_code, 303)
                    self.assertFalse(client.get('/gifts').json()[0]['reserved'])
                    self.assertEqual(client.post(f'/admin/gifts/{gift_id}/release', data={'csrf_token': csrf}).status_code, 404)

                    # Failed validation must not overwrite an existing image.
                    invalid = client.post(f'/admin/gifts/{gift_id}/edit', data={
                        'title': 'Kaputt', 'csrf_token': csrf,
                    }, files={'image': ('wrong.png', b'not-image', 'image/png')})
                    self.assertEqual(invalid.status_code, 422)
                    self.assertEqual(client.get('/gifts').json()[0]['title'], 'Altes Buch')
                    self.assertTrue((Path(tmp) / 'uploads' / first_image).exists())

                    # CSRF protects edit/delete, too.
                    self.assertEqual(client.post(f'/admin/gifts/{gift_id}/edit', data={
                        'title': 'Bad', 'csrf_token': 'wrong',
                    }).status_code, 403)
                    self.assertEqual(client.post(f'/admin/gifts/{gift_id}/delete', data={
                        'csrf_token': 'wrong',
                    }).status_code, 403)
                    self.assertEqual(client.get('/gifts').json()[0]['title'], 'Altes Buch')

                    changed = client.post(f'/admin/gifts/{gift_id}/edit', data={
                        'title': '  Neues Buch  ', 'description': '[Link](https://example.com)', 'csrf_token': csrf,
                    }, files={'image': ('second.png', png('blue'), 'image/png')}, follow_redirects=False)
                    self.assertEqual(changed.status_code, 303)
                    gift = client.get('/gifts').json()[0]
                    self.assertEqual(gift['title'], 'Neues Buch')
                    self.assertIn('<a href=', gift['description_html'])
                    self.assertNotEqual(gift['image'], first_image)
                    self.assertFalse((Path(tmp) / 'uploads' / first_image).exists())
                    self.assertTrue((Path(tmp) / 'uploads' / gift['image']).exists())
                    second_image = gift['image']

                    edit_text = client.post(f'/admin/gifts/{gift_id}/edit', data={
                        'title': 'Noch neuer', 'description': 'bleibt', 'csrf_token': csrf,
                    }, follow_redirects=False)
                    self.assertEqual(edit_text.status_code, 303)
                    self.assertEqual(client.get('/gifts').json()[0]['image'], second_image)

                    self.assertEqual(client.post(f'/gifts/{gift_id}/claim', json={'name': 'Lisa'}).status_code, 201)
                    deleted = client.post(f'/admin/gifts/{gift_id}/delete', data={'csrf_token': csrf}, follow_redirects=False)
                    self.assertEqual(deleted.status_code, 303)
                    self.assertEqual(client.get('/gifts').json(), [])
                    self.assertFalse((Path(tmp) / 'uploads' / second_image).exists())
                    self.assertEqual(client.get(f'/images/{second_image}').status_code, 404)
                    db = connect()
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0], 0)
                    db.close()

                    self.assertEqual(client.post('/admin/gifts/999/delete', data={'csrf_token': csrf}).status_code, 404)
                    self.assertEqual(client.post('/admin/gifts/999/edit', data={'title': 'missing', 'csrf_token': csrf}).status_code, 404)
                    self.assertEqual(client.post('/admin/gifts/999/release', data={'csrf_token': csrf}).status_code, 404)

                    # Logout revokes all management actions.
                    logout = client.post('/admin/logout', data={'csrf_token': csrf})
                    self.assertEqual(logout.status_code, 200)  # redirect followed
                    self.assertEqual(client.post('/admin/gifts/999/delete', data={'csrf_token': csrf}).status_code, 401)
