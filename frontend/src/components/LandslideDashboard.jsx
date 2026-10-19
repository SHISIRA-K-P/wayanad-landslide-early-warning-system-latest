import { useCallback, useRef, useState } from 'react'
import './LandslideDashboard.css'

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
).replace(/\/$/, '')
const OBSERVATIONS_URL = `${API_BASE_URL}/api/observations/`
const SAFETY_ASSISTANT_URL = `${API_BASE_URL}/api/safety-assistant/`

const INITIAL_FORM = {
  location_id: '',
  max_temp_c: '',
  humidity_pct: '',
  wind_speed_kmh: '',
  rainfall_mm: '',
  slope_angle_deg: '',
  vegetation_cover: '',
}

function getErrorMessage(data) {
  if (typeof data === 'string') return data
  if (data && typeof data === 'object') {
    if (typeof data.detail === 'string') return data.detail
    return Object.entries(data)
      .map(([field, messages]) => {
        const text = Array.isArray(messages) ? messages.join(' ') : String(messages)
        return `${field === 'non_field_errors' ? 'Error' : field}: ${text}`
      })
      .join(' ')
  }
  return 'The request failed. Please try again.'
}

function formatTimestamp(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

async function fetchObservations() {
  const response = await fetch(OBSERVATIONS_URL)
  if (!response.ok) {
    throw new Error(`Could not load observations (HTTP ${response.status}).`)
  }
  const data = await response.json()
  if (!Array.isArray(data)) {
    throw new Error('The observations API returned an unexpected response.')
  }
  return data
}

function LandslideDashboard() {
  const [form, setForm] = useState(INITIAL_FORM)
  const [observations, setObservations] = useState([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [submitError, setSubmitError] = useState('')
  const [predictionError, setPredictionError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [page, setPage] = useState('new')
  const [editingId, setEditingId] = useState(null)
  const [predictionResult, setPredictionResult] = useState(null)
  const [deletingId, setDeletingId] = useState(null)
  const [safetyQuestion, setSafetyQuestion] = useState('')
  const [safetyAnswer, setSafetyAnswer] = useState(null)
  const [safetyError, setSafetyError] = useState('')
  const [safetyLoading, setSafetyLoading] = useState(false)
  const submissionInFlight = useRef(false)

  const loadObservations = useCallback(async () => {
    try {
      setObservations(await fetchObservations())
      setLoadError('')
    } catch (error) {
      setLoadError(error.message || 'Could not connect to the observations API.')
    } finally {
      setLoading(false)
    }
  }, [])

  function refreshObservations() {
    setLoading(true)
    setLoadError('')
    loadObservations()
  }

  function handleChange(event) {
    const { name, value } = event.target
    setForm((currentForm) => ({ ...currentForm, [name]: value }))
    setPredictionResult(null)
    setPredictionError('')
    setSuccessMessage('')
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (submissionInFlight.current) return
    submissionInFlight.current = true
    setSubmitError('')
    setPredictionError('')
    setSuccessMessage('')
    setSubmitting(true)

    const payload = {
      Location_ID: Number(form.location_id),
      Max_Temp_C: Number(form.max_temp_c),
      Humidity_Pct: Number(form.humidity_pct),
      Wind_Speed_kmh: Number(form.wind_speed_kmh),
      Rainfall_mm: Number(form.rainfall_mm),
      Slope_Angle_Deg: Number(form.slope_angle_deg),
      Vegetation_Cover: form.vegetation_cover,
    }

    try {
      const url = editingId
        ? `${OBSERVATIONS_URL}${editingId}/`
        : OBSERVATIONS_URL
      const response = await fetch(url, {
        method: editingId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const responseData = await response.json().catch(() => null)

      if (!response.ok) {
        const error = new Error(getErrorMessage(responseData))
        error.status = response.status
        error.code = responseData?.code
        throw error
      }

      setPredictionResult(responseData)
      setForm(INITIAL_FORM)
      setEditingId(null)
      setSuccessMessage(`Observation #${responseData.id} saved successfully.`)
      setObservations((current) =>
        editingId
          ? current.map((observation) =>
              observation.id === responseData.id ? responseData : observation,
            )
          : [
              responseData,
              ...current.filter((observation) => observation.id !== responseData.id),
            ],
      )
      if (responseData.landslide_prediction == null) {
        setPredictionError(
          `Observation #${responseData.id} was saved, but the API did not return a prediction.`,
        )
      }
    } catch (error) {
      if (error.code === 'prediction_model_unavailable' || error.status === 503) {
        setPredictionError(
          `Prediction failed before the observation could be saved: ${error.message}`,
        )
      } else {
        setSubmitError(`Could not save the observation: ${error.message}`)
      }
    } finally {
      submissionInFlight.current = false
      setSubmitting(false)
    }
  }

  function startEditing(observation) {
    setForm({
      location_id: String(observation.location_id),
      max_temp_c: String(observation.max_temp_c),
      humidity_pct: String(observation.humidity_pct),
      wind_speed_kmh: String(observation.wind_speed_kmh),
      rainfall_mm: String(observation.rainfall_mm),
      slope_angle_deg: String(observation.slope_angle_deg),
      vegetation_cover: observation.vegetation_cover,
    })
    setEditingId(observation.id)
    setSubmitError('')
    setPredictionError('')
    setSuccessMessage('')
    setPredictionResult(null)
    setPage('new')
  }

  function startNewObservation() {
    setForm(INITIAL_FORM)
    setEditingId(null)
    setSubmitError('')
    setPredictionError('')
    setSuccessMessage('')
    setPredictionResult(null)
    setPage('new')
  }

  function returnToObservationForm() {
    if (page === 'records') {
      setForm(INITIAL_FORM)
      setEditingId(null)
      setSubmitError('')
      setPredictionError('')
      setSuccessMessage('')
      setPredictionResult(null)
      setSafetyQuestion('')
      setSafetyAnswer(null)
      setSafetyError('')
    }
    setPage('new')
  }

  async function deleteObservation(observation) {
    if (!window.confirm(`Delete observation #${observation.id}? This cannot be undone.`)) {
      return
    }

    setDeletingId(observation.id)
    setLoadError('')
    setSuccessMessage('')
    try {
      const response = await fetch(`${OBSERVATIONS_URL}${observation.id}/`, {
        method: 'DELETE',
      })
      if (!response.ok) {
        throw new Error(`Could not delete observation (HTTP ${response.status}).`)
      }
      setSuccessMessage(`Observation #${observation.id} was deleted.`)
      await loadObservations()
    } catch (error) {
      setLoadError(error.message || 'Could not delete the observation.')
    } finally {
      setDeletingId(null)
    }
  }

  async function askSafetyAssistant(event) {
    event.preventDefault()
    setSafetyError('')
    setSafetyAnswer(null)
    setSafetyLoading(true)

    try {
      const response = await fetch(SAFETY_ASSISTANT_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: safetyQuestion }),
      })
      const responseData = await response.json().catch(() => null)

      if (!response.ok) {
        throw new Error(getErrorMessage(responseData))
      }

      setSafetyAnswer(responseData)
    } catch (error) {
      setSafetyError(error.message || 'Could not contact the safety assistant.')
    } finally {
      setSafetyLoading(false)
    }
  }

  return (
    <main className="dashboard">
      <header className="dashboard-header">
        <div className="brand-mark" aria-hidden="true">W</div>
        <div>
          <p className="eyebrow">WAYANAD · FIELD MONITORING</p>
          <h1>Landslide observations</h1>
          <p className="header-description">
            Record daily site conditions and review submitted observations.
          </p>
        </div>
        <div className="connection-indicator">
          <span aria-hidden="true" />
          Observation API
        </div>
      </header>

      <nav className="page-nav" aria-label="Project pages">
        <button
          className={page === 'new' ? 'page-nav-button active' : 'page-nav-button'}
          type="button"
          onClick={returnToObservationForm}
        >
          New observation
        </button>
        <button
          className={page === 'records' ? 'page-nav-button active' : 'page-nav-button'}
          type="button"
          onClick={() => {
            setPage('records')
            setSuccessMessage('')
            refreshObservations()
          }}
        >
          All Records
        </button>
        <button
          className={page === 'safety' ? 'page-nav-button active' : 'page-nav-button'}
          type="button"
          onClick={() => {
            setPage('safety')
            setSuccessMessage('')
          }}
        >
          Safety assistant
        </button>
      </nav>

      {successMessage && <p className="message message-success" role="status">{successMessage}</p>}

      <section className="dashboard-grid">
        {page === 'new' && (
          <section className="panel form-panel" aria-labelledby="form-heading">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{editingId ? 'UPDATE RECORD' : 'NEW RECORD'}</p>
              <h2 id="form-heading">{editingId ? `Edit observation #${editingId}` : 'Daily site reading'}</h2>
            </div>
            <span className="panel-icon" aria-hidden="true">＋</span>
          </div>

          <form onSubmit={handleSubmit}>
            <div className="form-grid">
              <label className="field">
                <span>Location ID</span>
                <input name="location_id" type="number" min="1" step="1" value={form.location_id} onChange={handleChange} placeholder="e.g. 101" required />
              </label>
              <label className="field">
                <span>Maximum temperature <small>°C</small></span>
                <input name="max_temp_c" type="number" step="any" value={form.max_temp_c} onChange={handleChange} placeholder="28.5" required />
              </label>
              <label className="field">
                <span>Humidity <small>%</small></span>
                <input name="humidity_pct" type="number" min="0" max="100" step="any" value={form.humidity_pct} onChange={handleChange} placeholder="82" required />
              </label>
              <label className="field">
                <span>Wind speed <small>km/h</small></span>
                <input name="wind_speed_kmh" type="number" min="0" step="any" value={form.wind_speed_kmh} onChange={handleChange} placeholder="10" required />
              </label>
              <label className="field">
                <span>Rainfall <small>mm</small></span>
                <input name="rainfall_mm" type="number" min="0" step="any" value={form.rainfall_mm} onChange={handleChange} placeholder="35" required />
              </label>
              <label className="field">
                <span>Slope angle <small>degrees</small></span>
                <input name="slope_angle_deg" type="number" min="0" max="90" step="1" value={form.slope_angle_deg} onChange={handleChange} placeholder="32" required />
              </label>
              <label className="field">
                <span>Vegetation cover</span>
                <select name="vegetation_cover" value={form.vegetation_cover} onChange={handleChange} required>
                  <option value="" disabled>Select cover</option>
                  <option value="Low">Low</option>
                  <option value="Medium">Medium</option>
                  <option value="High">High</option>
                </select>
              </label>
            </div>

            {submitError && <p className="message message-error" role="alert">{submitError}</p>}
            {predictionError && <p className="message message-error" role="alert">{predictionError}</p>}
            <p className="prediction-note">
              Saving sends this reading to the existing Django API, which returns its model prediction with the saved record. This is a learning-project estimate, not a confirmed observation or an official warning.
            </p>

            <button className="submit-button" type="submit" disabled={submitting}>
              {submitting
                ? 'Saving & predicting…'
                : editingId
                  ? 'Update & Predict'
                  : 'Save & Predict'}
              {!submitting && <span aria-hidden="true">→</span>}
            </button>
            {editingId && (
              <button className="cancel-button" type="button" onClick={startNewObservation}>
                Cancel edit
              </button>
            )}
          </form>
          </section>
        )}

        {page === 'new' && predictionResult && (
          <section
            className={`panel prediction-result ${
              predictionResult.landslide_prediction === 'Yes'
                ? 'prediction-high'
                : predictionResult.landslide_prediction === 'No'
                  ? 'prediction-low'
                  : ''
            }`}
            aria-labelledby="prediction-heading"
            aria-live="polite"
          >
            <div className="panel-heading">
              <div>
                <p className="eyebrow">MODEL RESULT · OBSERVATION #{predictionResult.id}</p>
                <h2 id="prediction-heading">Landslide prediction</h2>
              </div>
              <span
                className={`status-pill ${
                  predictionResult.landslide_prediction === 'Yes'
                    ? 'status-yes'
                    : predictionResult.landslide_prediction === 'No'
                      ? 'status-no'
                      : 'status-unavailable'
                }`}
              >
                {predictionResult.landslide_prediction ?? 'Unavailable'}
              </span>
            </div>
            {predictionResult.landslide_probability == null ? (
              <p className="prediction-note">Probability was not included in the API response.</p>
            ) : (
              <p className="prediction-probability">
                Landslide probability
                <strong>{(predictionResult.landslide_probability * 100).toFixed(1)}%</strong>
              </p>
            )}
            <p className="prediction-note">
              This estimate is not an official warning. Follow local authorities and
              emergency services if you believe you are at risk.
            </p>
            <button
              className="text-button result-safety-button"
              type="button"
              onClick={() => {
                setSafetyQuestion(
                  `What safety steps should I take for observation #${predictionResult.id} at location ${predictionResult.location_id} with a ${predictionResult.landslide_prediction === 'Yes' ? 'positive' : 'negative'} landslide prediction?`,
                )
                setPage('safety')
              }}
            >
              Ask the safety guide about this result
            </button>
          </section>
        )}

        {page === 'records' && (
        <section className="panel records-panel" aria-labelledby="records-heading">
          <div className="panel-heading records-heading">
            <div>
              <p className="eyebrow">OBSERVATION LOG</p>
              <h2 id="records-heading">Saved records</h2>
            </div>
            <button className="refresh-button" type="button" onClick={refreshObservations} disabled={loading}>
              <span aria-hidden="true">↻</span> Refresh
            </button>
          </div>

          {loading ? (
            <div className="table-state" role="status">Loading observations…</div>
          ) : loadError ? (
            <div className="table-state table-error" role="alert">
              <p>{loadError}</p>
              <button className="text-button" type="button" onClick={refreshObservations}>Try again</button>
            </div>
          ) : observations.length === 0 ? (
            <div className="table-state">
              <span className="empty-icon" aria-hidden="true">⌁</span>
              <strong>No observations yet</strong>
              <span>Saved readings will appear here.</span>
            </div>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>ID / TIME</th><th>LOCATION</th><th>TEMP</th><th>HUMIDITY</th>
                    <th>WIND</th><th>RAINFALL</th><th>SLOPE</th><th>VEGETATION</th>
                    <th>PREDICTED LANDSLIDE</th><th>LANDSLIDE PROBABILITY</th><th>OBSERVED (HISTORY)</th><th>ACTIONS</th>
                  </tr>
                </thead>
                <tbody>
                  {observations.map((observation) => (
                    <tr key={observation.id}>
                      <td>
                        <strong>#{observation.id}</strong>
                        <span className="cell-subtext">{formatTimestamp(observation.created_at)}</span>
                      </td>
                      <td>{observation.location_id}</td>
                      <td>{observation.max_temp_c}°</td>
                      <td>{observation.humidity_pct}%</td>
                      <td>{observation.wind_speed_kmh} km/h</td>
                      <td>{observation.rainfall_mm} mm</td>
                      <td>{observation.slope_angle_deg}°</td>
                      <td>{observation.vegetation_cover}</td>
                      <td>
                        {observation.landslide_prediction ? (
                          <span className={`status-pill ${observation.landslide_prediction === 'Yes' ? 'status-yes' : 'status-no'}`}>
                            {observation.landslide_prediction}
                          </span>
                        ) : 'Not predicted'}
                      </td>
                      <td>{observation.landslide_probability == null ? '—' : `${(observation.landslide_probability * 100).toFixed(1)}%`}</td>
                      <td>{observation.landslide_observed || '—'}</td>
                      <td className="row-actions">
                        <button className="text-button" type="button" onClick={() => startEditing(observation)}>
                          Edit
                        </button>
                        <button
                          className="text-button delete-button"
                          type="button"
                          onClick={() => deleteObservation(observation)}
                          disabled={deletingId === observation.id}
                        >
                          {deletingId === observation.id ? 'Deleting…' : 'Delete'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!loading && !loadError && observations.length > 0 && (
            <p className="record-count">
              Showing {observations.length} {observations.length === 1 ? 'record' : 'records'} · newest first
            </p>
          )}
        </section>
        )}

        {page === 'safety' && (
          <section className="panel safety-panel" aria-labelledby="safety-heading">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">DOCUMENT-BASED HELP</p>
                <h2 id="safety-heading">Landslide safety assistant</h2>
              </div>
              <span className="panel-icon" aria-hidden="true">?</span>
            </div>

            <p className="safety-description">
              Ask a question about the project safety guide. Answers are generated from
              retrieved passages in Landslide_safety.pdf and include source pages.
            </p>
            <p className="prediction-note">
              For emergencies, follow local authorities and emergency services. This
              learning-project assistant is not an emergency service.
            </p>

            <form className="safety-form" onSubmit={askSafetyAssistant}>
              <label className="field" htmlFor="safety-question">
                <span>Your question</span>
                <textarea
                  id="safety-question"
                  value={safetyQuestion}
                  onChange={(event) => setSafetyQuestion(event.target.value)}
                  placeholder="What should I do if I hear rocks falling?"
                  maxLength={1000}
                  rows={4}
                  required
                />
              </label>
              {safetyError && <p className="message message-error" role="alert">{safetyError}</p>}
              <button className="submit-button" type="submit" disabled={safetyLoading}>
                {safetyLoading ? 'Searching the guide…' : 'Ask safety guide'}
              </button>
            </form>

            {safetyAnswer && (
              <section className="safety-answer" aria-live="polite">
                <h3>Answer</h3>
                <p className="safety-answer-text">{safetyAnswer.answer}</p>
                <h3>Sources from Landslide_safety.pdf</h3>
                {safetyAnswer.sources.length ? (
                  <ol className="safety-sources">
                    {safetyAnswer.sources.map((source, index) => (
                      <li key={`${source.page}-${index}`}>
                        <strong>Page {source.page}</strong>
                        <p>{source.text}</p>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="prediction-note">No matching passage was found.</p>
                )}
              </section>
            )}
          </section>
        )}
      </section>

      <footer className="dashboard-footer">
        <span>Wayanad Landslide Early Warning System</span>
        <span>Field observations · API-backed records</span>
      </footer>
    </main>
  )
}

export default LandslideDashboard
