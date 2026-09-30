"""
Abstraction de l'appel au LLM.

Prototype P0 : fonctionne 100% hors-ligne avec des réponses gabarits (templates),
pour que tu puisses tester le raisonnement de l'agent sans dépendre d'une API/du réseau.

Upgrade P1 : dès que tu as une clé API (OpenAI Agents SDK, Anthropic, etc.),
remplace le corps de `generate_response()` par un vrai appel LLM qui reçoit
le contexte structuré (session + résultats des tools) et rédige une réponse
plus naturelle. Le reste de l'orchestrateur n'a pas besoin de changer :
c'est justement le but de cette couche d'abstraction.
"""
import os


def is_real_llm_configured() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))


def generate_response(intent: str, context: dict) -> str:
    """
    Génère la réponse texte finale à partir d'une intention et d'un contexte structuré.
    intent: identifiant de l'action décidée par l'orchestrateur (voir orchestrator.py)
    context: dictionnaire de données utiles (résultats des tools, session, etc.)
    """
    if is_real_llm_configured():
        # TODO (P1) : appeler ici le vrai LLM avec le contexte structuré.
        # Pour l'instant on retombe sur les templates même si une clé est présente,
        # tant que l'intégration réelle n'est pas branchée.
        pass

    return _template_response(intent, context)


def _template_response(intent: str, context: dict) -> str:
    templates = {
        "ask_age": "Bonjour ! Pour commencer, quel âge a votre enfant (en mois ou en années) ?",
        "ask_vaccines_received": (
            "Merci. Pouvez-vous me dire quels vaccins votre enfant a déjà reçus ? "
            "Vous pouvez répondre librement, par exemple : \"il a eu le BCG et le premier Penta\"."
        ),
        "safety_decline": context.get("response_hint", "Je ne peux pas répondre à cela."),
        "misconception_correction": (
            f"Je comprends l'inquiétude. En réalité : {context.get('correction')} "
            f"(source : {context.get('source')})"
        ),
        "vaccine_explanation": _format_vaccine_explanation(context.get("info")),
        "missing_summary": _format_missing(context.get("missing", [])),
        "no_missing": "D'après ce que vous m'avez indiqué, aucun vaccin ne semble en retard pour l'instant. Continuez à suivre le calendrier !",
        "hors_pev_info": _format_hors_pev(context.get("entries", [])),
        "unknown": "Je n'ai pas d'information fiable sur ce point précis dans ma base de connaissances actuelle, je préfère ne pas deviner.",
        "generic_ack": "Merci, c'est noté.",
    }
    return templates.get(intent, "Je n'ai pas compris, pouvez-vous reformuler ?")


def _format_vaccine_explanation(info):
    if not info:
        return "Je n'ai pas de fiche fiable pour ce vaccin dans ma base actuelle."
    lines = [f"{info['vaccine']} — {info['pev_status']}"]
    lines.append(f"Voie d'administration : {info['route']}")
    lines.append(f"Effets secondaires possibles : {', '.join(info['side_effects'])}")
    lines.append(f"Pourquoi c'est important : {info['why_it_matters']}")
    if info.get("confidence") != "confirmé":
        lines.append(f"(Note : {info.get('confidence')})")
    return "\n".join(lines)


def _format_missing(missing):
    if not missing:
        return "Aucun vaccin en retard détecté."
    lines = ["Voici ce qui semble à vérifier :"]
    for m in missing:
        lines.append(f"  - {m['vaccine']} (dû depuis : {m['due_since']})")
    lines.append("Je vous conseille de vérifier cela avec un centre de santé.")
    return "\n".join(lines)


def _format_hors_pev(entries):
    if not entries:
        return "Je n'ai pas d'information sur ce vaccin dans ma base actuelle."
    lines = []
    for e in entries:
        lines.append(f"{e['vaccine']} : {e['pev_status']}, à partir de {e['age_min_months']} mois. {e.get('note', '')}")
    return "\n".join(lines)
