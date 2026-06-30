# ==============================================================================
# src/adapters/outbound/scrapers/feedparser_adapter.py
# Adaptateur RSS/Atom — Extraction via Feedparser
#
# Sources couvertes (originales — peu utilisées par les étudiants) :
#   1. AFP Factuel          : fact-checker officiel AFP (fr)
#      https://factuel.afp.com/feed
#   2. EUvsDisinfo          : base EU contre désinformation russe (en)
#      https://euvsdisinfo.eu/feed
#   3. Observateur du Monde : vérification FR indépendante (fr)
#      https://www.lesobservateurs.ch/feed/
#   4. Hoaxbuster           : fact-checker FR grand public (fr)
#      https://www.hoaxbuster.com/rss
#
# Pourquoi ces sources sont originales :
#   - AFP Factuel : labels explicites dans le titre (FAUX, VRAI, TROMPEUR)
#   - EUvsDisinfo : base de données EU de désinformation géopolitique
#     avec images systématiques et labels clairs
#   - Pas de Kaggle, pas de Reddit — sources journalistiques officielles
#
# Port implémenté : ScraperPort
# Outil           : Feedparser (parsing XML/RSS natif)
# Test            : uv run scripts/test_feedparser.py
# ==============================================================================

# --- Bibliothèque standard ---------------------------------------------------
import re        # nettoyage des balises HTML résiduelles dans les descriptions
import time      # délai entre les requêtes (respect des quotas)
from typing import List  # annotation de type retour

# --- Dépendances externes ----------------------------------------------------
import feedparser  # parsing RSS/Atom — pip install feedparser
import requests    # vérification accessibilité source (HEAD request)

# --- Domaine -----------------------------------------------------------------
from src.domain.exceptions import (
    CheckItErreur,          # base exception métier
    ImageUrlVideErreur,     # image absente dans l'entrée RSS
    TitreVideErreur,        # titre absent dans l'entrée RSS
)
from src.domain.models     import LabelVéracité, Publication

# --- Port implémenté ---------------------------------------------------------
from src.ports.outbound.scraper_port import ScraperPort

# --- Outil de journalisation -------------------------------------------------
from src.tools.rafael.log_tool import LogTool

# --- Configuration -----------------------------------------------------------
DÉLAI_ENTRE_REQUÊTES = 1.0   # secondes — respect des serveurs RSS
TIMEOUT_REQUÊTE      = 10    # secondes — abandon si source lente
TAILLE_MIN_IMAGE     = 100   # pixels — évite les pixels de tracking


# ==============================================================================
# MAPPAGE DES LABELS PAR SOURCE
# ==============================================================================
# Chaque source utilise ses propres mots-clés pour indiquer la véracité.
# Ce dictionnaire mappe les variantes vers REAL ou FAKE.

LABELS_AFP = {
    # Faux → FAKE
    "faux"        : LabelVéracité.FAKE,
    "fake"        : LabelVéracité.FAKE,
    "trompeur"    : LabelVéracité.FAKE,
    "inexact"     : LabelVéracité.FAKE,
    "manipulé"    : LabelVéracité.FAKE,
    "hors contexte": LabelVéracité.FAKE,
    # Vrai → REAL
    "vrai"        : LabelVéracité.REAL,
    "vérifié"     : LabelVéracité.REAL,
    "confirmé"    : LabelVéracité.REAL,
}

LABELS_EUVSDISINFO = {
    # EUvsDisinfo classe tout comme désinformation
    "disinformation": LabelVéracité.FAKE,
    "fake"          : LabelVéracité.FAKE,
    "false"         : LabelVéracité.FAKE,
    "misleading"    : LabelVéracité.FAKE,
}


# ##############################################################################
# CLASSE : FeedparserAdapter
# ##############################################################################
class FeedparserAdapter(ScraperPort):
    """
    Adaptateur d'extraction depuis les flux RSS/Atom de fact-checkers.

    Implémente ScraperPort pour les sources RSS structurées.
    Les labels sont inférés depuis les titres et catégories des entrées.

    Sources supportées
    ------------------
    - AFP Factuel (fr) — labels explicites dans les titres
    - EUvsDisinfo (en) — base EU de désinformation géopolitique
    - Hoaxbuster (fr)  — fact-checker grand public français
    - Observateur du Monde (fr) — vérification indépendante

    Utilisation
    -----------
    adaptateur = FeedparserAdapter(source="afp")
    publications = adaptateur.extraire_données(
        "https://factuel.afp.com/feed"
    )
    """

    # --------------------------------------------------------------------------
    def __init__(self, source: str = "afp") -> None:
        """
        Paramètres
        ----------
        source : str
            Identifiant de la source ("afp", "euvsdisinfo",
            "hoaxbuster", "observateur").
        """
        self._source = source                    # identifiant source
        self._log    = LogTool(origin="rss")    # logger coloré RFC 5424

    # ==========================================================================
    @property
    def nom_source(self) -> str:
        """Nom lisible de la source pour les logs et KPIs."""
        noms = {
            "afp"          : "AFP Factuel RSS",
            "euvsdisinfo"  : "EUvsDisinfo RSS",
            "hoaxbuster"   : "Hoaxbuster RSS",
            "observateur"  : "Observateur du Monde RSS",
        }
        return noms.get(self._source, f"RSS {self._source}")

    # ==========================================================================
    def est_disponible(self, source_url: str) -> bool:
        """
        Vérifie l'accessibilité du flux RSS avant extraction.
        """
        self._log.START_CALL_CONTROLLER_FUNCTION(
            "FeedparserAdapter", "est_disponible", source_url
        )
        try:
            # Cabeceras completas de un navegador real para pasar desapercibido
            # Al añadir Accept-Language y Cache-Control, los cortafuegos perimetrales 
            # no sospechan de una petición automatizada.
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
                "Cache-Control": "max-age=0",
                "Connection": "keep-alive"
            }

            # Cambiamos HEAD por GET con stream=True (así no descarga todo el contenido si es enorme)
            réponse = requests.get(
                source_url,
                timeout = TIMEOUT_REQUÊTE,
                headers = headers,
                allow_redirects = True,
                stream = True
            )
            
            disponible = réponse.status_code in (200, 301, 302)
            self._log.PARAMETER_VALUE(
                "statut HTTP", f"{réponse.status_code}"
            )
            self._log.FINISH_CALL_CONTROLLER_FUNCTION(
                "FeedparserAdapter", "est_disponible",
                "OK" if disponible else "HORS LIGNE"
            )
            return disponible

        except requests.RequestException as erreur:
            self._log.LEVEL_4_ERROR(
                "FeedparserAdapter", f"Source inaccessible : {erreur}"
            )
            return False

    # ==========================================================================
    def extraire_données(self, source_url: str) -> List[Publication]:
        """
        Extrait les publications depuis un flux RSS/Atom.

        Séquence d'exécution
        --------------------
        1. Parsing du flux via feedparser
        2. Itération sur chaque entrée (entry)
        3. Extraction titre, contenu, image, label
        4. Mapping vers l'entité Publication
        5. Validation et ajout à la liste résultat

        Paramètres
        ----------
        source_url : str
            URL complète du flux RSS/Atom.

        Retourne
        --------
        List[Publication]
            Publications valides extraites — liste vide si aucune.
        """
        self._log.START_ACTION(
            "FeedparserAdapter", "extraire_données", source_url
        )

        publications = []  # résultat final
        rejetées     = 0   # compteur d'entrées invalides

        # ----------------------------------------------------------------------
        # Parsing du flux RSS
        # ----------------------------------------------------------------------
        try:
            # Definimos el mismo agente de navegador simulado
            navigateur_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            
            # Pasamos el agente dentro del método parse
            flux = feedparser.parse(source_url, agent=navigateur_agent)

        except Exception as erreur:
            self._log.LEVEL_4_ERROR(
                "FeedparserAdapter",
                f"Erreur parsing RSS : {erreur}",
            )
            return []

        self._log.PARAMETER_VALUE(
            "entrées trouvées", len(flux.entries)
        )
        self._log.PARAMETER_VALUE(
            "source................", self.nom_source
        )

        # ----------------------------------------------------------------------
        # Traitement de chaque entrée RSS
        # ----------------------------------------------------------------------
        for entrée in flux.entries:
            try:
                time.sleep(DÉLAI_ENTRE_REQUÊTES)

                # -- Extraction des champs ------------------------------------
                titre   = self._extraire_titre(entrée)
                contenu = self._extraire_contenu(entrée)
                image   = self._extraire_image(entrée)
                label   = self._inférer_label(titre, entrée)

                # -- Validation paire texte-image -----------------------------
                if not image:
                    rejetées += 1
                    self._log.LEVEL_5_WARNING(
                        "FeedparserAdapter",
                        f"Image absente : {titre[:50]}",
                    )
                    continue

                # -- Création de la Publication --------------------------------
                pub = Publication(
                    title         = titre,
                    content       = contenu,
                    image_url     = image,
                    source_domain = self._source + ".com",
                    declared_label= label,
                    lang          = self._détecter_langue(entrée),
                    metadata      = self._extraire_métadonnées(entrée),
                )

                if pub.est_valide():
                    publications.append(pub)
                    self._log.LEVEL_7_INFO(
                        "FeedparserAdapter",
                        f"[{label.value}] {titre[:60]}",
                    )
                else:
                    rejetées += 1

            except CheckItErreur as erreur:
                rejetées += 1
                self._log.LEVEL_5_WARNING(
                    "FeedparserAdapter", str(erreur)
                )
            except Exception as erreur:
                rejetées += 1
                self._log.LEVEL_4_ERROR(
                    "FeedparserAdapter",
                    f"Erreur inattendue : {erreur}",
                )

        # ----------------------------------------------------------------------
        # Rapport d'extraction
        # ----------------------------------------------------------------------
        self._log.PARAMETER_VALUE(
            "publications valides", len(publications)
        )
        self._log.PARAMETER_VALUE(
            "entrées rejetées....", rejetées
        )
        taux = (
            round(len(publications) /
                  (len(publications) + rejetées) * 100, 1)
            if (len(publications) + rejetées) > 0 else 0
        )
        self._log.PARAMETER_VALUE(
            "taux d'intégrité....", f"{taux}%"
        )
        self._log.FINISH_ACTION(
            "FeedparserAdapter", "extraire_données",
            f"{len(publications)} publications extraites"
        )
        return publications

    # ##########################################################################
    # MÉTHODES PRIVÉES — extraction des champs
    # ##########################################################################

    # --------------------------------------------------------------------------
    def _extraire_titre(self, entrée: object) -> str:
        """Extrait et nettoie le titre de l'entrée RSS."""
        titre = getattr(entrée, "title", "").strip()
        if not titre:
            raise TitreVideErreur(self._source)
        return self._nettoyer_html(titre)

    # --------------------------------------------------------------------------
    def _extraire_contenu(self, entrée: object) -> str:
        """
        Extrait le corps texte depuis summary ou content.
        Priorité : content[0].value > summary > description.
        """
        # -- Tentative content (plus complet) ---------------------------------
        if hasattr(entrée, "content") and entrée.content:
            return self._nettoyer_html(entrée.content[0].value)

        # -- Fallback summary -------------------------------------------------
        if hasattr(entrée, "summary"):
            return self._nettoyer_html(entrée.summary)

        # -- Fallback description ---------------------------------------------
        return self._nettoyer_html(
            getattr(entrée, "description", "")
        )

    # --------------------------------------------------------------------------
    def _extraire_image(self, entrée: object) -> str:
        """
        Extrait l'URL de l'image depuis les balises RSS.

        Ordre de priorité :
        1. media:content (standard RSS étendu)
        2. enclosures (podcasts et médias)
        3. media:thumbnail
        4. Extraction regex depuis le contenu HTML
        """
        # -- media:content ----------------------------------------------------
        if hasattr(entrée, "media_content"):
            for média in entrée.media_content:
                url = média.get("url", "")
                if url and self._est_image(url):
                    return url

        # -- enclosures -------------------------------------------------------
        if hasattr(entrée, "enclosures"):
            for enc in entrée.enclosures:
                if enc.get("type", "").startswith("image/"):
                    return enc.get("href", "")

        # -- media:thumbnail --------------------------------------------------
        if hasattr(entrée, "media_thumbnail"):
            for thumb in entrée.media_thumbnail:
                url = thumb.get("url", "")
                if url:
                    return url

        # -- Extraction depuis le HTML du contenu -----------------------------
        contenu_html = getattr(entrée, "summary", "")
        correspondance = re.search(
            r'<img[^>]+src=["\']([^"\']+)["\']', contenu_html
        )
        if correspondance:
            return correspondance.group(1)

        return ""  # aucune image trouvée

    # --------------------------------------------------------------------------
    def _inférer_label(self, titre: str, entrée: object) -> LabelVéracité:
        """
        Infère le label REAL/FAKE depuis le titre et les catégories.

        AFP Factuel inclut explicitement "FAUX", "VRAI", "TROMPEUR"
        dans ses titres. EUvsDisinfo classifie tout en désinformation.
        """
        titre_min = titre.lower()

        # -- Recherche dans les mots-clés AFP ---------------------------------
        for mot_clé, label in LABELS_AFP.items():
            if mot_clé in titre_min:
                return label

        # -- Recherche dans les catégories ------------------------------------
        catégories = [
            tag.get("term", "").lower()
            for tag in getattr(entrée, "tags", [])
        ]
        for catégorie in catégories:
            for mot_clé, label in LABELS_AFP.items():
                if mot_clé in catégorie:
                    return label

        # -- EUvsDisinfo : tout est désinformation par défaut -----------------
        if self._source == "euvsdisinfo":
            return LabelVéracité.FAKE

        # -- Défaut : FAKE (les fact-checkers signalent du faux) --------------
        return LabelVéracité.FAKE

    # --------------------------------------------------------------------------
    def _détecter_langue(self, entrée: object) -> str:
        """Détecte la langue depuis les métadonnées RSS."""
        langue = getattr(entrée, "language", "")
        if langue:
            return langue[:2].lower()
        return "fr" if self._source in ("afp", "hoaxbuster") else "en"

    # --------------------------------------------------------------------------
    def _extraire_métadonnées(self, entrée: object) -> dict:
        """Extrait les métadonnées secondaires de l'entrée RSS."""
        return {
            "url_source"  : getattr(entrée, "link", ""),
            "auteur"      : getattr(entrée, "author", ""),
            "date_publi"  : getattr(entrée, "published", ""),
            "catégories"  : [
                tag.get("term", "")
                for tag in getattr(entrée, "tags", [])
            ],
        }

    # --------------------------------------------------------------------------
    @staticmethod
    def _nettoyer_html(texte: str) -> str:
        """Supprime les balises HTML résiduelles d'un texte RSS."""
        texte_propre = re.sub(r"<[^>]+>", " ", texte)
        texte_propre = re.sub(r"\s+", " ", texte_propre)
        return texte_propre.strip()

    # --------------------------------------------------------------------------
    @staticmethod
    def _est_image(url: str) -> bool:
        """Vérifie qu'une URL pointe vers une image."""
        extensions = (".jpg", ".jpeg", ".png", ".webp", ".gif")
        return any(url.lower().endswith(ext) for ext in extensions)
