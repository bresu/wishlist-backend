import os
import re
from html import escape
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from app.auth import get_session, require_admin, require_csrf
from app.database import connect
from app.markdown import render_description

router = APIRouter(include_in_schema=False)
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def upload_dir():
    return Path(os.getenv("UPLOAD_DIR", "uploads"))


@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    session = get_session(request)
    if session is None:
        return RedirectResponse("/admin/login", status_code=303)

    db = connect()
    try:
        gifts = db.execute("""
            SELECT g.id, g.title, g.description, g.image,
                   r.name AS reserved_by, r.created_at AS reserved_at
            FROM gifts AS g
            LEFT JOIN reservations AS r ON r.gift_id = g.id
            ORDER BY g.id DESC
        """).fetchall()
    finally:
        db.close()

    csrf = escape(session["csrf_token"], quote=True)
    cards = "".join(f"""
        <article class="gift">
          {f'<img src="/images/{gift["image"]}" alt="" loading="lazy">' if gift['image'] else ''}
          <div class="gift-content">
            <h3>{escape(gift['title'])}</h3>
            <div class="description">{render_description(gift['description'])}</div>
            {f'<p>Reserviert von <strong>{escape(gift["reserved_by"])}</strong> am {escape(gift["reserved_at"])}</p>' if gift['reserved_by'] else '<p>Verfügbar</p>'}
            {f'''<form method="post" action="/admin/gifts/{gift['id']}/release">
              <input type="hidden" name="csrf_token" value="{csrf}">
              <button type="submit">Reservierung freigeben</button>
            </form>''' if gift['reserved_by'] else ''}
            <details>
              <summary>Bearbeiten</summary>
              <form class="gift-form" method="post" action="/admin/gifts/{gift['id']}/edit" enctype="multipart/form-data">
                <input type="hidden" name="csrf_token" value="{csrf}">
                <label>Titel <input name="title" maxlength="150" required value="{escape(gift['title'], quote=True)}"></label>
                <label>Beschreibung (Markdown) <textarea name="description" maxlength="2000">{escape(gift['description'])}</textarea></label>
                <label>Foto ersetzen (optional) <input type="file" name="image" accept="image/jpeg,image/png,image/webp"></label>
                <img class="photo-preview" alt="Vorschau des neuen Fotos" hidden>
                <button type="submit">Änderungen speichern</button>
              </form>
            </details>
            <form method="post" action="/admin/gifts/{gift['id']}/delete" onsubmit="return confirm('Diesen Wunsch und seine Reservierung wirklich löschen?')">
              <input type="hidden" name="csrf_token" value="{csrf}">
              <button type="submit">Wunsch löschen</button>
            </form>
          </div>
        </article>
    """ for gift in gifts) or "<p>Noch keine Wünsche eingetragen.</p>"

    return HTMLResponse(f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wishlist Admin</title>
  <style>
    :root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
    body {{ max-width: 760px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
    header {{ display: flex; justify-content: space-between; align-items: center; gap: 1rem; }}
    form.gift-form {{ display: grid; gap: .75rem; margin: 2rem 0; }}
    label {{ display: grid; gap: .25rem; }}
    input, textarea, button {{ font: inherit; padding: .5rem; }}
    textarea {{ min-height: 5rem; }}
    button {{ cursor: pointer; }}
    .gift {{ display: flex; align-items: center; gap: 1rem; padding: 1rem 0; border-top: 1px solid gray; }}
    .gift img {{ width: 100px; height: 100px; object-fit: cover; border-radius: .5rem; }}
    .gift h3 {{ margin: 0; }}
    .gift-content {{ flex: 1; min-width: 0; }}
    details {{ margin: .75rem 0; }}
    summary {{ cursor: pointer; }}
    @media (max-width: 520px) {{ .gift {{ align-items: flex-start; }} .gift > img {{ width: 76px; height: 76px; }} }}
    .description p {{ margin: .4rem 0; }}
    .description a {{ overflow-wrap: anywhere; }}
    .photo-preview {{ display: block; max-width: min(100%, 360px); max-height: 280px; object-fit: contain; border-radius: .5rem; margin-top: .5rem; }}
    .photo-preview[hidden] {{ display: none; }}
    .upload-error {{ color: #b91c1c; }}
    #drop-overlay {{ position: fixed; inset: 0; z-index: 9999; display: grid; place-items: center;
      text-align: center; padding: 2rem; background: rgba(25, 85, 125, .92); color: white;
      font-size: clamp(2rem, 6vw, 4rem); font-weight: bold; opacity: 0; visibility: hidden;
      pointer-events: none; transition: opacity .12s, visibility .12s; }}
    #drop-overlay.active {{ opacity: 1; visibility: visible; }}
    #drop-overlay span {{ display: block; font-size: 1rem; font-weight: normal; margin-top: 1rem; }}
  </style>
</head>
<body>
  <header>
    <h1>Leander's Wishlist 🎁</h1>
    <form method="post" action="/admin/logout">
      <input type="hidden" name="csrf_token" value="{csrf}">
      <button type="submit">Ausloggen</button>
    </form>
  </header>
  <h2>Wunsch hinzufügen</h2>
  <form class="gift-form" method="post" action="/admin/gifts" enctype="multipart/form-data">
    <input type="hidden" name="csrf_token" value="{csrf}">
    <label>Titel <input name="title" maxlength="150" required></label>
    <label>Beschreibung (optional, Markdown) <textarea name="description" maxlength="2000" placeholder="**Fett**, *kursiv* oder [Link](https://beispiel.at)"></textarea></label>
    <small>Unterstützt Markdown: **fett**, *kursiv*, Listen und Links.</small>
    <label>Foto (optional) <input id="gift-image" type="file" name="image" accept="image/jpeg,image/png,image/webp"></label>
    <div id="upload-error" class="upload-error" role="alert" hidden></div>
    <img id="photo-preview" class="photo-preview" alt="Vorschau des ausgewählten Fotos" hidden>
    <button type="submit">Wunsch speichern</button>
  </form>
  <h2>Deine Wünsche ({len(gifts)})</h2>
  {cards}
  <div id="drop-overlay" role="status" aria-live="polite" aria-hidden="true">Drag and Drop<span>Foto hier ablegen</span></div>
  <script>
    const photoInput = document.getElementById('gift-image');
    const preview = document.getElementById('photo-preview');
    const error = document.getElementById('upload-error');
    const overlay = document.getElementById('drop-overlay');
    let previewUrl = null;
    let dragDepth = 0;

    function updatePreview() {{
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = null;
      preview.hidden = true;
      preview.removeAttribute('src');
      error.hidden = true;
      const file = photoInput.files[0];
      if (!file) return;
      if (!/\\.(jpe?g|png|webp)$/i.test(file.name) || file.size > 10 * 1024 * 1024) {{
        error.textContent = 'Nur JPG, PNG oder WebP mit maximal 10 MB erlaubt.';
        error.hidden = false;
        photoInput.value = '';
        return;
      }}
      previewUrl = URL.createObjectURL(file);
      preview.src = previewUrl;
      preview.hidden = false;
    }}

    function hideDropOverlay() {{
      dragDepth = 0;
      overlay.classList.remove('active');
      overlay.setAttribute('aria-hidden', 'true');
    }}

    const hasFiles = event => Array.from(event.dataTransfer?.types || []).includes('Files');
    document.addEventListener('dragenter', event => {{
      if (!hasFiles(event)) return;
      event.preventDefault();
      dragDepth++;
      overlay.classList.add('active');
      overlay.setAttribute('aria-hidden', 'false');
    }});
    document.addEventListener('dragover', event => {{
      if (hasFiles(event)) event.preventDefault();
    }});
    document.addEventListener('dragleave', event => {{
      if (dragDepth > 0) dragDepth--;
      if (dragDepth === 0) hideDropOverlay();
    }});
    document.addEventListener('drop', event => {{
      if (!hasFiles(event)) return;
      event.preventDefault();
      hideDropOverlay();
      const file = event.dataTransfer.files[0];
      if (!file) return;
      const transfer = new DataTransfer();
      transfer.items.add(file);
      photoInput.files = transfer.files;
      updatePreview();
    }});
    window.addEventListener('blur', hideDropOverlay);
    photoInput.addEventListener('change', updatePreview);
    for (const input of document.querySelectorAll('details input[type="file"]')) {{
      let url = null;
      const image = input.closest('label').nextElementSibling;
      input.addEventListener('change', () => {{
        if (url) URL.revokeObjectURL(url);
        url = null;
        image.hidden = true;
        image.removeAttribute('src');
        const file = input.files[0];
        if (!file) return;
        if (!/\\.(jpe?g|png|webp)$/i.test(file.name) || file.size > 10 * 1024 * 1024) {{
          alert('Nur JPG, PNG oder WebP mit maximal 10 MB erlaubt.');
          input.value = '';
          return;
        }}
        url = URL.createObjectURL(file);
        image.src = url;
        image.hidden = false;
      }});
      window.addEventListener('pagehide', () => {{ if (url) URL.revokeObjectURL(url); }});
    }}
    window.addEventListener('pagehide', () => {{ if (previewUrl) URL.revokeObjectURL(previewUrl); }});
  </script>
</body>
</html>""", headers={"Cache-Control": "no-store"})


def save_image(image: UploadFile | None) -> str | None:
    filename = None
    if image and image.filename:
        content = image.file.read(MAX_IMAGE_BYTES + 1)
        if len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Bild darf maximal 10 MB groß sein")
        try:
            with Image.open(BytesIO(content)) as picture:
                if picture.format not in {"JPEG", "PNG", "WEBP"}:
                    raise HTTPException(422, "Nur JPG, PNG und WebP unterstützt")
                if picture.width * picture.height > 20_000_000:
                    raise HTTPException(413, "Bildauflösung zu groß")
                picture.load()
                photo = ImageOps.exif_transpose(picture).convert("RGB")
                photo.thumbnail((1600, 1600))
                filename = f"{uuid4().hex}.webp"
                upload_dir().mkdir(parents=True, exist_ok=True)
                photo.save(upload_dir() / filename, "WEBP", quality=85)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise HTTPException(422, "Ungültige Bilddatei") from exc

    return filename


@router.post("/admin/gifts")
def create_gift(
    request: Request,
    title: str = Form(max_length=150),
    description: str = Form(default="", max_length=2000),
    csrf_token: str = Form(),
    image: UploadFile | None = File(default=None),
):
    session = require_admin(request)
    require_csrf(session, csrf_token)

    title = title.strip()
    if not title:
        raise HTTPException(422, "Titel darf nicht leer sein")

    filename = save_image(image)

    db = connect()
    try:
        db.execute(
            "INSERT INTO gifts (title, description, image) VALUES (?, ?, ?)",
            (title, description.strip(), filename),
        )
        db.commit()
    except Exception:
        if filename:
            (upload_dir() / filename).unlink(missing_ok=True)
        raise
    finally:
        db.close()

    return RedirectResponse("/admin", status_code=303)


@router.post("/admin/gifts/{gift_id}/edit")
def edit_gift(
    gift_id: int,
    request: Request,
    title: str = Form(max_length=150),
    description: str = Form(default="", max_length=2000),
    csrf_token: str = Form(),
    image: UploadFile | None = File(default=None),
):
    session = require_admin(request)
    require_csrf(session, csrf_token)
    title = title.strip()
    if not title:
        raise HTTPException(422, "Titel darf nicht leer sein")

    db = connect()
    filename = None
    try:
        gift = db.execute("SELECT image FROM gifts WHERE id = ?", (gift_id,)).fetchone()
        if gift is None:
            raise HTTPException(404, "Wunsch nicht gefunden")

        filename = save_image(image)
        db.execute(
            "UPDATE gifts SET title = ?, description = ?, image = COALESCE(?, image) WHERE id = ?",
            (title, description.strip(), filename, gift_id),
        )
        db.commit()
    except Exception:
        db.rollback()
        if filename:
            (upload_dir() / filename).unlink(missing_ok=True)
        raise
    finally:
        db.close()

    if filename and gift["image"]:
        (upload_dir() / gift["image"]).unlink(missing_ok=True)
    return RedirectResponse("/admin", status_code=303)


@router.post("/admin/gifts/{gift_id}/delete")
def delete_gift(gift_id: int, request: Request, csrf_token: str = Form()):
    session = require_admin(request)
    require_csrf(session, csrf_token)
    db = connect()
    try:
        gift = db.execute("SELECT image FROM gifts WHERE id = ?", (gift_id,)).fetchone()
        if gift is None:
            raise HTTPException(404, "Wunsch nicht gefunden")
        db.execute("DELETE FROM gifts WHERE id = ?", (gift_id,))
        db.commit()
    finally:
        db.close()

    if gift["image"]:
        (upload_dir() / gift["image"]).unlink(missing_ok=True)
    return RedirectResponse("/admin", status_code=303)


@router.post("/admin/gifts/{gift_id}/release")
def release_reservation(gift_id: int, request: Request, csrf_token: str = Form()):
    session = require_admin(request)
    require_csrf(session, csrf_token)
    db = connect()
    try:
        result = db.execute("DELETE FROM reservations WHERE gift_id = ?", (gift_id,))
        if result.rowcount == 0:
            raise HTTPException(404, "Reservierung nicht gefunden")
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin", status_code=303)


@router.get("/images/{filename}")
def get_image(filename: str):
    if not re.fullmatch(r"[0-9a-f]{32}\.webp", filename):
        raise HTTPException(404, "Image not found")
    path = upload_dir() / filename
    if not path.is_file():
        raise HTTPException(404, "Image not found")
    return FileResponse(
        path,
        media_type="image/webp",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )
