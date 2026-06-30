# ==============================================================================
# src/ports/inbound/orchestrateur_port.py — Contrat d'orchestration
#
# Règle absolue : ZÉRO import externe dans ce fichier.
# Ce port définit le contrat que le DAG Airflow doit respecter
# pour déclencher le pipeline ETL CheckIt.AI.
#
# C'est le seul point d'entrée autorisé dans le domaine depuis
# l'extérieur — le DAG appelle ce port, pas le domaine directement.
# ==============================================================================

# --- Bibliothèque standard uniquement ----------------------------------------
from abc     import ABC, abstractmethod  # contrat abstrait non instanciable
from typing  import Dict, Any            # annotations de types


# ==============================================================================
# PORT : OrchestreurPort
# ==============================================================================
class OrchestreurPort(ABC):
    """
    Contrat abstrait pour l'orchestrateur du pipeline ETL.

    Le DAG Airflow implémente ce port — il déclenche chaque étape
    du pipeline en respectant la séquence définie par le domaine :
    extraction → validation → transformation → chargement → notification.

    Implémentations attendues
    -------------------------
    - AirflowDag : adaptateur inbound dans adapters/inbound/airflow_dag.py
    """

    # --------------------------------------------------------------------------
    @abstractmethod
    def exécuter_extraction(self, **contexte: Any) -> Dict[str, Any]:
        """
        Déclenche l'étape d'extraction depuis toutes les sources.

        Correspond à extract_task dans le DAG Airflow.

        Paramètres
        ----------
        **contexte : Any
            Contexte Airflow passé par XCom entre les tâches.

        Retourne
        --------
        Dict[str, Any]
            Résultats : nombre d'entrées extraites, chemins fichiers,
            temps d'exécution, erreurs rencontrées.
        """

    # --------------------------------------------------------------------------
    @abstractmethod
    def exécuter_validation(self, **contexte: Any) -> Dict[str, Any]:
        """
        Vérifie l'intégrité des données brutes extraites.

        Correspond à validate_raw_task dans le DAG Airflow.
        Rejette les entrées sans paire texte-image complète.

        Retourne
        --------
        Dict[str, Any]
            Résultats : entrées valides, rejetées, taux d'intégrité.
        """

    # --------------------------------------------------------------------------
    @abstractmethod
    def exécuter_transformation(self, **contexte: Any) -> Dict[str, Any]:
        """
        Applique clean_text(), validate_image(), normalize_label().

        Correspond à transform_task dans le DAG Airflow.

        Retourne
        --------
        Dict[str, Any]
            Résultats : entrées transformées, rejetées, statistiques.
        """

    # --------------------------------------------------------------------------
    @abstractmethod
    def exécuter_chargement(self, **contexte: Any) -> Dict[str, Any]:
        """
        Persiste les données transformées en base de données.

        Correspond à load_task dans le DAG Airflow.

        Retourne
        --------
        Dict[str, Any]
            Résultats : entrées sauvegardées, doublons ignorés.
        """

    # --------------------------------------------------------------------------
    @abstractmethod
    def exécuter_notification(self, **contexte: Any) -> None:
        """
        Envoie le rapport d'exécution du pipeline.

        Correspond à notify_task dans le DAG Airflow.
        Envoie email + log critique si seuil d'alerte atteint.
        """
