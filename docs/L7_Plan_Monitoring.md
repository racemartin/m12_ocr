# Plan de Monitoring — CheckIt.AI (Livrable L7)

**Projet** CheckIt.AI — Pipeline ETL multimodal de détection de fake news
**Version** 1.0 · Juillet 2026
**Auteur** Rafael Cerezo Martín — Ingénieur Data junior

---

## 1. Objet du document

Ce document décrit la stratégie de surveillance du pipeline ETL en
conditions de production : quels indicateurs sont mesurés (KPI), à
quelle fréquence, quels seuils déclenchent une alerte, et comment le
tableau de bord (livrable L6) s'insère dans l'architecture existante.

**Point de vigilance appliqué** : ce plan documente uniquement ce qui
est **réellement automatisé** dans le projet (retries Airflow, logs
RFC 5424, historisation en base) — aucune promesse de surveillance
non implémentée.

---

## 2. Architecture de monitoring — vue d'ensemble

### 2.1 Où vit chaque composant Airflow (schéma corrigé)

Le schéma ci-dessous corrige deux approximations d'une version
antérieure : le port **8793** n'appartient pas à l'Executor mais au
**serveur de logs** que le Scheduler lance lui-même ; et le
**SequentialExecutor** n'est pas un processus séparé mais un
composant **interne** au Scheduler (d'où sa limite : une seule tâche
à la fois avec SQLite).

```
                         ┌──────────────────────────┐
                         │   Admin (navigateur)     │
                         └────────────┬─────────────┘
                                      │ HTTP
                                      ▼
                         ┌──────────────────────────┐
                         │      WEBSERVER           │
                         │  Port : 8080             │
                         │  Lit / écrit l'état      │
                         └────────────┬─────────────┘
                                      │
                    (Consulte / Met à jour l'état)
                                      │
                                      ▼
                         ┌──────────────────────────┐
                         │  BASE DE MÉTADONNÉES     │
                         │  SQLite — airflow.db     │
                         │  + Variables (checkit_*) │
                         └────────────▲─────────────┘
                                      │
                        (Scan continu du dags_folder)
                                      │
                         ┌────────────┴─────────────┐
                         │       SCHEDULER          │
                         │  ┌─────────────────────┐ │
                         │  │ SequentialExecutor  │ │  ← composant interne,
                         │  │ (exécute 1 tâche à  │ │    pas un processus
                         │  │  la fois — limite   │ │    séparé
                         │  │  imposée par SQLite) │ │
                         │  └─────────────────────┘ │
                         │  ┌─────────────────────┐ │
                         │  │ Serveur de logs      │ │  ← lance ce serveur,
                         │  │ Port : 8793          │ │    PAS l'Executor
                         │  │ (sert les logs des   │ │
                         │  │  tâches au Webserver)│ │
                         │  └─────────────────────┘ │
                         └───────────────────────────┘
```

### 2.2 Où s'insère le tableau de bord (nouveau, Étape 5)

Le dashboard **ne dépend pas d'Airflow** — il lit directement
PostgreSQL via le port `PersistencePort`, indépendamment de qui a
alimenté la base (CLI ou DAG). C'est une conséquence directe de
l'architecture hexagonale : Streamlit est un adaptateur de plus, au
même rang que le DAG.

```
   ┌─────────────────┐        ┌──────────────────┐
   │   DAG Airflow    │        │   CLI (manuel)   │
   │ (adaptateur      │        │ (adaptateur      │
   │  inbound)        │        │  inbound)        │
   └────────┬─────────┘        └────────┬─────────┘
            │                           │
            └───────────┬───────────────┘
                         ▼
              ┌─────────────────────┐
              │   PipelineService    │  (couche application)
              │   TransformService    │
              └──────────┬───────────┘
                         │ exécuter_chargement()
                         ▼
              ┌─────────────────────┐
              │   PersistencePort    │  (couche ports — contrat)
              └──────────┬───────────┘
                         │ implémente
                         ▼
              ┌─────────────────────┐
              │  PostgresqlAdapter   │  (couche adapters — SQL)
              └──────────┬───────────┘
                         ▼
              ┌─────────────────────┐
              │   PostgreSQL         │
              │   4 tables           │
              └──────────▲───────────┘
                         │ obtenir_runs() / obtenir_sources()
                         │ compter_par_label() / compter_par_source()
              ┌──────────┴───────────┐
              │   PersistencePort    │  (même contrat, lecture)
              └──────────▲───────────┘
                         │ injecté dans
              ┌──────────┴───────────┐
              │  MonitoringService    │  (couche application)
              │  calcule TOUS les KPI │  — zéro import Streamlit
              └──────────▲───────────┘
                         │ injecté dans
              ┌──────────┴───────────┐
              │ streamlit_dashboard  │  (adaptateur outbound —
              │ (adaptateur mince,    │   présentation seulement)
              │  affichage seulement) │
              └──────────────────────┘
```

**Conséquence pratique** : remplacer Streamlit par Grafana, une API
REST ou un export PDF automatisé ne nécessiterait de réécrire QUE le
fichier `streamlit_dashboard.py` — ni `MonitoringService`, ni
`PersistencePort`, ni le reste du pipeline ne seraient touchés.

---

## 3. Indicateurs de performance (KPI)

### 3.1 Précision des données

| KPI | Définition | Source | Seuil d'alerte |
|---|---|---|---|
| Taux d'intégrité | % d'entrées valides / entrées extraites | `extraction_runs.taux_intégrité` | 🔴 < 70 % · ⚠️ < 85 % |
| Ratio REAL/FAKE | Répartition des classes du dataset | `publications` (agrégation) | Informatif — pas d'alerte automatique |
| Taux de rejet | % d'entrées écartées (motif journalisé) | `extraction_runs.nb_rejetées` | ⚠️ > 15 % |

### 3.2 Rapidité

| KPI | Définition | Source | Seuil d'alerte |
|---|---|---|---|
| Durée par run | `finished_at - started_at` | `extraction_runs` | ⚠️ > 30 min (= `execution_timeout` Airflow) |
| Durée par tâche | Visible dans Airflow (Gantt/Task Duration) | Logs Airflow | Pas de seuil automatique — lecture visuelle |
| Tendance | Moyenne mobile sur les N derniers runs | `MonitoringService.calculer_rapidité()` | Dégradation progressive → investiguer |

### 3.3 Coût (estimation, proxy)

| KPI | Définition | Source | Note |
|---|---|---|---|
| Requêtes HTTP estimées | ≈ nombre d'entrées extraites | `extraction_runs.nb_extraites` | Proxy — pas de facturation cloud sur ce projet |
| Temps CPU estimé | `nb_requêtes × 1,2 s` (délai de politesse) | Calcul dérivé | Hypothèse documentée dans le code |

### 3.4 Statut par source (KPI le plus actionnable)

| Statut | Condition | Action attendue |
|---|---|---|
| 🔴 Rouge | 0 publication ou jamais extraite | Vérifier l'accessibilité de la source (403, changement de structure HTML/RSS) |
| ⚠️ Orange | Dernière extraction > 48h | Vérifier la planification (@daily) et les logs du dernier run |
| ✅ Vert | Fraîche et productive | Aucune action |

---

## 4. Fréquence de vérification

| Fréquence | Vérification | Mécanisme |
|---|---|---|
| Temps réel | Erreurs HTTP et exceptions | Logs `LogTool` (RFC 5424, niveaux WARNING/ERROR) |
| Par run (quotidien, `@daily`) | Taux d'intégrité, statut des sources | `extraction_runs` + tableau de bord L6 |
| À la demande | Vue d'ensemble complète | Ouverture du dashboard Streamlit |
| Hebdomadaire (manuel) | Qualité des labels, doublons résiduels | Requête SQL sur `publications` |

---

## 5. Gestion des erreurs et alertes

### 5.1 Ce qui est réellement automatisé (Airflow)

- **Retries** : 3 tentatives par tâche, délai exponentiel
  (`retry_exponential_backoff = True`).
- **Timeout** : 30 minutes maximum par tâche
  (`execution_timeout`) — au-delà, la tâche est marquée en échec.
- **Panne partielle tolérée** : une source RSS en échec (403, timeout)
  est journalisée en `LEVEL_4_ERROR` mais n'interrompt pas
  l'extraction des autres sources (`exécuter_extraction`).
- **Rejet propre** : toute entrée invalide (titre/image/label
  manquant) est comptabilisée avec son motif exact — jamais de
  donnée devinée ou silencieusement corrompue.

### 5.2 Ce qui est manuel aujourd'hui (limite assumée)

- **Notification** : `exécuter_notification()` publie le rapport dans
  les logs et la console — **aucun email n'est envoyé** dans la
  version actuelle. Amélioration identifiée : brancher un
  `EmailOperator` Airflow sur échec du DAG.
- **Lecture du dashboard** : consultation à la demande, pas de
  rafraîchissement automatique programmé (le bouton "Rafraîchir"
  vide le cache de connexion).

### 5.3 Procédure en cas d'alerte rouge

1. Consulter le tableau de bord (statut des sources) pour identifier
   la source en cause.
2. Ouvrir les logs Airflow de la tâche `extraction` (Grid → tâche →
   Logs) et chercher le message `LEVEL_4_ERROR` de la source.
3. Tester la source isolément :
   `uv run python3 scripts/test_feedparser.py`
4. Si la source est durablement inaccessible (403 permanent,
   changement de structure), documenter la décision (écarter,
   remplacer) dans le rapport d'exploration (L1) — voir le précédent
   Africa Check → Chequeado.

---

## 6. Cohérence avec les automatisations existantes

Ce plan a été rédigé en vérifiant chaque affirmation contre le code
réel du projet (point de vigilance de la mission) :

- Les seuils d'intégrité (70 % / 85 %) correspondent aux constantes
  `SEUIL_INTÉGRITÉ_CRITIQUE` / `SEUIL_INTÉGRITÉ_AVERTISSEMENT` de
  `monitoring_service.py`.
- Le seuil de fraîcheur (48h) correspond à
  `SEUIL_FRAÎCHEUR_HEURES`.
- Les retries et le timeout correspondent aux `paramètres_défaut`
  du DAG dans `airflow_dag.py`.
- L'absence d'envoi d'email est signalée explicitement plutôt que
  passée sous silence.

---

## 7. Configuration et lancement du tableau de bord

```bash
# Le dashboard lit le même .env que le pipeline (mêmes credentials
# PostgreSQL — CHECKIT_PG_HOST, CHECKIT_PG_PORT, CHECKIT_PG_DB,
# CHECKIT_PG_USER, CHECKIT_PG_PASSWORD).

uv pip install streamlit pandas python-dotenv

uv run streamlit run \
  src/adapters/outbound/monitoring/streamlit_dashboard.py
```

Le navigateur s'ouvre automatiquement sur `http://localhost:8501`.
Le bouton **🔄 Rafraîchir les données** vide le cache de connexion et
relit la base — utile après un nouveau run du pipeline.

---

*CheckIt.AI — Livrable L7 · Document vivant, à mettre à jour à chaque
évolution significative du pipeline (nouvelle source, nouveau seuil,
nouvelle automatisation).*
