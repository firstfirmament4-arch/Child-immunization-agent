"""
Session anonyme, en mémoire, sans identifiant nominatif.
Pour le prototype : stockage Python en RAM (perdu à la fermeture).
Pour le P1 : remplaçable par SQLite local, toujours sans nom/compte.

Multi-enfants : les champs "age_months"/"vaccines_received" représentent toujours
l'ENFANT ACTIF (celui dont on parle en ce moment). Quand le parent passe à un autre
enfant, start_new_child() archive l'enfant actif dans "other_children" et réinitialise
les champs actifs. Résultat : tout le code déjà écrit et testé pour un seul enfant
continue de fonctionner sans aucun changement — le multi-enfants est une extension
additive, pas une réécriture.
"""


def new_session():
    return {
        "age_months": None,
        "vaccines_received": {},   # {vaccine_name: nombre de doses confirmées} — enfant actif
        "other_children": [],      # enfants déjà évoqués et archivés : [{age_months, vaccines_received, missing}]
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


def start_new_child(session: dict) -> dict:
    """
    Archive l'enfant actif (s'il y a une info le concernant) et repart de zéro pour
    un nouvel enfant. Les tools existants (record_child_age, get_missing_vaccines,
    generate_summary...) continuent de fonctionner tels quels sur ce nouvel enfant.
    """
    had_data = session.get("age_months") is not None or bool(session.get("vaccines_received"))
    if had_data:
        session.setdefault("other_children", []).append({
            "age_months": session.get("age_months"),
            "vaccines_received": dict(session.get("vaccines_received", {})),
            "missing": session.get("last_missing") or [],
        })
    session["age_months"] = None
    session["vaccines_received"] = {}
    session["last_missing"] = None
    session["age_over_five_warned"] = False
    return {"status": "ok", "archived_children_count": len(session.get("other_children", []))}


def list_children_overview(session: dict, language: str = "fr") -> list[dict]:
    """Aperçu de tous les enfants évoqués (archivés + l'enfant actif), pour list_children()."""
    children = list(session.get("other_children", []))
    if session.get("age_months") is not None or session.get("vaccines_received"):
        children = children + [{
            "age_months": session.get("age_months"),
            "vaccines_received": dict(session.get("vaccines_received", {})),
            "missing": session.get("last_missing") or [],
        }]
    overview = []
    for i, child in enumerate(children, start=1):
        overview.append({
            "child_number": i,
            "age_months": child.get("age_months"),
            "vaccines_received_count": sum(child.get("vaccines_received", {}).values()),
            "missing_count": len(child.get("missing") or []),
        })
    return overview


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
        "child_label": "--- Enfant {n} ---",
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
        "child_label": "--- Child {n} ---",
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


def _format_child_lines(age, received: dict, missing: list, t: dict, show) -> list:
    lines = []
    received_display = ", ".join(
        f"{show(name)} (x{count})" if count > 1 else show(name) for name, count in received.items()
    )
    lines.append(t["age"].format(age=age) if age is not None else t["age_unknown"])
    lines.append(t["received"].format(value=received_display if received_display else t["none"]))
    if missing:
        lines.append(t["missing_header"])
        for m in missing:
            due = m.get("due_since_en", m["due_since"]) if t is SUMMARY_TEXT["en"] else m["due_since"]
            disease = m.get("disease_label_en" if t is SUMMARY_TEXT["en"] else "disease_label")
            disease_part = f" — {disease}" if disease else ""
            lines.append(t["missing_line"].format(vaccine=show(m["vaccine"]), due=due, disease=disease_part))
    else:
        lines.append(t["no_missing"])
    return lines


def generate_followup_summary(session: dict, missing: list[dict], language: str = "fr") -> str:
    """
    Fiche de suivi pour le parent (anonyme, pas de PII), en français ou en anglais.
    S'il n'y a qu'un enfant (cas normal), le format est strictement identique à avant.
    S'il y en a plusieurs (start_new_child a été appelé), une section par enfant.
    """
    lang = language if language in SUMMARY_TEXT else "fr"
    t = SUMMARY_TEXT[lang]

    def show(name: str) -> str:
        return VACCINE_DISPLAY_EN.get(name, name) if lang == "en" else name

    other = session.get("other_children") or []
    lines = [t["title"]]

    if not other:
        # Chemin normal, un seul enfant — comportement inchangé par rapport à avant.
        lines += _format_child_lines(session.get("age_months"), session.get("vaccines_received", {}), missing, t, show)
    else:
        all_children = other + [{
            "age_months": session.get("age_months"),
            "vaccines_received": session.get("vaccines_received", {}),
            "missing": missing,
        }]
        for i, child in enumerate(all_children, start=1):
            lines.append(t["child_label"].format(n=i))
            lines += _format_child_lines(child.get("age_months"), child.get("vaccines_received", {}), child.get("missing") or [], t, show)

    lines.append(t["disclaimer"])
    return "\n".join(lines)
