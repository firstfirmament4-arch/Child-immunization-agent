"""
Agent avec un vrai LLM (function-calling), compatible avec n'importe quel
fournisseur exposant une API compatible OpenAI (Groq, OpenAI, Gemini, etc.).

Implémentation volontairement SANS dépendance externe (juste urllib, stdlib) :
le package `openai` tire une dépendance compilée (jiter, en Rust) qui ne
build pas sur Termux/Android faute de toolchain Rust adaptée. Un simple
appel HTTP JSON suffit largement pour ce dont on a besoin ici, et ça marche
partout, y compris sur téléphone.

Principe de sécurité important : même avec un LLM, le garde-fou déterministe
(tools/safety_tools.check_safety_flags) reste un filtre AVANT d'appeler le modèle.
On ne fait jamais reposer une règle de sécurité uniquement sur le bon
comportement du LLM — défense en profondeur.

Variables d'environnement nécessaires :
    LLM_API_KEY    (obligatoire)
    LLM_BASE_URL   (par défaut : Groq — https://api.groq.com/openai/v1)
    LLM_MODEL      (par défaut : llama-3.3-70b-versatile)

Groq (recommandé, gratuit, sans carte) : https://console.groq.com
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

from agent.toolbox import AgentToolbox, TOOLS_SCHEMA
from tools.safety_tools import check_safety_flags
from tools.session_tools import add_turn, new_session

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"  # llama-3.3-70b-versatile a été retiré par Groq le 16/08/2026
MAX_TOOL_ROUNDS = 6
REQUEST_TIMEOUT_SECONDS = 60
MAX_RATE_LIMIT_RETRIES = 2  # moins d'attente perçue comme un "gel" ; le mode règles reste le secours
MAX_HISTORY_TURNS = 6  # nb d'échanges parent/agent conservés : limite les tokens envoyés à chaque appel

def build_system_prompt(language: str = "fr") -> str:
    language_instruction = {
        "fr": "Réponds UNIQUEMENT en français, quelle que soit la langue utilisée par le parent, sauf s'il demande explicitement de changer de langue en cours de conversation.",
        "en": "Reply ONLY in English, regardless of the language the parent uses, unless they explicitly ask to switch language during the conversation.",
    }.get(language, "Réponds en français par défaut.")

    return f"""Tu es un agent conversationnel anonyme d'aide au suivi vaccinal des enfants \
de 0 à 5 ans au Cameroun (PEV — Programme Élargi de Vaccination).

{language_instruction}

Les outils (get_vaccine_info, get_hors_pev_info, check_misconception) retournent des champs \
bilingues : les champs se terminant par "_en" sont en anglais, les champs sans suffixe sont en \
français. Utilise toujours les champs correspondant à la langue de réponse choisie ci-dessus — \
ne traduis jamais toi-même un champ factuel, utilise la version déjà fournie par l'outil.

Règles strictes, non négociables :
- Tu ne diagnostiques JAMAIS, tu ne prescris JAMAIS, tu ne remplaces JAMAIS un professionnel de santé.
- Tu n'orientes JAMAIS vers une consultation médecin/infirmière — ton rôle est d'informer et de rappeler, pas de soigner.
- Toute information vaccinale doit venir d'un appel d'outil (get_vaccine_info, get_missing_vaccines, \
get_hors_pev_info, check_misconception). N'invente JAMAIS une info vaccinale de ta propre mémoire, \
même si tu penses la connaître.
- Distingue toujours clairement les vaccins du PEV (gratuits) et les vaccins hors-PEV (payants, optionnels, \
en clinique privée).
- Dès que tu identifies ou que le parent confirme l'âge de l'enfant, appelle record_child_age.
- Dès qu'un vaccin précis est confirmé reçu OU explicitement pas reçu, appelle record_vaccine_dose. \
Ne suppose jamais qu'un vaccin est reçu sans confirmation explicite du parent.
- Si le parent exprime une croyance sur les vaccins (peur, doute), appelle check_misconception avant de répondre.
- Avant d'annoncer un retard ou de faire un résumé, appelle get_missing_vaccines.
- Une fois que tu as recueilli l'âge et au moins une information sur les vaccins reçus, propose \
spontanément un résumé (generate_summary) ou fais-le si le parent le demande.
- Si un outil indique qu'il ne trouve pas l'information (vaccin inconnu, etc.), dis-le clairement au \
parent plutôt que d'inventer une réponse.
- Si un vaccin à plusieurs doses a des doses manquantes, ne recommande JAMAIS de recommencer toute la \
série depuis le début : le rattrapage se fait en général en complétant seulement les doses manquantes.
- Quand tu listes des vaccins manquants (résultat de get_missing_vaccines), utilise le champ \
disease_label (ou disease_label_en) déjà fourni par l'outil pour dire contre quoi protège un vaccin. \
N'invente JAMAIS cette information toi-même. Exemple à ne jamais reproduire : le VPI n'est PAS un \
vaccin contre la coqueluche, c'est le vaccin injectable contre la poliomyélite — si tu as un doute \
sur un vaccin, appelle get_vaccine_info au lieu de deviner.
- Reste strictement anonyme : ne demande jamais de nom. Si le parent donne un prénom ou un nom, ne le répète JAMAIS et ne l'utilise jamais dans tes réponses ; dis simplement \"votre enfant\" (\"your child\" en anglais), et précise gentiment qu'aucun nom n'est nécessaire.
- Sois chaleureux, clair, et concis — pas de jargon inutile.
"""


def _post_chat_completion(base_url: str, api_key: str, model: str, messages: list, tools: list) -> dict:
    """Appelle l'endpoint /chat/completions en HTTP brut (aucune dépendance externe)."""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            # Sans ceci, Cloudflare (en amont de l'API) bloque le User-Agent
            # par défaut de Python avec une erreur 1010 (browser signature ban),
            # avant même que la clé API soit vérifiée.
            "User-Agent": "Mozilla/5.0 (compatible; child-immunization-agent/1.0)",
        },
        method="POST",
    )
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            if e.code == 429 and attempt < MAX_RATE_LIMIT_RETRIES:
                # Limite de débit (tier gratuit) : on attend puis on réessaie automatiquement.
                time.sleep(_retry_delay_seconds(error_body, attempt))
                continue
            raise RuntimeError(f"Erreur API ({e.code}) : {error_body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Impossible de joindre {url} : {e.reason}") from e


def _retry_delay_seconds(error_body: str, attempt: int) -> float:
    """Lit le délai suggéré par l'API ("try again in 720ms" / "in 3.2s"), sinon backoff court.
    Plafonné bas volontairement : mieux vaut basculer plus vite sur une erreur claire que de
    donner l'impression que l'app a gelé pendant 20-60 secondes."""
    match = re.search(r"try again in ([\d.]+)(ms|s)", error_body)
    if match:
        value = float(match.group(1))
        seconds = value / 1000 if match.group(2) == "ms" else value
        return min(seconds + 0.3, 6)
    return min(1.5 * (attempt + 1), 6)


def _trim_history(messages: list, max_turns: int = MAX_HISTORY_TURNS) -> list:
    """
    Ne garde que le prompt système + les N derniers échanges (un échange = un message parent
    et tout ce qui suit jusqu'au prochain message parent, y compris les tool_calls/tool).
    Objectif : moins de tokens envoyés à chaque appel -> réponses plus rapides et moins de
    limites de débit atteintes sur le tier gratuit, sans perdre le fil de la conversation récente.
    """
    if not messages:
        return messages
    has_system = messages[0].get("role") == "system"
    system = [messages[0]] if has_system else []
    rest = messages[1:] if has_system else messages

    turns, current = [], []
    for m in rest:
        if m.get("role") == "user":
            if current:
                turns.append(current)
            current = [m]
        else:
            current.append(m)
    if current:
        turns.append(current)

    kept = turns[-max_turns:] if max_turns > 0 else turns
    return system + [m for turn in kept for m in turn]


def create_llm_session(language: str = "fr") -> dict:
    session = new_session()
    session["language"] = language
    session["llm_messages"] = [{"role": "system", "content": build_system_prompt(language)}]
    return session


def handle_message_llm(session: dict, message: str) -> str:
    # Garde-fou déterministe AVANT tout appel au LLM — cf. docstring du module.
    safety = check_safety_flags(message)
    if safety["flag"]:
        add_turn(session, "parent", message)
        response = safety["response_hint"]
        add_turn(session, "agent", response)
        session["llm_messages"].append({"role": "user", "content": message})
        session["llm_messages"].append({"role": "assistant", "content": response})
        return response

    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise RuntimeError(
            "LLM_API_KEY n'est pas défini. Exporte ta clé, ex: export LLM_API_KEY=... "
            "(clé gratuite disponible sur https://console.groq.com)"
        )
    base_url = os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL)
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)

    add_turn(session, "parent", message)
    session["llm_messages"] = _trim_history(session["llm_messages"]) + [{"role": "user", "content": message}]

    toolbox = AgentToolbox(session)

    for _ in range(MAX_TOOL_ROUNDS):
        response_json = _post_chat_completion(base_url, api_key, model, session["llm_messages"], TOOLS_SCHEMA)

        if "error" in response_json:
            raise RuntimeError(f"Erreur API : {response_json['error']}")

        choice = response_json["choices"][0]["message"]
        tool_calls = choice.get("tool_calls")

        if tool_calls:
            session["llm_messages"].append(
                {
                    "role": "assistant",
                    "content": choice.get("content") or "",
                    "tool_calls": tool_calls,
                }
            )
            for tool_call in tool_calls:
                fn_name = tool_call["function"]["name"]
                try:
                    args = json.loads(tool_call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                method = getattr(toolbox, fn_name, None)
                result = method(**args) if method else {"error": f"outil inconnu: {fn_name}"}
                session["llm_messages"].append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            continue  # on relance pour laisser le modèle exploiter les résultats des outils

        final_text = choice.get("content") or "Désolé, je n'ai pas de réponse à formuler."
        session["llm_messages"].append({"role": "assistant", "content": final_text})
        add_turn(session, "agent", final_text)
        return final_text

    # Le modèle n'a pas conclu en MAX_TOOL_ROUNDS échanges (rare, mais possible sur le tier
    # gratuit). Plutôt qu'un "reformulez" qui n'aide personne, on retombe sur une réponse
    # déterministe utile (même principe de défense en profondeur que le garde-fou de sécurité).
    if session.get("age_months") is not None:
        result = toolbox.get_missing_vaccines()
        fallback = llm_client_fallback_summary(result.get("missing", []), session["language"])
    else:
        fallback = {
            "fr": "Je prends plus de temps que prévu à répondre. Pour repartir sur une base claire : quel âge a votre enfant ?",
            "en": "This is taking longer than expected. To restart clearly: how old is your child?",
        }[session["language"]]
    add_turn(session, "agent", fallback)
    session["llm_messages"].append({"role": "assistant", "content": fallback})
    return fallback


def llm_client_fallback_summary(missing: list, language: str) -> str:
    """Résumé minimal et sourcé des vaccins manquants, sans passer par le LLM (repli round-limit)."""
    if language == "en":
        if not missing:
            return "I'm having trouble replying right now, but based on what you've told me, nothing seems overdue."
        lines = ["I'm having trouble formulating a full reply right now. Here is what seems due, based only on what you've told me:"]
        lines += [f"  - {m['vaccine']} (due since: {m.get('due_since_en', m['due_since'])})" for m in missing]
        return "\n".join(lines)
    if not missing:
        return "J'ai du mal à répondre pleinement pour l'instant, mais rien ne semble en retard d'après ce que vous m'avez dit."
    lines = ["J'ai du mal à formuler une réponse complète pour l'instant. Voici ce qui semble dû, d'après ce que vous m'avez dit :"]
    lines += [f"  - {m['vaccine']} (dû depuis : {m['due_since']})" for m in missing]
    return "\n".join(lines)
