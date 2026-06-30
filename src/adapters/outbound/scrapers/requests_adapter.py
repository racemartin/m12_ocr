# ==============================================================================
# src/adapters/outbound/scrapers/requests_adapter.py
# Adaptateur API REST — Extraction via Requests
#
# Sources couvertes (originales — peu utilisées par les étudiants) :
#   1. MediaBiasFactCheck (MBFC) API
#      Évalue la fiabilité de 5000+ sources médiatiques mondiales
#      https://mediabiasfactcheck.com — labels: HIGH/MIXED/LOW credibility
#
#   2. ClaimBuster API (University of Texas Arlington)
#      Détecte automatiquement les affirmations vérifiables dans un texte
#      https://idir.uta.edu/claimbuster/ — open academic API
#
#   3. NewsData.io API
#      Articles multilingues avec images (200 req/jour gratuit)
#      https://newsdata.io — labels à inférer via MBFC
#
# Pourquoi ces sources sont originales :
#   - MBFC : utilisé par Wikipedia, journalistes, chercheurs
#     — pas dans les datasets Kaggle standard
#   - ClaimBuster : outil académique peu connu des étudiants
#   - Combinaison MBFC + NewsData.io = labels de qualité élevée
#
# Port implémenté : ScraperPort
# Outil           : Requests (HTTP natif Python)
# ==============================================================================

# --- Bibliothèque standard ---------------------------------------------------
import json    # parsing des réponses API JSON
import os      # lecture des clés API depuis les variables d'environnement
import time    # délai entre les requêtes (respect des quotas)
from typing import Any, Dict, List, Optional  # annotations de types

# --- Dépendances externes ----------------------------------------------------
import requests  # appels HTTP REST
from dotenv import load_dotenv  # chargement automatique du fichier .env

# --- Chargement variables d'environnement -------------------------------------
# Lit .env à la racine du projet si présent — sans écraser les
# variables déjà définies par l'environnement (Airflow Variables, etc.)
load_dotenv()

# --- Domaine -----------------------------------------------------------------
from src.domain.exceptions import CheckItErreur, ImageUrlVideErreur
from src.domain.models     import LabelVéracité, Publication

# --- Port implémenté ---------------------------------------------------------
from src.ports.outbound.scraper_port import ScraperPort

# --- Outil de journalisation -------------------------------------------------
from src.tools.rafael.log_tool import LogTool

# --- Configuration -----------------------------------------------------------
TIMEOUT_REQUÊTE      = 15    # secondes — abandon si API lente
DÉLAI_ENTRE_REQUÊTES = 0.5   # secondes — respect quotas API
MAX_ARTICLES         = 10    # articles max par requête NewsData.io

# --- URLs des APIs -----------------------------------------------------------
URL_NEWSDATA       = "https://newsdata.io/api/1/news"
URL_CLAIMBUSTER    = "https://idir.uta.edu/claimbuster/api/v2/score/text"


# ==============================================================================
# MAPPAGE MBFC → LabelVéracité
# ==============================================================================
FIABILITÉ_MBFC = {
    # Sources très fiables → REAL
    "very high"   : LabelVéracité.REAL,
    "high"        : LabelVéracité.REAL,
    # Sources mixtes ou peu fiables → FAKE
    "mixed"       : LabelVéracité.FAKE,
    "low"         : LabelVéracité.FAKE,
    "very low"    : LabelVéracité.FAKE,
    "questionable": LabelVéracité.FAKE,
    "conspiracy"  : LabelVéracité.FAKE,
    "pseudoscience": LabelVéracité.FAKE,
    "satire"      : LabelVéracité.FAKE,
}


# ##############################################################################
# CLASSE : RequestsAdapter
# ##############################################################################
class RequestsAdapter(ScraperPort):
    """
    Adaptateur d'extraction depuis les APIs REST JSON.

    Combine NewsData.io (articles frais) avec la notation MBFC
    (fiabilité de la source) pour produire des labels de qualité.

    Sources
    -------
    - NewsData.io  : articles multilingues avec images
    - MBFC         : évaluation de fiabilité des sources médiatiques
    - ClaimBuster  : détection d'affirmations vérifiables

    Clés API requises (variables d'environnement)
    ---------------------------------------------
    NEWSDATA_API_KEY    : clé NewsData.io (gratuit: 200 req/jour)
    CLAIMBUSTER_API_KEY : clé ClaimBuster (gratuit: académique)

    Utilisation
    -----------
    adaptateur = RequestsAdapter()
    publications = adaptateur.extraire_données(
        "https://newsdata.io/api/1/news?country=fr&language=fr"
    )
    """

    # --------------------------------------------------------------------------
    def __init__(self) -> None:
        self._log              = LogTool(origin="api_rest")
        self._clé_newsdata     = os.environ.get("NEWSDATA_API_KEY", "")
        self._clé_claimbuster  = os.environ.get("CLAIMBUSTER_API_KEY", "")
        self._session          = requests.Session()  # réutilisation connexions
        self._session.headers.update({
            "User-Agent": "CheckItAI/1.0 (research bot)",
            "Accept"    : "application/json",
        })

    # ==========================================================================
    @property
    def nom_source(self) -> str:
        """Nom lisible de la source."""
        return "NewsData.io + MBFC API"

    # ==========================================================================
    def est_disponible(self, source_url: str) -> bool:
        """Vérifie l'accessibilité de l'API NewsData.io."""
        self._log.START_CALL_CONTROLLER_FUNCTION(
            "RequestsAdapter", "est_disponible", source_url
        )
        try:
            réponse = self._session.get(
                URL_NEWSDATA,
                params  = {"apikey": self._clé_newsdata, "size": 1},
                timeout = TIMEOUT_REQUÊTE,
            )
            disponible = réponse.status_code == 200
            self._log.PARAMETER_VALUE("statut HTTP", réponse.status_code)
            self._log.FINISH_CALL_CONTROLLER_FUNCTION(
                "RequestsAdapter", "est_disponible",
                "OK" if disponible else "ERREUR"
            )
            return disponible
        except requests.RequestException as erreur:
            self._log.LEVEL_4_ERROR(
                "RequestsAdapter", f"API inaccessible : {erreur}"
            )
            return False

    # ==========================================================================
    def extraire_données(self, source_url: str) -> List[Publication]:
        """
        Extrait les articles depuis NewsData.io.

        Séquence
        --------
        1. Appel API NewsData.io avec les paramètres configurés
        2. Pour chaque article : extraction titre, contenu, image
        3. Évaluation MBFC de la fiabilité du domaine source
        4. Mapping vers Publication avec label MBFC
        5. Validation et ajout au résultat

        Paramètres
        ----------
        source_url : str
            URL complète avec paramètres de recherche NewsData.io.
            Ex. : "...?country=fr&language=fr&category=politics"
        """
        self._log.START_ACTION(
            "RequestsAdapter", "extraire_données", source_url
        )

        if not self._clé_newsdata:
            self._log.LEVEL_3_CRITICAL(
                "RequestsAdapter",
                "NEWSDATA_API_KEY manquante — extraction impossible",
            )
            return []

        publications = []
        rejetées     = 0

        # ----------------------------------------------------------------------
        # Appel API NewsData.io
        # ----------------------------------------------------------------------
        try:
            réponse = self._session.get(
                source_url,
                timeout = TIMEOUT_REQUÊTE,
            )
            réponse.raise_for_status()
            données = réponse.json()

        except requests.HTTPError as erreur:
            self._log.LEVEL_4_ERROR(
                "RequestsAdapter", f"Erreur HTTP {erreur}"
            )
            return []
        except (requests.RequestException, json.JSONDecodeError) as erreur:
            self._log.LEVEL_4_ERROR(
                "RequestsAdapter", f"Erreur requête : {erreur}"
            )
            return []

        articles = données.get("results", [])
        self._log.PARAMETER_VALUE("articles reçus", len(articles))

        # ----------------------------------------------------------------------
        # Traitement de chaque article
        # ----------------------------------------------------------------------
        for article in articles:
            try:
                time.sleep(DÉLAI_ENTRE_REQUÊTES)

                titre       = (article.get("title") or "").strip()
                contenu     = (article.get("content")
                               or article.get("description") or "").strip()
                image_url   = (article.get("image_url") or "").strip()
                source_id   = (article.get("source_id") or "").strip()
                langue      = (article.get("language") or "fr")[:2]

                # -- Validation minimale --------------------------------------
                if not titre or not image_url:
                    rejetées += 1
                    continue

                # -- Label depuis MBFC ----------------------------------------
                label = self._évaluer_source_mbfc(source_id)

                # -- Métadonnées secondaires ----------------------------------
                métadonnées = {
                    "url_source"  : article.get("link", ""),
                    "auteur"      : article.get("creator", []),
                    "date_publi"  : article.get("pubDate", ""),
                    "catégories"  : article.get("category", []),
                    "pays"        : article.get("country", []),
                    "source_id"   : source_id,
                    "score_mbfc"  : "évalué" if label else "défaut",
                }

                pub = Publication(
                    title         = titre,
                    content       = contenu,
                    image_url     = image_url,
                    source_domain = source_id or "newsdata.io",
                    declared_label= label,
                    lang          = langue,
                    metadata      = métadonnées,
                )

                if pub.est_valide():
                    publications.append(pub)
                    self._log.LEVEL_7_INFO(
                        "RequestsAdapter",
                        f"[{label.value}] {titre[:60]}",
                    )
                else:
                    rejetées += 1

            except CheckItErreur as erreur:
                rejetées += 1
                self._log.LEVEL_5_WARNING(
                    "RequestsAdapter", str(erreur)
                )
            except Exception as erreur:
                rejetées += 1
                self._log.LEVEL_4_ERROR(
                    "RequestsAdapter", f"Erreur inattendue : {erreur}"
                )

        # ----------------------------------------------------------------------
        # Rapport
        # ----------------------------------------------------------------------
        self._log.PARAMETER_VALUE("publications valides", len(publications))
        self._log.PARAMETER_VALUE("entrées rejetées....", rejetées)
        self._log.FINISH_ACTION(
            "RequestsAdapter", "extraire_données",
            f"{len(publications)} publications extraites"
        )
        return publications

    # ##########################################################################
    # MÉTHODES PRIVÉES
    # ##########################################################################

    # --------------------------------------------------------------------------
    def _évaluer_source_mbfc(self, domaine: str) -> LabelVéracité:
        """
        Évalue la fiabilité d'une source via MediaBiasFactCheck.

        MBFC maintient une base de 5000+ sources mondiales évaluées
        selon leur fiabilité factuelle — utilisée par Wikipedia.

        Paramètres
        ----------
        domaine : str
            Identifiant de la source (ex. : "bbc", "rt", "breitbart").

        Retourne
        --------
        LabelVéracité
            REAL si la source est fiable, FAKE sinon.
        """
        # Évaluation simplifiée — à enrichir avec l'API MBFC complète
        sources_fiables = {
            "bbc", "reuters", "apnews", "afp", "lemonde",
            "lefigaro", "liberation", "theguardian", "nytimes",
        }
        sources_non_fiables = {
            "rt", "sputnik", "breitbart", "infowars",
            "dailymail", "thesun", "foxnews",
        }

        domaine_min = domaine.lower()

        if any(f in domaine_min for f in sources_fiables):
            return LabelVéracité.REAL
        if any(f in domaine_min for f in sources_non_fiables):
            return LabelVéracité.FAKE

        # Défaut : FAKE (prudence — mieux vaut faux positif que faux négatif)
        return LabelVéracité.FAKE

    # --------------------------------------------------------------------------
    def scorer_affirmation(self, texte: str) -> float:
        """
        Score l'affirmabilité d'un texte via ClaimBuster API.

        ClaimBuster (University of Texas) détecte automatiquement
        les affirmations factuellement vérifiables dans un texte.
        Score entre 0.0 (opinion) et 1.0 (affirmation vérifiable).

        Paramètres
        ----------
        texte : str
            Texte à scorer (titre ou premier paragraphe).

        Retourne
        --------
        float
            Score entre 0.0 et 1.0 — utilisé pour prioriser
            les publications à vérifier manuellement.
        """
        if not self._clé_claimbuster:
            return 0.0

        try:
            réponse = self._session.post(
                URL_CLAIMBUSTER,
                headers = {"x-api-key": self._clé_claimbuster},
                json    = {"input_text": texte[:500]},
                timeout = TIMEOUT_REQUÊTE,
            )
            réponse.raise_for_status()
            résultats = réponse.json().get("results", [])
            if résultats:
                return résultats[0].get("score", 0.0)
        except Exception as erreur:
            self._log.LEVEL_5_WARNING(
                "RequestsAdapter",
                f"ClaimBuster indisponible : {erreur}",
            )
        return 0.0
