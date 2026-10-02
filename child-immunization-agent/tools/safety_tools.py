"""
Garde-fous de sécurité — cf. blueprint section 11.
Ces règles sont déterministes et volontairement simples pour le prototype :
mieux vaut un faux positif (l'agent est trop prudent) qu'un faux négatif.
"""

DIAGNOSIS_KEYWORDS = [
    "qu'est-ce qu'il a", "qu'est ce qu'il a", "il a quoi", "elle a quoi",
    "est-ce grave", "est ce grave", "c'est grave", "cest grave", "quelle maladie", "diagnostic",
    "c'est quoi sa maladie", "il est malade de quoi",
]

PRESCRIPTION_KEYWORDS = [
    "quel médicament", "que dois-je lui donner", "donne-moi un médicament",
    "prescris", "prescription", "quel traitement",
]

URGENT_KEYWORDS = [
    "convulsion", "ne respire plus", "inconscient", "très forte fièvre",
    "40 degrés", "40°", "ne se réveille pas",
]


def check_safety_flags(message: str) -> dict:
    """Détecte si le message sort du périmètre de l'agent ou signale une urgence potentielle."""
    text = message.lower()

    if any(k in text for k in URGENT_KEYWORDS):
        return {
            "flag": "potential_urgency",
            "action": "escalate",
            "response_hint": (
                "Ce que vous décrivez peut être sérieux. Je ne peux pas évaluer une urgence : "
                "rendez-vous immédiatement au centre de santé le plus proche ou appelez les secours."
            ),
        }

    if any(k in text for k in DIAGNOSIS_KEYWORDS):
        return {
            "flag": "diagnosis_request",
            "action": "explain_role_and_decline",
            "response_hint": (
                "Je ne peux pas poser de diagnostic — je ne suis pas médecin. "
                "Je peux vous aider à suivre et comprendre les vaccins de votre enfant. "
                "Pour un problème de santé, un professionnel de santé est la bonne ressource."
            ),
        }

    if any(k in text for k in PRESCRIPTION_KEYWORDS):
        return {
            "flag": "prescription_request",
            "action": "explain_role_and_decline",
            "response_hint": (
                "Je ne peux pas recommander de médicament ou de traitement. "
                "Je peux uniquement vous informer sur les vaccins et leur calendrier."
            ),
        }

    return {"flag": None, "action": None, "response_hint": None}
