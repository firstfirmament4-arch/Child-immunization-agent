"""
Interface en ligne de commande pour tester l'agent localement, sans API ni réseau.

Usage :
    python cli.py

Commandes spéciales pendant la conversation :
    /résumé   -> affiche la fiche de suivi générée pour la session en cours
    /quitter  -> termine
"""
from agent.orchestrator import create_session, handle_message, get_summary


def main():
    print("=== Child Immunization Guidance Agent — prototype CLI (anonyme, hors-ligne) ===")
    print("Tapez /résumé pour voir la fiche de suivi, /quitter pour arrêter.\n")

    session = create_session()
    print("Agent : Bonjour ! Pour commencer, quel âge a votre enfant (en mois ou en années) ?")

    while True:
        try:
            message = input("Vous : ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not message:
            continue
        if message.lower() in {"/quitter", "/quit", "/exit"}:
            break
        if message.lower() in {"/résumé", "/resume"}:
            print("\n" + get_summary(session) + "\n")
            continue

        response = handle_message(session, message)
        print(f"Agent : {response}\n")


if __name__ == "__main__":
    main()
