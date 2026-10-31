# Backend Documentation

The backend is a Django project under `app/`. The application code is in
`app/observations/`, configured by `app/config/`.

## Project files

| File | Purpose |
| --- | --- |
| `app/manage.py` | Django command-line entry point. Sets `DJANGO_SETTINGS_MODULE=config.settings`. |
| `app/config/settings.py` | Installed apps, middleware, MySQL config, SMTP settings, and CORS origins. |
| `app/config/urls.py` | Mounts Django Admin and includes `observations.urls` under `/api/`. |
| `app/config/asgi.py`, `app/config/wsgi.py` | ASGI and WSGI server entry points. |
| `app/observations/apps.py` | Declares the `observations` Django app. |
| `app/observations/models.py` | Defines persistent `LandslideObservation` and `EmergencyAuthority`. |
| `app/observations/admin.py` | Registers `EmergencyAuthority` in Django Admin. |
| `app/observations/urls.py` | Defines the safety endpoint and router-generated observation endpoints. |
| `app/observations/views.py` | DRF API views, lifecycle hooks, and API error mapping. |
| `app/observations/serializers.py` | Request validation and observation serialization. |
| `app/observations/services.py` | Create/list/update services and background task scheduling. |
| `app/observations/prediction.py` | Cached model load and inference. |
| `app/observations/rag.py` | Pinecone retrieval and Ollama answer generation. |
| `app/observations/response_agent.py` | Conditional guidance/contact/summary/email workflow. |
| `app/observations/tests.py` | API, model, RAG-related, contact, and email workflow tests. |
| `app/observations/migrations/` | Historical/current database schema changes. |
| `app/observations/fixtures/demo_emergency_authorities.json` | Non-real demo contact with `.invalid` address. |

## API URL routing

`app/config/urls.py` includes the observations app at `/api/`.
`app/observations/urls.py` registers a DRF `DefaultRouter` with
`LandslideObservationViewSet` at `observations/`, and defines
`SafetyAssistantView` at `safety-assistant/`.

### Observation endpoints

| Method | Endpoint | Behavior |
| --- | --- | --- |
| `GET` | `/api/observations/` | List all observations; model ordering is newest first. |
| `POST` | `/api/observations/` | Validate input, predict, save, return HTTP 201. |
| `GET` | `/api/observations/{id}/` | Retrieve one observation. |
| `PUT` | `/api/observations/{id}/` | Replace editable fields, recalculate prediction, save. |
| `PATCH` | `/api/observations/{id}/` | Partially update editable fields, recalculate prediction, save. |
| `DELETE` | `/api/observations/{id}/` | Delete one observation; normally returns HTTP 204. |

`GET` list responses are JSON arrays. Create/retrieve/update responses are JSON
objects with model fields and the server-computed outputs. The observations
serializer does not expose emergency authorities.

### Observation request

The serializer accepts either lower-case Django field names or the dataset
column names translated by `to_internal_value`. The React UI submits the
dataset-style form:

```json
{
  "Location_ID": 101,
  "Max_Temp_C": 27.5,
  "Humidity_Pct": 84.0,
  "Wind_Speed_kmh": 12.0,
  "Rainfall_mm": 35.5,
  "Slope_Angle_Deg": 32,
  "Vegetation_Cover": "Medium"
}
```

The equivalent lower-case field names are `location_id`, `max_temp_c`,
`humidity_pct`, `wind_speed_kmh`, `rainfall_mm`, `slope_angle_deg`, and
`vegetation_cover`. Do not supply prediction, probability, ID, or timestamp as
client-controlled values.

The response includes values such as:

```json
{
  "id": 1,
  "location_id": 101,
  "max_temp_c": 27.5,
  "humidity_pct": 84.0,
  "wind_speed_kmh": 12.0,
  "rainfall_mm": 35.5,
  "slope_angle_deg": 32,
  "vegetation_cover": "Medium",
  "landslide_observed": null,
  "landslide_prediction": "Yes",
  "landslide_probability": 0.72,
  "created_at": "2026-10-09T09:00:00Z"
}
```

Example prediction and timestamp values are illustrative; actual values depend
on the model and database.

### Safety assistant endpoint

`POST /api/safety-assistant/` accepts:

```json
{"question": "What should I do if I hear rocks falling?"}
```

`SafetyQuestionSerializer` trims whitespace and validates length from 3 to
1000 characters. A successful response is:

```json
{
  "answer": "Answer text with page citations.",
  "sources": [
    {"page": 2, "score": 0.81, "text": "Retrieved source excerpt"}
  ]
}
```

The actual source score and text are supplied by retrieval. `SafetyAssistantView`
uses `AllowAny` and maps missing/invalid RAG configuration and service failures
to HTTP 503.

## Views, serializers, and services

### `views.py`

- `PredictionModelUnavailable`: DRF exception returning HTTP 503 when model
  setup prevents inference.
- `SafetyAssistantUnavailable`: DRF exception returning HTTP 503 for safety
  assistant failures.
- `LandslideObservationViewSet.get_queryset`: delegates to `get_observations`.
- `perform_create`: calls `create_observation`; translates
  `ImproperlyConfigured` into a prediction-model service error.
- `perform_update`: calls `update_observation` and maps the same model error.
- `SafetyAssistantView.post`: validates the question, calls
  `answer_safety_question`, and returns its result.

### `serializers.py`

- `SafetyQuestionSerializer`: validates a safety-assistant question.
- `LandslideObservationSerializer`: a `ModelSerializer` for all observation
  model fields. Prediction outputs, ID, and `created_at` are read-only.
- `to_internal_value`: copies the request and maps dataset column labels to
  Django names; sending both names for the same field causes validation error.

### `services.py`

- `get_observations()`: returns `LandslideObservation.objects.all()`, ordered by
  the model's `Meta.ordering`.
- `create_observation(validated_data)`: predicts, creates the database row,
  and schedules the response agent only when prediction is `Yes`.
- `update_observation(observation, validated_data)`: merges updated fields with
  current model inputs, recomputes prediction, saves, and schedules follow-up
  for `Yes`.
- `_schedule_response_agent(observation)`: registers a transaction-commit
  callback.
- `_start_response_agent(observation_id)`: starts a daemon thread.
- `_run_response_agent(observation_id)`: runs the response function, logs
  errors, and prints its JSON result.
- `answer_safety_question(question)`: delegates to `rag.ask_rag`.

## Models and administration

See [Database Documentation](./Database_Documentation.md) for full fields.

- `LandslideObservation`: a site reading plus historical observed outcome and
  generated prediction/probability. Default table:
  `observations_landslideobservation`.
- `EmergencyAuthority`: a contact record managed in Django Admin. Table:
  `EmergencyAuthority`.
- `EmergencyAuthorityAdmin`: lists name, type, location ID, district, active,
  and verified status; provides filters and search.

There are no current `Location`, `Alert`, `LandslideResponseAlert`, or
`LandslideWorkflowEvent` model classes. Migrations 0003 and 0005 show alert
models were introduced and subsequently removed.

## Prediction and background response

`prediction.load_model` reads the joblib model once and checks its expected
feature names. `predict_landslide` performs prediction and probability
calculation. For `Yes`, the response-agent workflow is described in
[Email Notification Workflow](./Email_Notification_Workflow.md).

The thread is in-process and non-durable. The service result is not persisted
to an alert model and is not exposed as an API endpoint.

## Function and class reference for AI modules

### `prediction.py`

- `FEATURE_COLUMNS`, `ONE_HOT_FEATURE_COLUMNS`, and
  `SUPPORTED_MODEL_FEATURES`: allowed input column layouts for the fitted
  estimator.
- `MODEL_PATH`: path to `notebooks/landslide_logistic_pipeline.joblib`.
- `load_model()`: cached joblib loading plus a check that the model exposes a
  supported `feature_names_in_` schema. Raises `ImproperlyConfigured` if the
  artifact is missing or incompatible.
- `predict_landslide(observation)`: creates a one-row pandas frame from the
  validated observation fields, applies one-hot encoding if the estimator
  expects that layout, then returns prediction and probability.

### `rag.py`

- `RagConfigurationError`: missing or invalid required configuration, index,
  dimension, or namespace.
- `RagServiceError`: embedding, vector search, or generation failure.
- `_field(value, name, default)`: reads a key from a dictionary or an attribute
  from an SDK object.
- `_load_embedding_model()`: cached load of `intfloat/e5-base-v2`.
- `initialize_rag()`: loads the root `.env`, checks Pinecone credentials and
  index metadata, and returns the index, embedding model, and namespace. It
  connects to an existing index; it does not create/index the PDF.
- `retrieve_documents(question, top_k=TOP_K)`: embeds a non-empty query, asks
  Pinecone for top matches, and returns text/page/score dictionaries.
- `generate_answer(question, documents)`: returns a no-document response when
  no passages exist; otherwise asks Ollama for a page-cited answer grounded in
  the supplied excerpts.
- `ask_rag(question)`: public orchestration function returning an answer and
  source records.

### `response_agent.py`

- `ResponseAgentError`: represents a response-workflow failure.
- `NO_VERIFIED_GUIDANCE`: sentinel text used when RAG guidance is absent or
  unavailable.
- `retrieve_safety_measures(observation)`: queries `ask_rag` using the fixed
  landslide safety query and returns a status, answer, and sources. The
  observation parameter is not currently used to customize the query.
- `get_emergency_contact()`: returns the first authority ordered by name and
  ID as plain values, or `None` when no record exists.
- `send_emergency_email(observation, safety_result, emergency_contact,
  workflow_result=None)`: validates the address, formats a plain-text message,
  calls Django `send_mail`, and returns success/skipped/failed status data.
- `create_response_agent()`: configures an Ollama-backed CrewAI agent for
  summarization.
- `run_landslide_response_agent(observation_id)`: loads the saved observation,
  skips non-`Yes` predictions, sequences RAG and contact checks, runs one
  CrewAI summary task when checks pass, and then attempts email delivery.

### Model and admin classes

- `EmergencyAuthority.AuthorityType`: enumerates the allowed authority
  categories. `EmergencyAuthority.Meta` sets the database table and default
  ordering; `__str__` returns a readable name/location label.
- `LandslideObservation.VegetationCover` and
  `LandslideObservation.LandslideStatus`: define allowed values.
  `LandslideObservation.Meta` sets newest-first ordering; `__str__` formats the
  record identifier/location.
- `EmergencyAuthorityAdmin`: controls the authority list columns, filters,
  and search fields in Django Admin.
- `ObservationsConfig`: declares the Django app and default generated primary
  key type.

## Error behavior

- DRF serializer errors are returned as validation responses.
- Missing/incompatible prediction model is returned as HTTP 503 before an
  observation is created/updated.
- RAG configuration and operational errors are explicit service-unavailable
  responses for the user-operated safety assistant.
- Background response-agent failures are logged and do not undo a saved
  observation.

## Tests

`app/observations/tests.py` contains Django REST API tests, model prediction
tests, contact-selection/email tests, and checks for RAG-related behaviors.
Run with:

```powershell
python app\manage.py test observations
```

**Current source consistency note:** the test module imports
`create_chunks` and `load_pdf_pages` from `observations.rag` and `_tool_result`
from `observations.response_agent`, but those names are not defined in the
current runtime modules. Test discovery may therefore fail with an import
error. This documentation records that gap rather than claiming the full test
command passes.
