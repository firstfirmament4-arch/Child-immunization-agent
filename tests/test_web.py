"""
Tests de bout en bout de la Web App, sans réseau externe.
Exécution : python tests/test_web.py
"""
import http.server
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

import server as web  # noqa: E402

PASSED = FAILED = 0


def check(label, cond):
    global PASSED, FAILED
    PASSED += bool(cond)
    FAILED += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {label}")


def call(base, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def serve(httpd):
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}"


def make_fake_llm():
    """Faux fournisseur : 1er appel -> tool_call record_child_age(8) ; 2e appel -> texte final."""
    state = {"calls": 0}

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["calls"] += 1
            state["last_system"] = payload["messages"][0]["content"]
            if state["calls"] == 1:
                msg = {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "record_child_age", "arguments": json.dumps({"age_months": 8})}}]}
            else:
                msg = {"role": "assistant", "content": "**OK** 8 months noted."}
            body = json.dumps({"choices": [{"message": msg}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    from http.server import HTTPServer
    return HTTPServer(("127.0.0.1", 0), H), state


def test_rules_mode():
    os.environ.pop("LLM_API_KEY", None)
    base = serve(web.make_server("127.0.0.1", 0))
    s, h = call(base, "/api/health")
    check("Web — health indique le mode règles", s == 200 and h["mode"] == "rules")
    with urllib.request.urlopen(base + "/") as r:
        html = r.read().decode()
    check("Web — la page d'accueil est servie", "Vaccins de mon enfant" in html)
    s, st = call(base, "/api/start", {"language": "en"})
    check("Web — mode règles force le français", st["language"] == "fr" and st["mode"] == "rules")
    sid = st["session_id"]
    s, r = call(base, "/api/chat", {"session_id": sid, "message": "il a 9 mois"})
    check("Web — chat répond", s == 200 and len(r["reply"]) > 0)
    s, r = call(base, "/api/chat", {"session_id": sid, "message": "il a reçu le BCG"})
    s, sm = call(base, "/api/summary", {"session_id": sid})
    check("Web — fiche contient l'âge et le BCG", "9.0 mois" in sm["summary"] and "BCG" in sm["summary"])
    s, r = call(base, "/api/chat", {"session_id": "inexistant", "message": "x"})
    check("Web — session inconnue -> 410", s == 410)
    s, r = call(base, "/api/chat", {"session_id": sid, "message": "x" * 1001})
    check("Web — message trop long refusé", s == 413)
    s, r = call(base, "/api/chat", {"session_id": sid, "message": "   "})
    check("Web — message vide refusé", s == 400)
    s, r = call(base, "/api/chat", {"session_id": sid, "message": "Qu'est-ce qu'il a, c'est grave ?"})
    check("Web — garde-fou diagnostic actif via l'API", "diagnostic" in r["reply"].lower())


def test_guided_mode():
    """Mode 'cocher les vaccins' — ne doit jamais dépendre du LLM."""
    os.environ.pop("LLM_API_KEY", None)
    base = serve(web.make_server("127.0.0.1", 0))
    s, st = call(base, "/api/start", {"language": "fr"})
    sid = st["session_id"]

    s, r = call(base, "/api/guided/checklist", {"session_id": sid, "age_months": 4})
    check("Guidé — la checklist à 4 mois contient bien plusieurs visites", s == 200 and len(r["visits"]) >= 3)
    vpi_found = any(item["vaccine"] == "VPI" for v in r["visits"] for item in v["items"])
    check("Guidé — VPI présent avec son bon libellé de maladie",
          any(item["vaccine"] == "VPI" and "poliomyélite" in item["disease_label"]
              for v in r["visits"] for item in v["items"]))
    icons = {item["vaccine"]: item["icon"] for v in r["visits"] for item in v["items"]}
    check("Guidé — icône gouttes pour un vaccin oral, seringue pour un injectable",
          icons.get("Polio (VPO)") == "💧" and icons.get("Penta") == "💉")

    # Multi-doses : une seule case Penta cochée (visite 6 semaines) sur les 3 dues à 16 mois.
    s, st2 = call(base, "/api/start", {"language": "fr"})
    sid2 = st2["session_id"]
    checked = [{"vaccine": "Penta"}, {"vaccine": "Polio (VPO)"}]
    s, r = call(base, "/api/guided/submit", {"session_id": sid2, "age_months": 16, "checked": checked})
    check("Guidé — soumission renvoie un résumé cohérent", s == 200 and "Penta" in r["summary"])
    penta_missing = r["summary"].count("Penta (dû depuis")
    check("Guidé — 1 dose de Penta cochée -> il en reste bien 2 manquantes sur 3", penta_missing == 2)

    s, r = call(base, "/api/guided/checklist", {"session_id": sid2, "age_months": 500})
    check("Guidé — âge aberrant plafonné plutôt que planté", s == 200)
    s, r = call(base, "/api/guided/submit", {"session_id": sid2, "age_months": 4, "checked": [{"vaccine": "<script>x</script>"}] * 3})
    check("Guidé — liste 'checked' trop longue ou vaccin inconnu géré sans planter", s in (200, 400))


def test_llm_mode():
    upstream, state = make_fake_llm()
    up_base = serve(upstream)
    os.environ["LLM_API_KEY"] = "test-key"
    os.environ["LLM_BASE_URL"] = up_base
    base = serve(web.make_server("127.0.0.1", 0))
    s, st = call(base, "/api/start", {"language": "en"})
    check("Web LLM — langue anglaise respectée", st["mode"] == "llm" and st["language"] == "en")
    sid = st["session_id"]
    s, r = call(base, "/api/chat", {"session_id": sid, "message": "my child is 34 weeks"})
    check("Web LLM — boucle outil complète (tool_call puis réponse)", s == 200 and "8 months" in r["reply"] and state["calls"] == 2)
    check("Web LLM — le prompt système demande l'anglais", "ONLY in English" in state["last_system"])
    s, sm = call(base, "/api/summary", {"session_id": sid})
    check("Web LLM — fiche en anglais avec l'âge enregistré par l'outil", "follow-up sheet" in sm["summary"] and "8" in sm["summary"])
    os.environ["LLM_BASE_URL"] = "http://127.0.0.1:1"  # fournisseur injoignable
    s, r = call(base, "/api/chat", {"session_id": sid, "message": "hello"})
    check("Web LLM — panne fournisseur -> 503 avec message propre (sans détails)", s == 503 and "127.0.0.1" not in r["error"])
    os.environ.pop("LLM_API_KEY", None)
    os.environ.pop("LLM_BASE_URL", None)


if __name__ == "__main__":
    test_rules_mode()
    test_llm_mode()
    test_guided_mode()
    print(f"\n{PASSED} tests réussis, {FAILED} échoués.")
    sys.exit(1 if FAILED else 0)
