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
# SCHÉMA PHYSIQUE — table publications (aligné sur le livrable L4)
# ==============================================================================
SQL_CREATION_TABLE = """
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
"""

SQL_INSERTION = """
    INSERT INTO publications
        (id, title, content, image_url, source_domain,
         declared_label, lang, captured_at, metadata)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (id) DO NOTHING;
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
                curseur.execute(SQL_CREATION_TABLE)
            self._connexion.commit()
            self._log.LEVEL_6_NOTICE(
                "PostgresqlAdapter",
                f"Connexion ouverte : {self._config.get('dbname')}"
                f"@{self._config.get('host')}",
            )
        return self._connexion

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
    def fermer(self) -> None:
        """Ferme proprement la connexion PostgreSQL."""
        if self._connexion is not None and not self._connexion.closed:
            self._connexion.close()
            self._log.LEVEL_6_NOTICE(
                "PostgresqlAdapter", "Connexion fermée"
            )
