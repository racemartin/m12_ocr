# Cartographie du tableau de bord Streamlit — Fonctions & SQL

Projet : **CheckIt.AI** — `src/adapters/outbound/monitoring/streamlit_dashboard.py`
Ce document trace, pour chaque page et chaque graphique, la chaîne
complète d'appels jusqu'à la requête SQL exécutée sur PostgreSQL.

---

## 1. Chaîne d'appels générale (architecture hexagonale)

```
streamlit_dashboard.py          (adaptateur de présentation — UI pure)
        │  main() → construire_service() → générer_rapport_complet()
        ▼
MonitoringService               (couche application — calcul des KPI)
        │  calculer_précision() / calculer_rapidité()
        │  calculer_coût()      / calculer_statut_sources()
        ▼
PersistencePort                 (couche ports — contrat)
        │  compter_par_label() / obtenir_runs() / obtenir_sources()
        ▼
PostgresqlAdapter               (adaptateur outbound — SQL)
        ▼
PostgreSQL  (tables : publications, sources, extraction_runs, run_sources)
```

Point clé : le rapport est généré **une seule fois** par rechargement
de page (`rapport = service.générer_rapport_complet()` dans `main()`).
Les quatre pages consomment le **même** rapport — il n'y a donc que
**5 appels au port de persistance** (donc 5 requêtes SQL) par
rechargement, quelle que soit la page affichée.

---

## 2. Les 5 appels de persistance (requêtes SQL uniques)

| # | Méthode du port                 | Appelée par (service)        | SQL exécuté |
|---|---------------------------------|------------------------------|-------------|
| 1 | `compter_par_label()`           | `calculer_précision()`       | Q1 |
| 2 | `obtenir_runs(limite=1)`        | `calculer_précision()`       | Q2 |
| 3 | `obtenir_runs(limite=20)`       | `calculer_rapidité()`        | Q2 (LIMIT 20) |
| 4 | `obtenir_runs(limite=20)`       | `calculer_coût()`            | Q2 (LIMIT 20) |
| 5 | `obtenir_sources()`             | `calculer_statut_sources()`  | Q3 |

### Q1 — Répartition par label (`compter_par_label`)

```sql
SELECT declared_label,
       COUNT(*) AS nb
FROM   publications
GROUP BY declared_label;
```

### Q2 — Runs d'extraction (`obtenir_runs`)

```sql
SELECT run_id,
       started_at,
       finished_at,
       nb_extraites,
       nb_valides,
       nb_rejetées,
       taux_intégrité
FROM   extraction_runs
ORDER BY started_at DESC
LIMIT  %(limite)s;          -- 1 pour la précision, 20 pour rapidité/coût
```

> Remarque : la **durée** (`finished_at - started_at`) est calculée en
> Python dans `calculer_rapidité()`, pas en SQL. L'équivalent SQL de
> vérification (fichier `requetes_verification.sql`) est :
> `EXTRACT(EPOCH FROM (finished_at - started_at)) AS durée_secondes`.

### Q3 — Sources et fraîcheur (`obtenir_sources`)

SQL réel de l'adaptateur (constante `SQL_SELECT_SOURCES`) :

```sql
SELECT   nom_domaine, type_source, langue, méthode_extraction,
         première_extraction, dernière_extraction, nb_publications
FROM     sources
ORDER BY nb_publications DESC;
```

> Le tri SQL (`nb_publications DESC`) est ensuite **écrasé** par le tri
> Python de `calculer_statut_sources()` (rouge → orange → vert), qui
> prime pour l'affichage.

> Le statut vert/orange/rouge est calculé en Python dans
> `calculer_statut_sources()` (seuils : 0 publication = rouge,
> fraîcheur > 48 h = orange). Équivalent SQL de vérification :
> `CASE WHEN nb_publications = 0 OR dernière_extraction IS NULL
> THEN 'rouge' WHEN dernière_extraction < NOW() - INTERVAL '48 hours'
> THEN 'orange' ELSE 'vert' END`.

---

## 3. Page 1 — Vue d'ensemble (`page_vue_densemble`)

| Élément affiché | Fonction de rendu (dashboard) | Fonction service | Méthode port → SQL |
|---|---|---|---|
| Métrique « Publications » | `st.metric` (dans `page_vue_densemble`) | `calculer_précision()` | `compter_par_label()` → Q1 |
| Métrique « Taux REAL » | `st.metric` | `calculer_précision()` (`ratio_real_pct`, calcul Python) | `compter_par_label()` → Q1 |
| Métrique « Intégrité dernier run » | `st.metric` | `calculer_précision()` | `obtenir_runs(limite=1)` → Q2 |
| Métrique « Sources actives » | `st.metric` | `calculer_statut_sources()` | `obtenir_sources()` → Q3 |
| Bandeau d'alerte intégrité | `bandeau_intégrité()` + `statut_selon_taux()` | `calculer_précision()` + seuils du rapport | `obtenir_runs(limite=1)` → Q2 |
| Graphique « Historique des runs » (8 derniers) | `graphique_durées()` (Altair, barres horizontales) | `calculer_rapidité()` | `obtenir_runs(limite=20)` → Q2 |
| Caption coût (min CPU, requêtes) | `st.caption` | `calculer_coût()` (proxy 1,2 s/entrée, calcul Python) | `obtenir_runs(limite=20)` → Q2 |
| Liste « Statut des sources » (6 premières) | `st.markdown` avec `ÉMOJI_STATUT` | `calculer_statut_sources()` | `obtenir_sources()` → Q3 |
| Graphique « Répartition REAL / FAKE » | `graphique_répartition()` (Altair, barre empilée) | `calculer_précision()` | `compter_par_label()` → Q1 |

---

## 4. Page 2 — Rapidité (`page_rapidité`)

| Élément affiché | Fonction de rendu | Fonction service | Méthode port → SQL |
|---|---|---|---|
| Métriques « Durée moyenne / Dernier run / Plus rapide / Runs mesurés » | `st.metric` × 4 | `calculer_rapidité()` (moyenne et durées en Python) | `obtenir_runs(limite=20)` → Q2 |
| Graphique « Historique complet des runs » | `graphique_durées()` + `statut_selon_taux()` (couleur par intégrité) | `calculer_rapidité()` + seuils | `obtenir_runs(limite=20)` → Q2 |
| Tableau « Détail des runs récents » | `st.dataframe` (DataFrame pandas) | `calculer_rapidité()` (`durées_par_run`) | `obtenir_runs(limite=20)` → Q2 |

SQL de vérification équivalent (section 2 de `requetes_verification.sql`) :

```sql
SELECT run_id,
       EXTRACT(EPOCH FROM (finished_at - started_at)) AS durée_secondes,
       nb_valides
FROM   extraction_runs
WHERE  finished_at IS NOT NULL
ORDER BY started_at DESC
LIMIT  20;
```

---

## 5. Page 3 — Coût (`page_coût`)

| Élément affiché | Fonction de rendu | Fonction service | Méthode port → SQL |
|---|---|---|---|
| Métrique « Requêtes HTTP estimées » | `st.metric` | `calculer_coût()` (Σ `nb_extraites`) | `obtenir_runs(limite=20)` → Q2 |
| Métrique « Temps CPU estimé » | `st.metric` | `calculer_coût()` (nb_extraites × 1,2 s) | `obtenir_runs(limite=20)` → Q2 |
| Métrique « Coût moyen / run » | calcul local dans `page_coût` | `calculer_coût()` + `calculer_rapidité()` | Q2 |
| Métrique « Coût / publication » | calcul local dans `page_coût` | `calculer_coût()` + `calculer_précision()` | Q2 + Q1 |
| Graphique « Publications valides par run » | `graphique_valides_par_run()` (Altair, barres teal) | `calculer_rapidité()` (`durées_par_run`) | `obtenir_runs(limite=20)` → Q2 |
| Encadré « Hypothèse de calcul » | `st.info` | `calculer_coût()` (`hypothèse`, constante `TEMPS_MOYEN_PAR_REQUÊTE_S`) | — (aucun SQL) |

SQL de vérification équivalent :

```sql
SELECT SUM(nb_extraites)              AS nb_requêtes_estimées,
       ROUND(SUM(nb_extraites) * 1.2) AS temps_cpu_estimé_s
FROM   (SELECT nb_extraites
        FROM   extraction_runs
        ORDER BY started_at DESC
        LIMIT  20) AS derniers_runs;
```

---

## 6. Page 4 — Sources (`page_sources`)

| Élément affiché | Fonction de rendu | Fonction service | Méthode port → SQL |
|---|---|---|---|
| Métriques « Actives / En alerte / Cassées / Publications » | `st.metric` × 4 | `calculer_statut_sources()` (agrégats en Python) | `obtenir_sources()` → Q3 |
| Bandeaux d'alerte (rouge/orange/vert) | `st.error` / `st.warning` / `st.success` | `calculer_statut_sources()` | `obtenir_sources()` → Q3 |
| Grille de cartes par source (liseré coloré) | `carte_source_html()` + `st.markdown` | `calculer_statut_sources()` (tri rouge→orange→vert) | `obtenir_sources()` → Q3 |

SQL de vérification équivalent (section 4 de `requetes_verification.sql`) :

```sql
SELECT nom_domaine,
       type_source,
       nb_publications,
       dernière_extraction,
       CASE
           WHEN nb_publications = 0
                OR dernière_extraction IS NULL              THEN 'rouge'
           WHEN dernière_extraction < NOW()
                - INTERVAL '48 hours'                        THEN 'orange'
           ELSE                                                   'vert'
       END AS statut
FROM   sources
ORDER BY CASE
             WHEN nb_publications = 0
                  OR dernière_extraction IS NULL             THEN 0
             WHEN dernière_extraction < NOW()
                  - INTERVAL '48 hours'                      THEN 1
             ELSE                                                 2
         END,
         nom_domaine;
```

---

## 7. Fonctions du dashboard SANS accès aux données

Pour être exhaustif, ces fonctions n'exécutent aucun SQL :

| Fonction | Rôle |
|---|---|
| `construire_service()` | Composition root : `.env` + injection `PostgresqlAdapter` (connexion créée une fois via `@st.cache_resource`) |
| `injecter_style()` | CSS du thème (sidebar marine, cartes) |
| `logo_en_base64()` / `afficher_entête_sidebar()` | Logo en base64 dans la sidebar |
| `statut_selon_taux()` | Traduction taux → vert/orange/rouge (logique de seuils) |
| `main()` | Routage des 4 pages via `st.sidebar.radio` |

---

## 8. Récapitulatif — qui appelle quoi

```
main()
 └─ générer_rapport_complet()
     ├─ calculer_précision()        → Q1 + Q2(LIMIT 1)
     ├─ calculer_rapidité()         → Q2(LIMIT 20)
     ├─ calculer_coût()             → Q2(LIMIT 20)
     └─ calculer_statut_sources()   → Q3
```

*Note : les requêtes Q1, Q2 et Q3 ont été vérifiées contre le code
réel de `postgresql_adapter.py` (constantes `SQL_SELECT_RUNS`,
`SQL_SELECT_SOURCES` et la requête inline de `compter_par_label()`).
Les blocs « SQL de vérification équivalent » proviennent de
`docs/requetes_verification.sql` et reproduisent en SQL les calculs
faits en Python dans `MonitoringService`.*

*Détail utile pour le bilan : le dashboard n'utilise que 3 des
7 méthodes de lecture du `PostgresqlAdapter`. Les méthodes
`compter_par_source()`, `dernières_entrées()` et `existe()` existent
dans l'adaptateur mais ne sont pas consommées par `MonitoringService`.
Par ailleurs, `_obtenir_connexion()` exécute `SQL_CREATION_TABLES`
(CREATE TABLE IF NOT EXISTS) une fois par session Streamlit — la
connexion étant mise en cache par `@st.cache_resource`.*
