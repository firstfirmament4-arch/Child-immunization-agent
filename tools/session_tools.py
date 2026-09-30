"""
Session anonyme, en mémoire, sans identifiant nominatif.
Pour le prototype : stockage Python en RAM (perdu à la fermeture).
Pour le P1 : remplaçable par SQLite local, toujours sans nom/compte.
"""


def new_session():
    return {
        "age_months": None,
        "vaccines_received": {},   # {vaccine_name: nombre de doses confirmées}
        "history": [],       # liste de tours {role, text}
        "pending_question": None,
        "age_over_five_warned": False,
    }


def add_turn(session: dict, role: str, text: str):
    session["history"].append({"role": role, "text": text})


def set_age(session: dict, age_months: float):
    session["age_months"] = age_months


def add_vaccine(session: dict, vaccine_name: str):
    """Incrémente le nombre de doses confirmées pour ce vaccin (permet le suivi multi-doses)."""
    session["vaccines_received"][vaccine_name] = session["vaccines_received"].get(vaccine_name, 0) + 1


VACCINE_DISPLAY_EN = {
    "Polio (VPO)": "Polio (OPV)",
    "RR (Rougeole-Rubéole)": "MR (Measles-Rubella)",
    "VAA (Fièvre jaune)": "YF (Yellow fever)",
    "Penta": "Penta (DTP-HepB-Hib)",
    "Pneumo": "Pneumococcal (PCV)",
    "VPI": "IPV (injectable polio)",
}

SUMMARY_TEXT = {
    "fr": {
        "title": "=== Fiche de suivi vaccinal ===",
        "age": "Âge de l'enfant : {age} mois",
        "age_unknown": "Âge : non renseigné",
        "received": "Vaccins déjà reçus (déclarés) : {value}",
        "none": "aucun renseigné",
        "missing_header": "Vaccins à vérifier / possiblement en retard :",
        "missing_line": "  - {vaccine} (dû depuis : {due}){disease}",
        "no_missing": "Aucun retard détecté selon les informations données.",
        "disclaimer": "Ce résumé est basé uniquement sur les déclarations du parent et ne remplace pas une vérification par un professionnel de santé.",
    },
    "en": {
        "title": "=== Vaccination follow-up sheet ===",
        "age": "Child's age: {age} months",
        "age_unknown": "Age: not provided",
        "received": "Vaccines already received (declared): {value}",
        "none": "none provided",
        "missing_header": "Vaccines to check / possibly overdue:",
        "missing_line": "  - {vaccine} (due since: {due}){disease}",
        "no_missing": "No delay detected based on the information provided.",
        "disclaimer": "This summary is based only on the parent's statements and does not replace verification by a healthcare professional.",
    },
}


def generate_followup_summary(session: dict, missing: list[dict], language: str = "fr") -> str:
    """Fiche de suivi simple pour le parent (anonyme, pas de PII), en français ou en anglais."""
    lang = language if language in SUMMARY_TEXT else "fr"
    t = SUMMARY_TEXT[lang]

    def show(name: str) -> str:
        return VACCINE_DISPLAY_EN.get(name, name) if lang == "en" else name

    age = session.get("age_months")
    received = session.get("vaccines_received", {})
    received_display = ", ".join(
        f"{show(name)} (x{count})" if count > 1 else show(name) for name, count in received.items()
    )
    lines = [t["title"]]
    lines.append(t["age"].format(age=age) if age is not None else t["age_unknown"])
    lines.append(t["received"].format(value=received_display if received_display else t["none"]))
    if missing:
        lines.append(t["missing_header"])
        for m in missing:
            due = m.get("due_since_en", m["due_since"]) if lang == "en" else m["due_since"]
            disease = m.get("disease_label_en" if lang == "en" else "disease_label")
            disease_part = f" — {disease}" if disease else ""
            lines.append(t["missing_line"].format(vaccine=show(m["vaccine"]), due=due, disease=disease_part))
    else:
        lines.append(t["no_missing"])
    lines.append(t["disclaimer"])
    return "\n".join(lines)
