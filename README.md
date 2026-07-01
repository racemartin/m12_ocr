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
**Statut** En développement actif

---

## Sommaire

1. [Architecture du projet](#architecture-du-projet)
2. [Installation de l'environnement](#installation-de-lenvironnement)
3. [Configuration Airflow (WSL2)](#configuration-airflow-wsl2)
4. [Variables d'environnement](#variables-denvironnement)
5. [Sources de données et adaptateurs](#sources-de-données-et-adaptateurs)
6. [Tester chaque adaptateur](#tester-chaque-adaptateur)
7. [Livrables du projet](#livrables-du-projet)
8. [Historique de développement](#historique-de-développement)
9. [Problèmes rencontrés et solutions](#problèmes-rencontrés-et-solutions)

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
│   │   ├── models.py              Entité Publication, LabelVéracité
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
│   │   ├── pipeline_service.py
│   │   ├── transform_service.py
│   │   └── monitoring_service.py
│   │
│   ├── adapters/                   CAPA 4 — Infrastructure
│   │   ├── inbound/
│   │   │   └── airflow_dag.py      DAG Airflow — orchestration ETL
│   │   └── outbound/
│   │       ├── scrapers/           5 adaptateurs d'extraction
│   │       ├── persistence/        PostgreSQL, MongoDB
│   │       └── monitoring/         Dashboard Streamlit
│   │
│   └── tools/rafael/
│       └── log_tool.py             Journalisation colorée RFC 5424
│
├── scripts/                        Scripts de test individuels
├── tests/{unit,integration}/       Tests pytest
├── data/{raw,processed}/           Données extraites (hors Git)
├── config/                         Paramètres (hors Git)
├── docs/                           Livrables L1, L4...
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
export AIRFLOW_HOME=/mnt/c/Users/Public/IAE_DELL/pra_dell/m12_ocr/airflow_home
cd /mnt/c/Users/Public/IAE_DELL/pra_dell/m12_ocr
source .venv/bin/activate
airflow scheduler
```

```bash
# Terminal 2 — Webserver
export AIRFLOW_HOME=/mnt/c/Users/Public/IAE_DELL/pra_dell/m12_ocr/airflow_home
cd /mnt/c/Users/Public/IAE_DELL/pra_dell/m12_ocr
source .venv/bin/activate
airflow webserver --port 8080 --hostname 0.0.0.0
```

Accès UI : **http://localhost:8080** — identifiants `admin` / `admin`

---

## Variables d'environnement

Les clés API et identifiants de connexion sont gérés via un fichier
`.env` à la racine du projet, jamais commité (protégé par `.gitignore`).

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
| `POSTGRES_*` | Base de données | configuration locale |

Le fichier `.env` est chargé automatiquement par `python-dotenv` dans
chaque adaptateur et script de test — aucun `export` manuel requis.

---

## Sources de données et adaptateurs

Cinq adaptateurs implémentent le contrat `ScraperPort`, chacun couvrant
des sources **originales**, choisies pour leur faible présence dans les
datasets Kaggle/HuggingFace standards utilisés par la majorité des projets
étudiants.

### 1. `feedparser_adapter.py` — Flux RSS

| Source | Langue | Labels |
|--------|--------|--------|
| AFP Factuel | FR | Explicites dans le titre (FAUX/VRAI/TROMPEUR) |
| EUvsDisinfo | EN | Tous FAKE — base officielle UE |
| Les Observateurs (France 24) | FR | Explicites — vérification collaborative |
| Hoaxbuster | FR | Fact-checker FR grand public |

Outil léger, sans navigateur — parsing XML/Atom direct.

### 2. `requests_adapter.py` — API REST

| Source | Rôle |
|--------|------|
| NewsData.io | Articles frais multilingues avec image |
| MediaBiasFactCheck (MBFC) | Évaluation fiabilité du domaine source |
| ClaimBuster | Scoring d'affirmabilité d'un texte (académique UTA) |

### 3. `bs4_adapter.py` — HTML statique

| Source | Langue | Particularité |
|--------|--------|----------------|
| FullFact | EN | Fact-checker UK, 4 classes de labels |
| Correctiv | DE | Fact-checker allemand certifié IFCN |
| Maldita | ES | Fact-checker espagnol |

### 4. `scrapy_adapter.py` — Crawling multi-pages

| Source | Langue | Particularité |
|--------|--------|----------------|
| PolitiFact | EN | Pagination complexe, 6 niveaux de labels (Pants on Fire inclus) |
| Les Surligneurs | FR | Vérification déclarations politiques FR, pagination WordPress |

### 5. `selenium_adapter.py` — Sites JavaScript dynamiques

| Source | Langue | Pourquoi Selenium |
|--------|--------|--------------------|
| Logically Facts | EN | Rendu React complet requis |
| Decodex (Le Monde) | FR | Pagination JavaScript |



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

---

## Tester chaque adaptateur

Chaque adaptateur dispose d'un script de test autonome dans `scripts/`,
exécutable indépendamment du DAG Airflow — utile pour valider une source
avant de l'intégrer au pipeline complet.

```bash
# Toujours activer l'environnement avant de lancer un test
cd /mnt/c/Users/Public/IAE_DELL/pra_dell/m12_ocr
source .venv/bin/activate
```

### Flux RSS — AFP, EUvsDisinfo, Hoaxbuster
```bash
python3 scripts/test_feedparser.py
```

### API REST — NewsData.io + MBFC + ClaimBuster
```bash
# Nécessite NEWSDATA_API_KEY dans .env
python3 scripts/test_requests.py
```

### HTML statique — FullFact, Correctiv, Maldita
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

## Livrables du projet

| N° | Livrable | Format | Statut |
|----|----------|--------|--------|
| L1 | Rapport d'exploration des sources | [`docs/L1_rapport_exploration_sources.md`](docs/L1_rapport_exploration_sources.md) | ✅ |
| L2 | Scripts d'extraction automatisée | [`src/adapters/outbound/scrapers/*.py`](src/adapters/outbound/scrapers/) | ✅ |
| L3 | Pipeline de transformation | [`src/application/transform_service.py`](src/application/transform_service.py) | ⬜ À venir |
| L4 | Schéma de données finalisé | [`docs/L4_schema_donnees.md`](docs/L4_schema_donnees.md) (Mermaid) | ✅ |
| L5 | Flux ETL Airflow | [`src/adapters/inbound/airflow_dag.py`](src/adapters/inbound/airflow_dag.py) | ⬜ À venir |
| L6 | Tableau de bord KPI Streamlit | [`src/adapters/outbound/monitoring/`](src/adapters/outbound/monitoring/) | ⬜ À venir |
| L7 | Plan de monitoring | [`docs/L7_plan_monitoring.md`](docs/L7_plan_monitoring.md) | ⬜ À venir |

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
6. **Couche Domaine (L1)** — `models.py` (entité `Publication`,
   `LabelVéracité`) et `exceptions.py` (hiérarchie `CheckItErreur`).
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
    et schéma de données (modèle conceptuel + physique) en Mermaid.

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

---


## Auteur

**Rafael Cerezo Martín**

- Email : [rafael.cerezo.martin@icloud.com](mailto:rafael.cerezo.martin@icloud.com)
- GitHub : [@racemartin](https://github.com/racemartin)

---

## Licence

MIT License — voir [LICENSE](LICENSE) pour les détails.