# ============================================================
# IMPORTS
# ============================================================

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import LandslideObservationViewSet, SafetyAssistantView


# ============================================================
# API URL PATTERNS
# ============================================================

router = DefaultRouter()
router.register(
    'observations',
    LandslideObservationViewSet,
    basename='observation',
)

urlpatterns = [
    path(
        'safety-assistant/',
        SafetyAssistantView.as_view(),
        name='safety-assistant',
    ),
    *router.urls,
]
