# ==============================================================================
# src/ports/outbound/scraper_port.py — Contrat d'extraction de données
#
# Règle absolue : ZÉRO import externe dans ce fichier.
# Ce port définit le contrat que TOUS les adaptateurs d'extraction
# doivent respecter — indépendamment de la technologie utilisée
# (BeautifulSoup, Scrapy, Selenium, Requests, Feedparser...).
#
# Cas d'usage couverts :
#   - Extraction depuis une API REST (JSON)
#   - Extraction depuis un flux RSS/Atom (XML)
#   - Extraction depuis un site HTML statique (BeautifulSoup)
#   - Extraction depuis un site JavaScript dynamique (Selenium)
#   - Extraction depuis un crawl multi-pages (Scrapy)
# ==============================================================================

# --- Bibliothèque standard uniquement ----------------------------------------
from abc      import ABC, abstractmethod  # contrat abstrait non instanciable
from typing   import List                 # annotations de types


# --- Import domaine (autorisé — même couche logique) -------------------------
from src.domain.models import Publication  # entité cible de l'extraction


# ==============================================================================
# PORT : ScraperPort
# ==============================================================================
class ScraperPort(ABC):
    """
    Contrat abstrait pour tous les adaptateurs d'extraction.

    Chaque source de données (API, RSS, HTML, SPA) doit implémenter
    ce port via un adaptateur dédié dans adapters/outbound/scrapers/.

    Règle d'or : aucune logique métier dans les adaptateurs.
    Toute validation appartient au domaine (Publication.est_valide()).

    Implémentations attendues
    -------------------------
    - Bs4Adapter       : sites HTML statiques (BeautifulSoup)
    - RequestsAdapter  : APIs REST JSON + flux RSS (Feedparser)
    - ScrapyAdapter    : portails avec pagination multi-pages
    - SeleniumAdapter  : applications SPA JavaScript dynamiques
    """

    # --------------------------------------------------------------------------
    @abstractmethod
    def extraire_données(self, source_url: str) -> List[Publication]:
        """
        Extrait une liste de publications depuis une source distante.

        Paramètres
        ----------
        source_url : str
            URL complète de la source à extraire.
            Ex. : "https://feeds.afp.com/afp/fr/actualites"

        Retourne
        --------
        List[Publication]
            Liste d'instances Publication extraites et mappées.
            Liste vide [] si aucune publication valide trouvée.

        Lève
        ----
        CheckItErreur
            Si l'extraction échoue de manière non récupérable.
        """

    # --------------------------------------------------------------------------
    @abstractmethod
    def est_disponible(self, source_url: str) -> bool:
        """
        Vérifie l'accessibilité d'une source avant extraction.

        Appelé par le DAG Airflow avant chaque extract_task pour
        éviter de lancer une extraction sur une source hors ligne.

        Paramètres
        ----------
        source_url : str
            URL à tester (HEAD request recommandée).

        Retourne
        --------
        bool
            True si la source répond correctement (HTTP 200/301/302).
        """

    # --------------------------------------------------------------------------
    @property
    @abstractmethod
    def nom_source(self) -> str:
        """
        Identifiant lisible de la source gérée par cet adaptateur.

        Utilisé dans les logs et les KPIs du dashboard Streamlit.

        Retourne
        --------
        str
            Ex. : "AFP Factuel RSS", "NewsData.io API", "Reddit PRAW"
        """
