# Sneaker Scrapling Monitor

Een PWA die meerdere shops tegelijk server-side monitort met Scrapling. Standaard
twee monitors naast elkaar: **Solebox** (releases-lijst) en **Naked Copenhagen**
(timed product-drop). Elke shop gebruikt zijn eigen login.

## Inloggegevens

Per shop in `config/credentials.json` (niet in git):

```json
{
  "solebox":  { "username": "jij@example.com", "password": "..." },
  "nakedcph": { "username": "jij@example.com", "password": "..." }
}
```

Kopieer `config/credentials.example.json` als start. Environment-variabelen
overschrijven het bestand: `SOLEBOX_USERNAME` / `SOLEBOX_PASSWORD` enz. In de
gebouwde desktop-app komt dit bestand in `~/.solebox_monitor/credentials.json`.

- **Solebox** logt pas in bij de betaalstap (loginformulier zit achter checkout).
- **Naked Copenhagen** logt vooraf in op de eigen loginpagina.
- Elke shop heeft een eigen persistente browsersessie (`config/sessions/<shop>`),
  dus na één keer inloggen blijft de sessie bewaard.

## Setup

```bash
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
scrapling install
uvicorn app.main:app --reload
```

Open daarna `http://127.0.0.1:8000`. Scrapling `0.4.8` vereist Python `3.10+`.

## Losse desktop app bouwen

macOS bouw je op een Mac:

```bash
chmod +x scripts/build-macos.sh
PYTHON_BIN=/opt/homebrew/bin/python3.11 scripts/build-macos.sh
```

Output: `dist/SoleboxMonitor.app`.

Omdat de app unsigned is zonder Apple Developer account, moet je op eigen Macs de quarantine flag verwijderen:

```bash
xattr -dr com.apple.quarantine dist/SoleboxMonitor.app
open dist/SoleboxMonitor.app
```

Windows bouw je op Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-windows.ps1
```

Output: `dist\SoleboxMonitor\SoleboxMonitor.exe`.

De desktop app start lokaal een server op `127.0.0.1:8018` en opent automatisch je browser. De automation-browser blijft los zichtbaar voor Solebox.

## Ubuntu deploy met Nginx

Zet de projectbestanden op de server in `/var/www/anouk` en draai:

```bash
cd /var/www/anouk
sudo bash scripts/setup-ubuntu.sh anouk.googeng.com
```

Het script maakt een venv met Python `3.10+`, installeert Scrapling `0.4.8`, schrijft een systemd service op poort `8017`, en zet Nginx als reverse proxy voor het opgegeven subdomein. De app wordt alleen op `127.0.0.1` gestart en Nginx zet Basic Auth plus security headers voor de publieke URL. Zorg dat je DNS `A` record voor bijvoorbeeld `anouk.googeng.com` naar je Ubuntu server wijst.

Standaard genereert het script een wachtwoord voor gebruiker `anouk`. Zelf een wachtwoord instellen kan zo:

```bash
cd /var/www/anouk
sudo BASIC_AUTH_PASSWORD='kies-een-lang-wachtwoord' bash scripts/setup-ubuntu.sh anouk.googeng.com
```

Na deploy kun je logs volgen met:

```bash
journalctl -u anouk-monitor -f
```

Cloudflare solving staat standaard uit om ruis zoals `No Cloudflare challenge found` te voorkomen. Als Solebox later echt een Cloudflare challenge toont, zet dan in de systemd service `SOLVE_CLOUDFLARE=1` en restart `anouk-monitor`.

SSL voor `anouk.googeng.com` zet je daarna aan met:

```bash
cd /var/www/anouk
sudo CERTBOT_EMAIL='jij@googeng.com' bash scripts/enable-ssl.sh anouk.googeng.com
```

Zonder email kan ook interactief:

```bash
sudo bash scripts/enable-ssl.sh anouk.googeng.com
```

## Gedrag

Elke monitor heeft een eigen kaart in de PWA met eigen start/stop/log.

**Solebox (listing-modus)** — zoekt zoektekst op de releases-lijst. Default
zoektekst `muslin shy pink`, URL `.../s/releases`, maat `41`. Bij match: maat +
add-to-cart + checkout; daarna wordt het loginformulier op de checkoutpagina
ingevuld.

**Naked Copenhagen (product-modus)** — bewaakt één productpagina. De koopknop is
tijd-gestuurd en wordt client-side gerenderd, dus de monitor leest de
`releaseDate` uit de pagina en triggert op de klok. ~45s vóór release opent de
browser, logt in en gaat naar de productpagina; daarna wordt maat + add-to-cart
in een retry-loop geprobeerd tot de knop live is (tot `buy_window_seconds` na
release). Nieuwe shops voeg je toe in `app/sites.py`.

Bij een match stopt de monitor, speelt de PWA een geluid af en toont een
notificatie. De zichtbare browser blijft open om handmatig af te ronden.
