# ============================================================
# IMPORTS
# ============================================================

import logging

from django.core.exceptions import ImproperlyConfigured
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .rag import RagConfigurationError, RagServiceError
from .serializers import (
    LandslideObservationSerializer,
    SafetyQuestionSerializer,
)
from .services import (
    answer_safety_question,
    create_observation,
    get_observations,
    update_observation,
)

# ============================================================
# CONFIGURATION
# ============================================================

logger = logging.getLogger(__name__)

# ============================================================
# API EXCEPTIONS
# ============================================================

class PredictionModelUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'The landslide prediction model is not available.'
    default_code = 'prediction_model_unavailable'


class SafetyAssistantUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'The safety assistant is not available.'
    default_code = 'safety_assistant_unavailable'


# ============================================================
# OBSERVATION API
# ============================================================

class LandslideObservationViewSet(viewsets.ModelViewSet):
    serializer_class = LandslideObservationSerializer

    def get_queryset(self):
        return get_observations()

    def perform_create(self, serializer):
        try:
            serializer.instance = create_observation(serializer.validated_data)
        except ImproperlyConfigured as error:
            logger.exception('Could not load the landslide prediction model.')
            raise PredictionModelUnavailable(str(error)) from error

    def perform_update(self, serializer):
        try:
            serializer.instance = update_observation(
                serializer.instance,
                serializer.validated_data,
            )
        except ImproperlyConfigured as error:
            logger.exception('Could not load the landslide prediction model.')
            raise PredictionModelUnavailable(str(error)) from error


# ============================================================
# SAFETY-ASSISTANT API
# ============================================================

class SafetyAssistantView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SafetyQuestionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = answer_safety_question(
                serializer.validated_data['question']
            )
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
