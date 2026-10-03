"""
Tools de consultation de la base de connaissances.
Règle du projet : aucune info vaccinale n'est générée par le LLM lui-même,
tout passe par ces fonctions qui lisent des fichiers sources JSON.
"""
import json
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"


def _load(filename):
    with open(KNOWLEDGE_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def search_pev_calendar(age_months: float | None = None):
    """Retourne les visites du calendrier PEV dues à un âge donné (ou tout le calendrier si None)."""
    calendar = _load("pev_calendar.json")
    if age_months is None:
        return calendar
    return [v for v in calendar if v["age_months"] <= age_months]


def explain_vaccine_info(vaccine_name: str):
    """Retourne la fiche détaillée d'un vaccin du PEV (route, effets secondaires, importance)."""
    info = _load("vaccine_info.json")
    # recherche insensible à la casse et aux accents simples
    for name, data in info.items():
        if vaccine_name.lower().strip() in name.lower():
            return {"vaccine": name, **data}
    return None


def search_hors_pev(vaccine_name: str | None = None):
    """Retourne les infos sur les vaccins hors PEV (payants, optionnels)."""
    hors_pev = _load("hors_pev.json")
    if vaccine_name is None:
        return hors_pev
    return [v for v in hors_pev if vaccine_name.lower() in v["vaccine"].lower()]


def correct_misconception(message: str):
    """Cherche si le message correspond à une croyance connue et retourne la correction sourcée."""
    misconceptions = _load("misconceptions.json")
    text = message.lower()
    for m in misconceptions:
        if any(trigger in text for trigger in m["triggers"]):
            return m
    return None


def get_other_interventions(age_months: float, language: str = "fr"):
    """
    Interventions non-vaccinales dues à cet âge (vitamine A, déparasitage, TPIn, MILDA),
    avec leur fiche d'info. Volontairement séparé du suivi des vaccins (pas de comptage de
    doses ici) : ce ne sont pas des vaccins, on ne les mélange jamais dans le même calcul.
    """
    lang_suffix = "_en" if language == "en" else ""
    info = _load("autres_interventions.json")
    visits = search_pev_calendar(age_months)
    seen = set()
    out = []
    for visit in visits:
        for name in visit.get("autres", []):
            if name in seen:
                continue
            seen.add(name)
            entry = info.get(name, {})
            out.append({
                "name": name,
                "label": entry.get(f"nom_complet{lang_suffix}") or entry.get("nom_complet") or name,
                "why_it_matters": entry.get(f"why_it_matters{lang_suffix}") or entry.get("why_it_matters"),
                "regional_note": entry.get(f"regional_note{lang_suffix}") or entry.get("regional_note") or "",
                "pev_status": entry.get(f"pev_status{lang_suffix}") or entry.get("pev_status"),
                "due_since": visit.get(f"age_label{lang_suffix}") or visit["age_label"],
            })
    return out


def find_missing_vaccines(age_months: float, vaccines_received: dict):
    """
    Compare l'âge de l'enfant aux doses confirmées par vaccin (comptage, pas juste oui/non),
    et retourne les doses dues et non couvertes, visite par visite, dans l'ordre chronologique.
    Ex: si Penta est dû 3 fois (6/10/14 sem.) et que 1 seule dose a été confirmée,
    2 occurrences restent manquantes — au lieu de considérer Penta comme "fait".

    Chaque entrée manquante inclut aussi disease_label/disease_label_en (lu depuis
    vaccine_info.json) : le LLM n'a ainsi jamais besoin de deviner à quoi sert un vaccin
    en listant les doses manquantes — l'info correcte est déjà dans le résultat de l'outil.
    """
    due = search_pev_calendar(age_months)
    vaccine_info = _load("vaccine_info.json")
    remaining = dict(vaccines_received)  # copie, ne pas modifier l'original
    missing = []
    for visit in due:
        for vaccine in visit["vaccines"]:
            if remaining.get(vaccine, 0) > 0:
                remaining[vaccine] -= 1
            else:
                entry = {
                    "vaccine": vaccine,
                    "due_since": visit["age_label"],
                    "due_since_en": visit.get("age_label_en", visit["age_label"]),
                }
                info = vaccine_info.get(vaccine)
                if info:
                    entry["disease_label"] = info.get("disease_label")
                    entry["disease_label_en"] = info.get("disease_label_en")
                missing.append(entry)
    return missing
