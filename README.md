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

The Django admin is at http://127.0.0.1:8000/django-admin/. That path is for builder use.
The app's own admin screens come in Phase 1.

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

## Deployment

The host is not chosen yet. The app runs anywhere that sets the environment
variables above and runs:

```bash
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate
gunicorn config.wsgi
```
