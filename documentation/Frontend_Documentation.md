# Frontend Documentation

The frontend is a React application built and served by Vite from `frontend/`.
Its main interface is one dashboard component with three local view states.

## Source structure

| File | Purpose |
| --- | --- |
| `frontend/index.html` | HTML document containing the React mount element. |
| `frontend/src/main.jsx` | Creates the React root, enables `StrictMode`, and renders `App`. |
| `frontend/src/App.jsx` | Renders `LandslideDashboard`. |
| `frontend/src/components/LandslideDashboard.jsx` | Form, records view, safety assistant, requests, and UI state. |
| `frontend/src/components/LandslideDashboard.css` | Dashboard-specific styles. |
| `frontend/src/App.css`, `frontend/src/index.css` | App-wide and base styles. |
| `frontend/vite.config.js` | Enables the Vite React plugin. |
| `frontend/package.json` | Dependencies and npm scripts. |

There are no separate React Router routes. `LandslideDashboard` uses state
`page` with values such as `new`, `records`, and `safety` to choose which
section is displayed.

## Views and behavior

### New observation

The form collects `location_id`, `max_temp_c`, `humidity_pct`,
`wind_speed_kmh`, `rainfall_mm`, `slope_angle_deg`, and `vegetation_cover`.
HTML input requirements provide basic client-side constraints; Django's
serializer and model validators also validate the data on the server.

`handleChange` updates form state and clears stale result/error messages.
`handleSubmit`:

1. Prevents the default submit action and avoids duplicate requests.
2. Converts numeric values to numbers.
3. Creates a JSON payload using dataset-style field names.
4. Sends `POST /api/observations/` for new records or `PUT
   /api/observations/{id}/` when editing.
5. Parses response JSON and converts HTTP errors into visible messages.
6. On success, stores the returned object in `predictionResult`, resets the
   form, and updates the local record list.

The prediction result panel displays the returned prediction, probability as a
percentage, and a note that the result is not an official warning. It offers a
button to prefill a question and switch to the safety assistant view.

The returned prediction/probability are produced in Django. React does not
execute the ML model.

### All Records

`fetchObservations` issues `GET /api/observations/` and verifies the result is
an array. `loadObservations` stores the records and controls loading/error
state. The table shows newest-first records and includes:

- Observation ID and creation time
- Site measurements
- Predicted outcome and probability
- Optional historical `landslide_observed`
- Edit and delete actions

`startEditing` copies values into the form; submitting an edit causes Django to
recalculate the prediction. `deleteObservation` asks for confirmation, sends a
DELETE request, and reloads the records.

This view is a data table, not an analytics dashboard with charts, a map, or
Power BI integration.

### Safety assistant

`askSafetyAssistant` sends a JSON POST to `/api/safety-assistant/` with the
user's question. It shows loading and error state; a successful answer displays
the answer and a list of returned source page numbers/text. It is a
user-initiated RAG interaction and is separate from the background workflow
triggered by a `"Yes"` prediction.

## API configuration

At the top of `LandslideDashboard.jsx`:

```js
const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
).replace(/\/$/, '')
```

The component builds:

- `POST /api/observations/` to create
- `GET /api/observations/` to list
- `PUT /api/observations/{id}/` to update
- `DELETE /api/observations/{id}/` to delete
- `POST /api/safety-assistant/` to ask the guide

The backend CORS allow-list defaults to Vite development origins
`http://localhost:5173` and `http://127.0.0.1:5173`, configurable with
`CORS_ALLOWED_ORIGINS`.

## API response and displayed result

The observation POST response contains the saved database fields plus
`landslide_prediction` and `landslide_probability`. `handleSubmit` stores that
object in `predictionResult`. The result section renders a colored Yes/No
status and formats the probability as a percentage.

React does not wait for or display the background response-agent workflow.
There is no endpoint in the current source to retrieve the CrewAI summary or
email status.

## Run and build

From `frontend/`:

```powershell
npm install
npm run dev
npm run build
npm run lint
```

See [Project Setup Guide](./Project_Setup_Guide.md) for backend and environment
setup.
