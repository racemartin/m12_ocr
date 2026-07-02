# ==============================================================================
# src/adapters/outbound/scrapers/bs4_adapter.py
# Adaptateur HTML statique — Extraction via BeautifulSoup4
#
# Sources couvertes (originales — peu utilisées par les étudiants) :
#   1. FullFact (UK)   — https://fullfact.org
#      Fact-checker britannique indépendant, fondé en 2010.
#      Labels explicites : TRUE / FALSE / MISLEADING / UNVERIFIED
#      Images systématiques sur chaque article.
#
#   2. Correctiv (DE)  — https://correctiv.org/faktencheck
#      Fact-checker allemand leader — primé Reuters Institute 2023.
#      Couvre la désinformation germanophone et européenne.
#      Labels : FAUX / TROMPEUR / VRAI / PLUTÔT VRAI
#
#   3. Maldita (ES)    — https://maldita.es/malditobulo
#      Fact-checker espagnol — expert désinformation ibérique.
#      Labels : FAUX / TROMPEUR / VRAI / SATIRE
#
# Pourquoi ces sources sont originales :
#   - Pas dans les datasets Kaggle/HuggingFace standards
#   - Langues variées (EN/DE/ES) — valeur multilingue réelle
#   - Labels explicites sur chaque page — qualité élevée
#   - Robots.txt vérifiés — scraping autorisé (academic/research)
#
# Port implémenté : ScraperPort
# Outil           : BeautifulSoup4 + Requests
# ==============================================================================

# --- Bibliothèque standard ---------------------------------------------------
import re      # expressions régulières pour nettoyage HTML
import time    # délai entre les requêtes (respect des serveurs)
from typing import Dict, List, Optional  # annotations de types
from urllib.parse import urljoin, urlparse  # construction URLs absolues

# --- Dépendances externes ----------------------------------------------------
import requests                            # téléchargement des pages HTML
from bs4 import BeautifulSoup             # parsing HTML structuré

# --- Domaine -----------------------------------------------------------------
from src.domain.exceptions import (
    CheckItErreur,
    ImageUrlVideErreur,
    TitreVideErreur,
)
from src.domain.models import LabelVéracité, Publication

# --- Port implémenté ---------------------------------------------------------
from src.ports.outbound.scraper_port import ScraperPort

# --- Outil de journalisation -------------------------------------------------
from src.tools.rafael.log_tool import LogTool

# --- Configuration -----------------------------------------------------------
DÉLAI_ENTRE_REQUÊTES = 2.0   # secondes — respect des serveurs
TIMEOUT_REQUÊTE      = 15    # secondes
NB_ARTICLES_MAX      = 20    # articles max par extraction

# --- En-têtes HTTP réalistes (évite les blocages 403) -----------------------
ENTÊTES_HTTP = {
    "User-Agent"     : (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept"         : "text/html,application/xhtml+xml",
}


# ==============================================================================
# CONFIGURATION DES SOURCES
# ==============================================================================
# Chaque source a ses propres sélecteurs CSS — à adapter si le site change.

CONFIG_SOURCES: Dict[str, Dict] = {

    # --------------------------------------------------------------------------
    "fullfact": {
        "url_base"           : "https://fullfact.org",
        "url_liste"          : "https://fullfact.org/latest/",
        "sélecteur_articles" : "div.card.feature-card",
        "sélecteur_titre"    : "div.card-text h2",
        "sélecteur_contenu"  : "div.card-text p",
        "sélecteur_image"    : "div.card-image img",
        "sélecteur_label"    : "",
        "sélecteur_lien"     : "a.card-link",
        "langue"             : "en",
        "domaine"            : "fullfact.org",
        "mode"               : "card",
        "labels"             : {
            "true"           : LabelVéracité.REAL,
            "correct"        : LabelVéracité.REAL,
            "mostly true"    : LabelVéracité.REAL,
            "false"          : LabelVéracité.FAKE,
            "misleading"     : LabelVéracité.FAKE,
            "incorrect"      : LabelVéracité.FAKE,
            "unverified"     : LabelVéracité.FAKE,
            "missing context": LabelVéracité.FAKE,
        },
    },

    # --------------------------------------------------------------------------
    "correctiv": {
        "url_base"           : "https://correctiv.org",
        "url_liste"          : "https://correctiv.org/faktencheck/",

        # "sélecteur_articles" : "article, div.elementor-post",
        # "sélecteur_titre"    : "h1.entry-title, h1.elementor-heading-title, h2.entry-title",
        # "sélecteur_contenu"  : "div.entry-content p, div.elementor-widget-text-editor p",
        # "sélecteur_image"    : "figure.wp-block-image img, div.elementor-widget-image img, img.wp-post-image",        
        # "sélecteur_label"    : "div.fact-check-verdict, span.verdict, div.correctiv-verdict",
        # "sélecteur_lien"     : "a.entry-title-link, h2 a, h3 a",

        "sélecteur_articles" : "a.teaser__item",
        "sélecteur_titre"    : "h1.entry-title, h1.post-title, h1",
        "sélecteur_contenu"  : "div.entry-content p, div.post-content p",
        "sélecteur_image"    : "img.wp-post-image, figure.wp-block-image img",        
        "sélecteur_label"    : "div.fact-check-verdict img, .verdict",
        "sélecteur_lien"     : "a.teaser__item", 

        "langue"             : "de",
        "domaine"            : "correctiv.org",
        "labels"             : {
            "falsch"         : LabelVéracité.FAKE,
            "irreführend"    : LabelVéracité.FAKE,
            "fake"           : LabelVéracité.FAKE,
            "richtig"        : LabelVéracité.REAL,
            "wahr"           : LabelVéracité.REAL,
            "stimmt"         : LabelVéracité.REAL,
        },
    },

    # --------------------------------------------------------------------------
    "maldita": {
        "url_base"           : "https://maldita.es",
        "url_liste"          : "https://maldita.es/malditobulo/",
        "sélecteur_articles" : "a[href*='/malditobulo/']",
        "sélecteur_titre"    : "div#headline h1, h1",
        "sélecteur_contenu"  : "div#keys div, div#article-content div",
        "sélecteur_image"    : "div#featuredImage img",
        "sélecteur_label"    : "div#headline span.uppercase, div.flex.items-center span.uppercase",
        "sélecteur_lien"     : "self",
        "langue"             : "es",
        "domaine"            : "maldita.es",
        "labels"             : {
            "falso"          : LabelVéracité.FAKE,
            "engañoso"       : LabelVéracité.FAKE,
            "bulo"           : LabelVéracité.FAKE,
            "alerta"         : LabelVéracité.FAKE,
            "contexto"       : LabelVéracité.FAKE,
            "verdadero"      : LabelVéracité.REAL,
            "verdad"         : LabelVéracité.REAL,
            "verdadero/a"    : LabelVéracité.REAL,
        },
    },
}


# ##############################################################################
# CLASSE : Bs4Adapter
# ##############################################################################
class Bs4Adapter(ScraperPort):
    """
    Adaptateur d'extraction depuis les sites HTML statiques de fact-checkers.

    Utilise BeautifulSoup4 pour parser le HTML et extraire
    les articles avec leurs labels de véracité explicites.

    Sources supportées
    ------------------
    - FullFact (fullfact.org)   : fact-checker UK en anglais
    - Correctiv (correctiv.org) : fact-checker DE en allemand
    - Maldita (maldita.es)      : fact-checker ES en espagnol

    Utilisation
    -----------
    adaptateur   = Bs4Adapter(source="fullfact")
    publications = adaptateur.extraire_données(
        "https://fullfact.org/latest/"
    )
    """

    # --------------------------------------------------------------------------
    def __init__(self, source: str = "fullfact") -> None:
        """
        Paramètres
        ----------
        source : str
            Identifiant de la source parmi CONFIG_SOURCES.
        """
        if source not in CONFIG_SOURCES:
            raise ValueError(
                f"Source '{source}' inconnue. "
                f"Sources disponibles : {list(CONFIG_SOURCES.keys())}"
            )
        self._source  = source
        self._config  = CONFIG_SOURCES[source]
        self._log     = LogTool(origin="bs4")
        self._session = requests.Session()
        self._session.headers.update(ENTÊTES_HTTP)

    # ==========================================================================
    @property
    def nom_source(self) -> str:
        """Nom lisible de la source."""
        noms = {
            "fullfact" : "FullFact UK (HTML)",
            "correctiv": "Correctiv DE (HTML)",
            "maldita"  : "Maldita ES (HTML)",
        }
        return noms.get(self._source, f"BS4 {self._source}")

    # ==========================================================================
    def est_disponible(self, source_url: str) -> bool:
        """Vérifie l'accessibilité du site avant extraction."""
        self._log.START_CALL_CONTROLLER_FUNCTION(
            "Bs4Adapter", "est_disponible", source_url
        )
        try:
            réponse    = self._session.head(
                source_url, timeout=TIMEOUT_REQUÊTE
            )
            disponible = réponse.status_code in (200, 301, 302)
            self._log.PARAMETER_VALUE("statut HTTP", réponse.status_code)
            self._log.FINISH_CALL_CONTROLLER_FUNCTION(
                "Bs4Adapter", "est_disponible",
                "OK" if disponible else "HORS LIGNE"
            )
            return disponible
        except requests.RequestException as erreur:
            self._log.LEVEL_4_ERROR(
                "Bs4Adapter", f"Site inaccessible : {erreur}"
            )
            return False

    # ==========================================================================
    def extraire_données(self, source_url: str) -> List[Publication]:
        """
        Extrait les articles fact-checkés depuis un site HTML statique.

        Séquence
        --------
        1. Téléchargement de la page liste des articles
        2. Parsing HTML avec BeautifulSoup4
        3. Extraction des URLs d'articles individuels
        4. Pour chaque article : téléchargement et parsing
        5. Extraction titre, contenu, image, label
        6. Mapping vers Publication et validation
        """
        self._log.START_ACTION(
            "Bs4Adapter", "extraire_données", source_url
        )

        publications = []
        rejetées     = 0

        # ----------------------------------------------------------------------
        # Téléchargement page liste
        # ----------------------------------------------------------------------
        try:
            réponse = self._session.get(
                source_url, timeout=TIMEOUT_REQUÊTE
            )
            réponse.raise_for_status()
            soupe = BeautifulSoup(réponse.text, "html.parser")

        except requests.RequestException as erreur:
            self._log.LEVEL_4_ERROR(
                "Bs4Adapter", f"Erreur téléchargement : {erreur}"
            )
            return []

        # ----------------------------------------------------------------------
        # MODE CARD (FullFact) — extraction directe depuis les cards
        # sans suivre les liens vers les articles individuels
        # ----------------------------------------------------------------------
        if self._config.get("mode") == "card":
            cards = soupe.select(self._config["sélecteur_articles"])
            self._log.PARAMETER_VALUE("articles trouvés", len(cards))

            for card in cards[:NB_ARTICLES_MAX]:
                try:
                    time.sleep(DÉLAI_ENTRE_REQUÊTES)

                    # -- Titre ------------------------------------------------
                    el_titre = card.select_one(
                        self._config["sélecteur_titre"]
                    )
                    titre = el_titre.get_text(strip=True) if el_titre else ""

                    # -- Contenu ----------------------------------------------
                    els_contenu = card.select(
                        self._config["sélecteur_contenu"]
                    )
                    contenu = " ".join(
                        e.get_text(strip=True) for e in els_contenu
                    )

                    # -- Image ------------------------------------------------
                    el_img    = card.select_one(
                        self._config["sélecteur_image"]
                    )
                    image_url = ""
                    if el_img:
                        src = (
                            el_img.get("src")
                            or el_img.get("data-src", "")
                        )
                        if src and not src.startswith("data:"):
                            image_url = urljoin(
                                self._config["url_base"], src
                            )

                    # -- URL source (metadata) --------------------------------
                    el_lien   = card.select_one(
                        self._config["sélecteur_lien"]
                    )
                    url_source = ""
                    if el_lien and el_lien.get("href"):
                        url_source = urljoin(
                            self._config["url_base"], el_lien["href"]
                        )

                    if not titre or not image_url:
                        rejetées += 1
                        continue

                    pub = Publication(
                        title         = titre,
                        content       = contenu or titre,
                        image_url     = image_url,
                        source_domain = self._config["domaine"],
                        declared_label= LabelVéracité.FAKE,
                        lang          = self._config["langue"],
                        metadata      = {"url_source": url_source},
                    )
                    if pub.est_valide():
                        publications.append(pub)
                        self._log.LEVEL_7_INFO(
                            "Bs4Adapter",
                            f"[{pub.declared_label.value}] {pub.title[:60]}",
                        )
                    else:
                        rejetées += 1

                except Exception as erreur:
                    rejetées += 1
                    self._log.LEVEL_5_WARNING(
                        "Bs4Adapter", f"Card ignorée : {erreur}"
                    )

            self._log.PARAMETER_VALUE(
                "publications valides", len(publications)
            )
            self._log.PARAMETER_VALUE("entrées rejetées....", rejetées)
            self._log.FINISH_ACTION(
                "Bs4Adapter", "extraire_données",
                f"{len(publications)} publications extraites"
            )
            return publications

        # ----------------------------------------------------------------------
        # Extraction des URLs d'articles
        # ----------------------------------------------------------------------
        urls_articles = self._extraire_urls_articles(soupe, source_url)
        self._log.PARAMETER_VALUE(
            "articles trouvés", len(urls_articles)
        )

        # ----------------------------------------------------------------------
        # Traitement de chaque article
        # ----------------------------------------------------------------------
        for url_article in urls_articles[:NB_ARTICLES_MAX]:
            try:
                time.sleep(DÉLAI_ENTRE_REQUÊTES)
                pub = self._extraire_article(url_article)
                if pub and pub.est_valide():
                    publications.append(pub)
                    self._log.LEVEL_7_INFO(
                        "Bs4Adapter",
                        f"[{pub.declared_label.value}] "
                        f"{pub.title[:60]}",
                    )
                else:
                    rejetées += 1

            except CheckItErreur as erreur:
                rejetées += 1
                self._log.LEVEL_5_WARNING("Bs4Adapter", str(erreur))
            except Exception as erreur:
                rejetées += 1
                self._log.LEVEL_4_ERROR(
                    "Bs4Adapter", f"Erreur article : {erreur}"
                )

        # ----------------------------------------------------------------------
        # Rapport
        # ----------------------------------------------------------------------
        self._log.PARAMETER_VALUE("publications valides", len(publications))
        self._log.PARAMETER_VALUE("entrées rejetées....", rejetées)
        self._log.FINISH_ACTION(
            "Bs4Adapter", "extraire_données",
            f"{len(publications)} publications extraites"
        )
        return publications

    # ##########################################################################
    # MÉTHODES PRIVÉES
    # ##########################################################################

    # --------------------------------------------------------------------------
    def _extraire_urls_articles(
        self,
        soupe      : BeautifulSoup,
        url_base   : str,
    ) -> List[str]:
        """Extrait les URLs des articles depuis la page liste.

        Gère deux cas :
        - sélecteur pointe sur un conteneur (article, div) → cherche le lien enfant
        - sélecteur pointe directement sur un lien (a[href*=...]) → utilise href
        """
        urls      = []
        sélecteur = self._config["sélecteur_articles"]
        éléments  = soupe.select(sélecteur)

        for élément in éléments:
            # -- Cas 1 : l'élément EST un lien --------------------------------
            if élément.name == "a" and élément.get("href"):
                url = urljoin(self._config["url_base"], élément["href"])
            # -- Cas 2 : l'élément CONTIENT un lien ---------------------------
            else:
                lien = élément.find("a", href=True)
                if not lien:
                    continue
                url = urljoin(self._config["url_base"], lien["href"])

            # -- Déduplication et filtre domaine -------------------------------
            if url not in urls and self._config["url_base"] in url:
                urls.append(url)
        return urls

    # --------------------------------------------------------------------------
    def _extraire_article(self, url: str) -> Optional[Publication]:
        """
        Télécharge et parse un article individuel.

        Retourne une Publication ou None si l'article est invalide.
        """
        self._log.START_CALL_MANAGER_FUNCTION(
            "Bs4Adapter", "_extraire_article", url
        )
        try:
            réponse = self._session.get(url, timeout=TIMEOUT_REQUÊTE)
            réponse.raise_for_status()
            soupe   = BeautifulSoup(réponse.text, "html.parser")

            titre   = self._extraire_titre(soupe)
            contenu = self._extraire_contenu(soupe)
            image   = self._extraire_image(soupe, url)
            label   = self._extraire_label(soupe)

            if not image:
                self._log.LEVEL_5_WARNING(
                    "Bs4Adapter", f"Image absente : {url}"
                )
                return None

            self._log.FINISH_CALL_MANAGER_FUNCTION(
                "Bs4Adapter", "_extraire_article", "OK"
            )
            return Publication(
                title         = titre,
                content       = contenu,
                image_url     = image,
                source_domain = self._config["domaine"],
                declared_label= label,
                lang          = self._config["langue"],
                metadata      = {"url_source": url},
            )

        except (requests.RequestException, Exception) as erreur:
            self._log.LEVEL_4_ERROR(
                "Bs4Adapter", f"Erreur article {url} : {erreur}"
            )
            return None

    # --------------------------------------------------------------------------
    def _extraire_titre(self, soupe: BeautifulSoup) -> str:
        """Extrait le titre depuis les sélecteurs configurés."""
        for sélecteur in self._config["sélecteur_titre"].split(", "):
            élément = soupe.select_one(sélecteur.strip())
            if élément:
                return élément.get_text(strip=True)
        raise TitreVideErreur(self._config["domaine"])

    # --------------------------------------------------------------------------
    def _extraire_contenu(self, soupe: BeautifulSoup) -> str:
        """Extrait et concatène le texte de l'article.

        Gère deux cas :
        - Contenu en <p> (FullFact, Correctiv)
        - Contenu en <div> imbriqués (Maldita)
        """
        éléments = soupe.select(self._config["sélecteur_contenu"])
        if éléments:
            texte = " ".join(
                élément.get_text(separator=" ", strip=True)
                for élément in éléments
                if élément.get_text(strip=True)
            )
            return re.sub(r"\s+", " ", texte).strip()

        # -- Fallback : tout le texte de l'article ----------------------------
        article = soupe.select_one("article, main, div#content")
        if article:
            return re.sub(
                r"\s+", " ", article.get_text(separator=" ", strip=True)
            ).strip()[:2000]

        return ""

    # --------------------------------------------------------------------------
    def _extraire_image(
        self,
        soupe    : BeautifulSoup,
        url_page : str,
    ) -> str:
        """
        Extrait l'URL de l'image principale de l'article.

        Ordre de priorité :
        1. Sélecteurs CSS configurés (src, data-src, data-lazy-src)
        2. Balise meta og:image (fallback universel — présente sur 95% des sites)
        """
        # -- Tentative sélecteurs CSS configurés ------------------------------
        for sélecteur in self._config["sélecteur_image"].split(", "):
            élément = soupe.select_one(sélecteur.strip())
            if élément:
                for attr in ("src", "data-src", "data-lazy-src", "data-src-set"):
                    url = élément.get(attr, "")
                    if url and not url.startswith("data:"):
                        return urljoin(self._config["url_base"], url)

        # -- Fallback : meta og:image (présente sur presque tous les articles) -
        og_image = soupe.select_one('meta[property="og:image"]')
        if og_image and og_image.get("content"):
            return og_image["content"]

        # -- Fallback : meta twitter:image --------------------------------
        tw_image = soupe.select_one('meta[name="twitter:image"]')
        if tw_image and tw_image.get("content"):
            return tw_image["content"]

        return ""

    # --------------------------------------------------------------------------
    def _extraire_label(self, soupe: BeautifulSoup) -> LabelVéracité:
        """
        Extrait le label de véracité depuis les éléments de verdict.
        Retourne FAKE par défaut (prudence).
        """
        for sélecteur in self._config["sélecteur_label"].split(", "):
            élément = soupe.select_one(sélecteur.strip())
            if élément:
                texte = élément.get_text(strip=True).lower()
                for mot_clé, label in self._config["labels"].items():
                    if mot_clé in texte:
                        return label
        return LabelVéracité.FAKE  # défaut prudent
