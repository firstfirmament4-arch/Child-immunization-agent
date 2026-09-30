"""
Extraction d'informations à partir du message du parent.

⚠️ Prototype : extraction par règles/regex (fonctionne hors-ligne, sans API).
Upgrade prévu (P1) : remplacer par un vrai appel LLM avec tool-calling
(cf. agent/llm_client.py) pour une compréhension plus robuste et plus naturelle,
sans changer le reste de l'orchestrateur.
"""
import re

KNOWN_VACCINES = [
    "bcg", "polio", "vpo", "vpi", "penta", "pneumo", "rotavirus",
    "mosquirix", "paludisme", "rr", "rougeole", "rubéole", "rubeole",
    "vaa", "fièvre jaune", "fievre jaune",
]

VACCINE_CANONICAL = {
    "bcg": "BCG",
    "polio": "Polio (VPO)",
    "vpo": "Polio (VPO)",
    "vpi": "VPI",
    "penta": "Penta",
    "pneumo": "Pneumo",
    "rotavirus": "Rotavirus",
    "mosquirix": "Mosquirix",
    "paludisme": "Mosquirix",
    "rr": "RR (Rougeole-Rubéole)",
    "rougeole": "RR (Rougeole-Rubéole)",
    "rubéole": "RR (Rougeole-Rubéole)",
    "rubeole": "RR (Rougeole-Rubéole)",
    "vaa": "VAA (Fièvre jaune)",
    "fièvre jaune": "VAA (Fièvre jaune)",
    "fievre jaune": "VAA (Fièvre jaune)",
}


def extract_age_months(text: str):
    """Cherche une mention d'âge en mois ou en années. Retourne un float ou None."""
    text = text.lower()

    if re.search(r"vient de na[iî]tre|nouveau-n[ée]|nouveau ne|juste n[ée]", text):
        return 0.0

    match = re.search(r"(\d+)\s*semaine", text)
    if match:
        return float(match.group(1)) / 4.0  # cohérent avec le calendrier (6 sem. = 1.5 mois)

    match = re.search(r"(\d+)\s*mois", text)
    if match:
        return float(match.group(1))

    match = re.search(r"(\d+(?:[.,]\d+)?)\s*an", text)
    if match:
        years = float(match.group(1).replace(",", "."))
        return years * 12

    return None


NEGATION_PATTERN = re.compile(r"\b(non|pas|aucun|sans)\b")


def extract_vaccine_statuses(text: str) -> dict:
    """
    Découpe le message en clauses (séparées par "mais"/virgule) pour détecter,
    par vaccin mentionné, s'il a été reçu ou explicitement pas reçu.
    Ex: "il a eu le BCG mais le penta non" -> {"BCG": "received", "Penta": "not_received"}
    """
    clauses = re.split(r"\bmais\b|,", text.lower())
    statuses = {}
    for clause in clauses:
        vaccines_in_clause = extract_vaccine_mentions(clause)
        if not vaccines_in_clause:
            continue
        negative = bool(NEGATION_PATTERN.search(clause))
        for v in vaccines_in_clause:
            statuses[v] = "not_received" if negative else "received"
    return statuses


def extract_vaccine_mentions(text: str):
    """Retourne la liste des noms canoniques de vaccins mentionnés dans le texte."""
    text = text.lower()
    found = set()
    for keyword in KNOWN_VACCINES:
        if keyword in text:
            found.add(VACCINE_CANONICAL[keyword])
    return list(found)


def is_affirmative(text: str) -> bool:
    text = text.lower().strip()
    return text in {"oui", "yes", "ouais", "d'accord", "ok", "reçu", "il a reçu", "elle a reçu"}


def is_negative(text: str) -> bool:
    text = text.lower().strip()
    return text in {"non", "no", "pas reçu", "il n'a pas reçu", "elle n'a pas reçu", "aucun"}


UNKNOWN_VACCINE_PATTERN = __import__("re").compile(
    r"vaccin\s+(?:contre|de|pour)\s+(?:la|le|l')?\s*([a-zàâäéèêëïîôöùûüç\- ]{3,})"
)


def mentions_unknown_vaccine(text: str) -> bool:
    """Détecte une phrase du type 'vaccin contre X' où X n'est pas dans notre base connue."""
    text_lower = text.lower()
    match = UNKNOWN_VACCINE_PATTERN.search(text_lower)
    if not match:
        return False
    if extract_vaccine_mentions(text_lower):
        return False  # un vaccin connu est bien mentionné, ce n'est pas "inconnu"
    return True
