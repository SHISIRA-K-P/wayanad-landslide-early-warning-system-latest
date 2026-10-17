
import logging
import os

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
):
    """
    Prepare an email preview by default.
    Send only if dry-run mode is explicitly disabled.
    """

    recipient = emergency_contact.get("email", "").strip()

    if not recipient:
        return {
            "status": "skipped",
            "reason": "The emergency contact has no email address.",
        }

    try:
        validate_email(recipient)
    except ValidationError:
        return {
            "status": "skipped",
            "reason": "The emergency contact email address is invalid.",
        }

    sender = getattr(settings, "DEFAULT_FROM_EMAIL", "")

    if not sender:
        return {
            "status": "skipped",
            "reason": "DEFAULT_FROM_EMAIL is not configured.",
        }

    prediction = getattr(observation, "landslide_prediction", "Unknown")
    probability = getattr(observation, "landslide_probability", None)

    safety_answer = safety_result.get("answer", NO_VERIFIED_GUIDANCE)
    safety_sources = safety_result.get("sources", [])

    subject = "Wayanad Landslide POC - Observation Review"

    message = (
        "Hello,\n\n"
        "This is a notification generated by the Wayanad Landslide "
        "Early Warning and Response System learning prototype.\n\n"
        "OBSERVATION DETAILS\n"
        f"Observation ID: {observation.pk}\n"
        f"Location ID: {getattr(observation, 'location_id', 'Unknown')}\n"
        f"Prediction: {prediction}\n"
        f"Model probability: {probability}\n"
        f"Rainfall: {getattr(observation, 'rainfall_mm', 'Unknown')} mm\n"
        f"Humidity: {getattr(observation, 'humidity_pct', 'Unknown')}%\n"
        f"Wind speed: {getattr(observation, 'wind_speed_kmh', 'Unknown')} km/h\n"
        f"Slope angle: {getattr(observation, 'slope_angle_deg', 'Unknown')} degrees\n\n"
        "SAFETY GUIDANCE\n"
        f"{safety_answer}\n\n"
        "SOURCE REFERENCES\n"
        f"{safety_sources}\n\n"
        "IMPORTANT DISCLAIMER\n"
        "This is a proof-of-concept notification, not an official warning. "
        "The prediction and AI-generated content must be reviewed by "
        "authorized personnel. Follow official instructions from disaster "
        "management authorities.\n"
    )

    # Safe default: do not send a real email during development.
    dry_run = getattr(settings, "LANDSLIDE_EMAIL_DRY_RUN", True)

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

    try:
        sent_count = send_mail(
            subject=subject,
            message=message,
            from_email=sender,
            recipient_list=[recipient],
            fail_silently=False,
        )

        if sent_count != 1:
            return {
                "status": "failed",
                "reason": "Django did not confirm that the email was sent.",
            }

        return {
            "status": "sent",
            "recipient": recipient,
        }

    except Exception as exc:
        logger.exception("Email sending failed for observation %s", observation.pk)
        return {
            "status": "failed",
            "reason": str(exc),
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
            "agent_tools_called": tools_called,
        }

    # Execute the third operation. It will preview the email by default.
    email_result = send_emergency_email(
        observation=observation,
        safety_result=safety_result,
        emergency_contact=emergency_contact,
    )
    tools_called.append("send_emergency_email")

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
                f"Email operation status: {email_result.get('status')}\n\n"
                "Use only the supplied information. Do not invent details. "
                "State clearly that this is a POC and not an official warning."
            ),
            expected_output=(
                "A concise summary of the observation, source-backed safety "
                "guidance, contact lookup, email operation status, and "
                "human-review requirement."
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

    return {
        "status": "completed",
        "observation_id": observation_id,
        "prediction": prediction,
        "safety_result": safety_result,
        "emergency_contact": emergency_contact,
        "email_result": email_result,
        "summary": summary,
        "agent_tools_called": tools_called,
    }
