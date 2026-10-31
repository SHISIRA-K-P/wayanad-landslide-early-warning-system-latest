# AI and Machine-Learning Documentation

This project has three distinct AI-related jobs:

1. **Classifier:** predicts a binary landslide outcome from a site reading.
2. **RAG assistant:** finds safety-guide passages and asks an LLM to answer
   using those passages.
3. **CrewAI response summary:** summarizes already collected workflow results
   in the positive-prediction background process.

These are not interchangeable. The classifier does not generate safety
instructions, and the RAG/LLM does not produce the stored binary prediction.

## Landslide prediction model

### Files

- Training and model exploration: `notebooks/land_slide_prediction.ipynb`.
- Saved artifact used at runtime:
  `notebooks/landslide_logistic_pipeline.joblib`.
- Runtime inference: `app/observations/prediction.py`.
- Model input is produced from `LandslideObservation` data by
  `services.create_observation` or `services.update_observation`.

The notebook `land_slide_prediction.ipynb` reads `data/land_slide.csv`,
removes missing rows, drops `Location_ID` from the feature matrix, converts
`Vegetation_Cover` to one-hot columns, and maps the `Landslide` target to 0/1.
It uses a stratified 80/20 train/test split, then fits a
`RandomForestClassifier` with 100 trees and `random_state=42`. The notebook
evaluates the test set and saves the fitted estimator with joblib.

The artifact's filename contains `logistic_pipeline`, but the notebook code
currently trains and saves a `RandomForestClassifier`, not logistic
regression. The filename should not be used to infer the estimator type. This
is a demonstration dataset/model, not evidence of operational validation.

### Features used in inference

`predict_landslide` consumes these six model fields:

| Model feature | Observation field | Meaning |
| --- | --- | --- |
| `Max_Temp_C` | `max_temp_c` | Maximum temperature in degrees Celsius. |
| `Humidity_Pct` | `humidity_pct` | Relative humidity percentage. |
| `Wind_Speed_kmh` | `wind_speed_kmh` | Wind speed in km/h. |
| `Rainfall_mm` | `rainfall_mm` | Rainfall in millimeters. |
| `Slope_Angle_Deg` | `slope_angle_deg` | Slope angle in degrees. |
| `Vegetation_Cover` | `vegetation_cover` | `Low`, `Medium`, or `High`. |

`location_id` identifies a site in the observation but is not passed to the
model. `landslide_observed` is historical/optional and is not an inference
feature.

### Runtime loading and inference

`MODEL_PATH` is built from Django's base directory and points to
`notebooks/landslide_logistic_pipeline.joblib`. `load_model`, decorated with
`lru_cache(maxsize=1)`, loads it once per process using `joblib.load`.

It rejects a missing model file and model feature schemas other than the two
supported tuples declared in `prediction.py`:

- raw six columns, including `Vegetation_Cover`; or
- a one-hot version with `Vegetation_Cover_High`, `_Low`, and `_Medium`.

For the one-hot schema, `predict_landslide` calls `pandas.get_dummies` and
reindexes to the exact expected feature columns. It then calls:

```python
prediction = int(model.predict(model_input)[0])
probability = model.predict_proba(model_input)[0, positive_class_index]
```

The integer result `1` becomes `"Yes"`; other results become `"No"`.
Probability is the model's class-1 probability rounded to four decimal places.
The output keys are `landslide_prediction` and `landslide_probability`.
There is no separately configured probability threshold or risk-level
classification.

## Retrieval-augmented generation (RAG)

### Index-building is an offline notebook task

`notebooks/Landslide_safety.pdf` is the knowledge document.
`notebooks/landslide_rag_index.ipynb` performs the preparation and upload:

1. Load the project's `.env` and read `PINECONE_API_KEY`.
2. Extract each PDF page's text with the PDF library.
3. Split text page-by-page into word chunks. The notebook's
   `create_chunks(text, chunk_size, overlap)` validates that the overlap is
   non-negative and smaller than chunk size; each chunk retains its source
   page.
4. Prefix each chunk with `passage:`, load `intfloat/e5-base-v2`, and encode
   the passages with normalized embeddings.
5. Create or reuse a Pinecone serverless index with 768 dimensions.
6. Upsert vectors in the `landslide-safety-v1` namespace, with page and text
   metadata.

The exact chunk and batch constants are defined in the notebook. Re-run the
notebook after changing the PDF or rebuilding the vector index. The runtime
service does not create or populate Pinecone.

### Runtime retrieval

`app/observations/rag.py` uses:

- Embedding model: `intfloat/e5-base-v2`
- Vector dimension: `768`
- Pinecone index: `wayanad-landslide-safety`
- Namespace: `landslide-safety-v1`
- Retrieval count: `TOP_K = 3`
- Default generation model: `qwen2.5:3b`

The call chain is:

```text
ask_rag(question)
  -> retrieve_documents(question)
       -> initialize_rag()
       -> embedding_model.encode("query: " + question)
       -> Pinecone index.query(top_k=3, include_metadata=True)
  -> generate_answer(question, documents)
       -> Ollama chat completion using retrieved excerpts
  -> {"answer": ..., "sources": [...]}
```

`initialize_rag` checks the API key, that the named index exists, that its
dimension is 768, and that the expected namespace has vectors. The embedding
model and RAG initialization are cached for the process. A question embedding
uses the `query:` prefix and normalized vectors. Returned source records include
the page, similarity score, and text.

### Ollama answer generation

`generate_answer` constructs a prompt with retrieved page excerpts and the
user question. It explicitly tells the model to answer only from the excerpts,
not to follow instructions in the excerpts, not to invent information, and to
cite pages. If there are no retrieved documents, it returns
`I could not find the answer in the document.` without asking the model.

The result is generated by `ollama.chat` using `OLLAMA_MODEL` if set, otherwise
the code default. `rag.py` catches known Ollama errors and raises
`RagServiceError`. RAG configuration/runtime problems are surfaced by the
safety API as HTTP 503.

## CrewAI response agent

`app/observations/response_agent.py` imports `Agent`, `Crew`, `LLM`, `Process`,
and `Task` from CrewAI. It is invoked only by the background workflow when the
saved observation prediction is `"Yes"`.

`create_response_agent` configures an Ollama-backed CrewAI `LLM`, then creates
an agent with a summarization role. `run_landslide_response_agent` first
retrieves sourced RAG guidance and the emergency contact with ordinary Python
functions. If those checks pass, it creates one `Task`, puts that task in a
sequential `Crew`, and calls `crew.kickoff()` to generate a summary.

**Important current-code distinction:** CrewAI is not performing the RAG,
database lookup, or email sending as agent tools. The Python function controls
these steps; CrewAI only summarizes supplied results. Summary failure is
logged and a fallback summary string is placed in the workflow result, after
which email processing continues.

## Safety and model limitations

- No threshold calibration, geographic validation, field sensor interface, or
  official approval process is present in the inference code.
- The stored probability should not be presented as a validated real-world
  risk percentage.
- RAG output is constrained by a prompt and sourced excerpts, but this does not
  guarantee factual correctness.
- A positive result initiates an email workflow only if sourced guidance and a
  usable contact are present.
- This is a learning prototype, not an officially validated warning system.
