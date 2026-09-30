"""
Web App — serveur 100% bibliothèque standard (aucune dépendance à installer).

Pourquoi pas FastAPI ? Il dépend de pydantic-core (compilé en Rust) qui ne s'installe
pas sur Termux/Android. `http.server` suffit largement pour ce prototype.

Lancer :
    python web/server.py
puis ouvrir http://localhost:8000 dans le navigateur.

Modes (choisis automatiquement au démarrage de chaque conversation) :
    - LLM_API_KEY défini  -> agent avec vrai LLM (bilingue FR/EN)
    - sinon               -> agent à règles hors-ligne (français uniquement)

Variables optionnelles : HOST (défaut 127.0.0.1), PORT (défaut 8000).
Anonymat : aucune conversation n'est écrite sur disque ni dans les logs ;
les sessions vivent en mémoire et expirent après 2 h d'inactivité.
"""
import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import orchestrator  # noqa: E402
from agent.llm_agent import create_llm_session, handle_message_llm  # noqa: E402
from agent.toolbox import AgentToolbox  # noqa: E402
from tools.knowledge_tools import search_pev_calendar, explain_vaccine_info, find_missing_vaccines  # noqa: E402
from tools.session_tools import set_age, add_vaccine, generate_followup_summary  # noqa: E402

INDEX_HTML = (Path(__file__).parent / "index.html").read_bytes()

MAX_SESSIONS = 500
SESSION_TTL_SECONDS = 2 * 3600
MAX_MESSAGE_CHARS = 1000
MAX_BODY_BYTES = 10_000

GREETING = {
    "fr": ("Bonjour ! Je vous aide à suivre les vaccins de votre enfant (0 à 5 ans, Cameroun). "
           "Aucun nom n'est nécessaire. Quel âge a votre enfant ?"),
    "en": ("Hello! I help you keep track of your child's vaccines (ages 0 to 5, Cameroon). "
           "No name is needed. How old is your child?"),
}
ERRORS = {
    "fr": {
        "busy": "Le service est momentanément saturé. Patientez quelques secondes puis renvoyez votre message.",
        "generic": "Une erreur est survenue. Réessayez dans un instant.",
        "too_long": "Message trop long (1000 caractères maximum).",
        "expired": "Cette conversation a expiré. Veuillez en démarrer une nouvelle.",
    },
    "en": {
        "busy": "The service is temporarily busy. Please wait a few seconds and resend your message.",
        "generic": "Something went wrong. Please try again in a moment.",
        "too_long": "Message too long (1000 characters maximum).",
        "expired": "This conversation has expired. Please start a new one.",
    },
}

_sessions: dict = {}
_sessions_lock = threading.Lock()


def llm_mode_enabled() -> bool:
    return bool(os.environ.get("LLM_API_KEY"))


def _cleanup_sessions():
    now = time.time()
    for sid in [s for s, e in _sessions.items() if now - e["last"] > SESSION_TTL_SECONDS]:
        del _sessions[sid]
    while len(_sessions) >= MAX_SESSIONS:
        oldest = min(_sessions, key=lambda s: _sessions[s]["last"])
        del _sessions[oldest]


def start_session(language: str) -> dict:
    mode = "llm" if llm_mode_enabled() else "rules"
    language = language if language in ("fr", "en") else "fr"
    if mode == "rules":
        language = "fr"  # le mode hors-ligne n'existe qu'en français
        session = orchestrator.create_session()
        greeting = GREETING["fr"]
    else:
        session = create_llm_session(language=language)
        greeting = GREETING[language]
        session["llm_messages"].append({"role": "assistant", "content": greeting})
    session["language"] = language
    sid = uuid.uuid4().hex
    with _sessions_lock:
        _cleanup_sessions()
        _sessions[sid] = {"session": session, "mode": mode, "language": language,
                          "last": time.time(), "lock": threading.Lock()}
    return {"session_id": sid, "mode": mode, "language": language, "greeting": greeting}


def get_entry(sid):
    with _sessions_lock:
        entry = _sessions.get(sid)
        if entry:
            entry["last"] = time.time()
        return entry


def chat(entry: dict, message: str) -> str:
    with entry["lock"]:
        if entry["mode"] == "llm":
            return handle_message_llm(entry["session"], message)
        return orchestrator.handle_message(entry["session"], message)


def summary(entry: dict) -> str:
    with entry["lock"]:
        if entry["mode"] == "llm":
            return AgentToolbox(entry["session"]).generate_summary()["summary"]
        return orchestrator.get_summary(entry["session"])


def guided_checklist(age_months: float, language: str) -> list:
    """Visites dues jusqu'à cet âge, avec un libellé de maladie et une icône (orale/injectable)."""
    visits = search_pev_calendar(age_months)
    lang_suffix = "_en" if language == "en" else ""
    out = []
    for visit in visits:
        items = []
        for vaccine in visit["vaccines"]:
            info = explain_vaccine_info(vaccine) or {}
            route = (info.get(f"route{lang_suffix}") or info.get("route") or "").lower()
            items.append({
                "vaccine": vaccine,
                "disease_label": info.get(f"disease_label{lang_suffix}") or info.get("disease_label") or "",
                "icon": "💧" if "oral" in route else "💉",
            })
        out.append({
            "age_label": visit.get(f"age_label{lang_suffix}") or visit["age_label"],
            "items": items,
        })
    return out


def guided_submit(entry: dict, age_months: float, checked: list) -> dict:
    """Enregistre l'âge + les doses cochées (une par visite cochée) et calcule ce qui manque."""
    with entry["lock"]:
        session = entry["session"]
        set_age(session, age_months)
        for item in checked:
            vaccine = str(item.get("vaccine", "")).strip()
            if vaccine:
                add_vaccine(session, vaccine)
        missing = find_missing_vaccines(age_months, session["vaccines_received"])
        session["last_missing"] = missing
        summary_text = generate_followup_summary(session, missing, entry["language"])
        return {"summary": summary_text, "missing_count": len(missing)}


class Handler(BaseHTTPRequestHandler):
    server_version = "CIAgent/1.0"

    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict):
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, INDEX_HTML, "text/html; charset=utf-8")
        elif self.path == "/api/health":
            self._json(200, {"mode": "llm" if llm_mode_enabled() else "rules"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length > MAX_BODY_BYTES:
            return self._json(413, {"error": "payload too large"})
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:
            return self._json(400, {"error": "invalid json"})

        if self.path == "/api/start":
            return self._json(200, start_session(str(data.get("language", "fr"))))

        entry = get_entry(str(data.get("session_id", "")))
        if entry is None:
            return self._json(410, {"error": ERRORS["fr"]["expired"], "expired": True})
        lang = entry["language"]

        if self.path == "/api/chat":
            message = str(data.get("message", "")).strip()
            if not message:
                return self._json(400, {"error": "empty message"})
            if len(message) > MAX_MESSAGE_CHARS:
                return self._json(413, {"error": ERRORS[lang]["too_long"]})
            try:
                return self._json(200, {"reply": chat(entry, message)})
            except Exception as e:  # ne jamais journaliser le contenu des messages
                busy = "429" in str(e)
                print(f"[erreur chat] {type(e).__name__}{' (429)' if busy else ''}", file=sys.stderr)
                key = "busy" if busy else "generic"
                return self._json(503, {"error": ERRORS[lang][key]})

        if self.path == "/api/guided/checklist":
            try:
                age_months = float(data.get("age_months"))
            except (TypeError, ValueError):
                return self._json(400, {"error": "invalid age_months"})
            age_months = max(0.0, min(age_months, 120.0))
            return self._json(200, {"visits": guided_checklist(age_months, entry["language"])})

        if self.path == "/api/guided/submit":
            try:
                age_months = float(data.get("age_months"))
            except (TypeError, ValueError):
                return self._json(400, {"error": "invalid age_months"})
            checked = data.get("checked", [])
            if not isinstance(checked, list) or len(checked) > 200:
                return self._json(400, {"error": "invalid checked list"})
            age_months = max(0.0, min(age_months, 120.0))
            return self._json(200, guided_submit(entry, age_months, checked))

        if self.path == "/api/summary":
            return self._json(200, {"summary": summary(entry)})

        self._json(404, {"error": "not found"})

    def log_message(self, fmt, *args):  # pas de contenu de conversation dans les logs
        pass


def make_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    mode = "LLM (bilingue FR/EN)" if llm_mode_enabled() else "règles hors-ligne (français uniquement)"
    print(f"Child Immunization Guidance Agent — Web App\nMode : {mode}")
    print(f"Ouvrir : http://localhost:{port}   (Ctrl+C pour arrêter)")
    try:
        make_server(host, port).serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
