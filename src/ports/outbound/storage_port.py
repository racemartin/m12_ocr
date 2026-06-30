# ==============================================================================
# src/ports/outbound/storage_port.py — Contrat de stockage brut
#
# Règle absolue : ZÉRO import externe dans ce fichier.
# Ce port gère la persistence intermédiaire des données brutes
# extraites avant transformation — fichiers JSON/CSV dans data/raw/.
#
# Distinction avec PersistencePort :
#   StoragePort   → données brutes non transformées (data/raw/)
#   PersistencePort → données validées et normalisées (PostgreSQL/MongoDB)
# ==============================================================================

# --- Bibliothèque standard uniquement ----------------------------------------
from abc    import ABC, abstractmethod  # contrat abstrait non instanciable
from typing import Any, Dict, List      # annotations de types


# ==============================================================================
# PORT : StoragePort
# ==============================================================================
class StoragePort(ABC):
    """
    Contrat abstrait pour le stockage des données brutes.

    Gère l'écriture et la lecture des fichiers intermédiaires
    entre l'étape d'extraction et l'étape de transformation.

    Implémentations attendues
    -------------------------
    - JsonStorageAdapter : stockage JSON dans data/raw/
    - CsvStorageAdapter  : stockage CSV dans data/raw/
    """

    # --------------------------------------------------------------------------
    @abstractmethod
    def écrire_brut(
        self,
        données   : List[Dict[str, Any]],
        nom_source: str,
    ) -> str:
        """
        Écrit les données brutes extraites dans un fichier.

        Le nom du fichier est généré automatiquement avec
        la date et le nom de la source pour la traçabilité.

        Paramètres
        ----------
        données    : List[Dict]
            Liste de dictionnaires bruts (non transformés).
        nom_source : str
            Identifiant de la source (ex. : "afp_rss", "reddit").

        Retourne
        --------
        str
            Chemin absolu du fichier créé.
        """

    # --------------------------------------------------------------------------
    @abstractmethod
    def lire_brut(self, chemin_fichier: str) -> List[Dict[str, Any]]:
        """
        Lit les données brutes depuis un fichier existant.

        Paramètres
        ----------
        chemin_fichier : str
            Chemin absolu du fichier à lire.

        Retourne
        --------
        List[Dict]
            Liste de dictionnaires bruts.

        Lève
        ----
        FileNotFoundError
            Si le fichier n'existe pas.
        """

    # --------------------------------------------------------------------------
    @abstractmethod
    def lister_fichiers_bruts(self, nom_source: str = "") -> List[str]:
        """
        Liste les fichiers bruts disponibles dans data/raw/.

        Paramètres
        ----------
        nom_source : str
            Filtre optionnel par source (chaîne vide = tous).

        Retourne
        --------
        List[str]
            Liste des chemins absolus triés par date décroissante.
        """
