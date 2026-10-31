# Troubleshooting Guide

This guide is based on the checked-in settings and runtime code. Do not paste
database passwords, API keys, SMTP credentials, or `.env` contents into logs or
support requests.

## Backend does not start

### Django cannot import a package

Activate the virtual environment and install the pinned dependencies:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run backend commands from the repository root using `python app\manage.py ...`.

### Database environment variable missing

`app/config/settings.py` reads `DB_NAME`, `DB_USER`, and `DB_PASSWORD` directly.
If any are absent, settings initialization can fail. Add them to the
project-root `.env` or process environment. Optional connection variables are
`DB_HOST` and `DB_PORT`.

### MySQL connection refused or access denied

- Confirm the MySQL service is running.
- Confirm database name, user, password, host, and port match the server.
- Confirm the user has privileges on the configured database.
- Check that the database exists; Django migrations do not create the MySQL
  database itself.
- Confirm `mysqlclient` installed successfully.
- Check host firewall and whether MySQL accepts TCP connections from the
  Django process.

The code currently configures MySQL unconditionally. Setting `DB_ENGINE=sqlite`
does not switch engines in current `settings.py`, despite references to that
setting in the root README.

### `mysqlclient` installation fails on Windows

Check the `mysqlclient` package's requirements for your Python version and
Windows environment. Install the necessary compiler/build dependencies or use
a compatible prebuilt wheel as allowed by your environment. Do not replace the
database backend in settings without confirming compatibility.

### Migrations fail or tables are missing

From the repository root:

```powershell
python app\manage.py showmigrations observations
python app\manage.py migrate
```

Use the committed migration history; do not delete migration files or manually
alter tables as a first fix. For new source-model changes, use Django's
`makemigrations` only when intentionally changing the application schema.

## Prediction model errors

### Model file not found

`prediction.MODEL_PATH` resolves to
`notebooks/landslide_logistic_pipeline.joblib` relative to the project root.
Check that this exact artifact exists and is readable. The training notebook
can save a replacement artifact, but regenerate it only after confirming the
training data and feature schema.

### Unsupported input features

`load_model` checks the model's `feature_names_in_` against two supported
feature tuples. A model trained with a different set/order is rejected.
Compare the artifact's training pipeline with `FEATURE_COLUMNS` and
`ONE_HOT_FEATURE_COLUMNS` in `app/observations/prediction.py`.

The artifact name includes `logistic_pipeline`, but the current notebook trains
a `RandomForestClassifier`. Check the estimator and its actual feature metadata
rather than relying on the filename.

### Prediction endpoint returns HTTP 503

The observation view maps model-loading `ImproperlyConfigured` errors to
`prediction_model_unavailable`. The observation is not saved when prediction
fails before creation. Inspect the Django server log for the model loading
error and check the artifact path and dependencies.

## React/Vite problems

### Frontend cannot reach Django

- Start Django with `python app\manage.py runserver`.
- Check that the frontend's `VITE_API_BASE_URL` points to the correct backend
  origin; default is `http://127.0.0.1:8000`.
- Check backend CORS allow-list. The defaults are
  `http://localhost:5173` and `http://127.0.0.1:5173`; set
  `CORS_ALLOWED_ORIGINS` for a different development origin.
- Restart Vite after editing a `VITE_` variable.
- Use the browser developer console/network tab to inspect URL, status code,
  and returned validation details.

### npm build or lint fails

From `frontend/`, run `npm install`, then `npm run build` or `npm run lint`.
Resolve the first reported dependency or syntax error before retrying.
`package.json` lists the scripts and versions.

## Pinecone and RAG issues

### Pinecone key missing

`initialize_rag` loads the project-root `.env` and requires
`PINECONE_API_KEY`. Add it privately, restart Django, and do not print it.

### Index or namespace not found/empty

The runtime requires index `wayanad-landslide-safety`, 768 dimensions, and
namespace `landslide-safety-v1` with at least one vector. Run
`notebooks/landslide_rag_index.ipynb` to index the provided PDF and verify that
the notebook and runtime are using the same index, namespace, and embedding
model.

### Pinecone API/network error

Check internet access, key validity/permissions, index availability, and
provider status. `rag.py` raises `RagServiceError` for operational retrieval
failures, and the safety endpoint returns HTTP 503.

### Sources are empty or no answer found

The retrieval query may not match the indexed text, the namespace may be
incorrect, or the document may not contain the answer. Re-index after changing
the PDF. The runtime intentionally returns a no-answer response when there are
no retrieved passages; it should not be treated as proof that no real-world
safety advice exists.

## Embedding model issues

`SentenceTransformer("intfloat/e5-base-v2")` may download model data at first
use. Ensure internet access and enough disk/memory. If model loading fails,
check package compatibility and the local model cache. The runtime caches the
embedding model after loading; restart Django after changing configuration or
repairing the local cache.

For E5 retrieval, the query is encoded with a `query:` prefix and normalized.
Changing embedding model or dimensions requires rebuilding the Pinecone vectors
with matching settings.

## Ollama and CrewAI issues

### Ollama is unavailable

Ensure Ollama is installed and running, and the configured model is available.
The default model is `qwen2.5:3b`; `OLLAMA_MODEL` can override it. The CrewAI
agent's default base URL is `http://localhost:11434`, configurable through
`OLLAMA_BASE_URL`.

The user-operated RAG assistant catches generation errors and reports a
service-unavailable response. The positive-prediction CrewAI failure is logged;
the observation remains saved and workflow processing attempts to continue.

### CrewAI summary does not work

Check compatible installed versions from `requirements.txt`, Ollama
availability, model name, and base URL. CrewAI summarizes existing workflow
data; a successful summary is not required for safety guidance retrieval. The
workflow's Python code, not the LLM, handles contact selection and sending.

## SMTP/email errors

- Confirm `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD` are set privately and
  correspond to an account permitted to send via the configured SMTP host.
- Confirm SMTP host access, port 587, and TLS connectivity.
- Confirm the selected first `EmergencyAuthority` has a valid email address.
- Remember that the selected contact is not filtered by location, active
  status, or verified status.
- Inspect the Django process logs for failures. The email result is not shown
  in React and is not saved in an active alert table.
- A blank or invalid recipient skips sending. Backend errors return a failed
  status in the logged workflow result.
- Use mocks in the test suite for non-delivery verification. There is no
  production dry-run setting.

## Emergency contact data

Manage authorities through Django Admin after creating an admin user. The
`demo_emergency_authorities` fixture is intentionally fake and uses an invalid
email address. It must not be relied on or edited into a real contact without
independent verification.

## Still stuck?

Capture the relevant exception type, endpoint, and HTTP status, but redact all
credentials and personal contact data. Confirm whether the failure occurs in
the synchronous observation request, in the separate safety assistant, or in
the asynchronous positive-prediction worker; they have different error paths.

If `python app\manage.py test observations` fails immediately during test
module import, check for the current source mismatch: tests import
`create_chunks`/`load_pdf_pages` from `rag.py` and `_tool_result` from
`response_agent.py`, but the current runtime files do not define those names.
