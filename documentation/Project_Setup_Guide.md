# Project Setup Guide

This guide describes a local development setup based on the current settings
and source files. Commands below use Windows PowerShell from the repository
root.

## Prerequisites

- Windows, macOS, or Linux development machine (commands here are for Windows).
- A Python installation compatible with the pinned packages in
  `requirements.txt`.
- Node.js and npm compatible with the Vite version in `frontend/package.json`.
- MySQL server and a database user with permission to create/use the project
  database.
- Git, if cloning the repository.
- For the RAG assistant: a Pinecone account/API key, internet access for the
  embedding model, and Ollama with the configured model installed.
- For actual email delivery: SMTP access and valid sender credentials.

Some packages, particularly `mysqlclient` and the machine-learning dependencies,
may need platform-specific system libraries or compiler tools.

## Repository layout and working directory

Run backend commands from the repository root, which contains `app`,
`frontend`, `data`, and `notebooks`. Django's `manage.py` is under `app`.

```powershell
Set-Location C:\path\to\wayanad-landslide-early-warning-system
```

## Python virtual environment and backend packages

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell prevents activation, use the Python executable directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The supplied `requirements.txt` pins Django, DRF, MySQL driver, scikit-learn,
CrewAI, Ollama, Pinecone, Sentence Transformers, and related libraries.

## MySQL database

`app/config/settings.py` configures Django's default database engine as MySQL.
It reads these environment variables:

| Variable | Required? | Purpose |
| --- | --- | --- |
| `DB_NAME` | Yes | Existing MySQL database name. |
| `DB_USER` | Yes | Database account. |
| `DB_PASSWORD` | Yes | Database account password. |
| `DB_HOST` | No | Defaults to `localhost`. |
| `DB_PORT` | No | Defaults to `3306`. |

Create a database and a restricted database user using your MySQL administrator
account. For example, substitute your own identifiers and credentials in your
local MySQL client; do not put real passwords in source control:

```sql
CREATE DATABASE wayanad_landslide
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'wayanad_app'@'localhost' IDENTIFIED BY '<set-a-private-password>';
GRANT ALL PRIVILEGES ON wayanad_landslide.* TO 'wayanad_app'@'localhost';
```

The database and user are not created automatically by Django. Configure the
variables below before running migrations.

> The repository README mentions a `DB_ENGINE=sqlite` option, but the current
> `app/config/settings.py` does not read `DB_ENGINE`; it explicitly configures
> MySQL. SQLite is therefore not enabled simply by setting that variable.

## Environment variables

The Django settings and RAG code load a project-root `.env` file. No
`.env.example` is present in the current project tree. Create or edit the local
file without sharing it or committing it. A safe variable-name template is:

```dotenv
DJANGO_SECRET_KEY=<generate-a-private-random-value>
DB_NAME=wayanad_landslide
DB_USER=wayanad_app
DB_PASSWORD=<your-private-mysql-password>
DB_HOST=localhost
DB_PORT=3306
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

# Required only for RAG retrieval:
PINECONE_API_KEY=<your-private-pinecone-key>

# Optional model overrides:
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_BASE_URL=http://localhost:11434

# Required for SMTP email delivery:
EMAIL_HOST_USER=<your-sender-address>
EMAIL_HOST_PASSWORD=<your-private-smtp-or-app-password>
```

`DJANGO_SECRET_KEY` is read by settings, but use a private value rather than
relying on a development fallback. `EMAIL_HOST`, port, TLS, and backend are
configured in `app/config/settings.py` (SMTP, Gmail host, port 587, TLS).

The frontend optionally reads `VITE_API_BASE_URL`. If the backend is not at the
default local address, create `frontend/.env.local` with:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Vite environment changes require restarting its development server.

## Database migrations and optional demo contact

```powershell
python app\manage.py migrate
```

Optionally load the clearly marked non-real demo authority fixture:

```powershell
python app\manage.py loaddata demo_emergency_authorities
```

That fixture uses an `.invalid` email and is inactive/unverified. It is not a
real emergency contact and will not produce a valid delivery recipient. Manage
real authority rows only after independently verifying the details.

Create an admin login if needed:

```powershell
python app\manage.py createsuperuser
```

## Frontend installation

Open another PowerShell terminal:

```powershell
Set-Location C:\path\to\wayanad-landslide-early-warning-system\frontend
npm install
npm run dev
```

Vite prints the local URL, normally `http://localhost:5173`. To validate or
lint the frontend:

```powershell
npm run build
npm run lint
```

## RAG index and Ollama

The runtime expects an existing Pinecone index named
`wayanad-landslide-safety`, namespace `landslide-safety-v1`, with 768-dimensional
vectors. Run `notebooks/landslide_rag_index.ipynb` when the safety PDF needs to
be indexed or rebuilt. The notebook and `app/observations/rag.py` both read the
Pinecone key from the project-root `.env`.

Install/start Ollama separately and ensure its model is available. The default
configured model is `qwen2.5:3b`; the response-agent base URL defaults to
`http://localhost:11434`.

## Start the application

Start Django in one terminal from the repository root:

```powershell
python app\manage.py runserver
```

Start Vite in another terminal:

```powershell
Set-Location frontend
npm run dev
```

Open the Vite URL printed in the terminal. The React API default points to
`http://127.0.0.1:8000`.

## Optional verification

Run the Django tests from the repository root:

```powershell
python app\manage.py test observations
```

Some tests expect a configured database and the model artifact. Tests that
cover external RAG/SMTP behavior use mocks in the test suite. The current
`tests.py` also imports helper names that are not defined in the current RAG
and response-agent modules (`create_chunks`, `load_pdf_pages`, and
`_tool_result`), so the command may fail during test discovery until that
source/test mismatch is corrected. For endpoints and payloads, see
[Backend Documentation](./Backend_Documentation.md).
