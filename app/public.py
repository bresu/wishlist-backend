"""Public wishlist: display gifts and reserve them through the existing API."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)


@router.get("/wishlist", response_class=HTMLResponse)
def wishlist_page():
    return HTMLResponse("""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Leander's Wishlist 🎁</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
    body { max-width: 760px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
    label { display: grid; gap: .25rem; max-width: 320px; margin: 1rem 0 2rem; }
    input, button { font: inherit; padding: .5rem; }
    button { cursor: pointer; }
    button:disabled { cursor: not-allowed; opacity: .55; }
    .gift { display: flex; align-items: flex-start; gap: 1rem; padding: 1.25rem 0; border-top: 1px solid gray; }
    .gift > img { width: 110px; height: 110px; object-fit: cover; border-radius: .5rem; }
    .gift-content { flex: 1; min-width: 0; }
    .gift h2 { font-size: 1.2rem; margin: 0; }
    .description p { margin: .4rem 0; }
    .description a { overflow-wrap: anywhere; }
    .gift form { margin-top: .75rem; }
    .reserved { opacity: .7; }
    #message { min-height: 1.5em; }
    @media (max-width: 520px) { .gift > img { width: 76px; height: 76px; } }
  </style>
</head>
<body>
  <h1>Leander's Wishlist 🎁</h1>
  <p>Hier findest du Dinge, die ich mir wünsche. Du kannst dir ein Geschenk reservieren, damit ich es nicht doppelt bekomme.</p>
  <label>Dein Name (nur für die Reservierung)
    <input id="name" type="text" maxlength="100" autocomplete="name" required>
  </label>
  <p id="message" role="status" aria-live="polite">Wünsche werden geladen …</p>
  <div id="gifts"></div>
  <script>
    const nameInput = document.getElementById('name');
    const container = document.getElementById('gifts');
    const message = document.getElementById('message');

    function updateButtons() {
      for (const button of container.querySelectorAll('button')) {
        button.disabled = !nameInput.value.trim();
      }
    }
    nameInput.addEventListener('input', updateButtons);

    async function loadGifts() {
      try {
        const response = await fetch('/gifts');
        if (!response.ok) throw new Error('Wünsche konnten nicht geladen werden.');
        const gifts = await response.json();
        container.replaceChildren();
        message.textContent = gifts.length ? '' : 'Noch keine Wünsche eingetragen.';

        for (const gift of gifts) {
          const article = document.createElement('article');
          article.className = 'gift' + (gift.reserved ? ' reserved' : '');
          if (gift.image) {
            const img = document.createElement('img');
            img.src = '/images/' + encodeURIComponent(gift.image);
            img.alt = '';
            img.loading = 'lazy';
            article.append(img);
          }
          const content = document.createElement('div');
          content.className = 'gift-content';
          const title = document.createElement('h2');
          title.textContent = gift.title;
          content.append(title);
          const description = document.createElement('div');
          description.className = 'description';
          // description_html is rendered by the backend with raw HTML disabled.
          description.innerHTML = gift.description_html;
          content.append(description);

          if (gift.reserved) {
            const label = document.createElement('p');
            label.textContent = 'Bereits reserviert';
            content.append(label);
          } else {
            const form = document.createElement('form');
            const button = document.createElement('button');
            button.type = 'submit';
            button.textContent = 'Reservieren';
            form.append(button);
            form.addEventListener('submit', async event => {
              event.preventDefault();
              const name = nameInput.value.trim();
              if (!name || !confirm('„' + gift.title + '“ wirklich reservieren?')) return;
              button.disabled = true;
              try {
                const result = await fetch('/gifts/' + gift.id + '/claim', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ name })
                });
                if (result.status === 409) {
                  await loadGifts();
                  message.textContent = 'Dieses Geschenk wurde gerade von jemand anderem reserviert.';
                } else if (!result.ok) {
                  message.textContent = 'Reservierung fehlgeschlagen. Bitte erneut versuchen.';
                } else {
                  await loadGifts();
                  message.textContent = 'Geschenk erfolgreich reserviert. Danke! 🎁';
                }
              } catch {
                message.textContent = 'Verbindung fehlgeschlagen. Bitte erneut versuchen.';
              } finally {
                button.disabled = !nameInput.value.trim();
              }
            });
            content.append(form);
          }
          article.append(content);
          container.append(article);
        }
        updateButtons();
      } catch {
        message.textContent = 'Die Wunschliste konnte nicht geladen werden.';
      }
    }
    loadGifts();
  </script>
</body>
</html>""", headers={"Cache-Control": "no-store"})
