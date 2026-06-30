# ==============================================================================
# src/adapters/outbound/scrapers/selenium_adapter.py
# Adaptateur Selenium — Sites JavaScript Dynamiques (SPA)
#
# Sources couvertes (originales) :
#   1. Logically Facts (EN)  — https://www.logically.ai/factchecks
#      Fact-checker basé sur l'IA — rendu React complet nécessaire.
#      Couvre la désinformation mondiale en anglais.
#      Labels : TRUE / FALSE / MISLEADING / UNVERIFIED
#
#   2. Decodex Le Monde (FR) — https://www.lemonde.fr/verification/
#      Outil de vérification du journal Le Monde.
#      Évalue la fiabilité des sites web et leurs articles.
#      Site en React — chargement dynamique obligatoire.
#
# Pourquoi Selenium ici :
#   - Logically.ai : rendu React — HTML vide sans JavaScript
#   - Decodex : pagination infinie JavaScript
#   - Les autres scrapers (BS4, Scrapy) ne peuvent pas traiter ces sites
#
# Port implémenté : ScraperPort
# Outil           : Selenium 4 + Chrome headless (WebDriver Manager)
# Test            : uv run scripts/test_selenium.py
# ==============================================================================

# --- Bibliothèque standard ---------------------------------------------------
import time      # attente chargement JavaScript
from typing import List, Optional  # annotations de types

# --- Dépendances externes ----------------------------------------------------
import requests   # vérification disponibilité (HEAD request)
from selenium                           import webdriver
from selenium.common.exceptions         import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options  import Options
from selenium.webdriver.chrome.service  import Service
from selenium.webdriver.common.by       import By
from selenium.webdriver.support         import expected_conditions as EC
from selenium.webdriver.support.ui      import WebDriverWait
from webdriver_manager.chrome           import ChromeDriverManager

# --- Domaine -----------------------------------------------------------------
from src.domain.exceptions import CheckItErreur, TitreVideErreur
from src.domain.models     import LabelVéracité, Publication

# --- Port implémenté ---------------------------------------------------------
from src.ports.outbound.scraper_port import ScraperPort

# --- Outil de journalisation -------------------------------------------------
from src.tools.rafael.log_tool import LogTool

# --- Configuration -----------------------------------------------------------
DÉLAI_CHARGEMENT     = 3.0   # secondes — attente rendu JavaScript
TIMEOUT_DRIVER       = 20    # secondes — attente élément DOM
TIMEOUT_REQUÊTE      = 15    # secondes — vérification disponibilité
NB_ARTICLES_MAX      = 15    # articles max (Selenium est lent)
DÉLAI_ENTRE_ARTICLES = 2.0   # secondes — respect du serveur


# ==============================================================================
# CONFIGURATION DES SOURCES
# ==============================================================================
CONFIG_SOURCES = {

    # --------------------------------------------------------------------------
    "logically": {
        "url_liste"          : "https://www.logically.ai/factchecks",
        "attente_élément"    : "div.fact-check-card",
        "sélecteur_articles" : "div.fact-check-card",
        "sélecteur_lien"     : "a",
        "sélecteur_titre"    : "h1.article-title, h1.fc-title",
        "sélecteur_contenu"  : "div.article-body p, div.fc-body p",
        "sélecteur_image"    : "img.article-image, img.fc-image",
        "sélecteur_label"    : "span.verdict-label, div.verdict-badge",
        "langue"             : "en",
        "domaine"            : "logically.ai",
        "labels"             : {
            "true"       : LabelVéracité.REAL,
            "verified"   : LabelVéracité.REAL,
            "false"      : LabelVéracité.FAKE,
            "misleading" : LabelVéracité.FAKE,
            "unverified" : LabelVéracité.FAKE,
            "partly false": LabelVéracité.FAKE,
        },
    },

    # --------------------------------------------------------------------------
    "decodex": {
        "url_liste"          : "https://www.lemonde.fr/verification/",
        "attente_élément"    : "article.article",
        "sélecteur_articles" : "article.article",
        "sélecteur_lien"     : "a.article__title-link",
        "sélecteur_titre"    : "h1.article__title",
        "sélecteur_contenu"  : "section.article__content p",
        "sélecteur_image"    : "figure.article__media img",
        "sélecteur_label"    : "span.article__label, div.verification-tag",
        "langue"             : "fr",
        "domaine"            : "lemonde.fr",
        "labels"             : {
            "faux"       : LabelVéracité.FAKE,
            "trompeur"   : LabelVéracité.FAKE,
            "inexact"    : LabelVéracité.FAKE,
            "vrai"       : LabelVéracité.REAL,
            "vérifié"    : LabelVéracité.REAL,
        },
    },
}


# ##############################################################################
# CLASSE : SeleniumAdapter
# ##############################################################################
class SeleniumAdapter(ScraperPort):
    """
    Adaptateur d'extraction depuis les sites JavaScript dynamiques (SPA).

    Utilise Chrome headless via Selenium 4 pour rendre le JavaScript
    avant d'extraire le contenu — indispensable pour les sites React/Vue.

    Sources supportées
    ------------------
    - Logically Facts (logically.ai) : fact-checker IA en anglais
    - Decodex Le Monde (lemonde.fr)  : vérification française

    Prérequis
    ---------
    - Google Chrome installé sur le système
    - webdriver-manager (installé automatiquement via uv)

    Utilisation
    -----------
    adaptateur   = SeleniumAdapter(source="logically")
    publications = adaptateur.extraire_données(
        "https://www.logically.ai/factchecks"
    )
    """

    # --------------------------------------------------------------------------
    def __init__(self, source: str = "logically") -> None:
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
        self._log     = LogTool(origin="selenium")
        self._driver: Optional[webdriver.Chrome] = None

    # ==========================================================================
    @property
    def nom_source(self) -> str:
        """Nom lisible de la source."""
        noms = {
            "logically": "Logically Facts (Selenium)",
            "decodex"  : "Decodex Le Monde (Selenium)",
        }
        return noms.get(self._source, f"Selenium {self._source}")

    # ==========================================================================
    def est_disponible(self, source_url: str) -> bool:
        """Vérifie l'accessibilité du site (HEAD request — pas de Selenium)."""
        try:
            réponse = requests.head(
                source_url,
                timeout = TIMEOUT_REQUÊTE,
                headers = {"User-Agent": "CheckItAI/1.0"},
            )
            return réponse.status_code in (200, 301, 302)
        except requests.RequestException:
            return False

    # ==========================================================================
    def extraire_données(self, source_url: str) -> List[Publication]:
        """
        Extrait les articles via Chrome headless.

        Séquence
        --------
        1. Lancement de Chrome headless
        2. Navigation vers la page liste
        3. Attente du rendu JavaScript
        4. Extraction des URLs d'articles
        5. Pour chaque article : navigation, attente, extraction
        6. Mapping vers Publication et validation
        7. Fermeture propre du driver
        """
        self._log.START_ACTION(
            "SeleniumAdapter", "extraire_données", source_url
        )

        publications = []
        rejetées     = 0

        try:
            self._démarrer_driver()
            urls_articles = self._extraire_urls(source_url)

            self._log.PARAMETER_VALUE(
                "articles trouvés", len(urls_articles)
            )

            for url in urls_articles[:NB_ARTICLES_MAX]:
                try:
                    time.sleep(DÉLAI_ENTRE_ARTICLES)
                    pub = self._extraire_article(url)
                    if pub and pub.est_valide():
                        publications.append(pub)
                        self._log.LEVEL_7_INFO(
                            "SeleniumAdapter",
                            f"[{pub.declared_label.value}] "
                            f"{pub.title[:60]}",
                        )
                    else:
                        rejetées += 1

                except CheckItErreur as erreur:
                    rejetées += 1
                    self._log.LEVEL_5_WARNING(
                        "SeleniumAdapter", str(erreur)
                    )
                except Exception as erreur:
                    rejetées += 1
                    self._log.LEVEL_4_ERROR(
                        "SeleniumAdapter",
                        f"Erreur article : {erreur}",
                    )

        except WebDriverException as erreur:
            self._log.LEVEL_3_CRITICAL(
                "SeleniumAdapter", f"Erreur driver Chrome : {erreur}"
            )
        finally:
            self._arrêter_driver()

        self._log.PARAMETER_VALUE("publications valides", len(publications))
        self._log.PARAMETER_VALUE("entrées rejetées....", rejetées)
        self._log.FINISH_ACTION(
            "SeleniumAdapter", "extraire_données",
            f"{len(publications)} publications extraites"
        )
        return publications

    # ##########################################################################
    # MÉTHODES PRIVÉES
    # ##########################################################################

    # --------------------------------------------------------------------------
    def _démarrer_driver(self) -> None:
        """Lance Chrome en mode headless — sans interface graphique."""
        self._log.STEP(2, "Démarrage Chrome headless")
        options = Options()
        options.add_argument("--headless=new")   # nouveau mode headless
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--lang=fr-FR")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )

        service      = Service(ChromeDriverManager().install())
        self._driver = webdriver.Chrome(service=service, options=options)
        self._driver.set_page_load_timeout(TIMEOUT_DRIVER)
        self._log.PARAMETER_VALUE("driver Chrome", "démarré ✓")

    # --------------------------------------------------------------------------
    def _arrêter_driver(self) -> None:
        """Ferme proprement le driver Chrome."""
        if self._driver:
            self._driver.quit()
            self._driver = None
            self._log.PARAMETER_VALUE("driver Chrome", "fermé ✓")

    # --------------------------------------------------------------------------
    def _extraire_urls(self, url_liste: str) -> List[str]:
        """Navigue vers la liste et extrait les URLs des articles."""
        self._driver.get(url_liste)
        time.sleep(DÉLAI_CHARGEMENT)

        try:
            WebDriverWait(self._driver, TIMEOUT_DRIVER).until(
                EC.presence_of_element_located((
                    By.CSS_SELECTOR,
                    self._config["attente_élément"],
                ))
            )
        except TimeoutException:
            self._log.LEVEL_5_WARNING(
                "SeleniumAdapter",
                "Timeout attente éléments — extraction partielle",
            )

        articles = self._driver.find_elements(
            By.CSS_SELECTOR, self._config["sélecteur_articles"]
        )
        urls = []
        for article in articles:
            try:
                lien = article.find_element(
                    By.CSS_SELECTOR, self._config["sélecteur_lien"]
                )
                url = lien.get_attribute("href")
                if url and url not in urls:
                    urls.append(url)
            except NoSuchElementException:
                continue
        return urls

    # --------------------------------------------------------------------------
    def _extraire_article(self, url: str) -> Optional[Publication]:
        """Navigue vers un article et extrait ses données."""
        self._log.START_CALL_MANAGER_FUNCTION(
            "SeleniumAdapter", "_extraire_article", url
        )
        self._driver.get(url)
        time.sleep(DÉLAI_CHARGEMENT)

        # -- Titre ------------------------------------------------------------
        titre = self._extraire_texte(self._config["sélecteur_titre"])
        if not titre:
            self._log.FINISH_CALL_MANAGER_FUNCTION(
                "SeleniumAdapter", "_extraire_article", "titre absent"
            )
            return None

        # -- Contenu ----------------------------------------------------------
        contenu = self._extraire_texte(self._config["sélecteur_contenu"])

        # -- Image ------------------------------------------------------------
        image_url = self._extraire_attribut(
            self._config["sélecteur_image"], "src"
        )
        if not image_url:
            self._log.LEVEL_5_WARNING(
                "SeleniumAdapter", f"Image absente : {url}"
            )
            return None

        # -- Label ------------------------------------------------------------
        label = self._extraire_label()

        self._log.FINISH_CALL_MANAGER_FUNCTION(
            "SeleniumAdapter", "_extraire_article", "OK"
        )
        return Publication(
            title         = titre,
            content       = contenu,
            image_url     = image_url,
            source_domain = self._config["domaine"],
            declared_label= label,
            lang          = self._config["langue"],
            metadata      = {
                "url_source": url,
                "driver"    : "selenium_chrome_headless",
            },
        )

    # --------------------------------------------------------------------------
    def _extraire_texte(self, sélecteur_css: str) -> str:
        """Extrait le texte depuis un sélecteur CSS."""
        for sel in sélecteur_css.split(", "):
            try:
                éléments = self._driver.find_elements(
                    By.CSS_SELECTOR, sel.strip()
                )
                if éléments:
                    return " ".join(
                        é.text.strip() for é in éléments if é.text.strip()
                    )
            except NoSuchElementException:
                continue
        return ""

    # --------------------------------------------------------------------------
    def _extraire_attribut(self, sélecteur_css: str, attribut: str) -> str:
        """Extrait un attribut HTML depuis un sélecteur CSS."""
        for sel in sélecteur_css.split(", "):
            try:
                élément = self._driver.find_element(
                    By.CSS_SELECTOR, sel.strip()
                )
                valeur = élément.get_attribute(attribut)
                if valeur:
                    return valeur
            except NoSuchElementException:
                continue
        return ""

    # --------------------------------------------------------------------------
    def _extraire_label(self) -> LabelVéracité:
        """Extrait et mappe le label de véracité."""
        texte_label = self._extraire_texte(
            self._config["sélecteur_label"]
        ).lower()
        for mot_clé, label in self._config["labels"].items():
            if mot_clé in texte_label:
                return label
        return LabelVéracité.FAKE  # défaut prudent
