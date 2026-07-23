<div align="center">
  <img src="docs/images/CheckIt_AI.png" alt="CheckIt.AI" width="150">

  # CheckIt.AI — Pipeline d'extraction de données multimodales
  **Détection de Fake News · Architecture Hexagonale · Apache Airflow**

  [![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org)
  [![Airflow](https://img.shields.io/badge/Airflow-2.10.5-017CEE)](https://airflow.apache.org)
  [![Scrapy](https://img.shields.io/badge/Scrapy-latest-60a839)](https://scrapy.org)
  [![Selenium](https://img.shields.io/badge/Selenium-4-43B02A)](https://www.selenium.dev)
  [![PostgreSQL](https://img.shields.io/badge/PostgreSQL-latest-336791)](https://www.postgresql.org)
  [![Streamlit](https://img.shields.io/badge/Streamlit-latest-red)](https://streamlit.io)
</div>

---

Pipeline d'extraction de données multimodales (texte + image) pour
l'entraînement d'un détecteur de fake news, orchestré via Apache Airflow
selon une architecture hexagonale (Ports & Adapters).

**Projet** OpenClassrooms — *Extrayez des données multimodales de sites web*
**Auteur** Rafael Cerezo Martín
**Statut** Pipeline fonctionnel de bout en bout — finalisation des livrables

---

## Sommaire

1. [Architecture du projet](#architecture-du-projet)
2. [Installation de l'environnement](#installation-de-lenvironnement)
3. [Configuration Airflow (WSL2)](#configuration-airflow-wsl2)
4. [Variables d'environnement](#variables-denvironnement)
5. **Étapes de la mission**
   1. [Étape 1 — Explorez et qualifiez les sources de données](#étape-1--explorez-et-qualifiez-les-sources-de-données)
   2. [Étape 2 — Développez des scripts d'extraction automatisée](#étape-2--développez-des-scripts-dextraction-automatisée)
   3. [Étape 3 — Implémentez un pipeline de transformation](#étape-3--implémentez-un-pipeline-de-transformation)
   4. [Étape 4 — Orchestrez le pipeline avec Airflow](#étape-4--orchestrez-le-pipeline-avec-airflow)
   5. [Vérification préalable — Dashboard console (CLI)](#vérification-préalable--dashboard-console-cli)
   6. [Étape 5 — Évaluez et visualisez les performances](#étape-5--évaluez-et-visualisez-les-performances)
6. [Livrables du projet](#livrables-du-projet)
7. [Historique de développement](#historique-de-développement)
8. [Problèmes rencontrés et solutions](#problèmes-rencontrés-et-solutions)

---

## Architecture du projet

Le projet suit une **architecture hexagonale** stricte à 4 couches,
où le domaine métier ne dépend d'aucune technologie externe.

```
Infrastructure (4) → Application (3) → Ports (2) → Domaine (1)
```

```
m12_ocr/
├── src/
│   ├── domain/                    CAPA 1 — Domaine (zéro dépendance)
│   │   ├── models.py              Entités Publication, Source, ExtractionRun
│   │   └── exceptions.py          Hiérarchie d'exceptions métier
│   │
│   ├── ports/                     CAPA 2 — Contrats abstraits
│   │   ├── inbound/
│   │   │   └── orchestrateur_port.py
│   │   └── outbound/
│   │       ├── scraper_port.py
│   │       ├── persistence_port.py
│   │       └── storage_port.py
│   │
│   ├── application/                CAPA 3 — Orchestration des cas d'usage
│   │   ├── pipeline_service.py     Composition root (CLI + Airflow)
│   │   ├── transform_service.py    Nettoyage, validation, normalisation
│   │   └── monitoring_service.py   Calcul des KPI (zéro import Streamlit)
│   │
│   ├── adapters/                   CAPA 4 — Infrastructure
│   │   ├── inbound/
│   │   │   └── airflow_dag.py      DAG Airflow — adaptateur mince
│   │   └── outbound/
│   │       ├── scrapers/           5 adaptateurs d'extraction
│   │       ├── persistence/        PostgreSQL (PersistencePort)
│   │       └── monitoring/         2 adaptateurs de présentation :
│   │                               streamlit_dashboard.py (web)
│   │                               console_dashboard.py   (CLI)
│   │
│   └── tools/rafael/
│       └── log_tool.py             Journalisation colorée RFC 5424
│
├── scripts/                        Scripts de test individuels
├── tests/{unit,integration}/       Tests pytest
├── data/{raw,processed}/           Données extraites (hors Git)
├── config/                         Paramètres (hors Git)
├── docs/                           Livrables L1, L4, L7...
│   └── requetes_verification.sql   Vérification des KPI en psql
├── airflow_home/                   Métadonnées Airflow (hors Git)
├── .env.example                    Modèle de variables d'environnement
└── pyproject.toml                  Dépendances uv
```

---

## Installation de l'environnement

### Pourquoi WSL2 est obligatoire

Apache Airflow dépend de modules Unix (`pwd`, `fcntl`, `daemon`) absents
sous Windows natif. Le développement s'effectue donc en **deux environnements
complémentaires** : PowerShell pour l'édition et Git, WSL2 Ubuntu pour
l'exécution d'Airflow et des scrapers.

### Étape 1 — Structure du projet et `uv`

```powershell
# Depuis PowerShell, dans le dossier du projet
uv init checkit_ai
cd checkit_ai
uv python pin 3.12
uv venv --python 3.12
```

### Étape 2 — Lancer WSL2 et recréer l'environnement Linux

```powershell
wsl -d Ubuntu
```

```bash
# Dans WSL2 Ubuntu — se placer dans le projet partagé
cd /mnt/c/Users/Public/IAE_DELL/pra_dell/m12_ocr

# Installer uv si absent
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# Recréer le venv en Linux (le venv Windows ne fonctionne pas dans WSL2)
uv venv --python 3.12 --seed
source .venv/bin/activate
```

### Étape 3 — Installer les dépendances du projet

```bash
# Scrapers et extraction
uv add requests feedparser beautifulsoup4 scrapy selenium praw

# Selenium — gestion automatique du driver Chrome
uv add webdriver-manager

# Transformation et persistence
uv add psycopg2-binary pymongo pandas

# Monitoring
uv add streamlit

# Variables d'environnement
uv add python-dotenv

# Qualité de code
uv add --dev ruff pytest
```

### Étape 4 — Airflow (installation via pip, pas uv)

Airflow n'est officiellement supporté que via `pip` avec son fichier
de contraintes — `uv add` provoque des conflits de versions.

```bash
pip install "apache-airflow==2.10.5" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.10.5/constraints-3.12.txt"
```

### Étape 5 — Google Chrome (requis pour Selenium)

Sous WSL2, privilégier Chrome via `apt` plutôt que `snap`, qui pose des
problèmes de sandboxing.

```bash
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | \
  sudo gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg

echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] \
  http://dl.google.com/linux/chrome/deb/ stable main" | \
  sudo tee /etc/apt/sources.list.d/google-chrome.list

sudo apt update
sudo apt install -y google-chrome-stable
google-chrome --version
```

---

## Configuration Airflow (WSL2)

### Variable `AIRFLOW_HOME` persistante

L'erreur la plus fréquente du projet provient d'un `AIRFLOW_HOME` non
défini ou défini avec une syntaxe Windows (`\`) incompatible avec SQLite
sous Linux. La solution définitive : l'ajouter au `.bashrc`.

```bash
echo 'export AIRFLOW_HOME=/mnt/c/Users/Public/IAE_DELL/pra_dell/m12_ocr/airflow_home' >> ~/.bashrc
source ~/.bashrc
```

### Initialisation de la base de données

```bash
# db migrate (pas db init, déprécié depuis Airflow 2.10)
airflow db migrate

# Créer l'utilisateur admin
airflow users create \
    --username admin \
    --firstname Admin \
    --lastname CheckIt \
    --role Admin \
    --email admin@checkit.ai \
    --password admin
```

### Lancer les deux services (deux terminaux WSL2 séparés)

```bash
# Terminal 1 — Scheduler
# export AIRFLOW_HOME=/mnt/c/Users/Public/IAE_DELL/pra_dell/m12_ocr/airflow_home
export AIRFLOW_HOME=~/airflow_home_local
cd /mnt/c/Users/Public/IAE_DELL/pra_dell/m12_ocr
source .venv/bin/activate
airflow scheduler
```

```bash
# Terminal 2 — Webserver
# export AIRFLOW_HOME=/mnt/c/Users/Public/IAE_DELL/pra_dell/m12_ocr/airflow_home
export AIRFLOW_HOME=~/airflow_home_local
cd /mnt/c/Users/Public/IAE_DELL/pra_dell/m12_ocr
source .venv/bin/activate
airflow webserver --port 8080 --hostname 0.0.0.0
```

Accès UI : **http://localhost:8080** — identifiants `admin` / `admin`

---

## Variables d'environnement

Les clés API et identifiants de connexion sont gérés via un fichier
`.env` à la racine du projet, jamais commité (protégé par `.gitignore`)
et chargé par `python-dotenv` (`load_dotenv`).

```bash
# Copier le modèle et le remplir
cp .env.example .env
nano .env
```

| Variable | Source | Obtention |
|----------|--------|-----------|
| `NEWSDATA_API_KEY` | NewsData.io | https://newsdata.io/register (gratuit, 200 req/jour) |
| `CLAIMBUSTER_API_KEY` | ClaimBuster (optionnel) | https://idir.uta.edu/claimbuster/ |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | Reddit API (futur) | https://www.reddit.com/prefs/apps |
| `CHECKIT_PG_*` | PostgreSQL | configuration locale |
| `CHECKIT_VERIFIER_IMAGES` | Pipeline | `True` = validation HTTP des images |
| `LOG_LEVEL` | LogTool | 1–8 (RFC 5424) |

En mode CLI, le `.env` est lu par le composition root de
`pipeline_service.py`. Sous Airflow, les mêmes valeurs vivent dans les
**Variables Airflow** — jamais de credentials en dur dans le DAG.

---

## Étape 1 — Explorez et qualifiez les sources de données

> Livrable associé : **L1 — Rapport d'exploration des sources**

Cinq adaptateurs implémentent le contrat `ScraperPort`, chacun couvrant
des sources **originales**, choisies pour leur faible présence dans les
datasets Kaggle/HuggingFace standards utilisés par la majorité des projets
étudiants.

### Sources actives (état actuel du pipeline)

Après plusieurs itérations de débogage (voir
[Problèmes rencontrés](#problèmes-rencontrés-et-solutions)), le
`FeedparserAdapter` concentre les sources les plus stables — les flux
RSS/Bluesky se sont révélés bien plus fiables que les pages scrapées.

| | Source | Canal | Langue |
|--|--------|-------|--------|
| <img src="docs/images/afp_factual_logo.png" height="20"> | AFP Factuel | Bluesky RSS | FR |
| <img src="docs/images/eu_vs_disinfo.png" height="20"> | EUvsDisinfo | RSS | EN |
| <img src="docs/images/hoaxbuster_logo.png" height="20"> | Hoaxbuster | RSS | FR |
| | El País | MRSS | ES |
| <img src="docs/images/politi_fact_logo.png" height="20"> | PolitiFact | RSS | EN |
| <img src="docs/images/le_monde_fr_logo.png" height="20"> | Les Décodeurs (Le Monde) | RSS | FR |
| | Chequeado | RSS | ES |

*(Africa Check a été abandonné — HTTP 403 anti-bot persistant.)*

Tous les sources retenues sont des fact-checkers certifiés **IFCN**,
ce qui justifie le label binaire REAL/FAKE : elles ne vérifient que des
affirmations factuelles, jamais des opinions (distinction opinion vs
désinformation documentée dans le L1).

### Panorama complet des adaptateurs

| Adaptateur | | Source | Langue | Labels |
|-----------|-----|--------|--------|--------|
| <img src="docs/images/feedparser_logo.png" height="16"> Feedparser | <img src="docs/images/afp_factual_logo.png" height="20"> | AFP Factuel | FR | Explicites titre |
| <img src="docs/images/feedparser_logo.png" height="16"> Feedparser | <img src="docs/images/eu_vs_disinfo.png" height="20"> | EUvsDisinfo | EN | Tous FAKE |
| <img src="docs/images/feedparser_logo.png" height="16"> Feedparser | <img src="docs/images/les_observateurs_logo.png" height="20"> | Les Observateurs | FR | 3 classes |
| <img src="docs/images/feedparser_logo.png" height="16"> Feedparser | <img src="docs/images/hoaxbuster_logo.png" height="20"> | Hoaxbuster | FR | Explicites |
| <img src="docs/images/requests_logo.png" height="16"> Requests | <img src="docs/images/newdata_io.png" height="20"> | NewsData.io | Multi | Via MBFC |
| <img src="docs/images/requests_logo.png" height="16"> Requests | <img src="docs/images/claim_buster_logo.png" height="20"> | ClaimBuster | Multi | Enrichissement score |
| <img src="docs/images/requests_logo.png" height="16"> Requests | <img src="docs/images/media_bias_fact_check.png" height="20"> | MBFC | Multi | Inférence label |
| <img src="docs/images/beautifull_soup_logo.png" height="16"> BS4 | <img src="docs/images/full_fact.png" height="20"> | FullFact UK | EN | 4 classes |
| <img src="docs/images/beautifull_soup_logo.png" height="16"> BS4 | <img src="docs/images/correctiv_logo.png" height="20"> | Correctiv DE | DE | 3 classes |
| <img src="docs/images/beautifull_soup_logo.png" height="16"> BS4 | <img src="docs/images/maldita_es.png" height="20"> | Maldita ES | ES | 4 classes |
| <img src="docs/images/scrapy_logo.png" height="16"> Scrapy | <img src="docs/images/politi_fact_logo.png" height="20"> | PolitiFact | EN | 6 classes |
| <img src="docs/images/scrapy_logo.png" height="16"> Scrapy | <img src="docs/images/les_surligneurs_logo.png" height="20"> | Les Surligneurs | FR | 5 classes |
| <img src="docs/images/selenium_logo.png" height="16"> Selenium | <img src="docs/images/logically_facts_logo.png" height="20"> | Logically | EN | 3 classes |
| <img src="docs/images/selenium_logo.png" height="16"> Selenium | <img src="docs/images/le_monde_fr_logo.png" height="20"> | Decodex | FR | 3 classes |

### Correspondance des labels bruts → REAL / FAKE

| | Source | REAL ✅ | FAKE ❌ |
|--|--------|---------|---------|
| <img src="docs/images/afp_factual_logo.png" height="20"> | AFP Factuel | `vrai` `vérifié` `confirmé` | `faux` `fake` `trompeur` `inexact` `manipulé` `hors contexte` |
| <img src="docs/images/eu_vs_disinfo.png" height="20"> | EUvsDisinfo | — | `disinformation` `fake` `false` `misleading` *(tous FAKE)* |
| <img src="docs/images/les_observateurs_logo.png" height="20"> | Les Observateurs | `vrai` `vérifié` | `faux` `trompeur` |
| <img src="docs/images/hoaxbuster_logo.png" height="20"> | Hoaxbuster | `vrai` `vérifié` | `faux` `hoax` `trompeur` |
| <img src="docs/images/newdata_io.png" height="20"> | NewsData.io | *(source fiable MBFC)* `bbc` `reuters` `afp` `lemonde` | *(source non fiable MBFC)* `rt` `sputnik` `breitbart` `infowars` |
| <img src="docs/images/claim_buster_logo.png" height="20"> | ClaimBuster | — | — *(score 0.0→1.0 — enrichissement uniquement)* |
| <img src="docs/images/media_bias_fact_check.png" height="20"> | MBFC | `very high` `high` | `mixed` `low` `very low` `questionable` `conspiracy` `pseudoscience` `satire` |
| <img src="docs/images/full_fact.png" height="20"> | FullFact UK | `true` `correct` `mostly true` | `false` `misleading` `incorrect` `unverified` `missing context` |
| <img src="docs/images/correctiv_logo.png" height="20"> | Correctiv DE | `richtig` `wahr` `stimmt` | `falsch` `irreführend` `fake` |
| <img src="docs/images/maldita_es.png" height="20"> | Maldita ES | `verdadero` `verdad` | `falso` `engañoso` `bulo` `satira` |
| <img src="docs/images/politi_fact_logo.png" height="20"> | PolitiFact | `true` `mostly true` | `half-true` `mostly false` `false` `pants on fire` |
| <img src="docs/images/les_surligneurs_logo.png" height="20"> | Les Surligneurs | `exact` `vrai` | `inexact` `faux` `trompeur` `exagéré` |
| <img src="docs/images/logically_facts_logo.png" height="20"> | Logically | `true` `verified` | `false` `misleading` `unverified` `partly false` |
| <img src="docs/images/le_monde_fr_logo.png" height="20"> | Decodex | `vrai` `vérifié` | `faux` `trompeur` `inexact` |

---

## Étape 2 — Développez des scripts d'extraction automatisée

> Livrable associé : **L2 — Scripts d'extraction automatisée**

Chaque adaptateur dispose d'un script de test autonome dans `scripts/`,
exécutable indépendamment du DAG Airflow — utile pour valider une source
avant de l'intégrer au pipeline complet.

```bash
# Toujours activer l'environnement avant de lancer un test
cd /mnt/c/Users/Public/IAE_DELL/pra_dell/m12_ocr
source .venv/bin/activate
```

### Flux RSS — AFP (Bluesky), EUvsDisinfo, Hoaxbuster, El País, PolitiFact, Les Décodeurs, Chequeado
```bash
python3 scripts/test_feedparser.py
```

### API REST — NewsData.io + MBFC + ClaimBuster
```bash
# Nécessite NEWSDATA_API_KEY dans .env
python3 scripts/test_requests.py
```

### HTML statique — FullFact, Correctiv, Maldita (BS4)
```bash
# Toutes les sources
python3 scripts/test_bs4.py

# Une source spécifique
python3 scripts/test_bs4.py --source fullfact
python3 scripts/test_bs4.py --source correctiv
python3 scripts/test_bs4.py --source maldita
```

### Crawling — PolitiFact (Scrapy)
```bash
# Plus lent (30-90s) — respecte AUTOTHROTTLE et robots.txt
python3 scripts/test_scrapy.py
```

### Sites JavaScript — Logically, Decodex (Selenium)
```bash
# Nécessite Google Chrome installé — voir Installation ci-dessus
python3 scripts/test_selenium.py

# Une source spécifique
python3 scripts/test_selenium.py --source logically
python3 scripts/test_selenium.py --source decodex
```

Chaque script affiche un rapport coloré via `LogTool` (titre, label,
langue, taux d'intégrité) et sauvegarde le résultat en JSON dans
`data/raw/test_<adaptateur>_<horodatage>.json`.

---

## Étape 3 — Implémentez un pipeline de transformation

> Livrables associés : **L3 — Pipeline de transformation**
> et **L4 — Schéma de données finalisé**

Le `TransformService` (couche application) applique en séquence :
lecture des données brutes, filtrage des paires texte–image incomplètes,
`nettoie_texte()`, `valide_image()`, `normalise_label()` (→ REAL/FAKE),
dédoublonnage par hash SHA-256, puis mapping vers le schéma physique.

Le pipeline complet est exécutable **hors Airflow** grâce au composition
root CLI de `pipeline_service.py`, qui charge le `.env` via
`python-dotenv` :

```bash
uv run python3 src/application/pipeline_service.py
```

Résultat validé sur données réelles :

```
RAPPORT DE TRANSFORMATION — ÉTAPE 3
  Entrées brutes......: 644
  Publications valides: 254
  Entrées rejetées....: 390
  Taux d'intégrité....: 39.4%
  REAL / FAKE.........: 177 / 77
```

> Lecture du taux d'intégrité : `data/raw` accumule les extractions de
> test de plusieurs jours — la majorité des rejets sont des **doublons
> neutralisés par le hash SHA-256** (preuve du bon fonctionnement du
> dédoublonnage), et non des données invalides.

La persistance est assurée par `PostgresqlAdapter` (implémentation de
`PersistencePort`) : tout le SQL du projet vit dans cet adaptateur —
insert idempotent (`ON CONFLICT (id) DO NOTHING`), quatre tables
(`publications`, `sources`, `extraction_runs`, `run_sources`).

---

## Étape 4 — Orchestrez le pipeline avec Airflow

> Livrable associé : **L5 — Flux ETL Airflow**

Le DAG `checkit_etl` (`src/adapters/inbound/airflow_dag.py`) est un
**adaptateur inbound mince** : il ne contient aucune logique métier et se
limite à invoquer les méthodes de l'`OrchestreurPort`.

Principes respectés :

- **XCom ne transporte que des chemins de fichiers**, jamais les données
  elles-mêmes.
- **Credentials PostgreSQL via les Variables Airflow** — jamais en dur.
- 5 tâches atomiques : `extract` → `validate_raw` → `transform` →
  `load` → `notify`.

État validé : **5/5 tâches SUCCESS** dans l'UI Airflow, et chargement
confirmé en base :

```
checkit=> SELECT declared_label, COUNT(*)
          FROM publications GROUP BY 1;
 declared_label | count
 FAKE           |    77
 REAL           |   302
```

L'**idempotence** est vérifiée : un second lancement sur les mêmes
données n'insère aucun doublon, tandis qu'un nouveau run est historisé
dans `extraction_runs`.

### Exécution ciblée d'une tâche (débogage)

Pour déboguer une tâche isolément, sans dépendre du scheduler ni de
l'UI, la CLI Airflow permet de l'exécuter directement en premier plan :

```bash
airflow tasks test checkit_etl extraction 2026-07-21
```

Avantages par rapport à un run déclenché depuis l'UI :

- **Aucune dépendance au scheduler** — s'exécute même si celui-ci
  n'est pas lancé.
- **Traceback affiché immédiatement** dans le terminal, sans avoir à
  chercher le fichier de log correspondant sous `airflow_home/logs/`.
- **N'écrit aucun état en base** (pas de `DagRun`, pas de tentative
  comptabilisée) — usage strictement de débogage.

Pour rejouer le pipeline complet en une seule commande (toutes les
tâches enchaînées, en premier plan, sans scheduler) :

```bash
airflow dags test checkit_etl 2026-07-21
```

Cette seconde commande simule un run réel (état persisté), utile pour
valider l'enchaînement complet sans subir la latence du
`DagFileProcessorManager` en environnement WSL2/`/mnt/c/`.

---

## Vérification préalable — Dashboard console (CLI)

> Étape intermédiaire réalisée **après l'orchestration (Étape 4)** et
> **avant la visualisation Streamlit (Étape 5)**.

Avant de lancer le serveur web, tous les KPI se vérifient en ligne de
commande grâce à un **deuxième adaptateur de présentation** qui consomme
exactement le même `MonitoringService` que Streamlit :

```bash
uv run python3 src/adapters/outbound/monitoring/console_dashboard.py
```

Ce que ce rapport texte apporte :

- **Preuve d'architecture hexagonale** : `console_dashboard.py` importe
  `MonitoringService` et ne recalcule rien — il ne fait que `print()`.
  Ajouter un adaptateur de présentation ne coûte que ce fichier, jamais
  les couches inférieures.
- **Vérification rapide** de tous les KPI (précision, rapidité, coût,
  statut par source) sans serveur web, avant tout commit du dashboard.
- **Alignement garanti** : étiquettes ASCII à largeur fixe
  (`[OK]` / `[!!]` / `[XX]`) dans les tableaux — les emojis sont
  réservés aux lignes d'alerte en texte libre.

En complément, `docs/requetes_verification.sql` reproduit chaque KPI
directement en psql, indépendamment de Python :

```bash
psql -h localhost -U checkit -d checkit -f docs/requetes_verification.sql
```

---

## Étape 5 — Évaluez et visualisez les performances

> Livrables associés : **L6 — Tableau de bord KPI Streamlit**
> et **L7 — Plan de monitoring**

Le `MonitoringService` est un **service pur de la couche application**
(zéro import Streamlit) qui calcule trois familles de KPI :

| Famille | Contenu |
|---------|---------|
| **Précision** | Répartition REAL/FAKE, taux d'intégrité du dernier run |
| **Rapidité** | Durée par run, moyenne mobile |
| **Coût** | Proxy requêtes cumulées × temps CPU estimé |

Statut par source avec seuils de couleur :

| Seuil | Statut |
|-------|--------|
| Taux d'intégrité ≥ 85 % | 🟢 vert |
| 70 % ≤ taux < 85 % | 🟠 orange |
| Taux < 70 % | 🔴 rouge |
| Fraîcheur > 48 h | 🟠 orange |

Lancement du dashboard web :

```bash
uv run streamlit run src/adapters/outbound/monitoring/streamlit_dashboard.py

# Redirige le port 8501 de Windows vers WSL2
netsh interface portproxy add v4tov4 listenport=8501 listenaddress=0.0.0.0 connectport=8501 connectaddress=172.18.139.119

# Ouvre le port dans le pare-feu Windows
New-NetFirewallRule -DisplayName "WSL2 Streamlit 8501" -Direction Inbound -LocalPort 8501 -Protocol TCP -Action Allow

```

Le plan de monitoring (L7) documente les seuils d'alerte, la gestion
des erreurs et les fréquences de vérification, en cohérence avec les
automatisations du DAG.

---

## Livrables du projet

| N° | Livrable | Format | Statut |
|----|----------|--------|--------|
| L1 | Rapport d'exploration des sources | [`docs/L1_rapport_exploration_sources.md`](docs/L1_rapport_exploration_sources.md) | ✅ |
| L2 | Scripts d'extraction automatisée | [`src/adapters/outbound/scrapers/*.py`](src/adapters/outbound/scrapers/) | ✅ |
| L3 | Pipeline de transformation | [`src/application/transform_service.py`](src/application/transform_service.py) | ✅ |
| L4 | Schéma de données finalisé | [`docs/L4_schema_donnees.md`](docs/L4_schema_donnees.md) (Mermaid + PNG) | ✅ |
| L5 | Flux ETL Airflow | [`src/adapters/inbound/airflow_dag.py`](src/adapters/inbound/airflow_dag.py) | ✅ 5/5 SUCCESS |
| L6 | Tableau de bord KPI Streamlit | [`src/adapters/outbound/monitoring/`](src/adapters/outbound/monitoring/) | ✅ (+ console) |
| L7 | Plan de monitoring | [`docs/L7_plan_monitoring.md`](docs/L7_plan_monitoring.md) | 🔶 En finalisation |

---

## Historique de développement

Chronologie des étapes réalisées, dans l'ordre logique suivi pour
ce projet.

1. **Initialisation `uv`** — structure du projet, venv Python 3.12,
   premier commit Git (`uv init` initialise Git automatiquement).
2. **Installation Airflow 2.10.5** — découverte de l'incompatibilité
   Windows native (modules `pwd`, `daemon`), bascule vers WSL2 Ubuntu 24.04.
3. **Configuration `AIRFLOW_HOME`** — résolution des erreurs en cascade
   liées aux chemins mixtes Windows/Linux (`\` vs `/`) dans `sql_alchemy_conn`.
4. **Authentification Airflow UI** — diagnostic et résolution des échecs
   de login successifs (table `session` manquante, hash de mot de passe).
5. **Structure hexagonale complète** — création des 4 couches
   (`domain`, `ports`, `application`, `adapters`) avec leurs `__init__.py`.
6. **Couche Domaine (L1)** — `models.py` (entités `Publication`,
   `Source`, `ExtractionRun`) et `exceptions.py` (hiérarchie `CheckItErreur`).
7. **Couche Ports (L2)** — quatre interfaces abstraites :
   `ScraperPort`, `PersistencePort`, `StoragePort`, `OrchestreurPort`.
8. **Cinq adaptateurs d'extraction (L4)** — un par technologie de
   scraping, avec sources originales sélectionnées pour leur rareté
   dans les datasets académiques standards.
9. **Scripts de test individuels** — un script autonome par adaptateur,
   validant chaque source indépendamment du DAG Airflow.
10. **Installation Google Chrome** — résolution des conflits
    snap/apt sous WSL2 pour le fonctionnement de Selenium.
11. **Documentation L1 et L4** — rapport d'exploration des sources
    et schéma de données (modèle conceptuel + physique) en Mermaid,
    diagrammes corrigés pour le rendu GitHub, blocs cassés remplacés
    par des exports PNG.
12. **Débogage des sélecteurs** — inspection du DOM réel via DevTools,
    mode "card" FullFact, fallback universel `og:image`, remplacement
    d'AFP Factuel RSS (403) par le flux Bluesky.
13. **Consolidation Feedparser** — extension à 8 sources RSS/Bluesky
    (dont El País MRSS, PolitiFact RSS, Les Décodeurs, Chequeado),
    correction du rating PolitiFact et de l'inférence de labels
    Chequeado (scan des catégories RSS).
14. **Refactor persistence** — extraction de `psycopg2` hors de
    `PipelineService` vers `PostgresqlAdapter` (contrat
    `PersistencePort`) ; adoption de `python-dotenv`.
15. **Pipeline de transformation (L3)** — `TransformService` validé
    sur données réelles (644 → 254 valides, dédoublonnage SHA-256).
16. **Orchestration Airflow (L5)** — DAG `checkit_etl` : 5/5 tâches
    SUCCESS, XCom limité aux chemins de fichiers, credentials via
    Variables Airflow.
17. **Monitoring (L6/L7)** — `MonitoringService` pur (3 familles de
    KPI + statut par source), deux adaptateurs de présentation
    (console puis Streamlit) et `requetes_verification.sql` pour la
    contre-vérification en psql.

---

## Problèmes rencontrés et solutions

Cette section documente les obstacles techniques significatifs
rencontrés pendant le développement — utile en cas de réinstallation
ou pour la session de bilan avec le mentor.

### Airflow ne démarre pas sous PowerShell natif
**Cause** Modules Unix (`pwd`, `daemon`) absents sous Windows.
**Solution** Développement exécuté depuis WSL2 Ubuntu 24.04 ;
PowerShell reste utilisé pour l'édition et Git.

### `AirflowConfigException: Cannot use relative path`
**Cause** `AIRFLOW_HOME` défini avec `$PWD` depuis PowerShell, produisant
un chemin Windows (`C:\Users\...`) incompatible avec SQLite sous Linux.
**Solution** Définir `AIRFLOW_HOME` en chemin Linux absolu
(`/mnt/c/Users/...`) directement dans WSL2, persisté via `.bashrc`.

### `sqlite3.OperationalError: no such table: session`
**Cause** La base `airflow.db` a été initialisée alors que
`sql_alchemy_conn` contenait un mélange `/` et `\` dans le chemin.
**Solution** Suppression complète de `airflow.db` et `airflow.cfg`,
correction du chemin, puis `airflow db migrate` (pas `db init`,
déprécié en 2.10.5).

### Login Airflow UI échoue malgré un mot de passe correct
**Cause** Le CLI `airflow users create` utilisait un `AIRFLOW_HOME`
différent de celui du webserver (terminal sans variable exportée).
**Solution** Vérification systématique de `echo $AIRFLOW_HOME` avant
toute commande Airflow ; export persisté dans `.bashrc`.

### Selenium — `Status code was: 127`
**Cause** ChromeDriver téléchargé par `webdriver-manager` ne trouvait
aucun binaire Chrome compatible (Chromium installé via `snap`, sandboxing
incompatible avec WSL2).
**Solution** Suppression du Chromium snap, installation de Google Chrome
via le dépôt `apt` officiel ; détection explicite du binaire dans
l'adaptateur via `shutil.which()`.

### Accès réseau local (`192.168.x.x:8080`) inaccessible
**Cause** WSL2 utilise une IP interne distincte de l'hôte Windows ;
pas de pont réseau automatique.
**Solution** `netsh interface portproxy` + règle de pare-feu Windows
pour rediriger le port 8080 vers l'IP WSL2. Non bloquant pour l'usage
du projet — `localhost:8080` suffit en développement local.

### Sources retournant 0 publication
**Cause(s)** Trois familles de pannes distinctes :
`403` anti-bot (AFP Factuel RSS, Africa Check), sélecteurs CSS
obsolètes après refonte des sites (FullFact, Correctiv, Maldita,
PolitiFact scraping), timeouts JS (Decodex).
**Solution** Réinspection du DOM réel via DevTools et correction des
sélecteurs ; bascule vers les flux RSS/Bluesky, plus stables que les
pages scrapées (AFP → Bluesky, PolitiFact → RSS) ; abandon
d'Africa Check (403 persistant).

### Alignement des tableaux du dashboard console
**Cause** Les emojis de statut ont une largeur variable selon le
terminal, cassant l'alignement des colonnes.
**Solution** Étiquettes ASCII à largeur fixe (`[OK]`/`[!!]`/`[XX]`)
dans les tableaux ; emojis réservés aux lignes d'alerte en texte libre.

---

## Auteur

**Rafael Cerezo Martín**

- Email : [rafael.cerezo.martin@icloud.com](mailto:rafael.cerezo.martin@icloud.com)
- GitHub : [@racemartin](https://github.com/racemartin)

---

## Licence

MIT License — voir [LICENSE](LICENSE) pour les détails.
