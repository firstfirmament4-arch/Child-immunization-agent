"""
Boîte à outils exposée au LLM via function-calling.

Principe : le LLM ne connaît AUCUNE info vaccinale par lui-même.
Toute donnée factuelle passe obligatoirement par ces fonctions, qui lisent
les fichiers sources JSON dans knowledge/. Le system prompt (voir llm_agent.py)
le rappelle explicitement au modèle.
"""
from tools.knowledge_tools import (
    explain_vaccine_info,
    search_hors_pev,
    correct_misconception,
    find_missing_vaccines,
)
from tools.session_tools import set_age, add_vaccine, generate_followup_summary


class AgentToolbox:
    """Chaque instance est liée à UNE session (anonyme, en mémoire)."""

    def __init__(self, session: dict):
        self.session = session

    def record_child_age(self, age_months: float) -> dict:
        set_age(self.session, age_months)
        if age_months > 60:
            return {
                "status": "ok",
                "age_months": age_months,
                "warning": (
                    "Enfant de plus de 5 ans : le rattrapage de plusieurs vaccins PEV n'est "
                    "généralement plus possible. Recommande explicitement une vérification en "
                    "centre de santé plutôt que de traiter ce cas comme un suivi normal."
                ),
            }
        return {"status": "ok", "age_months": age_months}

    def record_vaccine_dose(self, vaccine_name: str, received: bool = True) -> dict:
        if received:
            add_vaccine(self.session, vaccine_name)
            return {"status": "ok", "vaccine": vaccine_name, "recorded_as": "reçu"}
        return {"status": "ok", "vaccine": vaccine_name, "recorded_as": "non reçu (rien à enregistrer)"}

    def get_missing_vaccines(self) -> dict:
        if self.session.get("age_months") is None:
            return {"error": "âge de l'enfant inconnu — demande d'abord l'âge avant d'appeler cet outil"}
        missing = find_missing_vaccines(self.session["age_months"], self.session["vaccines_received"])
        self.session["last_missing"] = missing
        return {"missing": missing, "age_months": self.session["age_months"]}

    def get_vaccine_info(self, vaccine_name: str) -> dict:
        info = explain_vaccine_info(vaccine_name)
        if info is None:
            return {"found": False, "note": "vaccin absent de la base de connaissances — ne pas inventer, le dire au parent"}
        return {"found": True, **info}

    def get_hors_pev_info(self, vaccine_name: str) -> dict:
        entries = search_hors_pev(vaccine_name)
        if not entries:
            return {"found": False}
        return {"found": True, "entries": entries}

    def check_misconception(self, claim: str) -> dict:
        result = correct_misconception(claim)
        if result is None:
            return {"found": False}
        return {"found": True, **result}

    def generate_summary(self) -> dict:
        """Fiche de suivi textuelle, anonyme, pour le parent (pas pour le professionnel — pas de PII)."""
        missing = self.session.get("last_missing")
        if missing is None and self.session.get("age_months") is not None:
            missing = find_missing_vaccines(self.session["age_months"], self.session["vaccines_received"])
        summary_text = generate_followup_summary(self.session, missing or [], self.session.get("language", "fr"))
        return {"summary": summary_text}


TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "record_child_age",
            "description": "Enregistre l'âge de l'enfant (en mois) dès qu'il est mentionné ou déduit du message du parent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "age_months": {"type": "number", "description": "Âge de l'enfant en mois (convertir ans/semaines en mois)."}
                },
                "required": ["age_months"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_vaccine_dose",
            "description": "Enregistre qu'un vaccin précis a été reçu ou explicitement pas reçu par l'enfant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vaccine_name": {"type": "string", "description": "Nom du vaccin, ex: BCG, Penta, Polio (VPO), Pneumo, Rotavirus, VPI, Mosquirix, RR (Rougeole-Rubéole), VAA (Fièvre jaune)."},
                    "received": {"type": "boolean", "description": "true si reçu, false si explicitement pas reçu."},
                },
                "required": ["vaccine_name", "received"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_missing_vaccines",
            "description": "Calcule les vaccins dus mais non confirmés reçus, selon l'âge et les doses déjà enregistrées pour cette session. Appelle ceci avant d'annoncer un retard ou de faire un résumé.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_vaccine_info",
            "description": "Retourne la fiche officielle d'un vaccin du PEV (voie d'administration, effets secondaires, importance). Utilise ceci avant de répondre à toute question sur un vaccin précis — ne réponds jamais de mémoire.",
            "parameters": {
                "type": "object",
                "properties": {"vaccine_name": {"type": "string"}},
                "required": ["vaccine_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_hors_pev_info",
            "description": "Retourne les infos sur un vaccin optionnel/payant hors-PEV (typhoïde, méningite ACWY135, hépatite A, grippe).",
            "parameters": {
                "type": "object",
                "properties": {"vaccine_name": {"type": "string"}},
                "required": ["vaccine_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_misconception",
            "description": "Vérifie si l'affirmation du parent correspond à une croyance connue et fournit la correction sourcée officielle. Appelle ceci avant de corriger toi-même une croyance.",
            "parameters": {
                "type": "object",
                "properties": {"claim": {"type": "string", "description": "L'affirmation du parent, telle quelle."}},
                "required": ["claim"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_summary",
            "description": "Génère une fiche de suivi vaccinal textuelle pour le parent (âge, vaccins reçus, vaccins à vérifier). Appelle ceci quand le parent demande un résumé, ou spontanément une fois que tu as recueilli assez d'informations (âge + au moins une réponse sur les vaccins).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

TOOL_DISPATCH = {
    "record_child_age": "record_child_age",
    "record_vaccine_dose": "record_vaccine_dose",
    "get_missing_vaccines": "get_missing_vaccines",
    "get_vaccine_info": "get_vaccine_info",
    "get_hors_pev_info": "get_hors_pev_info",
    "check_misconception": "check_misconception",
}
