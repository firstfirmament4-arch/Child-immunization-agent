"""
Orchestrateur — cœur de l'agent.

Boucle : sécurité d'abord → démystification → question directe sur un vaccin
→ vaccin hors-PEV → collecte d'info / calcul des vaccins manquants → réponse.

C'est ici que se joue le critère "agentique" du hackathon : l'agent ne se contente
pas de répondre, il décide de la prochaine action utile selon l'état de la session.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import nlu, llm_client
from tools.knowledge_tools import (
    explain_vaccine_info,
    search_hors_pev,
    correct_misconception,
    find_missing_vaccines,
)
from tools.safety_tools import check_safety_flags
from tools.session_tools import new_session, add_turn, set_age, add_vaccine, generate_followup_summary

VACCINE_QUESTION_MARKERS = [
    "c'est quoi", "qu'est-ce que", "qu est ce que", "effets secondaires",
    "comment on donne", "voie d'administration", "à quoi sert", "a quoi sert",
]

HORS_PEV_KEYWORDS = ["typhoïde", "typhoide", "méningite", "meningite", "hépatite a", "hepatite a", "grippe"]

UNCERTAIN_MARKERS = [
    "je ne sais plus", "je ne sais pas", "carnet perdu", "aucune idée",
    "je ne me souviens plus", "je ne suis pas sûr", "je ne suis pas sur", "je sais pas",
]

NO_VACCINE_MARKERS = [
    "aucun vaccin", "aucun", "rien reçu", "n'a rien reçu", "na rien reçu",
    "pas de vaccin", "zéro vaccin", "zero vaccin", "il n'a reçu aucun", "elle n'a reçu aucun",
]


def _is_uncertain(text: str) -> bool:
    text_lower = text.lower()
    return any(marker in text_lower for marker in UNCERTAIN_MARKERS)


def _is_explicit_none(text: str) -> bool:
    text_lower = text.lower()
    return any(marker in text_lower for marker in NO_VACCINE_MARKERS)


def create_session():
    return new_session()


def handle_message(session: dict, message: str) -> str:
    add_turn(session, "parent", message)
    text_lower = message.lower()

    # 1. Sécurité d'abord — priorité absolue
    safety = check_safety_flags(message)
    if safety["flag"]:
        response = llm_client.generate_response("safety_decline", {"response_hint": safety["response_hint"]})
        add_turn(session, "agent", response)
        return response

    # 2. Démystification si une croyance connue est détectée
    misconception = correct_misconception(message)
    if misconception:
        response = llm_client.generate_response("misconception_correction", misconception)
        add_turn(session, "agent", response)
        return response

    vaccines_mentioned = nlu.extract_vaccine_mentions(message)

    # 3. Question directe sur un vaccin du PEV ("le BCG, c'est quoi ?")
    if vaccines_mentioned and any(marker in text_lower for marker in VACCINE_QUESTION_MARKERS):
        info = explain_vaccine_info(vaccines_mentioned[0])
        response = llm_client.generate_response("vaccine_explanation", {"info": info})
        add_turn(session, "agent", response)
        return response

    # 4. Mention d'un vaccin hors-PEV
    for kw in HORS_PEV_KEYWORDS:
        if kw in text_lower:
            entries = search_hors_pev(kw)
            response = llm_client.generate_response("hors_pev_info", {"entries": entries})
            add_turn(session, "agent", response)
            return response

    # 4bis. Vaccin explicitement nommé mais absent de notre base — on le dit honnêtement
    if nlu.mentions_unknown_vaccine(message):
        response = llm_client.generate_response("unknown", {})
        add_turn(session, "agent", response)
        return response

    # 5. Collecte d'informations
    age = nlu.extract_age_months(message)
    if age is not None:
        if session["age_months"] is not None and abs(age - session["age_months"]) >= 1:
            response = (
                f"Vous m'aviez indiqué {session['age_months']} mois plus tôt, et là je comprends "
                f"{age} mois. Pouvez-vous confirmer l'âge exact de votre enfant avant qu'on continue ?"
            )
            add_turn(session, "agent", response)
            return response
        set_age(session, age)

        if age > 60 and not session["age_over_five_warned"]:
            session["age_over_five_warned"] = True
            response = (
                "Votre enfant a plus de 5 ans. Au-delà de cet âge, le rattrapage de plusieurs vaccins du PEV "
                "n'est généralement plus possible. Ce suivi est pensé pour les 0-5 ans : je vous recommande "
                "de faire le point directement avec un centre de santé plutôt que de vous fier uniquement à moi."
            )
            add_turn(session, "agent", response)
            return response

    vaccine_statuses = nlu.extract_vaccine_statuses(message)
    for v, status in vaccine_statuses.items():
        if status == "received":
            add_vaccine(session, v)

    if session["age_months"] is None:
        response = llm_client.generate_response("ask_age", {})
    elif (
        not vaccines_mentioned
        and not session["vaccines_received"]
        and not _is_uncertain(message)
        and not _is_explicit_none(message)
    ):
        response = llm_client.generate_response("ask_vaccines_received", {})
    else:
        missing = find_missing_vaccines(session["age_months"], session["vaccines_received"])
        session["last_missing"] = missing
        intent = "missing_summary" if missing else "no_missing"
        response = llm_client.generate_response(intent, {"missing": missing})
        if _is_uncertain(message) and missing:
            response += "\n\nComme vous n'êtes pas sûr(e) du carnet, je vous recommande de vérifier ces informations avec un centre de santé plutôt que de vous fier uniquement à ma réponse."

    add_turn(session, "agent", response)
    return response


def get_summary(session: dict) -> str:
    missing = session.get("last_missing")
    if missing is None and session.get("age_months") is not None:
        missing = find_missing_vaccines(session["age_months"], session["vaccines_received"])
    return generate_followup_summary(session, missing or [])
