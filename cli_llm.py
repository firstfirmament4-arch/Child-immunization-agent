"""
CLI pour tester l'agent avec un vrai LLM (function-calling).

Configuration (variables d'environnement) :
    export LLM_API_KEY=ta_cle
    export LLM_BASE_URL=https://api.groq.com/openai/v1   # optionnel, Groq par défaut
    export LLM_MODEL=llama-3.3-70b-versatile              # optionnel

Clé gratuite (sans carte bancaire) : https://console.groq.com

Usage :
    python cli_llm.py
"""
import os
import sys

from agent.llm_agent import create_llm_session, handle_message_llm


def main():
    if not os.environ.get("LLM_API_KEY"):
        print("⚠️  LLM_API_KEY n'est pas défini.")
        print("    export LLM_API_KEY=ta_cle   (clé gratuite sur https://console.groq.com)")
        sys.exit(1)

    print("=== Child Immunization Guidance Agent — mode LLM réel ===")
    print(f"Modèle : {os.environ.get('LLM_MODEL', 'openai/gpt-oss-120b')}")

    print("\nChoisissez votre langue / Choose your language:")
    print("  1. Français")
    print("  2. English")
    choice = input("> ").strip()
    language = "en" if choice == "2" else "fr"

    print("\nTapez /quitter pour arrêter." if language == "fr" else "\nType /quitter to stop.")

    session = create_llm_session(language=language)

    while True:
        try:
            message = input("Vous : ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not message:
            continue
        if message.lower() in {"/quitter", "/quit", "/exit"}:
            break

        try:
            response = handle_message_llm(session, message)
        except Exception as e:
            print(f"[Erreur] {e}\n")
            continue

        print(f"Agent : {response}\n")


if __name__ == "__main__":
    main()
