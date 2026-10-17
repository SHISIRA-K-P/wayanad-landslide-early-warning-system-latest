import json
import logging
import threading

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import LandslideObservation
from .prediction import predict_landslide
from .rag import RagConfigurationError, RagServiceError, ask_rag
from .response_agent import ResponseAgentError, run_landslide_response_agent
from .serializers import (
    LandslideObservationSerializer,
    SafetyQuestionSerializer,
)


logger = logging.getLogger(__name__)


class PredictionModelUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'The landslide prediction model is not available.'
    default_code = 'prediction_model_unavailable'


class SafetyAssistantUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'The safety assistant is not available.'
    default_code = 'safety_assistant_unavailable'


def _run_response_agent(observation_id):
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
            {
                'observation_id': observation_id,
                'status': result.get('status'),
                'rag_retrieval': result.get('safety_result'),
                'emergency_contact': result.get('emergency_contact'),
                'email_status': result.get('email_result', {}).get('status'),
                'reason': result.get('reason'),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


def _start_response_agent(observation_id):
    worker = threading.Thread(
        target=_run_response_agent,
        args=(observation_id,),
        daemon=True,
        name=f'landslide-response-agent-{observation_id}',
    )
    worker.start()


class LandslideObservationViewSet(viewsets.ModelViewSet):
    queryset = LandslideObservation.objects.all()
    serializer_class = LandslideObservationSerializer

    def _predict(self, validated_data):
        try:
            return predict_landslide(validated_data)
        except ImproperlyConfigured as error:
            logger.exception('Could not load the landslide prediction model.')
            raise PredictionModelUnavailable(str(error)) from error

    def _schedule_response_agent(self, observation):
        transaction.on_commit(
            lambda observation_id=observation.pk: _start_response_agent(
                observation_id
            )
        )

    def perform_create(self, serializer):
        prediction = self._predict(serializer.validated_data)
        observation = serializer.save(**prediction)
        if observation.landslide_prediction == 'Yes':
            self._schedule_response_agent(observation)

    def perform_update(self, serializer):
        observation = {
            **serializer.instance.__dict__,
            **serializer.validated_data,
        }
        prediction = self._predict(observation)
        observation = serializer.save(**prediction)
        if observation.landslide_prediction == 'Yes':
            self._schedule_response_agent(observation)


class SafetyAssistantView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SafetyQuestionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = ask_rag(serializer.validated_data['question'])
        except RagConfigurationError as error:
            logger.error('Safety assistant configuration error: %s', error)
            raise SafetyAssistantUnavailable(
                detail=str(error),
                code='safety_assistant_not_configured',
            ) from error
        except RagServiceError as error:
            logger.exception('Safety assistant service is unavailable.')
            raise SafetyAssistantUnavailable(
                detail=str(error),
                code='safety_assistant_unavailable',
            ) from error

        return Response(result, status=status.HTTP_200_OK)
