# ==============================================================================
# src/application/pipeline_service.py — Service d'orchestration du pipeline
#
# Implémentation de référence du port inbound OrchestreurPort.
# TOUTE la logique d'orchestration vit ici — le déclencheur technique
# (DAG Airflow, cron, CLI) n'est qu'un adaptateur mince qui appelle les
# cinq méthodes du contrat.
#
# Injection de dépendances (principe hexagonal) :
#   - La couche application n'importe JAMAIS airflow ni psycopg2 : la
#     persistance arrive par le contrat PersistencePort, et les
#     paramètres techniques sont INJECTÉS par le composition root
#     (.env en CLI, Variables Airflow dans le DAG).
# ==============================================================================

# --- Bibliothèque standard : fichiers et horodatage ----------------------------
import json                                # Sérialisation des lots JSON
import os                                  # Lecture des variables du .env
import sys                                 # Bootstrap du chemin projet (main)

from   datetime import datetime, timezone  # Horodatage et identifiant de run
from   pathlib  import Path                # Chemins portables
from   typing   import Dict                # Annotations de types

# --- Racine du projet : indispensable AVANT les imports src.* ------------------
# En exécution directe (python3 src/application/pipeline_service.py),
# Python place src/application/ dans sys.path — pas la racine du projet.
RACINE_PROJET = Path(__file__).resolve().parents[2]
if str(RACINE_PROJET) not in sys.path:
    sys.path.insert(0, str(RACINE_PROJET))

# --- Couches du projet : ports implémentés/consommés et services ----------------
from   src.adapters.outbound.scrapers.feedparser_adapter import (
    FeedparserAdapter,                     # Extraction RSS (7 sources)
)
from   src.application.transform_service    import TransformService
from   src.ports.inbound.orchestrateur_port import OrchestreurPort
from   src.ports.outbound.persistence_port  import PersistencePort
from   src.tools.rafael.log_tool             import LogTool


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
    persistence : PersistencePort
        Adaptateur de persistance INJECTÉ (PostgresqlAdapter en
        production, adaptateur mémoire dans les tests). La couche
        application ne connaît que le contrat, jamais la technologie.
    sources_rss : dict
        Identifiant de source → URL du flux (défaut : les 7 sources
        opérationnelles de l'Étape 2).
    vérifier_images : bool
        Transmis au TransformService (validation HTTP des images).

    Utilisation
    -----------
    service = PipelineService(racine, persistence=PostgresqlAdapter(...))
    chemin  = service.exécuter_extraction()
    service.exécuter_validation(chemin)
    ...
    """

    # ##########################################################################
    def __init__(
        self,
        racine_projet   : Path,
        persistence     : PersistencePort,
        sources_rss     : Dict[str, str] = None,
        vérifier_images : bool           = False,
    ) -> None:
        self._racine          = Path(racine_projet)   # Racine du projet
        self._dossier_brut    = self._racine / "data" / "raw"
        self._dossier_propre  = self._racine / "data" / "processed"
        self._persistence     = persistence           # Port de persistance
        self._sources         = sources_rss or SOURCES_RSS_DÉFAUT
        self._vérifier_images = vérifier_images       # Validation HTTP images
        self._log             = LogTool(origin="pipeline")  # Logger RFC 5424
        self._run_id          = (                     # Identifiant unique du
            "run_"                                    # run — sous Airflow, le
            + datetime.now().strftime("%Y%m%d_%H%M%S")  # dag_run.run_id
        )                                             # pourra l'écraser

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
    # OPÉRATION 4 — CHARGEMENT (via PersistencePort)
    # ##########################################################################
    def exécuter_chargement(self, chemin_propre: str) -> int:
        """
        Charge les publications propres via le port de persistance.

        La couche application ignore la technologie de stockage :
        elle compte simplement les insertions confirmées par le
        contrat (sauvegarder → True si insérée, False si doublon).
        L'idempotence et la sécurité SQL vivent dans l'adaptateur.
        """
        lot = json.loads(Path(chemin_propre).read_text(encoding="utf-8"))
        self._log.START_ACTION(
            "PipelineService", "exécuter_chargement",
            f"{len(lot)} publications"
        )

        insérées = 0
        try:
            for publication in lot:
                if self._persistence.sauvegarder(publication):
                    insérées += 1

            # -- Historisation du run (extraction_runs / sources / liaison) -----
            # Faite ICI (même instance que la boucle) : sous Airflow chaque
            # tâche construit son propre service — les compteurs viennent
            # donc du fichier de stats, pas d'un état en mémoire.
            stats = json.loads(
                (self._dossier_propre / "stats_transformation.json")
                .read_text(encoding="utf-8")
            )
            self._persistence.enregistrer_run({
                "run_id"          : self._run_id,
                "started_at"      : stats["exécuté_le"],
                "finished_at"     : datetime.now(timezone.utc).isoformat(),
                "nb_extraites"    : stats["entrées_brutes"],
                "nb_valides"      : stats["valides"],
                "nb_rejetées"     : stats["rejetées"],
                "taux_intégrité"  : stats["taux_intégrité"],
                "sources_domains" : sorted(
                    {pub["source_domain"] for pub in lot}
                ),
            })
        finally:
            self._persistence.fermer()       # Libération garantie

        self._log.PARAMETER_VALUE("doublons ignorés", len(lot) - insérées)
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
# POINT D'ENTRÉE : composition root CLI (démo et débogage hors Airflow)
# ==============================================================================
# C'est ICI que les pièces s'assemblent : chargement du .env, construction
# de l'adaptateur de persistance, injection dans le service. Aucune
# credential n'apparaît dans le code — tout vient du fichier .env
# (CHECKIT_PG_HOST, CHECKIT_PG_PORT, CHECKIT_PG_DB, CHECKIT_PG_USER,
#  CHECKIT_PG_PASSWORD, CHECKIT_VERIFIER_IMAGES).
# Même mécanisme que la phase d'extraction : python-dotenv.
if __name__ == "__main__":
    from dotenv import load_dotenv           # Chargement du fichier .env

    from src.adapters.outbound.persistence.postgresql_adapter import (
        PostgresqlAdapter,
    )

    # -- Chargement du .env (les variables déjà exportées gardent priorité) -----
    load_dotenv(RACINE_PROJET / ".env")
    if not os.environ.get("CHECKIT_PG_PASSWORD"):
        sys.exit(
            "ERREUR : CHECKIT_PG_PASSWORD absent du fichier .env — "
            "voir .env.example"
        )

    persistance = PostgresqlAdapter(config={
        "host"     : os.environ.get("CHECKIT_PG_HOST", "localhost"),
        "port"     : os.environ.get("CHECKIT_PG_PORT", "5432"),
        "dbname"   : os.environ.get("CHECKIT_PG_DB",   "checkit"),
        "user"     : os.environ.get("CHECKIT_PG_USER", "checkit"),
        "password" : os.environ["CHECKIT_PG_PASSWORD"],
    })

    service = PipelineService(
        racine_projet   = RACINE_PROJET,
        persistence     = persistance,
        vérifier_images = os.environ.get(
            "CHECKIT_VERIFIER_IMAGES", "False"
        ).lower() == "true",
    )
    chemin_brut   = service.exécuter_extraction()
    service.exécuter_validation(chemin_brut)
    chemin_propre = service.exécuter_transformation()
    insérées      = service.exécuter_chargement(chemin_propre)
    service.exécuter_notification(insérées)
