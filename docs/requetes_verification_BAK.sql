-- =============================================================================
-- docs/requetes_verification.sql — Requêtes de vérification manuelle
--
-- Chaque requête ci-dessous est l'équivalent SQL exact d'une méthode du
-- MonitoringService (couche application) — elles servent à vérifier "à la
-- main" que le tableau de bord (console ou Streamlit) n'invente rien.
--
-- Lancement complet (toutes les requêtes à la suite, une seule commande) :
--   psql -h localhost -U checkit -d checkit -f docs/requetes_verification.sql
--
-- Lancement d'une requête isolée : copier le bloc voulu et l'exécuter en
-- mode interactif (psql -h localhost -U checkit -d checkit), ou l'extraire
-- dans un fichier séparé et le lancer avec -f.
-- =============================================================================
-- psql -h localhost -U checkit -d checkit -f docs/requetes_verification.sql



-- =============================================================================
-- SECTION 1 — PRÉCISION DES DONNÉES
-- Équivalent de MonitoringService.calculer_précision()
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1.1 Répartition REAL / FAKE du dataset complet
-- -----------------------------------------------------------------------------
SELECT declared_label AS classe,
       COUNT(*)        AS effectif
FROM   publications
GROUP BY declared_label;

-- -----------------------------------------------------------------------------
-- 1.2 Taux d'intégrité et compteurs du DERNIER run (le plus récent)
-- -----------------------------------------------------------------------------
SELECT run_id,
       started_at,
       finished_at,
       nb_extraites,
       nb_valides,
       nb_rejetées,
       taux_intégrité
FROM   extraction_runs
ORDER BY started_at DESC
LIMIT  1;

-- -----------------------------------------------------------------------------
-- 1.3 Ratio REAL en pourcentage (calcul manuel du KPI ratio_real_pct)
-- -----------------------------------------------------------------------------
SELECT ROUND(
           100.0 * COUNT(*) FILTER (WHERE declared_label = 'REAL')
           / NULLIF(COUNT(*), 0),
           1
       ) AS ratio_real_pct
FROM   publications;


-- =============================================================================
-- SECTION 2 — RAPIDITÉ DU PIPELINE
-- Équivalent de MonitoringService.calculer_rapidité()
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 2.1 Durée de chaque run (les 20 derniers), en secondes
-- -----------------------------------------------------------------------------
SELECT run_id,
       started_at,
       finished_at,
       EXTRACT(EPOCH FROM (finished_at - started_at)) AS durée_secondes,
       nb_valides
FROM   extraction_runs
WHERE  finished_at IS NOT NULL
ORDER BY started_at DESC
LIMIT  20;

-- -----------------------------------------------------------------------------
-- 2.2 Durée moyenne tous runs confondus (KPI durée_moyenne_s)
-- -----------------------------------------------------------------------------
SELECT ROUND(
           AVG(EXTRACT(EPOCH FROM (finished_at - started_at)))::numeric,
           1
       ) AS durée_moyenne_s,
       COUNT(*) AS nb_runs_mesurés
FROM   extraction_runs
WHERE  finished_at IS NOT NULL;


-- =============================================================================
-- SECTION 3 — COÛT ESTIMÉ (RESSOURCES)
-- Équivalent de MonitoringService.calculer_coût()
--
-- Hypothèse documentée dans le code : une entrée extraite ≈ une requête
-- HTTP (fetch RSS + éventuel fetch og:image), pondérée par le délai de
-- politesse de 1,2 seconde utilisé par le FeedparserAdapter.
-- =============================================================================

SELECT SUM(nb_extraites)                 AS nb_requêtes_estimées,
       ROUND(SUM(nb_extraites) * 1.2, 1) AS temps_cpu_estimé_s,
       ROUND(SUM(nb_extraites) * 1.2 / 60, 1) AS temps_cpu_estimé_min
FROM   extraction_runs;


-- =============================================================================
-- SECTION 4 — STATUT DES SOURCES (KPI le plus actionnable)
-- Équivalent de MonitoringService.calculer_statut_sources()
--
-- Reproduit le sémaphore du dashboard :
--   rouge  : 0 publication ou jamais extraite
--   orange : dernière extraction plus ancienne que le seuil (48h)
--   vert   : fraîche et productive
-- =============================================================================

SELECT nom_domaine,
       type_source,
       nb_publications,
       ROUND(
           EXTRACT(EPOCH FROM (NOW() - dernière_extraction)) / 3600,
           1
       ) AS âge_heures,
       CASE
           WHEN nb_publications = 0 OR dernière_extraction IS NULL
               THEN '🔴 rouge'
           WHEN dernière_extraction < NOW() - INTERVAL '48 hours'
               THEN '⚠️  orange'
           ELSE '✅ vert'
       END AS statut
FROM   sources
ORDER BY CASE
             WHEN nb_publications = 0 OR dernière_extraction IS NULL THEN 0
             WHEN dernière_extraction < NOW() - INTERVAL '48 hours'  THEN 1
             ELSE 2
         END,
         nom_domaine;


-- =============================================================================
-- SECTION 5 — TRAÇABILITÉ N-N (relation ExtractionRun ↔ Source)
-- Vérifie que la table de liaison run_sources reflète bien le modèle
-- conceptuel du livrable L4 (un run couvre plusieurs sources).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 5.1 Détail complet : quelles sources chaque run a-t-il couvertes ?
-- -----------------------------------------------------------------------------
SELECT r.run_id,
       r.started_at,
       r.taux_intégrité,
       s.nom_domaine
FROM   run_sources     rs
JOIN   extraction_runs r  ON r.run_id      = rs.run_id
JOIN   sources          s ON s.nom_domaine = rs.nom_domaine
ORDER BY r.started_at DESC, s.nom_domaine;

-- -----------------------------------------------------------------------------
-- 5.2 Nombre de sources distinctes couvertes par run (vérifie N-N)
-- -----------------------------------------------------------------------------
SELECT rs.run_id,
       COUNT(DISTINCT rs.nom_domaine) AS nb_sources_couvertes
FROM   run_sources rs
GROUP BY rs.run_id
ORDER BY rs.run_id DESC;


-- =============================================================================
-- SECTION 6 — PREUVES COMPLÉMENTAIRES (livrable L5)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 6.1 Idempotence : aucun id en double dans publications (clé primaire
-- garantit déjà l'unicité — cette requête le confirme explicitement)
-- -----------------------------------------------------------------------------
SELECT id, COUNT(*) AS occurrences
FROM   publications
GROUP BY id
HAVING COUNT(*) > 1;
-- Résultat attendu : AUCUNE ligne (0 rows) — preuve d'idempotence.

-- -----------------------------------------------------------------------------
-- 6.2 Les 10 publications les plus récentes (fraîcheur du dataset)
-- -----------------------------------------------------------------------------
SELECT id,
       title,
       source_domain,
       declared_label,
       captured_at
FROM   publications
ORDER BY captured_at DESC
LIMIT  10;

-- -----------------------------------------------------------------------------
-- 6.3 Vue d'ensemble rapide : les quatre tables en un coup d'œil
-- -----------------------------------------------------------------------------
SELECT 'publications'    AS table_nom, COUNT(*) AS nb_lignes FROM publications
UNION ALL
SELECT 'sources',                      COUNT(*)              FROM sources
UNION ALL
SELECT 'extraction_runs',              COUNT(*)              FROM extraction_runs
UNION ALL
SELECT 'run_sources',                  COUNT(*)              FROM run_sources;
