# Child Immunization Guidance Agent — Prototype P0

Agent conversationnel anonyme d'aide au suivi vaccinal (0–5 ans, Cameroun).
Prototype P0 : fonctionne **entièrement hors-ligne**, sans clé API, avec Python 3.11+ seul.

## Multi-enfants (mode LLM) et repli automatique (nouveau)

**Plusieurs enfants dans une même conversation** : si un parent dit "et mon deuxième enfant...",
l'agent archive proprement les infos de l'enfant précédent (`start_new_child`) et repart de zéro,
sans jamais mélanger les deux. `list_children` donne un aperçu de tous les enfants évoqués, et la
fiche de suivi (`generate_summary`) devient automatiquement multi-sections ("Enfant 1", "Enfant 2"...)
dès qu'il y en a plus d'un — sans rien changer pour le cas normal à un seul enfant.
Non disponible en mode règles hors-ligne (limitation connue, documentée).

**Repli automatique vers le mode règles** : si l'appel au LLM échoue (panne, quota épuisé) au
milieu d'une conversation, l'agent ne laisse plus jamais le parent sans réponse. Pour ce tour
précis, il retombe sur le moteur déterministe du mode règles (qui lit les mêmes données de
session), avec une petite note indiquant le mode simplifié temporaire. Si le LLM revient au tour
suivant, la conversation redevient fluide automatiquement. Limitation connue : le mode règles ne
gère qu'un seul enfant à la fois, donc si plusieurs enfants ont été enregistrés et que le repli
s'active, seul l'enfant actif est traité pour ce tour.

## Trace de raisonnement visible (nouveau)

Retour terrain de la chef médecin des vaccinations : l'agent "faisait trop chatbot". Diagnostic :
tout le travail réel (consultation du calendrier, calcul des doses, vérification des croyances)
était invisible — de l'extérieur, un chatbot à réponses toutes faites produit le même rendu visuel.

Chaque réponse du mode LLM affiche maintenant une courte trace en italique au-dessus du texte,
quand un outil a réellement été utilisé (ex: `_🔍 Calendrier PEV officiel consulté — 3 dose(s) en
attente_`). Cette trace n'est jamais envoyée dans l'historique transmis au modèle (pas de pollution
du contexte ni de tokens gaspillés) — elle n'existe que dans ce qui est montré au parent. Le repli
déterministe (panne LLM) a aussi été harmonisé : sa note d'avertissement apparaît maintenant en
haut du message, dans le même style, plutôt qu'en bas où elle pouvait passer inaperçue.

Le system prompt a aussi été ajusté contre l'effet "formules toutes faites" : variation des
formulations, réaction à ce que dit le parent avant d'enchaîner, une seule question à la fois.

⚠️ **Avant de conclure que c'est un problème de style de conversation** : si l'agent semble
"scripté" en usage réel (pas en test contrôlé), vérifier d'abord les logs du service déployé — le
repli automatique vers le mode règles (ajouté juste avant) peut se déclencher silencieusement si
le quota gratuit du fournisseur LLM est saturé, produisant exactement cette impression sans que ce
soit un problème de conception.

## Déploiement en ligne (Render, gratuit, sans carte bancaire)

Vérifié en septembre 2026 : Render offre toujours un vrai tier gratuit (512 Mo RAM, 750 h
d'instance/mois — largement assez pour un service tournant en continu tout le mois).

**1. Pousser le projet sur GitHub** (depuis Termux) :
```bash
pkg install git -y
cd ~/storage/shared/.../child-immunization-agent
git init && git add . && git commit -m "Initial commit"
```
Crée un dépôt vide sur https://github.com/new (public, sans README/gitignore générés
automatiquement pour éviter un conflit). Puis :
```bash
git remote add origin https://github.com/TON_PSEUDO/child-immunization-agent.git
git branch -M main
git push -u origin main
```
GitHub demandera un **Personal Access Token** au moment du push (pas ton mot de passe) :
Settings → Developer settings → Personal access tokens → Generate new token (classic),
coche juste "repo", copie-le et colle-le comme mot de passe quand Git le demande.

**2. Déployer sur Render**
- Crée un compte gratuit sur https://render.com (aucune carte requise)
- New → Blueprint → connecte ton dépôt GitHub → Render détecte `render.yaml` automatiquement
- Il demandera uniquement la valeur de `LLM_API_KEY` (ta clé Groq) — jamais écrite dans le code
- Déploie : tu obtiens une URL du genre `https://child-immunization-agent.onrender.com`

**3. À savoir**
- Le service s'endort après 15 min sans trafic ; la requête suivante prend 30 à 60 secondes
  (redémarrage à froid) — normal sur le tier gratuit, pas un bug.
- Comme rien n'est stocké sur disque (anonymat), un redémarrage à froid efface aussi les
  conversations en mémoire de tout le monde, pas seulement celle qui était inactive.
- Ne mets jamais `LLM_API_KEY` dans un fichier du dépôt — uniquement dans les variables
  d'environnement Render (`sync: false` dans `render.yaml` empêche justement ça).
- Si tu veux éviter le temps de réveil pendant une démo planifiée à l'avance, un service
  gratuit comme UptimeRobot (ping toutes les 10-14 min) garde le service éveillé, dans la
  limite des 750 h/mois — un seul service tournant en continu y reste tout juste.

## Corrections de fiabilité et de réactivité (mode LLM)

Trois soucis remontés en test réel, maintenant corrigés :
- **Historique tronqué automatiquement** (6 derniers échanges + prompt système) : moins de tokens
  envoyés à chaque appel, donc réponses plus rapides et moins de limites de débit atteintes.
- **Reprises moins agressives sur erreur 429** : plafond de temps d'attente abaissé, pour éviter
  l'impression que l'app a "gelé" pendant 20-60 secondes.
- **Repli déterministe si le modèle boucle sans conclure** (rare) : au lieu du message inutile
  "pouvez-vous reformuler ?", l'agent calcule et affiche directement les vaccins manquants via le
  code déterministe (pas de LLM), donc toujours une réponse utile même dans le pire des cas.

Interface rafraîchie : dégradé de couleur, animations douces, indicateur de frappe animé (points),
et message "toujours en train de réfléchir…" si une réponse prend plus de 4 secondes.

## Web App (nouveau)

```bash
export LLM_API_KEY=ta_cle      # optionnel : sans clé, l'app tourne en mode règles (français)
python web/server.py
```
Puis ouvrir **http://localhost:8000** dans le navigateur du téléphone. Écran d'accueil avec choix
de langue (FR/EN), chat, bouton « Fiche de suivi » (copiable), bouton « Nouvelle conversation ».

- Zéro dépendance (bibliothèque standard) : FastAPI/pydantic ne s'installent pas sur Termux (Rust).
- Anonyme : aucune conversation écrite sur disque ni dans les logs ; sessions en mémoire, expirées après 2 h.
- Pour l'ouvrir depuis un autre appareil du même réseau : `HOST=0.0.0.0 PORT=8000 python web/server.py`.
- Tests : `python tests/test_web.py` (serveur réel + faux fournisseur LLM, sans réseau externe).

**Mode guidé (☑️ cocher les vaccins, sans écrire)** : suggéré par la sœur médecin, pour les
parents peu à l'aise avec l'écrit ou l'orthographe des noms de vaccins. Après le choix de la
langue, un écran propose « Discuter » ou « Cocher les vaccins ». Le mode guidé : âge choisi dans
une liste déroulante (aucune saisie), puis une case à cocher **par dose due** (pas juste par
vaccin — donc "Penta à 6 semaines", "Penta à 10 semaines" etc. séparément, pour que le comptage
multi-doses reste correct), avec une icône 💧 (oral) ou 💉 (injectable) et le libellé de la
maladie visée. Ce mode n'appelle jamais le LLM : il réutilise directement `knowledge_tools` et
`session_tools`, donc zéro coût, zéro risque d'invention, et il fonctionne même sans clé API.
Le bouton final « Discuter avec l'agent » démarre une **nouvelle** session de chat (plutôt que
de réutiliser celle du mode guidé), pour éviter tout double comptage si le parent redit les mêmes
informations en discutant — un compromis simple plutôt qu'une fusion de session plus complexe.

## Mode LLM réel (nouveau — zéro dépendance, marche sur Termux)

```bash
export LLM_API_KEY=ta_cle          # clé gratuite sans carte : https://console.groq.com
export LLM_BASE_URL=https://api.groq.com/openai/v1   # optionnel, c'est déjà la valeur par défaut
export LLM_MODEL=openai/gpt-oss-120b                  # optionnel, c'est déjà la valeur par défaut
python cli_llm.py
```

Rien à installer avec `pip` — l'appel à l'API se fait avec `urllib` (bibliothèque standard).
C'est volontaire : le package `openai` tire une dépendance compilée (`jiter`, en Rust) qui ne
compile pas sur Termux/Android faute de toolchain Rust adaptée. Un simple appel HTTP JSON suffit
largement pour ce qu'on fait ici, et ça marche partout, y compris sur téléphone.

⚠️ **Les fournisseurs LLM retirent régulièrement des modèles** (ex: `llama-3.3-70b-versatile` a
été retiré par Groq le 16/08/2026). Si `cli_llm.py` renvoie une erreur `model_not_found` ou
`model_decommissioned`, vérifie la liste actuelle sur https://console.groq.com/docs/models et
mets à jour `LLM_MODEL` en conséquence — pas besoin de toucher au code.

Fonctionne avec n'importe quel fournisseur compatible OpenAI (Groq, OpenAI, Gemini via son
endpoint OpenAI-compatible, etc.) — il suffit de changer les 3 variables d'environnement.

**Bilingue (français / anglais)** : au lancement, `cli_llm.py` demande la langue. Toute la base
de connaissances (`vaccine_info.json`, `misconceptions.json`, `hors_pev.json`) a des champs
français et anglais (suffixe `_en`) déjà traduits et vérifiés — le LLM ne traduit jamais une info
factuelle à la volée, il pioche dans la bonne langue. Le mode règles (`cli.py`) reste français
uniquement : c'est le filet de secours hors-ligne, pas la version qu'on cherche à enrichir.

**Démystification pour parents sceptiques** : déjà active (pas repoussée à plus tard), via le
tool `check_misconception` + `knowledge/misconceptions.json` (5 croyances courantes couvertes,
bilingue). Facile à enrichir : ajouter une entrée `{claim, triggers, correction, correction_en, source}`.

**Comment ça marche** : le LLM ne connaît aucune donnée vaccinale par lui-même. Il appelle des
"tools" Python (`agent/toolbox.py`) pour consulter le calendrier PEV, les fiches vaccins, les
croyances fréquentes, et pour enregistrer l'âge/les doses confirmées — exactement les mêmes
fonctions que le prototype P0 utilisait via des règles. Le garde-fou de sécurité
(`tools/safety_tools.py`) reste un filtre déterministe **avant** tout appel au LLM : une règle
de sécurité ne dépend jamais uniquement du bon comportement du modèle.

Tester la boîte à outils seule, sans réseau ni clé API :
```bash
python tests/test_toolbox.py
```

## Lancer le prototype (mode règles, sans LLM, toujours disponible)

```bash
python cli.py
```

Commandes spéciales dans la conversation :
- `/résumé` → affiche la fiche de suivi générée à partir des informations données
- `/quitter` → termine

## Lancer les tests automatisés

```bash
python tests/test_scenarios.py
```

13 cas de test (cf. blueprint section 12) : collecte d'info, détection de vaccins manquants,
gestion de l'incertitude ("carnet perdu"), refus de diagnostic, explication de vaccin sourcée,
correction de croyance, distinction PEV/hors-PEV, mémoire sur conversation longue.

## Structure

```
child-immunization-agent/
├── cli.py                    # interface règles (P0, hors-ligne)
├── cli_llm.py                # interface avec un vrai LLM (function-calling)
├── web/
│   ├── server.py             # Web App : API JSON + service de la page (stdlib)
│   └── index.html            # interface de chat mobile-first, bilingue
├── agent/
│   ├── orchestrator.py       # boucle règles : sécurité → démystification → collecte → réponse
│   ├── nlu.py                # extraction d'âge/vaccins par règles (mode hors-ligne uniquement)
│   ├── llm_client.py         # réponses gabarits utilisées par le mode règles
│   ├── toolbox.py            # tools exposés au LLM (function-calling)
│   └── llm_agent.py          # boucle agentique avec un vrai LLM
├── tools/
│   ├── knowledge_tools.py    # lecture du calendrier PEV, fiches vaccins, hors-PEV, croyances
│   ├── safety_tools.py       # garde-fous (diagnostic, prescription, urgence) — utilisés par les 2 modes
│   └── session_tools.py      # mémoire de session anonyme (pas de PII)
├── knowledge/
│   ├── pev_calendar.json     # calendrier par âge (⚠️ dose Mosquirix 24 mois à confirmer)
│   ├── vaccine_info.json     # fiche détaillée par vaccin
│   ├── hors_pev.json         # vaccins optionnels/payants
│   └── misconceptions.json   # croyances fréquentes + correction sourcée
└── tests/
    ├── test_scenarios.py     # tests du mode règles (24 cas, aucune dépendance)
    ├── test_toolbox.py       # tests de la boîte à outils LLM (sans réseau)
    └── test_web.py           # tests de bout en bout de la Web App
```

## Ce que ce prototype fait déjà (P0)

- Anonyme : aucune donnée nominative, session en mémoire uniquement
- Comprend l'âge et les vaccins mentionnés en langage libre (règles simples, pas encore de LLM)
- Retient le contexte sur toute la conversation
- Calcule les vaccins dus/manquants selon le calendrier PEV
- Refuse poliment diagnostic/prescription, escalade en cas de mots-clés d'urgence
- Corrige deux croyances fréquentes avec source
- Distingue clairement PEV (gratuit) et hors-PEV (payant)
- Génère une fiche de suivi texte

## Prochaines étapes (P1 — voir blueprint)

1. ✅ ~~Brancher un vrai LLM~~ — fait (`cli_llm.py` / `agent/llm_agent.py`), reste à tester avec une vraie clé API.
2. **RAG réel** : remplacer la recherche par mot-clé dans `knowledge_tools.py` par
   `sentence-transformers` + `chromadb` si la base de connaissances grossit.
3. ✅ ~~Web App~~ — faite (`web/`), reste à la tester sur téléphone et à la déployer.
4. **Confirmer la dose Mosquirix à 24 mois** avec le document PEV officiel avant le freeze du 13 octobre.
5. Étendre `misconceptions.json` et `vaccine_info.json` avec plus d'entrées.
6. Tester le mode LLM sur de vrais cas difficiles (ceux qui cassaient le mode règles : "aucun vaccin", "6 semaines", vaccin inconnu, contradiction d'âge) — le LLM devrait les gérer nativement, à vérifier.

## Sécurité — rappel des règles du projet

- Jamais de vaccin/calendrier inventé — tout vient des fichiers JSON sourcés dans `knowledge/`
- Jamais de diagnostic, prescription, ou orientation vers un médecin/infirmière
- Toujours préciser le statut PEV (gratuit) vs hors-PEV (payant/optionnel)
- En cas d'incertitude, l'agent le dit plutôt que d'inventer
