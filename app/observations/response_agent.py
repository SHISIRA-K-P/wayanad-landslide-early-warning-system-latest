
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
    Get landslide guidance and its sources from the existing RAG system.

    An answer is considered usable only when the RAG system also returns
    source references. This prevents unsourced text from being treated as
    verified safety guidance.
    """
    query = (
        "LANDSLIDE Before & During precautions "
    )

    try:
        result = ask_rag(query)

        # The RAG helper may return text, a dictionary, or a tuple/list.
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

        # An empty answer means there is no guidance to share.
        if not answer or not str(answer).strip():
            return {
                "status": "unavailable",
                "answer": NO_VERIFIED_GUIDANCE,
                "sources": [],
            }

        # Never treat guidance as verified unless the RAG system cites sources.
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
    Return the first emergency authority, or None if the table is empty.

    Ordering by name and ID makes the selected contact predictable.
    """
    try:
        authority = (
            EmergencyAuthority.objects
            .order_by("authority_name", "id")
            .first()
        )

        if authority is None:
            return None

        # Return plain values so the rest of the workflow does not need
        # to work directly with a Django model instance.
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


# ============================================================
# EMAIL DELIVERY
# ============================================================


def send_emergency_email(
    observation,
    safety_result,
    emergency_contact,
    workflow_result=None,
):
    """
    Email source-backed safety guidance to the selected emergency contact.

    Missing or invalid addresses are skipped. SMTP errors and unsuccessful
    send counts are returned as failures rather than reported as success.
    """
    recipient = (emergency_contact.get("email") or "").strip()

    # Check the address before asking Django's mail backend to send anything.
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

    # Django's configured sender and SMTP settings control actual delivery.
    sender = getattr(settings, "DEFAULT_FROM_EMAIL", "")
    subject = f"Wayanad Landslide POC - Observation {observation.pk} Response Details"

    # Use the full workflow data when available, or create a small fallback
    # payload when this function is called on its own.
    email_payload = dict(workflow_result or {})
    if workflow_result is None:
        email_payload.update({
            "status": "completed",
            "observation_id": observation.pk,
            "observation": {
                "id": observation.pk,
                "location_id": getattr(observation, "location_id", None),
                "landslide_prediction": getattr(observation, "landslide_prediction", None),
                "landslide_probability": getattr(observation, "landslide_probability", None),
            },
            "safety_result": safety_result,
            "emergency_contact": emergency_contact,
        })

    displayed_contact = email_payload.get("emergency_contact") or emergency_contact
    displayed_safety = email_payload.get("safety_result") or safety_result

    def display(value):
        return "Not available" if value is None or value == "" else str(value)

    safety_answer = displayed_safety.get("answer") or displayed_safety.get("recommendation")

    # Keep the email body focused on the safety guidance and its recipient.
    message = (
        "Dear " + display(displayed_contact.get("authority_name")) + ",\n\n"
        "LANDSLIDE SAFETY GUIDANCE - WAYANAD\n\n"
        "The following safety guidance has been retrieved "
        "from the landslide safety knowledge base.\n\n"
        "SAFETY GUIDANCE\n\n"
        f"{display(safety_answer)}\n\n"
        "Please read and follow the above safety guidance carefully. "
        "For further assistance, contact the appropriate authorized "
        "disaster management authorities.\n\n"
        "Regards,\n"
        "Wayanad Landslide Early Warning and Response System\n\n"
    )

    try:
        sent_count = send_mail(
            subject=subject,
            message=message,
            from_email=sender,
            recipient_list=[recipient],
            fail_silently=False,
        )
        # Django returns the number of messages accepted by the backend.
        if sent_count != 1:
            logger.error(
                "Email backend sent %s messages for observation %s.",
                sent_count,
                observation.pk,
            )
            return {
                "status": "failed",
                "recipient": recipient,
                "subject": subject,
                "error": f"Email backend sent {sent_count} messages; expected 1.",
            }
        return {
            "status": "success",
            "recipient": recipient,
        }
    except Exception as exc:
        logger.exception("Email sending failed for observation %s", observation.pk)
        return {
            "status": "failed",
            "recipient": recipient,
            "subject": subject,
            "error": str(exc),
        }


# ---------------------------------------------------------
# CREWAI AGENT
# ---------------------------------------------------------

def create_response_agent():
    """
    Create a CrewAI assistant to summarize the workflow results.

    This agent only writes a summary; the Python code performs safety lookup,
    contact lookup, and email delivery.
    """
    model_name = os.getenv("OLLAMA_MODEL", OLLAMA_MODEL)
    base_url = os.getenv(
        "OLLAMA_BASE_URL",
        "http://localhost:11434",
    )

    # CrewAI connects to the configured local Ollama model.
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
    Handle one positive landslide prediction in a fixed order.

    The steps are: load the saved observation, retrieve sourced guidance,
    find a contact, summarize with CrewAI, and send the email. CrewAI does
    not decide whether these required Python steps happen.
    """
    try:
        observation = LandslideObservation.objects.get(
            pk=observation_id
        )
    except LandslideObservation.DoesNotExist as exc:
        raise ResponseAgentError(
            f"Observation {observation_id} was not found."
        ) from exc

    # Only a positive prediction starts the emergency response workflow.
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

    # Step 1: Retrieve guidance directly, without relying on the language model.
    safety_result = retrieve_safety_measures(observation)
    tools_called.append("retrieve_safety_measures")

    # Step 2: Find the emergency authority that will receive the email.
    emergency_contact = get_emergency_contact()
    tools_called.append("get_emergency_contact")

    # There is no recipient to email if the authority table has no contact.
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

    # Require human review if the guidance is missing or has no sources.
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

    # CrewAI provides a summary for the result; it does not run the workflow.
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

        # Run this single summary task in order, without delegation.
        crew = Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )

        summary = str(crew.kickoff())

    except Exception as exc:
        # A summary failure should not hide the guidance or stop email delivery.
        logger.exception("CrewAI summary generation failed")
        summary = (
            "CrewAI could not generate a summary. "
            f"Error: {exc}"
        )

    # Collect the observation fields used in the final workflow result.
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

    # Step 3: Send the message after safety guidance and contact are confirmed.
    email_result = send_emergency_email(
        observation=observation,
        safety_result=safety_result,
        emergency_contact=emergency_contact,
        workflow_result=workflow_result,
    )
    workflow_result["email_result"] = email_result
    return workflow_result