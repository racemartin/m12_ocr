# ==============================================================================
# src/ports/outbound/persistence_port.py — Contrat de persistence
#
# Règle absolue : ZÉRO import externe dans ce fichier.
# Ce port définit le contrat que tous les adaptateurs de persistence
# doivent respecter — PostgreSQL, MongoDB ou tout autre SGBD futur.
#
# Cas d'usage couverts :
#   - Sauvegarde d'une publication validée
#   - Vérification de l'existence d'une publication (déduplication)
#   - Comptage des entrées par source et par label
#   - Récupération des dernières entrées rejetées (dashboard KPI)
# ==============================================================================

# --- Bibliothèque standard uniquement ----------------------------------------
from abc     import ABC, abstractmethod  # contrat abstrait non instanciable
from typing  import Dict, List, Optional # annotations de types


# --- Import domaine (autorisé — même couche logique) -------------------------
from src.domain.models import Publication  # entité à persister


# ==============================================================================
# PORT : PersistencePort
# ==============================================================================
class PersistencePort(ABC):
    """
    Contrat abstrait pour tous les adaptateurs de persistence.

    Définit les opérations CRUD minimales requises par le pipeline ETL.
    Les adaptateurs implémentent ce contrat pour PostgreSQL et MongoDB.

    Implémentations attendues
    -------------------------
    - PostgresqlAdapter : persistence SQL structurée (recommandé)
    - MongodbAdapter    : persistence NoSQL flexible (alternatif)
    """

    # --------------------------------------------------------------------------
    @abstractmethod
    def sauvegarder(self, publication: Publication) -> bool:
        """
        Persiste une publication validée dans la base de données.

        Paramètres
        ----------
        publication : Publication
            Instance validée par le pipeline de transformation.

        Retourne
        --------
        bool
            True si la sauvegarde a réussi, False sinon.

        Lève
        ----
        CheckItErreur
            Si la connexion à la base de données échoue.
        """

    # --------------------------------------------------------------------------
    @abstractmethod
    def existe(self, publication_id: str) -> bool:
        """
        Vérifie si une publication existe déjà (déduplication).

        Utilisé avant la sauvegarde pour éviter les doublons —
        l'id SHA-256 garantit l'unicité du contenu.

        Paramètres
        ----------
        publication_id : str
            Hash SHA-256 de la publication à rechercher.

        Retourne
        --------
        bool
            True si la publication existe déjà en base.
        """

    # --------------------------------------------------------------------------
    @abstractmethod
    def compter_par_source(self) -> Dict[str, int]:
        """
        Retourne le nombre de publications par source.

        Utilisé par le dashboard Streamlit pour afficher
        la distribution des données par source d'extraction.

        Retourne
        --------
        Dict[str, int]
            Ex. : {"afp.com": 142, "snopes.com": 89, "reddit.com": 203}
        """

    # --------------------------------------------------------------------------
    @abstractmethod
    def compter_par_label(self) -> Dict[str, int]:
        """
        Retourne le nombre de publications par label REAL/FAKE.

        Utilisé par le dashboard pour afficher l'équilibre du dataset.

        Retourne
        --------
        Dict[str, int]
            Ex. : {"REAL": 312, "FAKE": 287}
        """

    # --------------------------------------------------------------------------
    @abstractmethod
    def dernières_entrées(self, limite: int = 10) -> List[Publication]:
        """
        Retourne les N dernières publications sauvegardées.

        Paramètres
        ----------
        limite : int
            Nombre maximum d'entrées à retourner (défaut : 10).

        Retourne
        --------
        List[Publication]
            Publications triées par date de capture décroissante.
        """
