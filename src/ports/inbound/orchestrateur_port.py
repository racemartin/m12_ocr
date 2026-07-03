# ==============================================================================
# src/ports/inbound/orchestrateur_port.py — Port inbound de l'orchestration
#
# Contrat que TOUT déclencheur technique (Airflow, cron, CLI, API...) doit
# utiliser pour piloter le pipeline ETL. Le déclencheur ne connaît que ce
# port — jamais les services ni les adaptateurs concrets.
#
# Règle absolue : ZÉRO import externe dans ce fichier (couche PORTS).
# Implémentation de référence : src/application/pipeline_service.py
# ==============================================================================

# --- Bibliothèque standard : classes abstraites --------------------------------
from   abc import ABC, abstractmethod      # Contrat d'interface abstrait


# ##############################################################################
# PORT : OrchestreurPort
# ##############################################################################
class OrchestreurPort(ABC):
    """
    Contrat d'orchestration du pipeline ETL CheckIt.AI.

    Les cinq opérations correspondent aux cinq tâches atomiques du flux :
    extraction → validation → transformation → chargement → notification.

    Les échanges se font par CHEMINS de fichiers (str) et compteurs (int)
    — jamais par structures volumineuses : le déclencheur (ex. Airflow)
    peut ainsi les transmettre via son mécanisme natif (XCom).
    """

    # ##########################################################################
    @abstractmethod
    def exécuter_extraction(self) -> str:
        """
        Extrait les publications de toutes les sources configurées.

        Retourne
        --------
        str : chemin du fichier JSON brut produit (data/raw/...).
        """

    # ##########################################################################
    @abstractmethod
    def exécuter_validation(self, chemin_brut: str) -> int:
        """
        Contrôle l'intégrité du lot brut avant transformation.

        Lève une exception si le lot est vide ou illisible (le
        déclencheur décide alors : retry, alerte, arrêt).

        Retourne
        --------
        int : nombre d'entrées du lot validé.
        """

    # ##########################################################################
    @abstractmethod
    def exécuter_transformation(self) -> str:
        """
        Applique le pipeline de transformation (Étape 3) au lot brut.

        Retourne
        --------
        str : chemin du fichier JSON propre (data/processed/...).
        """

    # ##########################################################################
    @abstractmethod
    def exécuter_chargement(self, chemin_propre: str) -> int:
        """
        Charge les publications propres dans la base de persistance.

        Retourne
        --------
        int : nombre de publications réellement insérées (hors doublons).
        """

    # ##########################################################################
    @abstractmethod
    def exécuter_notification(self, insérées: int) -> None:
        """
        Publie le rapport final du run (logs, KPIs, alertes).
        """
