# ==============================================================================
# src/ports/outbound/persistence_port.py — Port outbound de persistance
#
# Contrat que TOUTE technologie de stockage (PostgreSQL, MongoDB...) doit
# implémenter pour persister et interroger les publications du dataset.
#
# Règle absolue : ZÉRO import externe dans ce fichier (couche PORTS).
# Implémentation de référence : adapters/outbound/persistence/
#                               postgresql_adapter.py
#
# Les méthodes de comptage alimentent le futur dashboard KPI (L6) —
# le contrat anticipe l'Étape 5 sans coût supplémentaire.
# ==============================================================================

# --- Bibliothèque standard : classes abstraites et types ------------------------
from   abc    import ABC, abstractmethod   # Contrat d'interface abstrait
from   typing import Dict, List            # Annotations de types


# ##############################################################################
# PORT : PersistencePort
# ##############################################################################
class PersistencePort(ABC):
    """
    Contrat de persistance des publications CheckIt.AI.

    Les publications circulent sous forme de dictionnaires conformes au
    schéma physique (id, title, content, image_url, source_domain,
    declared_label, lang, captured_at, metadata).
    """

    # ##########################################################################
    @abstractmethod
    def sauvegarder(self, publication: dict) -> bool:
        """
        Persiste UNE publication de façon idempotente.

        Retourne
        --------
        bool : True si insérée, False si déjà présente (doublon d'id).
        """

    # ##########################################################################
    @abstractmethod
    def existe(self, id_publication: str) -> bool:
        """Indique si une publication est déjà persistée (par son id)."""

    # ##########################################################################
    @abstractmethod
    def compter_par_source(self) -> Dict[str, int]:
        """Nombre de publications par source_domain (KPI dashboard)."""

    # ##########################################################################
    @abstractmethod
    def compter_par_label(self) -> Dict[str, int]:
        """Répartition REAL / FAKE du dataset (KPI dashboard)."""

    # ##########################################################################
    @abstractmethod
    def dernières_entrées(self, limite: int = 10) -> List[dict]:
        """Les N publications les plus récentes (fraîcheur des données)."""

    # ##########################################################################
    @abstractmethod
    def obtenir_runs(self, limite: int = 20) -> List[dict]:
        """
        Historique des derniers runs d'extraction (table extraction_runs).

        Alimente les KPIs de précision (taux_intégrité) et de rapidité
        (durée started_at → finished_at) du tableau de bord (L6).
        """

    # ##########################################################################
    @abstractmethod
    def obtenir_sources(self) -> List[dict]:
        """
        État du référentiel des sources (table sources).

        Alimente le KPI de fraîcheur (dernière_extraction) et le volume
        par source du tableau de bord — permet de détecter une source
        tombée à zéro publication.
        """

    # ##########################################################################
    @abstractmethod
    def enregistrer_run(self, run: dict) -> None:
        """
        Historise un run d'extraction complet.

        Alimente les tables extraction_runs (statistiques du run),
        run_sources (liaison N-N run ↔ sources) et sources (mise à
        jour de dernière_extraction et nb_publications).

        Le dictionnaire run contient : run_id, started_at, finished_at,
        nb_extraites, nb_valides, nb_rejetées, taux_intégrité,
        sources_domains (liste des domaines impliqués).
        """

    # ##########################################################################
    @abstractmethod
    def fermer(self) -> None:
        """Libère proprement les ressources (connexion, curseurs)."""
