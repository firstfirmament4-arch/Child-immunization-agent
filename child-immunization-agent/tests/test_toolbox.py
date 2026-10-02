"""
Teste AgentToolbox directement (sans appeler un LLM), pour vérifier que les
fonctions exposées au modèle produisent des données correctes.
Exécution : python tests/test_toolbox.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.toolbox import AgentToolbox
from tools.session_tools import new_session

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


def test_record_age_and_over_five_warning():
    session = new_session()
    tb = AgentToolbox(session)
    r1 = tb.record_child_age(9)
    check("Toolbox — âge normal, pas d'avertissement", "warning" not in r1)
    session2 = new_session()
    tb2 = AgentToolbox(session2)
    r2 = tb2.record_child_age(72)
    check("Toolbox — plus de 5 ans déclenche un avertissement", "warning" in r2)


def test_multi_dose_via_toolbox():
    session = new_session()
    tb = AgentToolbox(session)
    tb.record_child_age(16)
    tb.record_vaccine_dose("Penta", True)  # une seule dose confirmée sur 3 dues
    result = tb.get_missing_vaccines()
    penta_missing_count = sum(1 for m in result["missing"] if m["vaccine"] == "Penta")
    check("Toolbox — multi-doses cohérent (2 doses de Penta encore dues)", penta_missing_count == 2)


def test_unknown_vaccine_honesty():
    session = new_session()
    tb = AgentToolbox(session)
    result = tb.get_vaccine_info("rage")
    check("Toolbox — vaccin inconnu signalé honnêtement (found=False)", result["found"] is False)


def test_misconception_lookup():
    session = new_session()
    tb = AgentToolbox(session)
    result = tb.check_misconception("j'ai peur que le vaccin donne la maladie")
    check("Toolbox — croyance connue reconnue avec correction sourcée", result.get("found") and "source" in result)


def test_generate_summary_tool():
    session = new_session()
    tb = AgentToolbox(session)
    tb.record_child_age(9)
    tb.record_vaccine_dose("BCG", True)
    result = tb.generate_summary()
    check("Toolbox — generate_summary retourne une fiche cohérente", "Fiche de suivi" in result["summary"] and "BCG" in result["summary"])


def test_summary_bilingual():
    session = new_session()
    session["language"] = "en"
    tb = AgentToolbox(session)
    tb.record_child_age(8)
    tb.record_vaccine_dose("BCG", True)
    tb.get_missing_vaccines()
    en = tb.generate_summary()["summary"]
    check("Bilingue — fiche en anglais (titre, âge, échéances)", "follow-up sheet" in en and "weeks" in en and "semaines" not in en)
    session["language"] = "fr"
    fr = tb.generate_summary()["summary"]
    check("Bilingue — fiche en français", "Fiche de suivi" in fr and "semaines" in fr)


def test_history_trimming():
    from agent.llm_agent import _trim_history
    msgs = [{"role": "system", "content": "S"}]
    for i in range(10):
        msgs += [
            {"role": "user", "content": f"u{i}"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": f"c{i}"}]},
            {"role": "tool", "tool_call_id": f"c{i}", "content": "r"},
            {"role": "assistant", "content": f"a{i}"},
        ]
    trimmed = _trim_history(msgs, max_turns=3)
    users = [m["content"] for m in trimmed if m["role"] == "user"]
    check("Découpage — garde le prompt système", trimmed[0]["role"] == "system")
    check("Découpage — ne garde que les derniers échanges demandés", users == ["u7", "u8", "u9"])
    no_orphan = all(trimmed[i - 1]["role"] == "assistant" for i, m in enumerate(trimmed) if m["role"] == "tool")
    check("Découpage — aucun tool_call laissé orphelin", no_orphan)


def test_round_limit_fallback():
    import threading
    import http.server
    import os as _os
    from agent.llm_agent import create_llm_session, handle_message_llm

    state = {"n": 0}

    class LoopingH(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            state["n"] += 1
            if state["n"] == 1:
                msg = {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "a", "type": "function", "function": {"name": "record_child_age", "arguments": '{"age_months":4}'}}]}
            else:
                msg = {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "x", "type": "function", "function": {"name": "get_missing_vaccines", "arguments": "{}"}}]}
            body = json.dumps({"choices": [{"message": msg}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), LoopingH)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _os.environ["LLM_API_KEY"] = "k"
    _os.environ["LLM_BASE_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        s = create_llm_session("fr")
        r = handle_message_llm(s, "mon enfant a 4 mois")
        check("Repli round-limit — liste de vraies doses au lieu d'un message vide",
              "BCG" in r and "dû depuis" in r)
        check("Repli round-limit — pas de message 'reformulez' inutile", "reformuler" not in r.lower())
    finally:
        srv.shutdown()
        _os.environ.pop("LLM_API_KEY", None)
        _os.environ.pop("LLM_BASE_URL", None)


def test_multi_child():
    from agent.toolbox import AgentToolbox
    s = new_session(); s["language"] = "fr"
    tb = AgentToolbox(s)
    tb.record_child_age(9)
    tb.record_vaccine_dose("BCG", True)
    tb.get_missing_vaccines()
    archived = tb.start_new_child()
    check("Multi-enfants — archivage du premier enfant", archived["archived_children_count"] == 1)
    tb.record_child_age(18)
    tb.record_vaccine_dose("BCG", True)
    tb.record_vaccine_dose("Penta", True)
    tb.get_missing_vaccines()
    overview = tb.list_children()["children"]
    check("Multi-enfants — deux enfants distincts dans l'aperçu", len(overview) == 2 and overview[0]["age_months"] == 9 and overview[1]["age_months"] == 18)
    summary = tb.generate_summary()["summary"]
    check("Multi-enfants — la fiche contient les deux enfants séparément", "Enfant 1" in summary and "Enfant 2" in summary)
    check("Multi-enfants — pas de mélange des vaccins entre enfants", summary.count("Vaccins déjà reçus (déclarés) : BCG\n") >= 1 and "BCG, Penta" in summary)


def test_visible_reasoning_trace():
    import threading
    import http.server
    import os as _os
    from agent.llm_agent import create_llm_session, handle_message_llm

    state = {"n": 0}

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            state["n"] += 1
            if state["n"] == 1:
                msg = {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "a", "type": "function", "function": {"name": "record_child_age", "arguments": '{"age_months":9}'}}]}
            elif state["n"] == 2:
                msg = {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "b", "type": "function", "function": {"name": "get_missing_vaccines", "arguments": "{}"}}]}
            else:
                msg = {"role": "assistant", "content": "Voici ce qui semble à vérifier."}
            body = json.dumps({"choices": [{"message": msg}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _os.environ["LLM_API_KEY"] = "k"
    _os.environ["LLM_BASE_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        s = create_llm_session("fr")
        r = handle_message_llm(s, "mon enfant a 9 mois")
        check("Trace visible — la réponse commence par une trace de vérification", r.startswith("_🔍"))
        check("Trace visible — le texte final de l'agent est bien présent après la trace", "vérifier" in r)
        clean_history = all("🔍" not in (m.get("content") or "") for m in s["llm_messages"] if isinstance(m.get("content"), str))
        check("Trace visible — mémoire envoyée au modèle non polluée par la trace affichée", clean_history)
    finally:
        srv.shutdown()
        _os.environ.pop("LLM_API_KEY", None)
        _os.environ.pop("LLM_BASE_URL", None)


def run_all():
    test_record_age_and_over_five_warning()
    test_multi_dose_via_toolbox()
    test_unknown_vaccine_honesty()
    test_misconception_lookup()
    test_generate_summary_tool()
    test_summary_bilingual()
    test_history_trimming()
    test_round_limit_fallback()
    test_multi_child()
    test_visible_reasoning_trace()
    print(f"\n{PASSED} tests réussis, {FAILED} échoués.")
    if FAILED:
        sys.exit(1)


if __name__ == "__main__":
    run_all()
