# Pickleball Tournament App

Runs pickleball events: a round robin, then an elimination bracket. Players sign up,
join with a code, see their schedule, and enter scores. Spectators follow along with
their own code.

The full spec is in [CLAUDE.md](CLAUDE.md). This README covers setup and day-to-day commands.

## Stack

- Python 3.12+ (developed on 3.13), Django 5.2 LTS
- Server-rendered templates + HTMX (vendored in `static/js/htmx.min.js`)
- Tailwind CSS v4 via the standalone CLI (no Node.js needed)
- SQLite locally, PostgreSQL in production via `DATABASE_URL`
- pytest + pytest-django
- whitenoise + gunicorn for deployment

## First-time setup (Windows PowerShell)

```powershell
# 1. Create and activate the virtual environment
python -m venv pvenv
.\pvenv\Scripts\Activate.ps1

# 2. Install packages
pip install -r requirements.txt

# 3. Local settings
Copy-Item .env.example .env
# Open .env and keep DJANGO_DEBUG=true for local work.

# 4. Download the Tailwind CLI (one file, kept out of git)
New-Item -ItemType Directory -Force bin
Invoke-WebRequest https://github.com/tailwindlabs/tailwindcss/releases/download/v4.3.5/tailwindcss-windows-x64.exe -OutFile bin\tailwindcss.exe

# 5. Set up the database
python manage.py migrate
python manage.py createsuperuser
```

On macOS or Linux, use `source pvenv/bin/activate` and download the matching
`tailwindcss-macos-arm64` / `tailwindcss-linux-x64` file from the same release page.

## Every day

```powershell
.\pvenv\Scripts\Activate.ps1
python manage.py runserver
```

Then open http://127.0.0.1:8000/.

Organizers use the **Manage** link in the app. The Django admin at
http://127.0.0.1:8000/django-admin/ is for the builder only.

### Styles (Tailwind)

The source is `assets/tailwind.css`. The built file is `static/css/app.css`, which is
committed so deployment does not need the Tailwind CLI.

While editing templates, run this in a second terminal. It rebuilds on every save:

```powershell
.\bin\tailwindcss.exe -i assets\tailwind.css -o static\css\app.css --watch
```

Before committing, build the minified version:

```powershell
.\bin\tailwindcss.exe -i assets\tailwind.css -o static\css\app.css --minify
```

Brand colors are CSS variables in the `@theme` block of `assets/tailwind.css`.

### Tests and checks

```powershell
pytest
python manage.py check
```

### Load check (500 players)

```powershell
python manage.py load_check          # seed 500 players, run two full events, time the main pages
python manage.py load_check --clean  # remove everything it made
```

It makes a Mixed doubles event (250 teams in pools of 6, 8 courts, a 16-team bracket)
and a 500-player Scramble, scores every match, then loads each player, spectator, and
admin page and prints its time and database query count. A page over 40 queries is
flagged. Everything it makes is named `loadcheck-...` or "Load check ...", so it never
touches real data. The data stays so you can click through it; run `--clean` after.

## Configuration

All settings come from environment variables. See [.env.example](.env.example).
A local `.env` file is read automatically. Real environment variables take priority.

| Variable | Purpose |
|---|---|
| `DJANGO_DEBUG` | `true` for local work only |
| `DJANGO_SECRET_KEY` | Required when debug is off |
| `DJANGO_ALLOWED_HOSTS` | Comma separated host names |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Comma separated `https://` origins in production |
| `DATABASE_URL` | `postgres://user:pass@host:5432/db`. Blank means local SQLite. |
| `SESSION_COOKIE_AGE` | Sign-in length in seconds. Default is one year. |
| `DJANGO_ADMIN_USERNAME`, `DJANGO_ADMIN_PASSWORD` | Optional. Makes the first admin on deploy if there is none. |
| `DJANGO_HSTS_SECONDS` | Optional. HTTPS-only browser setting. Leave at 0 until the final domain works. |
| `RENDER_EXTERNAL_HOSTNAME` | Set by Render automatically. Trusted as a host. |

## Project layout

| Folder | Holds |
|---|---|
| `config/` | Settings, URLs, WSGI, env helpers |
| `core/` | Shared pages and helpers |
| `accounts/` | Custom user model, login, players |
| `events/` | Events, levels, divisions, codes |
| `scheduling/` | Round robin and Scramble scheduling |
| `scoring/` | Score entry, confirmation, locking |
| `standings/` | Rankings and seeding |
| `brackets/` | Elimination brackets |
| `chat/` | Event chat |
| `templates/` | `base.html` and shared templates |
| `assets/` | Tailwind source |
| `static/` | Built CSS, HTMX, images |

## Deploying to Render

The repository has everything Render needs:

| File | Does |
|---|---|
| `render.yaml` | Blueprint: a Python web service and a PostgreSQL database |
| `build.sh` | Runs on every deploy: install, `collectstatic`, `migrate`, `ensure_admin` |
| `.python-version` | Python 3.13 |

### First time

1. Push this repository to GitHub (private is fine).
2. In the Render dashboard choose **New > Blueprint** and pick the repository.
   Render reads `render.yaml` and shows the web service and the database.
3. Render asks for two values. Pick the first organizer login:
   - `DJANGO_ADMIN_USERNAME`, for example `rachel`
   - `DJANGO_ADMIN_PASSWORD`, at least 8 characters and not a common password
4. Click **Apply**. The first build takes a few minutes. When it says **Live**,
   open the `https://<name>.onrender.com` address it shows.
5. Sign in with the admin login from step 3. To change that password later, open
   **Manage > Players**, find yourself, and set a new one (you'll sign in again
   afterward). You can delete the two admin variables in Render once you're in;
   `ensure_admin` does nothing once an admin exists.

`DJANGO_SECRET_KEY` is generated by Render. `DATABASE_URL` is filled in from the database.

### Before a real event

- **Plans.** The Blueprint starts on free plans. A free web service sleeps after
  15 idle minutes and takes about a minute to wake up, and a free database is
  deleted after 30 days. Switch both to paid plans in the dashboard before players use it.
- **Your own domain (optional).** Add it under the web service's **Settings > Custom Domains**,
  then set `DJANGO_ALLOWED_HOSTS=pickleball.example.com` and
  `DJANGO_CSRF_TRUSTED_ORIGINS=https://pickleball.example.com` in **Environment**.
- **HSTS (optional).** Once the final domain works over HTTPS, set
  `DJANGO_HSTS_SECONDS=31536000`. Browsers then refuse plain HTTP for a year, so only
  do this when the domain is settled.

### Every update

Push to the main branch. Render rebuilds and runs the migrations on its own.
If a deploy fails, the **Events** and **Logs** tabs in Render show why, and the
previous version keeps running.

### Other hosts

Nothing is Render-only. Any host works if it sets the variables above and runs:

```bash
bash build.sh
gunicorn config.wsgi --bind 0.0.0.0:$PORT
```
