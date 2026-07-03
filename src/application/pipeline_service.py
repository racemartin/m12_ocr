# ==============================================================================
# src/application/pipeline_service.py — Service d'orchestration du pipeline
#
# Implémentation de référence du port inbound OrchestreurPort.
# TOUTE la logique d'orchestration vit ici — le déclencheur technique
# (DAG Airflow, cron, CLI) n'est qu'un adaptateur mince qui appelle les
# cinq méthodes du contrat.
#
# Injection de configuration (principe hexagonal) :
#   - La couche application n'importe JAMAIS airflow : les paramètres
#     techniques (credentials PostgreSQL, drapeaux) sont INJECTÉS par
#     l'adaptateur via le constructeur.
#
# Dette technique documentée :
#   - exécuter_chargement() utilise psycopg2 en direct ; il migrera vers
#     PersistencePort → PostgresqlAdapter au branchement de la couche
#     persistence (le contrat du port, lui, ne changera pas).
# ==============================================================================

# --- Bibliothèque standard : fichiers et horodatage ----------------------------
import json                                # Sérialisation des lots JSON
import sys                                 # Bootstrap du chemin projet (main)

from   datetime import datetime            # Horodatage des fichiers bruts
from   pathlib  import Path                # Chemins portables
from   typing   import Dict                # Annotations de types

# --- Couches du projet : port implémenté, services et adaptateurs --------------
from   src.adapters.outbound.scrapers.feedparser_adapter import (
    FeedparserAdapter,                     # Extraction RSS (7 sources)
)
from   src.application.transform_service   import TransformService
from   src.ports.inbound.orchestrateur_port import OrchestreurPort
from   src.tools.rafael.log_tool            import LogTool


# ==============================================================================
# CONFIGURATION PAR DÉFAUT — sources RSS opérationnelles (Étape 2)
# ==============================================================================
SOURCES_RSS_DÉFAUT = {
    "afp_bluesky" : ("https://bsky.app/profile/"
                     "did:plc:4ks5wkubjfcbgxvphqkd3wxm/rss"),
    "euvsdisinfo" : "https://euvsdisinfo.eu/feed/",
    "hoaxbuster"  : "https://www.hoaxbuster.com/rss/",
    "elpais"      : ("https://feeds.elpais.com/mrss-s/pages/ep/site/"
                     "elpais.com/portada"),
    "politifact"  : "https://www.politifact.com/rss/factchecks/",
    "decodeurs"   : "https://www.lemonde.fr/les-decodeurs/rss_full.xml",
    "chequeado"   : "https://chequeado.com/feed/",
}


# ##############################################################################
# CLASSE : PipelineService
# ##############################################################################
class PipelineService(OrchestreurPort):
    """
    Orchestrateur du pipeline ETL — implémente OrchestreurPort.

    Paramètres
    ----------
    racine_projet : Path
        Racine du projet (les dossiers data/raw et data/processed
        en sont dérivés).
    sources_rss : dict
        Identifiant de source → URL du flux (défaut : les 7 sources
        opérationnelles de l'Étape 2).
    config_pg : dict
        Connexion PostgreSQL : host, port, dbname, user, password.
        INJECTÉE par l'adaptateur (Variables Airflow, .env, CLI...) —
        jamais lue ici, jamais en dur.
    vérifier_images : bool
        Transmis au TransformService (validation HTTP des images).

    Utilisation
    -----------
    service = PipelineService(racine, config_pg={...})
    chemin  = service.exécuter_extraction()
    service.exécuter_validation(chemin)
    ...
    """

    # ##########################################################################
    def __init__(
        self,
        racine_projet   : Path,
        sources_rss     : Dict[str, str] = None,
        config_pg       : Dict[str, str] = None,
        vérifier_images : bool           = False,
    ) -> None:
        self._racine          = Path(racine_projet)   # Racine du projet
        self._dossier_brut    = self._racine / "data" / "raw"
        self._dossier_propre  = self._racine / "data" / "processed"
        self._sources         = sources_rss or SOURCES_RSS_DÉFAUT
        self._config_pg       = config_pg or {}       # Injecté par l'adaptateur
        self._vérifier_images = vérifier_images       # Validation HTTP images
        self._log             = LogTool(origin="pipeline")  # Logger RFC 5424

    # ##########################################################################
    # OPÉRATION 1 — EXTRACTION
    # ##########################################################################
    def exécuter_extraction(self) -> str:
        """
        Extrait les publications des sources RSS et persiste le lot brut.

        Une source en échec est journalisée mais ne bloque pas les
        autres — robustesse aux pannes partielles.
        """
        self._log.START_ACTION(
            "PipelineService", "exécuter_extraction",
            f"{len(self._sources)} sources RSS"
        )
        publications = []

        for source, url in self._sources.items():
            try:
                adaptateur = FeedparserAdapter(source=source)
                lot        = adaptateur.extraire_données(url)
                publications.extend(lot)
                self._log.PARAMETER_VALUE(source, f"{len(lot)} publications")
            except Exception as erreur:
                # Panne partielle : on continue avec les autres sources
                self._log.LEVEL_4_ERROR(
                    "PipelineService", f"{source} en échec : {erreur}"
                )

        # -- Sérialisation du lot brut (horodaté = traçabilité des runs) --------
        self._dossier_brut.mkdir(parents=True, exist_ok=True)
        horodatage = datetime.now().strftime("%Y-%m-%d_%H-%M")
        chemin     = self._dossier_brut / f"etl_extraction_{horodatage}.json"
        chemin.write_text(
            json.dumps(
                [pub.__dict__ for pub in publications],
                ensure_ascii = False,
                indent       = 2,
                default      = str,          # Enum et datetime → str
            ),
            encoding="utf-8",
        )

        self._log.FINISH_ACTION(
            "PipelineService", "exécuter_extraction",
            f"{len(publications)} publications → {chemin.name}"
        )
        return str(chemin)

    # ##########################################################################
    # OPÉRATION 2 — VALIDATION DU LOT BRUT
    # ##########################################################################
    def exécuter_validation(self, chemin_brut: str) -> int:
        """
        Vérifie l'intégrité du lot brut : lisible, non vide, paires
        texte-image présentes. Lot vide → exception → le déclencheur
        applique sa politique (retries Airflow, alerte).
        """
        self._log.START_ACTION(
            "PipelineService", "exécuter_validation", chemin_brut
        )

        lot = json.loads(Path(chemin_brut).read_text(encoding="utf-8"))
        if not lot:
            raise ValueError(f"Lot brut vide : {chemin_brut}")

        # -- Contrôle de présence des champs indispensables ---------------------
        complets = sum(
            1 for pub in lot
            if pub.get("title") and pub.get("image_url")
        )
        self._log.PARAMETER_VALUE("entrées dans le lot", len(lot))
        self._log.PARAMETER_VALUE("paires texte-image", complets)
        self._log.FINISH_ACTION(
            "PipelineService", "exécuter_validation", f"{len(lot)} OK"
        )
        return len(lot)

    # ##########################################################################
    # OPÉRATION 3 — TRANSFORMATION (Étape 3)
    # ##########################################################################
    def exécuter_transformation(self) -> str:
        """
        Délègue au TransformService (Étape 3 / L3) : lecture des bruts,
        nettoyage, normalisation, validation, dédoublonnage, export.
        """
        service = TransformService(
            dossier_brut    = self._dossier_brut,
            dossier_sortie  = self._dossier_propre,
            vérifier_images = self._vérifier_images,
        )
        stats = service.exécuter()
        return stats["sorties"]["json"]      # Chemin du dataset propre

    # ##########################################################################
    # OPÉRATION 4 — CHARGEMENT (PostgreSQL)
    # ##########################################################################
    def exécuter_chargement(self, chemin_propre: str) -> int:
        """
        Charge les publications propres dans la table publications.

        Sécurité : connexion injectée (jamais en dur), INSERT paramétré
        (aucune injection SQL), ON CONFLICT (id) DO NOTHING = idempotence
        (rejouer le pipeline ne crée jamais de doublons).

        NOTE dette technique : psycopg2 direct — migrera vers
        PersistencePort → PostgresqlAdapter sans changer ce contrat.
        """
        import psycopg2                      # Import local : dépendance
                                             # limitée à cette opération

        lot = json.loads(Path(chemin_propre).read_text(encoding="utf-8"))
        self._log.START_ACTION(
            "PipelineService", "exécuter_chargement",
            f"{len(lot)} publications"
        )

        connexion = psycopg2.connect(**self._config_pg)
        curseur   = connexion.cursor()

        # -- Création de la table si absente (schéma physique L4) ---------------
        curseur.execute("""
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
        """)

        # -- Insertion idempotente ------------------------------------------------
        insérées = 0
        for pub in lot:
            curseur.execute(
                """
                INSERT INTO publications
                    (id, title, content, image_url, source_domain,
                     declared_label, lang, captured_at, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING;
                """,
                (
                    pub["id"],            pub["title"],
                    pub["content"],       pub["image_url"],
                    pub["source_domain"], pub["declared_label"],
                    pub["lang"],          pub["captured_at"],
                    json.dumps(
                        pub.get("metadata", {}), ensure_ascii=False
                    ),
                ),
            )
            insérées += curseur.rowcount     # 0 si doublon (conflit id)

        connexion.commit()
        curseur.close()
        connexion.close()

        self._log.FINISH_ACTION(
            "PipelineService", "exécuter_chargement", f"{insérées} insérées"
        )
        return insérées

    # ##########################################################################
    # OPÉRATION 5 — NOTIFICATION
    # ##########################################################################
    def exécuter_notification(self, insérées: int) -> None:
        """
        Publie le rapport final du run dans les logs.

        Source des chiffres : stats_transformation.json (Étape 3).
        En production, cette opération enverra aussi un email (L7).
        """
        stats = json.loads(
            (self._dossier_propre / "stats_transformation.json")
            .read_text(encoding="utf-8")
        )

        print("\n==========================================================")
        print("RAPPORT ETL — CHECKIT.AI")
        print("==========================================================")
        print(f"  Entrées brutes......: {stats['entrées_brutes']}")
        print(f"  Publications valides: {stats['valides']}")
        print(f"  Taux d'intégrité....: {stats['taux_intégrité']}%")
        print(f"  REAL / FAKE.........: "
              f"{stats['répartition']['REAL']} / "
              f"{stats['répartition']['FAKE']}")
        print(f"  Insérées en base....: {insérées}")
        print("==========================================================")
        self._log.LEVEL_6_NOTICE(
            "PipelineService", "Run ETL terminé — rapport publié"
        )


# ==============================================================================
# POINT D'ENTRÉE : exécution complète hors Airflow (démo et débogage)
# ==============================================================================
if __name__ == "__main__":
    # Bootstrap : ajoute la racine du projet au chemin des imports
    RACINE = Path(__file__).resolve().parents[2]
    if str(RACINE) not in sys.path:
        sys.path.insert(0, str(RACINE))

    service = PipelineService(
        racine_projet = RACINE,
        config_pg     = {                    # Démo locale — en production,
            "host"     : "localhost",        # ces valeurs sont injectées
            "port"     : "5432",             # par l'adaptateur (Variables
            "dbname"   : "checkit",          # Airflow, .env...)
            "user"     : "checkit",
            "password" : "checkit",
        },
    )
    chemin_brut   = service.exécuter_extraction()
    service.exécuter_validation(chemin_brut)
    chemin_propre = service.exécuter_transformation()
    insérées      = service.exécuter_chargement(chemin_propre)
    service.exécuter_notification(insérées)
