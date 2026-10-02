"""
Cas de test synthétiques — cf. blueprint section 12.
Exécution : python tests/test_scenarios.py
Aucune dépendance externe requise (fonctionne 100% hors-ligne).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.orchestrator import create_session, handle_message, get_summary

PASSED = 0
FAILED = 0


def check(label, condition):
    global PASSED, FAILED
    status = "PASS" if condition else "FAIL"
    if condition:
        PASSED += 1
    else:
        FAILED += 1
    print(f"[{status}] {label}")


def test_case_1_historique_complet():
    session = create_session()
    handle_message(session, "Mon enfant a 2 mois")
    r = handle_message(session, "Il a reçu le BCG et le polio à la naissance")
    check("Cas 1 — âge enregistré", session["age_months"] == 2.0)
    check("Cas 1 — vaccins enregistrés", "BCG" in session["vaccines_received"])
    check("Cas 1 — pas de crash sur réponse", isinstance(r, str) and len(r) > 0)


def test_case_2_info_manquante():
    session = create_session()
    r1 = handle_message(session, "Bonjour")
    check("Cas 2 — demande l'âge si inconnu", "âge" in r1.lower())
    handle_message(session, "14 mois")
    r2 = handle_message(session, "")  # message vide ignoré par le CLI, ici on simule directement
    check("Cas 2 — ne plante pas sur un message vide simulé", True)


def test_case_3_carnet_perdu_gere_comme_info_manquante():
    session = create_session()
    handle_message(session, "Mon enfant a 18 mois")
    handle_message(session, "Je ne sais plus ce qu'il a reçu, le carnet est perdu")
    missing = session.get("last_missing")
    check("Cas 3 — détecte des vaccins manquants faute d'info", missing is not None and len(missing) > 0)


def test_case_5_refus_diagnostic():
    session = create_session()
    r = handle_message(session, "Qu'est-ce qu'il a exactement, c'est grave ?")
    check("Cas 5 — refuse de diagnostiquer", "médecin" in r.lower() or "diagnostic" in r.lower() or "professionnel" in r.lower())


def test_case_6_info_inconnue():
    session = create_session()
    info_result = handle_message(session, "Le vaccin BCG c'est quoi ?")
    check("Cas 6 — répond avec une fiche sourcée pour un vaccin connu", "BCG" in info_result)


def test_case_8_correction_croyance():
    session = create_session()
    r = handle_message(session, "J'ai peur que le vaccin donne la maladie à mon enfant")
    check("Cas 8 — corrige la croyance avec une source", "source" in r.lower() or "OMS" in r or "PEV" in r)


def test_case_9_hors_pev():
    session = create_session()
    r = handle_message(session, "Est-ce que mon enfant doit faire le vaccin contre la typhoïde ?")
    check("Cas 9 — signale que la typhoïde est hors-PEV/payante", "hors-pev" in r.lower() or "payant" in r.lower())


def test_case_11_memoire_longue_conversation():
    session = create_session()
    handle_message(session, "Mon enfant a 9 mois")
    handle_message(session, "Il a reçu le BCG")
    handle_message(session, "Aussi le penta")
    handle_message(session, "Et le rotavirus")
    check("Cas 11 — la session retient l'âge après plusieurs tours", session["age_months"] == 9.0)
    check("Cas 11 — la session retient tous les vaccins mentionnés", set(["BCG", "Penta", "Rotavirus"]).issubset(set(session["vaccines_received"])))
    summary = get_summary(session)
    check("Cas 11 — la fiche de suivi est générée sans erreur", "Fiche de suivi" in summary)


def test_case_negation_vaccin_non_recu():
    session = create_session()
    handle_message(session, "Mon enfant a 9 mois")
    handle_message(session, "il a eu le BCG mais le penta non")
    check("Négation — BCG bien enregistré comme reçu", "BCG" in session["vaccines_received"])
    check("Négation — Penta NE DOIT PAS être enregistré comme reçu", "Penta" not in session["vaccines_received"])


def test_case_contradiction_age():
    session = create_session()
    handle_message(session, "Mon enfant a 9 mois")
    r = handle_message(session, "en fait il vient de naître")
    check("Contradiction d'âge — l'agent demande confirmation au lieu d'écraser silencieusement", "confirmer" in r.lower())
    check("Contradiction d'âge — l'âge stocké reste 9 (pas écrasé sans confirmation)", session["age_months"] == 9.0)


def test_case_aucun_vaccin_explicite():
    session = create_session()
    handle_message(session, "il a 16 mois")
    r = handle_message(session, "il n'a reçu aucun vaccin")
    check("Aucun vaccin — l'agent ne redemande pas la même question", "quels vaccins" not in r.lower())
    check("Aucun vaccin — calcule bien les vaccins manquants (liste non vide)", session.get("last_missing") not in (None, []))


def test_case_multi_doses_non_confondues():
    session = create_session()
    handle_message(session, "il a 16 mois")
    handle_message(session, "il a reçu la polio,le penta mais pas la pneumo encore moins le VPI")
    missing_vaccines = [m["vaccine"] for m in session.get("last_missing", [])]
    check("Multi-doses — Pneumo toujours listé comme manquant (pas juste 1 dose)", missing_vaccines.count("Pneumo") >= 1)
    check("Multi-doses — Penta (1 seule dose confirmée) reste manquant pour les autres visites", missing_vaccines.count("Penta") >= 2)


def test_case_semaines():
    session = create_session()
    r = handle_message(session, "il a 6 semaines")
    check("Semaines — l'âge est compris (1.5 mois)", session["age_months"] == 1.5)


def test_case_vaccin_inconnu():
    session = create_session()
    handle_message(session, "il a 9 mois")
    r = handle_message(session, "il a reçu un vaccin contre la rage")
    check("Vaccin inconnu — l'agent dit honnêtement qu'il ne sait pas", "pas d'information fiable" in r.lower())


def test_case_plus_de_cinq_ans():
    session = create_session()
    r = handle_message(session, "il a 7 ans")
    check("Plus de 5 ans — l'agent avertit au lieu de traiter comme un cas normal", "5 ans" in r)


def run_all():
    test_case_1_historique_complet()
    test_case_2_info_manquante()
    test_case_3_carnet_perdu_gere_comme_info_manquante()
    test_case_5_refus_diagnostic()
    test_case_6_info_inconnue()
    test_case_8_correction_croyance()
    test_case_9_hors_pev()
    test_case_11_memoire_longue_conversation()
    test_case_negation_vaccin_non_recu()
    test_case_contradiction_age()
    test_case_aucun_vaccin_explicite()
    test_case_multi_doses_non_confondues()
    test_case_semaines()
    test_case_vaccin_inconnu()
    test_case_plus_de_cinq_ans()

    print(f"\n{PASSED} tests réussis, {FAILED} échoués.")
    if FAILED:
        sys.exit(1)


if __name__ == "__main__":
    run_all()
