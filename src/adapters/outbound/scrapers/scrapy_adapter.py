# ==============================================================================
# src/adapters/outbound/scrapers/scrapy_adapter.py
# Adaptateur Scrapy — Crawling multi-pages
#
# Source couverte (originale) :
#   Poynter IFCN (International Fact-Checking Network)
#   https://www.poynter.org/ifcn-fact-checkers/
#
#   L'IFCN est le réseau mondial des fact-checkers certifiés.
#   Il regroupe 120+ organisations dans 65+ pays — signataires
#   d'un code de principes strict. Leurs articles sont la référence
#   mondiale en matière de vérification des faits.
#
#   Autres sources Scrapy :
#   - PolitiFact (EN)  : https://www.politifact.com/factchecks/
#     Labels : TRUE / MOSTLY TRUE / HALF TRUE / MOSTLY FALSE / FALSE / PANTS ON FIRE
#   - Les Surligneurs (FR) : https://www.lessurligneurs.eu
#     Vérifie les déclarations des politiques français
#
# Pourquoi Scrapy ici :
#   - PolitiFact a une pagination complexe (infinite scroll simulé)
#   - IFCN agrège des sources de 65+ pays — crawl multi-niveaux
#   - Scrapy gère nativement la concurrence et le retry
#
# Port implémenté : ScraperPort
# Outil           : Scrapy (via CrawlerRunner en mode inline)
# ==============================================================================

# --- Bibliothèque standard ---------------------------------------------------
import json    # sérialisation des résultats du spider
import os      # répertoires temporaires
import tempfile  # fichier de sortie temporaire Scrapy
from typing import List  # annotation de type retour

# --- Dépendances externes ----------------------------------------------------
import scrapy                              # framework de crawling
from scrapy.crawler   import CrawlerProcess  # lancement inline
from scrapy.utils.project import get_project_settings  # settings Scrapy

# --- Domaine -----------------------------------------------------------------
from src.domain.exceptions import CheckItErreur
from src.domain.models     import LabelVéracité, Publication

# --- Port implémenté ---------------------------------------------------------
from src.ports.outbound.scraper_port import ScraperPort

# --- Outil de journalisation -------------------------------------------------
from src.tools.rafael.log_tool import LogTool

# --- Configuration -----------------------------------------------------------
NB_ARTICLES_MAX      = 30    # articles max par crawl
DÉLAI_ENTRE_REQUÊTES = 1.5   # secondes (DOWNLOAD_DELAY Scrapy)
TIMEOUT_REQUÊTE      = 20    # secondes


# ==============================================================================
# MAPPAGE DES LABELS POLITIFACT
# ==============================================================================
LABELS_POLITIFACT = {
    "true"           : LabelVéracité.REAL,
    "mostly true"    : LabelVéracité.REAL,
    "half-true"      : LabelVéracité.FAKE,  # ambigu → FAKE par prudence
    "mostly false"   : LabelVéracité.FAKE,
    "false"          : LabelVéracité.FAKE,
    "pants on fire"  : LabelVéracité.FAKE,  # mensonge flagrant
}

LABELS_SURLIGNEURS = {
    "inexact"        : LabelVéracité.FAKE,
    "faux"           : LabelVéracité.FAKE,
    "trompeur"       : LabelVéracité.FAKE,
    "exagéré"        : LabelVéracité.FAKE,
    "exact"          : LabelVéracité.REAL,
    "vrai"           : LabelVéracité.REAL,
}


# ##############################################################################
# SPIDER : PolitiFactSpider
# ##############################################################################
class PolitiFactSpider(scrapy.Spider):
    """
    Spider Scrapy pour PolitiFact.com.

    Utilise l'API JSON non-officielle de PolitiFact plutôt que le parsing HTML
    — plus fiable car indépendant des changements de structure du site.

    URL API : https://www.politifact.com/factchecks/list/?format=json&n=30
    """

    name             = "politifact_spider"
    allowed_domains  = ["politifact.com"]
    custom_settings  = {
        "DOWNLOAD_DELAY"          : DÉLAI_ENTRE_REQUÊTES,
        "ROBOTSTXT_OBEY"          : True,
        "USER_AGENT"              : "CheckItAI/1.0 (academic research)",
        "LOG_LEVEL"               : "WARNING",
        "FEEDS"                   : {},
        "AUTOTHROTTLE_ENABLED"    : True,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 1.0,
    }

    # --------------------------------------------------------------------------
    def __init__(self, résultats: list, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._résultats = résultats

    # --------------------------------------------------------------------------
    def start_requests(self):
        """Démarre le crawl depuis la page liste HTML — l'API JSON n'existe plus."""
        yield scrapy.Request(
            "https://www.politifact.com/factchecks/",
            callback    = self.parse_html,
            headers     = {"User-Agent": "CheckItAI/1.0 (academic research)"},
        )

    # --------------------------------------------------------------------------
    def parse_html(self, response):
        """Parse la page liste HTML de PolitiFact."""
        items = response.css("li.o-listicle__item")
        for item in items[:NB_ARTICLES_MAX]:
            # -- Titre (citation dans le lien) --------------------------------
            titre = item.css(
                "div.m-statement__quote a::text"
            ).get("").strip()

            # -- URL article --------------------------------------------------
            lien = item.css(
                "div.m-statement__quote a::attr(href)"
            ).get("")
            url_art = (
                "https://www.politifact.com" + lien if lien else ""
            )

            # -- Label via alt de l'image truth-o-meter ----------------------
            label_texte = item.css(
                "div.m-statement__meter img::attr(alt)"
            ).get("").lower().strip()

            # -- Image du speaker (seule image disponible dans la liste) ------
            image_url = item.css(
                "div.m-statement__image img.c-image__original::attr(src), "
                "div.m-statement__image img.c-image__thumb::attr(src)"
            ).get("")

            # -- Mapping label ------------------------------------------------
            label = LabelVéracité.FAKE
            for mot_clé, val in LABELS_POLITIFACT.items():
                if mot_clé in label_texte:
                    label = val
                    break

            if titre and image_url:
                self._résultats.append({
                    "title"         : titre,
                    "content"       : titre,
                    "image_url"     : image_url,
                    "source_domain" : "politifact.com",
                    "declared_label": label.value,
                    "lang"          : "en",
                    "metadata"      : {
                        "url_source": url_art,
                        "label_brut": label_texte,
                    },
                })

        # -- Pagination -------------------------------------------------------
        page_suivante = response.css(
            "a.o-listicle__more::attr(href), "
            "a[rel='next']::attr(href)"
        ).get()
        if page_suivante and len(self._résultats) < NB_ARTICLES_MAX:
            yield response.follow(page_suivante, self.parse_html)


# ##############################################################################
# CLASSE : ScrapyAdapter
# ##############################################################################
class ScrapyAdapter(ScraperPort):
    """
    Adaptateur d'extraction via Scrapy pour les sites à pagination complexe.

    Lance un CrawlerProcess Scrapy inline et récupère les résultats
    via une liste partagée en mémoire — pas de fichier intermédiaire.

    Sources supportées
    ------------------
    - PolitiFact (politifact.com) : fact-checker US leader mondial
    - Les Surligneurs (lessurligneurs.eu) : vérification politique FR

    Utilisation
    -----------
    adaptateur   = ScrapyAdapter(source="politifact")
    publications = adaptateur.extraire_données(
        "https://www.politifact.com/factchecks/"
    )
    """

    # --------------------------------------------------------------------------
    def __init__(self, source: str = "politifact") -> None:
        """
        Paramètres
        ----------
        source : str
            Identifiant de la source ("politifact", "surligneurs").
        """
        self._source = source
        self._log    = LogTool(origin="scrapy")

    # ==========================================================================
    @property
    def nom_source(self) -> str:
        """Nom lisible de la source."""
        noms = {
            "politifact" : "PolitiFact (Scrapy)",
            "surligneurs": "Les Surligneurs FR (Scrapy)",
        }
        return noms.get(self._source, f"Scrapy {self._source}")

    # ==========================================================================
    def est_disponible(self, source_url: str) -> bool:
        """Vérifie l'accessibilité du site."""
        import requests as req
        try:
            réponse = req.head(
                source_url,
                timeout = 10,
                headers = {"User-Agent": "CheckItAI/1.0"},
            )
            return réponse.status_code in (200, 301, 302)
        except Exception:
            return False

    # ==========================================================================
    def extraire_données(self, source_url: str) -> List[Publication]:
        """
        Lance le spider Scrapy et retourne les publications extraites.

        Utilise CrawlerProcess en mode inline — compatible avec
        l'appel depuis un PythonOperator Airflow.
        """
        self._log.START_ACTION(
            "ScrapyAdapter", "extraire_données", source_url
        )

        résultats_bruts: list = []  # liste partagée avec le spider

        # ----------------------------------------------------------------------
        # Lancement du crawler Scrapy
        # ----------------------------------------------------------------------
        try:
            paramètres = get_project_settings()
            paramètres.set("LOG_LEVEL", "WARNING")

            processus = CrawlerProcess(paramètres)
            processus.crawl(
                PolitiFactSpider,
                résultats=résultats_bruts,
            )
            processus.start()

        except Exception as erreur:
            self._log.LEVEL_4_ERROR(
                "ScrapyAdapter", f"Erreur crawl : {erreur}"
            )
            return []

        self._log.PARAMETER_VALUE(
            "résultats bruts", len(résultats_bruts)
        )

        # ----------------------------------------------------------------------
        # Mapping vers les entités Publication
        # ----------------------------------------------------------------------
        publications = []
        rejetées     = 0

        for données in résultats_bruts:
            try:
                pub = Publication(
                    title         = données["title"],
                    content       = données["content"],
                    image_url     = données["image_url"],
                    source_domain = données["source_domain"],
                    declared_label= LabelVéracité(données["declared_label"]),
                    lang          = données.get("lang", "en"),
                    metadata      = données.get("metadata", {}),
                )
                if pub.est_valide():
                    publications.append(pub)
                else:
                    rejetées += 1
            except (KeyError, ValueError, CheckItErreur) as erreur:
                rejetées += 1
                self._log.LEVEL_5_WARNING(
                    "ScrapyAdapter", f"Mapping échoué : {erreur}"
                )

        self._log.PARAMETER_VALUE("publications valides", len(publications))
        self._log.PARAMETER_VALUE("entrées rejetées....", rejetées)
        self._log.FINISH_ACTION(
            "ScrapyAdapter", "extraire_données",
            f"{len(publications)} publications extraites"
        )
        return publications
