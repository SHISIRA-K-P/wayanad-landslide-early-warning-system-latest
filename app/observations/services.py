# ============================================================
# IMPORTS
# ============================================================

import json
import logging
import threading

from django.db import transaction

from .models import LandslideObservation
from .prediction import predict_landslide
from .rag import ask_rag
from .response_agent import ResponseAgentError, run_landslide_response_agent


# ============================================================
# CONFIGURATION
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
# RESPONSE-AGENT BACKGROUND TASK
# ============================================================

def _run_response_agent(observation_id):
    """Run and log response-agent results without blocking the API request."""
    try:
        result = run_landslide_response_agent(observation_id)
    except ResponseAgentError:
        logger.exception(
            'Response AI agent failed for observation %s.',
            observation_id,
        )
        return
    except Exception:
        logger.exception(
            'Unexpected response AI agent error for observation %s.',
            observation_id,
        )
        return

    print(
        'Landslide response agent result:\n'
        + json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


def _start_response_agent(observation_id):
    """Start the response agent after the observation transaction commits."""
    worker = threading.Thread(
        target=_run_response_agent,
        args=(observation_id,),
        daemon=True,
        name=f'landslide-response-agent-{observation_id}',
    )
    worker.start()


def _schedule_response_agent(observation):
    transaction.on_commit(
        lambda observation_id=observation.pk: _start_response_agent(
            observation_id
        )
    )


# ============================================================
# OBSERVATION WORKFLOW
# ============================================================

def get_observations():
    """Return observations in the model's existing newest-first order."""
    return LandslideObservation.objects.all()


def create_observation(validated_data):
    """Predict and save one validated observation, then schedule follow-up."""
    prediction = predict_landslide(validated_data)
    observation = LandslideObservation.objects.create(
        **validated_data,
        **prediction,
    )
    if observation.landslide_prediction == 'Yes':
        _schedule_response_agent(observation)
    return observation


def update_observation(observation, validated_data):
    """Update an observation and recalculate prediction using all current data."""
    prediction_data = {
        'max_temp_c': observation.max_temp_c,
        'humidity_pct': observation.humidity_pct,
        'wind_speed_kmh': observation.wind_speed_kmh,
        'rainfall_mm': observation.rainfall_mm,
        'slope_angle_deg': observation.slope_angle_deg,
        'vegetation_cover': observation.vegetation_cover,
    }
    prediction_data.update(validated_data)
    prediction = predict_landslide(prediction_data)

    for field, value in validated_data.items():
        setattr(observation, field, value)
    for field, value in prediction.items():
        setattr(observation, field, value)
    observation.save()

    if observation.landslide_prediction == 'Yes':
        _schedule_response_agent(observation)
    return observation


# ============================================================
# SAFETY-ASSISTANT WORKFLOW
# ============================================================

def answer_safety_question(question):
    """Return the existing RAG answer and source passages for a question."""
    return ask_rag(question)
