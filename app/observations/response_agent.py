
import json
import logging
import os
import smtplib

from crewai import Agent, Crew, LLM, Process, Task
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import DatabaseError

from .models import EmergencyAuthority, LandslideObservation

from .rag import (
    OLLAMA_MODEL,
    RagConfigurationError,
    RagServiceError,
    ask_rag,
)


logger = logging.getLogger(__name__)

NO_VERIFIED_GUIDANCE = "NO_VERIFIED_GUIDANCE"


class ResponseAgentError(Exception):
    """Raised when the landslide response workflow fails."""


# ---------------------------------------------------------
# TOOL 1: Retrieve safety measures from the RAG system
# ---------------------------------------------------------

def retrieve_safety_measures(observation):
    """
    Retrieve landslide safety guidance from the existing RAG system.
    """

    query = (
        "Provide verified landslide safety precautions and response guidance "
        "for an observation with the following details: "
        f"Location: {getattr(observation, 'location_id', 'Unknown')}; "
        f"Rainfall: {getattr(observation, 'rainfall_mm', 'Unknown')} mm; "
        f"Humidity: {getattr(observation, 'humidity_pct', 'Unknown')}%; "
        f"Wind speed: {getattr(observation, 'wind_speed_kmh', 'Unknown')} km/h; "
        f"Slope angle: {getattr(observation, 'slope_angle_deg', 'Unknown')} degrees. "
        "Use only the supplied safety-document context. "
        "If relevant verified guidance is unavailable, say so explicitly."
    )

    try:
        result = ask_rag(query)

        # Support common RAG return formats.
        if isinstance(result, str):
            answer = result
            sources = []
        elif isinstance(result, dict):
            answer = (
                result.get("answer")
                or result.get("response")
                or result.get("result")
                or ""
            )
            sources = (
                result.get("sources")
                or result.get("source_documents")
                or []
            )
        elif isinstance(result, (tuple, list)):
            answer = result[0] if result else ""
            sources = result[1] if len(result) > 1 else []
        else:
            answer = ""
            sources = []

        if not answer or not str(answer).strip():
            return {
                "status": "unavailable",
                "answer": NO_VERIFIED_GUIDANCE,
                "sources": [],
            }

        # Do not claim that guidance is verified if no source was returned.
        if not sources:
            return {
                "status": "unverified",
                "answer": (
                    "The RAG system returned an answer, but no source "
                    "references were provided. Do not treat this answer "
                    "as verified guidance."
                ),
                "sources": [],
            }

        return {
            "status": "success",
            "answer": str(answer),
            "sources": sources,
        }

    except (RagConfigurationError, RagServiceError) as exc:
        logger.exception("RAG safety retrieval failed")
        return {
            "status": "error",
            "answer": NO_VERIFIED_GUIDANCE,
            "sources": [],
            "error": str(exc),
        }


# ---------------------------------------------------------
# TOOL 2: Retrieve an emergency contact from Django
# ---------------------------------------------------------

def get_emergency_contact():
    """
    Get an emergency authority from the database.
    """

    try:
        authority = (
            EmergencyAuthority.objects
            .order_by("authority_name", "id")
            .first()
        )

        if authority is None:
            return None

        return {
            "id": authority.id,
            "authority_name": authority.authority_name,
            "authority_type": authority.authority_type,
            "district": getattr(authority, "district", ""),
            "email": getattr(authority, "email", "") or "",
            "phone_number": getattr(authority, "phone_number", "") or "",
        }

    except DatabaseError as exc:
        logger.exception("Could not retrieve emergency contact")
        raise ResponseAgentError(
            "Could not retrieve an emergency contact from the database."
        ) from exc


# ---------------------------------------------------------
# TOOL 3: Prepare or send an emergency email
# ---------------------------------------------------------

def send_emergency_email(
    observation,
    safety_result,
    emergency_contact,
    workflow_result=None,
):
    """
    Prepare an email preview by default.
    Send only if dry-run mode is explicitly disabled.
    """

    recipient = (emergency_contact.get("email") or "").strip()

    if not recipient:
        logger.warning(
            "Email skipped for observation %s because the contact has no email.",
            observation.pk,
        )
        return {
            "status": "skipped",
            "reason": "The emergency contact has no email address.",
        }

    try:
        validate_email(recipient)
    except ValidationError:
        logger.warning(
            "Email skipped for observation %s because the contact email is invalid.",
            observation.pk,
        )
        return {
            "status": "skipped",
            "reason": "The emergency contact email address is invalid.",
        }

    # Safe default: do not send a real email during development.
    dry_run = getattr(settings, "LANDSLIDE_EMAIL_DRY_RUN", True)
    sender = getattr(settings, "DEFAULT_FROM_EMAIL", "")
    subject = (
        f"Wayanad Landslide POC - Observation {observation.pk} - "
        "Response Details"
    )
    email_payload = dict(workflow_result or {})
    if workflow_result is None:
        email_payload.update(
            {
                "status": "completed",
                "observation_id": observation.pk,
                "observation": {
                    "id": observation.pk,
                    "location_id": getattr(observation, "location_id", None),
                    "landslide_prediction": getattr(
                        observation,
                        "landslide_prediction",
                        None,
                    ),
                    "landslide_probability": getattr(
                        observation,
                        "landslide_probability",
                        None,
                    ),
                },
                "safety_result": safety_result,
                "emergency_contact": emergency_contact,
            }
        )
    email_status = {
        "status": "dry_run" if dry_run else "pending",
        "recipient": recipient,
        "subject": subject,
    }
    if dry_run:
        email_status["reason"] = (
            "Dry-run mode is enabled; no message was sent."
        )
    else:
        email_status["reason"] = (
            "Delivery status will be available after the mail backend responds."
        )
    email_payload["email_result"] = email_status

    displayed_contact = email_payload.get("emergency_contact") or emergency_contact
    displayed_safety = email_payload.get("safety_result") or safety_result



    def display(value):
        return "Not available" if value is None or value == "" else str(value)

    sources = (
        displayed_safety.get("sources")
        or displayed_safety.get("source_documents")
        or []
    )
    sources_text = json.dumps(
        sources,
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    safety_answer = (
        displayed_safety.get("answer")
        or displayed_safety.get("recommendation")
    )
    email_result = email_payload["email_result"]
    email_reason = email_result.get("reason")
    email_status_text = (
        f"Status: {email_result.get('status', 'Not available')}\n"
        f"Recipient: {display(recipient)}\n"
        f"Reason: {display(email_reason)}"
    )

    message = (
        "This message is generated by the Wayanad Landslide Early Warning "
        "and Response System learning prototype. It is not an official "
        "emergency warning.\n\n"
        "OBSERVATION AND WORKFLOW\n"
        f"Observation ID: {display(email_payload.get('observation_id', observation.pk))}\n"
        f"Workflow status: {display(email_payload.get('status'))}\n\n"
        "RAG SAFETY GUIDANCE\n"
        f"Retrieval status: {display(displayed_safety.get('status'))}\n"
        f"Answer: {display(safety_answer)}\n\n"
        "RETRIEVED SOURCE REFERENCES (all source fields)\n"
        f"{sources_text}\n\n"
        "EMERGENCY AUTHORITY\n"
        f"Name: {display(displayed_contact.get('authority_name'))}\n"
        f"Authority type: {display(displayed_contact.get('authority_type'))}\n"
        f"District: {display(displayed_contact.get('district'))}\n"
        f"Email: {display(displayed_contact.get('email'))}\n"
        f"Phone: {display(displayed_contact.get('phone_number'))}\n\n"
        "EMAIL OPERATION\n"
        f"{email_status_text}\n\n"
        "COMPLETE WORKFLOW RESPONSE (JSON)\n"
        f"{json.dumps(email_payload, ensure_ascii=False, indent=2, default=str)}\n\n"
        "IMPORTANT DISCLAIMER\n"
        "The prediction and AI-generated content must be reviewed by "
        "authorized personnel. Follow official instructions from disaster "
        "management authorities.\n"
    )

    if dry_run:
        logger.info(
            "Email dry-run for observation %s to %s",
            observation.pk,
            recipient,
        )
        return {
            "status": "dry_run",
            "recipient": recipient,
            "subject": subject,
            "message": message,
        }

    required_settings = {
    "EMAIL_BACKEND": settings.EMAIL_BACKEND,
    "EMAIL_HOST": settings.EMAIL_HOST,
    "EMAIL_HOST_USER": settings.EMAIL_HOST_USER,
    "EMAIL_HOST_PASSWORD": settings.EMAIL_HOST_PASSWORD,
    "DEFAULT_FROM_EMAIL": settings.DEFAULT_FROM_EMAIL,
}
    missing_settings = [
        name for name, value in required_settings.items() if not value
    ]
    if missing_settings:
        error = (
            "Email sending is enabled, but required settings are missing: "
            + ", ".join(missing_settings)
        )
        logger.error(
            "Email configuration is incomplete for observation %s: %s",
            observation.pk,
            ", ".join(missing_settings),
        )
        return {
            "status": "failed",
            "recipient": recipient,
            "subject": subject,
            "error": error,
        }

    if (
        settings.EMAIL_BACKEND
        != "django.core.mail.backends.smtp.EmailBackend"
    ):
        error = (
            "Email sending is enabled, but EMAIL_BACKEND is not Django's "
            "SMTP email backend."
        )
        logger.error(
            "Email backend is not SMTP for observation %s",
            observation.pk,
        )
        return {
            "status": "failed",
            "recipient": recipient,
            "subject": subject,
            "error": error,
        }

    if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
        error = "EMAIL_USE_TLS and EMAIL_USE_SSL cannot both be enabled."
        logger.error(
            "Conflicting SMTP TLS/SSL settings for observation %s",
            observation.pk,
        )
        return {
            "status": "failed",
            "recipient": recipient,
            "subject": subject,
            "error": error,
        }

    logger.info(
        "SMTP configuration for observation %s: backend=%s host=%s port=%s "
        "use_tls=%s use_ssl=%s username_configured=%s "
        "password_configured=%s",
        observation.pk,
        settings.EMAIL_BACKEND,
        settings.EMAIL_HOST,
        settings.EMAIL_PORT,
        settings.EMAIL_USE_TLS,
        settings.EMAIL_USE_SSL,
        bool(settings.EMAIL_HOST_USER),
        bool(settings.EMAIL_HOST_PASSWORD),
    )

    try:
        sent_count = send_mail(
            subject=subject,
            message=message,
            from_email=sender,
            recipient_list=[recipient],
            fail_silently=False,
        )

        if sent_count != 1:
            logger.error(
                "Email backend did not confirm delivery for observation %s "
                "(sent count: %s).",
                observation.pk,
                sent_count,
            )
            return {
                "status": "failed",
                "recipient": recipient,
                "subject": subject,
                "error": (
                    "Django did not confirm that the mail backend accepted "
                    "exactly one email."
                ),
            }

        return {
            "status": "success",
            "recipient": recipient,
        }

    except smtplib.SMTPAuthenticationError:
        logger.exception(
            "SMTP authentication failed for observation %s",
            observation.pk,
        )
        return {
            "status": "failed",
            "recipient": recipient,
            "subject": subject,
            "error": (
                "SMTP authentication was rejected. Verify EMAIL_HOST_USER "
                "and replace EMAIL_HOST_PASSWORD with a valid Google App "
                "Password, then restart Django."
            ),
        }

    except smtplib.SMTPServerDisconnected as exc:
        logger.exception(
            "SMTP server disconnected while sending observation %s",
            observation.pk,
        )
        return {
            "status": "failed",
            "recipient": recipient,
            "subject": subject,
            "error": (
                "The SMTP server closed the connection before Django "
                f"confirmed submission ({type(exc).__name__}: {exc}). "
                "Check that Django uses the same Gmail username and App "
                "Password as the successful standalone test, and that "
                "network access to smtp.gmail.com:587 is allowed."
            ),
        }

    except (smtplib.SMTPException, OSError, ImproperlyConfigured) as exc:
        logger.exception("Email sending failed for observation %s", observation.pk)
        return {
            "status": "failed",
            "recipient": recipient,
            "subject": subject,
            "error": f"{type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------
# CREWAI AGENT
# ---------------------------------------------------------

def create_response_agent():
    """
    Create the CrewAI agent for summarizing the response.
    """

    model_name = os.getenv("OLLAMA_MODEL", OLLAMA_MODEL)
    base_url = os.getenv(
        "OLLAMA_BASE_URL",
        "http://localhost:11434",
    )

    llm = LLM(
        model=f"ollama/{model_name}",
        base_url=base_url,
        temperature=0,
    )

    return Agent(
        role="Landslide Response Assistant",
        goal=(
            "Summarize observation results, retrieved safety guidance, "
            "and contact lookup results accurately."
        ),
        backstory=(
            "You assist a landslide-response proof of concept. "
            "Never invent safety guidance, contacts, or predictions. "
            "Never claim that an email was sent unless the backend confirms it. "
            "This system does not issue official public warnings."
        ),
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )


# ---------------------------------------------------------
# MAIN WORKFLOW
# ---------------------------------------------------------

def run_landslide_response_agent(observation_id):
    """
    Run the three required operations in a predictable order.
    CrewAI then summarizes the results.

    Email sending remains controlled by Django settings.
    """

    try:
        observation = LandslideObservation.objects.get(
            pk=observation_id
        )
    except LandslideObservation.DoesNotExist as exc:
        raise ResponseAgentError(
            f"Observation {observation_id} was not found."
        ) from exc

    # Do not initiate the response workflow for a negative prediction.
    prediction = getattr(observation, "landslide_prediction", None)

    if prediction != "Yes":
        return {
            "status": "skipped",
            "reason": "Prediction is not Yes.",
            "observation_id": observation_id,
            "email_result": {
                "status": "skipped",
                "reason": "Prediction is not Yes.",
            },
            "agent_tools_called": [],
        }

    tools_called = []

    # STEP 1: Call the Python function directly.
    # This does not depend on the LLM choosing a tool.
    safety_result = retrieve_safety_measures(observation)
    tools_called.append("retrieve_safety_measures")

    # STEP 2: Look up the contact directly.
    emergency_contact = get_emergency_contact()
    tools_called.append("get_emergency_contact")

    if emergency_contact is None:
        return {
            "status": "contact_not_found",
            "observation_id": observation_id,
            "safety_result": safety_result,
            "email_result": {
                "status": "skipped",
                "reason": "No emergency contact is available.",
            },
            "agent_tools_called": tools_called,
        }

    # STEP 3: Do not prepare/send an alert email when there is no
    # source-backed guidance. Require human review in that case.
    if safety_result.get("status") != "success":
        return {
            "status": "needs_human_review",
            "reason": "Verified safety guidance is unavailable.",
            "observation_id": observation_id,
            "safety_result": safety_result,
            "emergency_contact": emergency_contact,
            "email_result": {
                "status": "skipped",
                "reason": "Verified safety guidance is unavailable; human review is required.",
            },
            "agent_tools_called": tools_called,
        }

    # CrewAI summarizes the results; it does not control the
    # mandatory database, RAG, or email operations.
    try:
        agent = create_response_agent()

        task = Task(
            description=(
                "Summarize the following landslide POC workflow results.\n"
                f"Observation ID: {observation_id}\n"
                f"Prediction: {prediction}\n"
                f"Safety retrieval status: {safety_result.get('status')}\n"
                f"Safety guidance: {safety_result.get('answer')}\n"
                f"Sources: {safety_result.get('sources')}\n"
                f"Contact lookup: {emergency_contact}\n"
                "Email delivery will be handled after summary generation.\n\n"
                "Use only the supplied information. Do not invent details. "
                "State clearly that this is a POC and not an official warning."
            ),
            expected_output=(
                "A concise summary of the observation, source-backed safety "
                "guidance, contact lookup, and human-review requirement."
            ),
            agent=agent,
        )

        crew = Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )

        summary = str(crew.kickoff())

    except Exception as exc:
        # A summarization failure must not hide the results of the
        # operations already performed.
        logger.exception("CrewAI summary generation failed")
        summary = (
            "CrewAI could not generate a summary. "
            f"Error: {exc}"
        )

    observation_result = {
        "id": observation.pk,
        "location_id": observation.location_id,
        "max_temp_c": observation.max_temp_c,
        "humidity_pct": observation.humidity_pct,
        "wind_speed_kmh": observation.wind_speed_kmh,
        "rainfall_mm": observation.rainfall_mm,
        "slope_angle_deg": observation.slope_angle_deg,
        "vegetation_cover": observation.vegetation_cover,
        "landslide_observed": observation.landslide_observed,
        "landslide_prediction": prediction,
        "landslide_probability": observation.landslide_probability,
        "created_at": observation.created_at,
    }
    workflow_result = {
        "status": "completed",
        "observation_id": observation_id,
        "observation": observation_result,
        "prediction": prediction,
        "safety_result": safety_result,
        "emergency_contact": emergency_contact,
        "email_result": {"status": "pending"},
        "summary": summary,
        "agent_tools_called": [*tools_called, "send_emergency_email"],
    }

    # Email delivery is the third required operation and receives the entire
    # workflow payload. Its final status is only known after send_mail returns.
    email_result = send_emergency_email(
        observation=observation,
        safety_result=safety_result,
        emergency_contact=emergency_contact,
        workflow_result=workflow_result,
    )
    workflow_result["email_result"] = email_result
    return workflow_result