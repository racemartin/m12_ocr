# ==============================================================================
# src/adapters/outbound/persistence/postgresql_adapter.py
# Adaptateur PostgreSQL — implémentation du PersistencePort
#
# Encapsule TOUTE la connaissance SQL du projet : connexion, création de
# la table, insertion idempotente, requêtes de comptage. Aucune autre
# couche ne parle jamais SQL — substituer PostgreSQL par MongoDB revient
# à écrire un mongodb_adapter.py implémentant le même contrat.
#
# Sécurité (points de vigilance de la mission) :
#   - Credentials INJECTÉS par le constructeur (composition root : .env
#     en CLI, Variables en Airflow) — jamais lus ici, jamais en dur
#   - Requêtes 100 % paramétrées (aucune injection SQL possible)
#   - ON CONFLICT (id) DO NOTHING : idempotence entre les runs
#   - Authentification scram-sha-256 (défaut PostgreSQL 16 / Ubuntu 24)
# ==============================================================================

# --- Bibliothèque standard : sérialisation des métadonnées ----------------------
import json                                # metadata dict → colonne JSONB

from   typing import Dict, List            # Annotations de types

# --- Dépendances externes : driver PostgreSQL -----------------------------------
import psycopg2                            # pip install psycopg2-binary

# --- Port implémenté : contrat de persistance défini par le domaine -------------
from   src.ports.outbound.persistence_port import PersistencePort

# --- Outil de journalisation colorée en console (RFC 5424) ----------------------
from   src.tools.rafael.log_tool import LogTool


# ==============================================================================
# SCHÉMA PHYSIQUE — quatre tables alignées sur le modèle de domaine (L4)
# ==============================================================================
# publications    : le dataset multimodal (entité Publication)
# sources         : référentiel des sources (entité Source)
# extraction_runs : historique des runs (entité ExtractionRun)
# run_sources     : liaison N-N run ↔ sources (run_sources du domaine)
SQL_CREATION_TABLES = """
    CREATE TABLE IF NOT EXISTS publications (
        id             VARCHAR(64)   PRIMARY KEY,
        title          TEXT          NOT NULL,
        content        TEXT,
        image_url      VARCHAR(2048) NOT NULL,
        source_domain  VARCHAR(255)  NOT NULL,
        declared_label VARCHAR(4)    NOT NULL
                       CHECK (declared_label IN ('REAL', 'FAKE')),
        lang           CHAR(2)       DEFAULT 'fr',
        captured_at    TIMESTAMPTZ   DEFAULT NOW(),
        metadata       JSONB
    );

    CREATE TABLE IF NOT EXISTS sources (
        nom_domaine         VARCHAR(255)  PRIMARY KEY,
        type_source         VARCHAR(50)   NOT NULL,
        langue              VARCHAR(10),
        url_base            VARCHAR(2048),
        méthode_extraction  VARCHAR(100),
        première_extraction TIMESTAMPTZ,
        dernière_extraction TIMESTAMPTZ,
        nb_publications     INTEGER       DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS extraction_runs (
        run_id          VARCHAR(64)   PRIMARY KEY,
        started_at      TIMESTAMPTZ   NOT NULL,
        finished_at     TIMESTAMPTZ,
        nb_extraites    INTEGER       DEFAULT 0,
        nb_valides      INTEGER       DEFAULT 0,
        nb_rejetées     INTEGER       DEFAULT 0,
        taux_intégrité  FLOAT,
        erreurs_json    TEXT
    );

    CREATE TABLE IF NOT EXISTS run_sources (
        run_id      VARCHAR(64)  REFERENCES extraction_runs (run_id),
        nom_domaine VARCHAR(255) REFERENCES sources (nom_domaine),
        PRIMARY KEY (run_id, nom_domaine)
    );
"""

SQL_INSERTION = """
    INSERT INTO publications
        (id, title, content, image_url, source_domain,
         declared_label, lang, captured_at, metadata)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (id) DO NOTHING;
"""

# Upsert d'une source : créée à la première extraction, puis seules
# dernière_extraction et nb_publications évoluent aux runs suivants.
SQL_UPSERT_SOURCE = """
    INSERT INTO sources
        (nom_domaine, type_source, méthode_extraction,
         première_extraction, dernière_extraction)
    VALUES (%s, 'rss', 'feedparser', NOW(), NOW())
    ON CONFLICT (nom_domaine)
    DO UPDATE SET dernière_extraction = NOW();
"""

SQL_MAJ_NB_PUBLICATIONS = """
    UPDATE sources
    SET    nb_publications = (
        SELECT COUNT(*) FROM publications
        WHERE  publications.source_domain = sources.nom_domaine
    )
    WHERE  nom_domaine = %s;
"""

SQL_INSERTION_RUN = """
    INSERT INTO extraction_runs
        (run_id, started_at, finished_at, nb_extraites,
         nb_valides, nb_rejetées, taux_intégrité)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (run_id) DO NOTHING;
"""

SQL_LIAISON_RUN_SOURCE = """
    INSERT INTO run_sources (run_id, nom_domaine)
    VALUES (%s, %s)
    ON CONFLICT DO NOTHING;
"""

# Alimente le tableau de bord (L6) : historique des runs et référentiel
# des sources — aucune logique, uniquement de la lecture (SELECT).
SQL_SELECT_RUNS = """
    SELECT   run_id, started_at, finished_at, nb_extraites,
             nb_valides, nb_rejetées, taux_intégrité
    FROM     extraction_runs
    ORDER BY started_at DESC
    LIMIT    %s;
"""

SQL_SELECT_SOURCES = """
    SELECT   nom_domaine, type_source, langue, méthode_extraction,
             première_extraction, dernière_extraction, nb_publications
    FROM     sources
    ORDER BY nb_publications DESC;
"""


# ##############################################################################
# CLASSE : PostgresqlAdapter
# ##############################################################################
class PostgresqlAdapter(PersistencePort):
    """
    Adaptateur de persistance PostgreSQL — implémente PersistencePort.

    Paramètres
    ----------
    config : dict
        Connexion : host, port, dbname, user, password.
        Injectée par le composition root — jamais lue ici.

    Utilisation
    -----------
    adaptateur = PostgresqlAdapter(config={...})
    insérée    = adaptateur.sauvegarder(publication)
    adaptateur.fermer()
    """

    # ##########################################################################
    def __init__(self, config: Dict[str, str]) -> None:
        self._config    = config             # Connexion injectée
        self._connexion = None               # Ouverte paresseusement
        self._log       = LogTool(origin="postgres")  # Logger RFC 5424

    # ##########################################################################
    def _obtenir_connexion(self):
        """
        Ouvre la connexion à la première utilisation (lazy) et garantit
        l'existence de la table publications (CREATE IF NOT EXISTS).
        """
        if self._connexion is None or self._connexion.closed:
            self._connexion = psycopg2.connect(**self._config)
            with self._connexion.cursor() as curseur:
                curseur.execute(SQL_CREATION_TABLES)
            self._connexion.commit()
            self._log.LEVEL_6_NOTICE(
                "PostgresqlAdapter",
                f"Connexion ouverte : {self._config.get('dbname')}"
                f"@{self._config.get('host')}",
            )
        return self._connexion

    # ##########################################################################
    def enregistrer_run(self, run: dict) -> None:
        """
        Historise un run d'extraction dans les trois tables associées.

        Séquence (transaction unique) :
          1. extraction_runs : la ligne de statistiques du run
          2. sources         : upsert de chaque source impliquée
             (première_extraction figée, dernière_extraction rafraîchie,
              nb_publications recalculé depuis publications)
          3. run_sources     : liaison N-N run ↔ sources

        Idempotence : ON CONFLICT DO NOTHING partout — rejouer un run
        avec le même run_id n'écrit jamais deux fois.
        """
        connexion = self._obtenir_connexion()
        with connexion.cursor() as curseur:
            # -- 1. La ligne du run ------------------------------------------------
            curseur.execute(
                SQL_INSERTION_RUN,
                (
                    run["run_id"],       run["started_at"],
                    run["finished_at"],  run["nb_extraites"],
                    run["nb_valides"],   run["nb_rejetées"],
                    run["taux_intégrité"],
                ),
            )
            # -- 2. et 3. Les sources impliquées et la liaison -----------------------
            for domaine in run.get("sources_domains", []):
                curseur.execute(SQL_UPSERT_SOURCE,      (domaine,))
                curseur.execute(SQL_MAJ_NB_PUBLICATIONS, (domaine,))
                curseur.execute(
                    SQL_LIAISON_RUN_SOURCE, (run["run_id"], domaine)
                )
        connexion.commit()
        self._log.LEVEL_6_NOTICE(
            "PostgresqlAdapter",
            f"Run historisé : {run['run_id']} "
            f"({len(run.get('sources_domains', []))} sources)",
        )

    # ##########################################################################
    def sauvegarder(self, publication: dict) -> bool:
        """
        Insère UNE publication de façon idempotente.

        ON CONFLICT (id) DO NOTHING : un id déjà présent n'insère rien
        (rowcount = 0) → rejouer le pipeline ne crée jamais de doublons.
        """
        connexion = self._obtenir_connexion()
        with connexion.cursor() as curseur:
            curseur.execute(
                SQL_INSERTION,
                (
                    publication["id"],
                    publication["title"],
                    publication["content"],
                    publication["image_url"],
                    publication["source_domain"],
                    publication["declared_label"],
                    publication["lang"],
                    publication["captured_at"],
                    json.dumps(
                        publication.get("metadata", {}),
                        ensure_ascii=False,
                    ),
                ),
            )
            insérée = curseur.rowcount == 1  # 0 = doublon (conflit id)
        connexion.commit()
        return insérée

    # ##########################################################################
    def existe(self, id_publication: str) -> bool:
        """Vérifie la présence d'une publication par son identifiant."""
        connexion = self._obtenir_connexion()
        with connexion.cursor() as curseur:
            curseur.execute(
                "SELECT 1 FROM publications WHERE id = %s;",
                (id_publication,),
            )
            return curseur.fetchone() is not None

    # ##########################################################################
    def compter_par_source(self) -> Dict[str, int]:
        """Nombre de publications par source (KPI dashboard L6)."""
        connexion = self._obtenir_connexion()
        with connexion.cursor() as curseur:
            curseur.execute("""
                SELECT   source_domain, COUNT(*)
                FROM     publications
                GROUP BY source_domain
                ORDER BY COUNT(*) DESC;
            """)
            return dict(curseur.fetchall())

    # ##########################################################################
    def compter_par_label(self) -> Dict[str, int]:
        """Répartition REAL / FAKE du dataset (KPI dashboard L6)."""
        connexion = self._obtenir_connexion()
        with connexion.cursor() as curseur:
            curseur.execute("""
                SELECT   declared_label, COUNT(*)
                FROM     publications
                GROUP BY declared_label;
            """)
            return dict(curseur.fetchall())

    # ##########################################################################
    def dernières_entrées(self, limite: int = 10) -> List[dict]:
        """Les N publications les plus récentes (fraîcheur des données)."""
        connexion = self._obtenir_connexion()
        with connexion.cursor() as curseur:
            curseur.execute(
                """
                SELECT   id, title, source_domain, declared_label,
                         captured_at
                FROM     publications
                ORDER BY captured_at DESC
                LIMIT    %s;
                """,
                (limite,),
            )
            colonnes = [col[0] for col in curseur.description]
            return [dict(zip(colonnes, ligne)) for ligne in curseur]

    # ##########################################################################
    def obtenir_runs(self, limite: int = 20) -> List[dict]:
        """Historique des derniers runs d'extraction (KPI L6)."""
        connexion = self._obtenir_connexion()
        with connexion.cursor() as curseur:
            curseur.execute(SQL_SELECT_RUNS, (limite,))
            colonnes = [col[0] for col in curseur.description]
            return [dict(zip(colonnes, ligne)) for ligne in curseur]

    # ##########################################################################
    def obtenir_sources(self) -> List[dict]:
        """État complet du référentiel des sources (KPI L6)."""
        connexion = self._obtenir_connexion()
        with connexion.cursor() as curseur:
            curseur.execute(SQL_SELECT_SOURCES)
            colonnes = [col[0] for col in curseur.description]
            return [dict(zip(colonnes, ligne)) for ligne in curseur]

    # ##########################################################################
    def fermer(self) -> None:
        """Ferme proprement la connexion PostgreSQL."""
        if self._connexion is not None and not self._connexion.closed:
            self._connexion.close()
            self._log.LEVEL_6_NOTICE(
                "PostgresqlAdapter", "Connexion fermée"
            )
