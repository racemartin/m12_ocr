-- =============================================================================
-- docs/requetes_verification.sql — Requêtes de vérification manuelle
--
-- Chaque requête est l'équivalent SQL exact d'une méthode du
-- MonitoringService (couche application) — sert à vérifier "à la main"
-- que le tableau de bord (console ou Streamlit) n'invente rien.
--
-- Les lignes \echo impriment des bandeaux de séparation directement dans
-- la sortie de psql (mécanisme client, actif en mode -f et interactif) —
-- même principe visuel que les bandeaux print("="*80) du code Python.
--
-- Lancement complet (toutes les requêtes à la suite, une seule commande) :
--   psql -h localhost -U checkit -d checkit -f docs/requetes_verification.sql
-- =============================================================================

-- Désactive le pager (less/more) : sans cette ligne, psql suspend
-- l'affichage dès que la sortie dépasse la hauteur du terminal et
-- attend une touche — ce qui ressemble à un script "bloqué".
\pset pager off

\echo '================================================================================'
\echo 'CHECKIT.AI — REQUÊTES DE VÉRIFICATION MANUELLE'
\echo '================================================================================'


-- =============================================================================
-- SECTION 1 — PRÉCISION DES DONNÉES (calculer_précision)
-- =============================================================================
\echo ''
\echo '================================================================================'
\echo 'SECTION 1 — PRÉCISION DES DONNÉES'
\echo '================================================================================'

\echo '--------------------------------------------------------------------------------'
\echo '1.1 Répartition REAL / FAKE du dataset complet'
\echo '--------------------------------------------------------------------------------'
SELECT declared_label AS classe,
       COUNT(*)        AS effectif
FROM   publications
GROUP BY declared_label;

\echo '--------------------------------------------------------------------------------'
\echo '1.2 Taux d''intégrité et compteurs du DERNIER run'
\echo '--------------------------------------------------------------------------------'
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

\echo '--------------------------------------------------------------------------------'
\echo '1.3 Ratio REAL en pourcentage'
\echo '--------------------------------------------------------------------------------'
SELECT ROUND(
           100.0 * COUNT(*) FILTER (WHERE declared_label = 'REAL')
           / NULLIF(COUNT(*), 0),
           1
       ) AS ratio_real_pct
FROM   publications;


-- =============================================================================
-- SECTION 2 — RAPIDITÉ DU PIPELINE (calculer_rapidité)
-- =============================================================================
\echo ''
\echo '================================================================================'
\echo 'SECTION 2 — RAPIDITÉ DU PIPELINE'
\echo '================================================================================'

\echo '--------------------------------------------------------------------------------'
\echo '2.1 Durée de chaque run (les 20 derniers), en secondes'
\echo '--------------------------------------------------------------------------------'
SELECT run_id,
       started_at,
       finished_at,
       EXTRACT(EPOCH FROM (finished_at - started_at)) AS durée_secondes,
       nb_valides
FROM   extraction_runs
WHERE  finished_at IS NOT NULL
ORDER BY started_at DESC
LIMIT  20;

\echo '--------------------------------------------------------------------------------'
\echo '2.2 Durée moyenne tous runs confondus'
\echo '--------------------------------------------------------------------------------'
SELECT ROUND(
           AVG(EXTRACT(EPOCH FROM (finished_at - started_at)))::numeric,
           1
       ) AS durée_moyenne_s,
       COUNT(*) AS nb_runs_mesurés
FROM   extraction_runs
WHERE  finished_at IS NOT NULL;


-- =============================================================================
-- SECTION 3 — COÛT ESTIMÉ (calculer_coût)
--
-- Hypothèse : une entrée extraite ≈ une requête HTTP, pondérée par le
-- délai de politesse de 1,2 s utilisé par le FeedparserAdapter.
-- =============================================================================
\echo ''
\echo '================================================================================'
\echo 'SECTION 3 — COÛT ESTIMÉ (RESSOURCES)'
\echo '================================================================================'

SELECT SUM(nb_extraites)                      AS nb_requêtes_estimées,
       ROUND(SUM(nb_extraites) * 1.2, 1)      AS temps_cpu_estimé_s,
       ROUND(SUM(nb_extraites) * 1.2 / 60, 1) AS temps_cpu_estimé_min
FROM   extraction_runs;


-- =============================================================================
-- SECTION 4 — STATUT DES SOURCES (calculer_statut_sources)
--
-- Reproduit le sémaphore du dashboard :
--   rouge  : 0 publication ou jamais extraite
--   orange : dernière extraction plus ancienne que le seuil (48h)
--   vert   : fraîche et productive
-- =============================================================================
\echo ''
\echo '================================================================================'
\echo 'SECTION 4 — STATUT DES SOURCES'
\echo '================================================================================'

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
-- SECTION 5 — TRAÇABILITÉ N-N (ExtractionRun ↔ Source, livrable L4)
-- =============================================================================
\echo ''
\echo '================================================================================'
\echo 'SECTION 5 — TRAÇABILITÉ N-N (run_sources)'
\echo '================================================================================'

\echo '--------------------------------------------------------------------------------'
\echo '5.1 Détail complet : sources couvertes par chaque run'
\echo '--------------------------------------------------------------------------------'
SELECT r.run_id,
       r.started_at,
       r.taux_intégrité,
       s.nom_domaine
FROM   run_sources     rs
JOIN   extraction_runs r  ON r.run_id      = rs.run_id
JOIN   sources          s ON s.nom_domaine = rs.nom_domaine
ORDER BY r.started_at DESC, s.nom_domaine;

\echo '--------------------------------------------------------------------------------'
\echo '5.2 Nombre de sources distinctes couvertes par run'
\echo '--------------------------------------------------------------------------------'
SELECT rs.run_id,
       COUNT(DISTINCT rs.nom_domaine) AS nb_sources_couvertes
FROM   run_sources rs
GROUP BY rs.run_id
ORDER BY rs.run_id DESC;


-- =============================================================================
-- SECTION 6 — PREUVES COMPLÉMENTAIRES (livrable L5)
-- =============================================================================
\echo ''
\echo '================================================================================'
\echo 'SECTION 6 — PREUVES COMPLÉMENTAIRES'
\echo '================================================================================'

\echo '--------------------------------------------------------------------------------'
\echo '6.1 Idempotence : doublons d''id (résultat attendu : 0 ligne)'
\echo '--------------------------------------------------------------------------------'
SELECT id, COUNT(*) AS occurrences
FROM   publications
GROUP BY id
HAVING COUNT(*) > 1;

\echo '--------------------------------------------------------------------------------'
\echo '6.2 Les 10 publications les plus récentes'
\echo '--------------------------------------------------------------------------------'
SELECT id,
       title,
       source_domain,
       declared_label,
       captured_at
FROM   publications
ORDER BY captured_at DESC
LIMIT  10;

\echo '--------------------------------------------------------------------------------'
\echo '6.3 Vue d''ensemble : les quatre tables en un coup d''œil'
\echo '--------------------------------------------------------------------------------'
SELECT 'publications'    AS table_nom, COUNT(*) AS nb_lignes FROM publications
UNION ALL
SELECT 'sources',                      COUNT(*)              FROM sources
UNION ALL
SELECT 'extraction_runs',              COUNT(*)              FROM extraction_runs
UNION ALL
SELECT 'run_sources',                  COUNT(*)              FROM run_sources;

\echo '--------------------------------------------------------------------------------'
\echo 'Q3 — Sources et fraîcheur (obtenir_sources)'
\echo '--------------------------------------------------------------------------------'

SELECT   nom_domaine, type_source, langue, méthode_extraction,
         première_extraction, dernière_extraction, nb_publications
FROM     sources
ORDER BY nb_publications DESC;

\echo ''
\echo '================================================================================'
\echo 'FIN DU RAPPORT DE VÉRIFICATION'
\echo '================================================================================'
