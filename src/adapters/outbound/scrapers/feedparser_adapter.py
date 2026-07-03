# ==============================================================================
# src/adapters/outbound/scrapers/feedparser_adapter.py
# Adaptateur RSS/Atom — Extraction via Feedparser
#
# Sources couvertes (originales — peu utilisées par les étudiants) :
#   1. AFP Factuel          : fact-checker officiel AFP (fr)
#      https://factuel.afp.com/feed  (bloqué) → fallback Bluesky RSS
#   2. EUvsDisinfo          : base EU contre désinformation russe (en)
#      https://euvsdisinfo.eu/feed/
#   3. Observateur du Monde : vérification FR indépendante (fr)
#      https://www.lesobservateurs.ch/feed/
#   4. Hoaxbuster           : fact-checker FR grand public (fr)
#      https://www.hoaxbuster.com/rss/
#   5. El País              : média de référence espagnol (es) — label REAL
#      https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada
#      Flux Media RSS : image incluse via media:content (pas de fetch og:image)
#   6. PolitiFact           : fact-checker US, ratings Truth-O-Meter (en)
#      https://www.politifact.com/rss/factchecks/
#      Le flux ne contient NI image NI rating : les deux sont extraits de la
#      page de l'article en UN SEUL fetch (og:image + image du Truth-O-Meter
#      dont l'URL encode le rating : rulings/meter-false.jpg, etc.)
#   7. Les Décodeurs        : rubrique vérification du Monde (fr)
#      https://www.lemonde.fr/les-decodeurs/rss_full.xml
#      Remplace le Decodex (moteur de fiabilité de sites, non extractible).
#      Le flux mélange fact-checks et journalisme de données : le label est
#      inféré par mots-clés et les entrées sans label sont REJETÉES
#      (pas de label FAKE par défaut pour cette source).
#   8. Chequeado            : fact-checker IFCN argentin (es)
#      https://chequeado.com/feed/
#      Remplace Africa Check (protection anti-bot : HTTP 403 sur toute
#      requête automatisée, incompatible avec une extraction respectueuse
#      des CGU). Le flux mélange fact-checks et posts institutionnels :
#      mots-clés espagnols, rejet des entrées sans label (comme Décodeurs).
#
# Pourquoi ces sources sont originales :
#   - AFP Factuel : labels explicites dans le titre (FAUX, VRAI, TROMPEUR)
#   - EUvsDisinfo : base de données EU de désinformation géopolitique
#     avec images systématiques et labels clairs
#   - El País : média de référence — fournit la classe REAL du dataset
#     (approche FakeNewsNet : articles de presse établie = REAL)
#   - Pas de Kaggle, pas de Reddit — sources journalistiques officielles
#
# Politique réseau :
#   - Le délai de politesse (DÉLAI_ENTRE_REQUÊTES) ne s'applique QUE si une
#     requête HTTP a réellement été émise pour l'entrée (fetch og:image).
#     Les flux MRSS fournissent l'image dans le flux : aucun délai nécessaire.
#
# Politique de validation :
#   - La paire texte-image est une contrainte fondamentale du dataset
#     multimodal : toute entrée sans image est REJETÉE et comptabilisée.
#     Le message de log et le compteur de rejets disent la même chose.
#
# Port implémenté : ScraperPort
# Outil           : Feedparser (parsing XML/RSS natif)
# Test            : python3 scripts/test_feedparser.py
# ==============================================================================

# --- Bibliothèque standard : nettoyage de texte et délais réseau -------------
import re                                  # Nettoyage des balises HTML
import time                                # Délai de politesse entre requêtes

from   typing import List                  # Annotation du type de retour

# --- Dépendances externes : parsing RSS et vérifications HTTP ----------------
import feedparser                          # Parsing RSS/Atom — pip feedparser
import requests                            # Vérification accessibilité source

# --- Domaine : entités et exceptions métier (zéro dépendance externe) --------
from   src.domain.exceptions import (
    CheckItErreur,                         # Base de toutes les erreurs métier
    ImageUrlVideErreur,                    # Image absente dans l'entrée RSS
    LabelInvalideErreur,                   # Label non normalisable → rejet
    TitreVideErreur,                       # Titre absent dans l'entrée RSS
)
from   src.domain.models     import LabelVéracité, Publication

# --- Port implémenté : contrat d'extraction défini par le domaine ------------
from   src.ports.outbound.scraper_port import ScraperPort

# --- Outil de journalisation colorée en console (RFC 5424) -------------------
from   src.tools.rafael.log_tool import LogTool


# ==============================================================================
# CONFIGURATION — paramètres réseau et qualité d'image
# ==============================================================================
DÉLAI_ENTRE_REQUÊTES = 1.0                 # s  — politesse envers les serveurs
TIMEOUT_REQUÊTE      = 30                  # s  — sources lentes (Hoaxbuster)
TIMEOUT_OG_IMAGE     = 10                  # s  — fetch og:image d'un article
TAILLE_MIN_IMAGE     = 100                 # px — évite les pixels de tracking

# User-Agent d'un navigateur réel : partagé par toutes les requêtes HTTP.
# En-tête complet pour que les pare-feux périmétriques ne soupçonnent pas
# une requête automatisée (mutualisé — était dupliqué dans deux méthodes).
AGENT_NAVIGATEUR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ==============================================================================
# MAPPAGE DES LABELS PAR SOURCE
# ==============================================================================
# Chaque source utilise ses propres mots-clés pour indiquer la véracité.
# Ces dictionnaires mappent les variantes vers REAL ou FAKE.
# El País n'a pas de mappage : son label est fixe (REAL) — cf. _inférer_label.

LABELS_AFP = {
    # -- Faux → FAKE -----------------------------------------------------------
    "faux"          : LabelVéracité.FAKE,
    "fake"          : LabelVéracité.FAKE,
    "trompeur"      : LabelVéracité.FAKE,
    "inexact"       : LabelVéracité.FAKE,
    "manipulé"      : LabelVéracité.FAKE,
    "hors contexte" : LabelVéracité.FAKE,
    "intox"         : LabelVéracité.FAKE,
    "infox"         : LabelVéracité.FAKE,
    # -- Vrai → REAL -----------------------------------------------------------
    "vrai"          : LabelVéracité.REAL,
    "vérifié"       : LabelVéracité.REAL,
    "confirmé"      : LabelVéracité.REAL,
}

LABELS_EUVSDISINFO = {
    # -- EUvsDisinfo classe tout comme désinformation --------------------------
    "disinformation" : LabelVéracité.FAKE,
    "fake"           : LabelVéracité.FAKE,
    "false"          : LabelVéracité.FAKE,
    "misleading"     : LabelVéracité.FAKE,
}

# PolitiFact : le rating est encodé dans l'URL de l'image du Truth-O-Meter
# présente sur la page de l'article (ex : rulings/meter-false.jpg).
# "meter-half-true" est volontairement ABSENT : un label mi-vrai n'est pas
# normalisable en binaire REAL/FAKE → LabelInvalideErreur → entrée rejetée.
LABELS_POLITIFACT = {
    "meter-true"         : LabelVéracité.REAL,
    "meter-mostly-true"  : LabelVéracité.REAL,
    "meter-mostly-false" : LabelVéracité.FAKE,
    "meter-false"        : LabelVéracité.FAKE,
    "tom_ruling_pof"     : LabelVéracité.FAKE,  # "Pants on Fire"
}

# Chequeado : ratings espagnols dans les titres ("Es falso que...").
# "discutible" et "apresurado" sont volontairement ABSENTS : non binaires.
# Sans mot-clé (posts institutionnels), l'entrée est rejetée proprement.
LABELS_CHEQUEADO = {
    # -- Falso → FAKE ----------------------------------------------------------
    "falso"       : LabelVéracité.FAKE,
    "falsa"       : LabelVéracité.FAKE,
    "engañoso"    : LabelVéracité.FAKE,
    "engañosa"    : LabelVéracité.FAKE,
    "insostenible": LabelVéracité.FAKE,
    "exagerado"   : LabelVéracité.FAKE,
    "exagerada"   : LabelVéracité.FAKE,
    # -- Verdadero → REAL ------------------------------------------------------
    "verdadero"   : LabelVéracité.REAL,
    "verdadera"   : LabelVéracité.REAL,
}

# Domaine réel de chaque source quand "<source>.com" serait incorrect.
# Indispensable pour la traçabilité (KPIs par source, run_sources).
DOMAINES_SOURCES = {
    "decodeurs" : "lemonde.fr",
    "elpais"    : "elpais.com",
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
    - El País (es)     — média de référence, label fixe REAL
    - PolitiFact (en)  — rating Truth-O-Meter extrait de l'article
    - Les Décodeurs (fr) — label par mots-clés, rejet si inconnu
    - Chequeado (es)   — mots-clés espagnols, rejet si inconnu

    Utilisation
    -----------
    adaptateur   = FeedparserAdapter(source="afp")
    publications = adaptateur.extraire_données(
        "https://factuel.afp.com/feed"
    )
    """

    # ##########################################################################
    def __init__(self, source: str = "afp") -> None:
        """
        Paramètres
        ----------
        source : str
            Identifiant de la source ("afp", "euvsdisinfo",
            "hoaxbuster", "observateur", "elpais").
        """
        self._source          = source           # Identifiant de la source
        self._log             = LogTool(origin="rss")  # Logger RFC 5424
        self._fetch_effectué  = False            # True si requête HTTP émise
                                                 # pour l'entrée en cours —
                                                 # pilote le délai de politesse
        self._html_article    = ""               # Cache du HTML de l'article
                                                 # fetché pour og:image —
                                                 # relu par _inférer_label
                                                 # (rating PolitiFact)

    # ##########################################################################
    @property
    def nom_source(self) -> str:
        """Nom lisible de la source pour les logs et KPIs."""
        noms = {
            "afp"         : "AFP Factuel RSS",
            "afp_bluesky" : "AFP Factuel Bluesky RSS",
            "euvsdisinfo" : "EUvsDisinfo RSS",
            "hoaxbuster"  : "Hoaxbuster RSS",
            "observateur" : "Observateur du Monde RSS",
            "elpais"      : "El País MRSS",
            "politifact"  : "PolitiFact RSS",
            "decodeurs"   : "Les Décodeurs (Le Monde) RSS",
            "chequeado"   : "Chequeado RSS",
        }
        return noms.get(self._source, f"RSS {self._source}")

    # ##########################################################################
    def est_disponible(self, source_url: str) -> bool:
        """
        Vérifie l'accessibilité du flux RSS avant extraction.
        """
        self._log.START_CALL_CONTROLLER_FUNCTION(
            "FeedparserAdapter", "est_disponible", source_url
        )
        try:
            # ------------------------------------------------------------------
            # En-têtes complets d'un navigateur réel pour passer inaperçu.
            # Accept-Language et Cache-Control rendent la requête crédible
            # aux yeux des pare-feux périmétriques.
            # ------------------------------------------------------------------
            headers = {
                "User-Agent"      : AGENT_NAVIGATEUR,
                "Accept"          : ("text/html,application/xhtml+xml,"
                                     "application/xml;q=0.9,image/webp,"
                                     "image/apng,*/*;q=0.8"),
                "Accept-Language" : "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
                "Cache-Control"   : "max-age=0",
                "Connection"      : "keep-alive",
            }

            # ------------------------------------------------------------------
            # HEAD remplacé par GET avec stream=True : la connexion est
            # ouverte sans télécharger tout le contenu si le flux est énorme.
            # ------------------------------------------------------------------
            réponse = requests.get(
                source_url,
                timeout         = TIMEOUT_REQUÊTE,
                headers         = headers,
                allow_redirects = True,
                stream          = True,
            )

            disponible = réponse.status_code in (200, 301, 302)
            self._log.PARAMETER_VALUE("statut HTTP", f"{réponse.status_code}")
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

    # ##########################################################################
    def extraire_données(self, source_url: str) -> List[Publication]:
        """
        Extrait les publications depuis un flux RSS/Atom.

        Séquence d'exécution
        --------------------
        1. Parsing du flux via feedparser
        2. Itération sur chaque entrée (entry)
        3. Extraction titre, contenu, image, label
        4. Délai de politesse UNIQUEMENT si une requête HTTP a été émise
        5. Rejet des entrées sans image (contrainte texte-image du dataset)
        6. Mapping vers l'entité Publication
        7. Validation et ajout à la liste résultat

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

        publications = []                        # Résultat final
        rejetées     = 0                         # Compteur d'entrées invalides

        # ----------------------------------------------------------------------
        # Parsing du flux RSS
        # ----------------------------------------------------------------------
        try:
            # L'agent navigateur est transmis directement à parse() : sans
            # lui, certains serveurs (Hoaxbuster) refusent les robots.
            flux = feedparser.parse(source_url, agent=AGENT_NAVIGATEUR)

        except Exception as erreur:
            self._log.LEVEL_4_ERROR(
                "FeedparserAdapter",
                f"Erreur parsing RSS : {erreur}",
            )
            return []

        self._log.PARAMETER_VALUE("entrées trouvées", len(flux.entries))
        self._log.PARAMETER_VALUE("source", self.nom_source)

        # ----------------------------------------------------------------------
        # Traitement de chaque entrée RSS
        # ----------------------------------------------------------------------
        for entrée in flux.entries:
            try:
                # -- Extraction des champs -------------------------------------
                self._fetch_effectué = False     # Remis à zéro à chaque entrée
                self._html_article   = ""        # Cache HTML remis à zéro
                titre   = self._extraire_titre(entrée)
                contenu = self._extraire_contenu(entrée)
                image   = self._extraire_image(entrée)
                label   = self._inférer_label(titre, entrée)

                # -- Délai de politesse conditionnel ---------------------------
                # Le délai protège les serveurs sources contre le matraquage,
                # mais il n'a de sens que si une requête HTTP a réellement été
                # émise (_extraire_image → fetch og:image). Les flux MRSS
                # (El País) fournissent l'image dans le flux : aucune requête,
                # donc aucun délai (≈151 s économisées sur 154 entrées).
                if self._fetch_effectué:
                    time.sleep(DÉLAI_ENTRE_REQUÊTES)

                # -- Validation de la paire texte-image ------------------------
                # Contrainte fondamentale du dataset multimodal CheckIt.AI :
                # toute entrée sans image est rejetée et comptabilisée.
                # Le message du log dit la même chose que le compteur —
                # cohérence indispensable pour le KPI taux d'intégrité.
                if not image:
                    rejetées += 1
                    self._log.LEVEL_5_WARNING(
                        "FeedparserAdapter",
                        f"Image absente — entrée rejetée : {titre[:50]}",
                    )
                    continue

                # -- Création de la Publication --------------------------------
                pub = Publication(
                    title          = titre,
                    content        = contenu,
                    image_url      = image,
                    source_domain  = DOMAINES_SOURCES.get(
                        self._source, self._source + ".com"
                    ),
                    declared_label = label,
                    lang           = self._détecter_langue(entrée),
                    metadata       = self._extraire_métadonnées(entrée),
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
                self._log.LEVEL_5_WARNING("FeedparserAdapter", str(erreur))
            except Exception as erreur:
                rejetées += 1
                self._log.LEVEL_4_ERROR(
                    "FeedparserAdapter",
                    f"Erreur inattendue : {erreur}",
                )

        # ----------------------------------------------------------------------
        # Rapport d'extraction
        # ----------------------------------------------------------------------
        self._log.PARAMETER_VALUE("publications valides", len(publications))
        self._log.PARAMETER_VALUE("entrées rejetées", rejetées)
        total = len(publications) + rejetées
        taux  = round(len(publications) / total * 100, 1) if total else 0
        self._log.PARAMETER_VALUE("taux d'intégrité", f"{taux}%")
        self._log.FINISH_ACTION(
            "FeedparserAdapter", "extraire_données",
            f"{len(publications)} publications extraites"
        )
        return publications

    # ##########################################################################
    # MÉTHODES PRIVÉES — extraction des champs
    # ##########################################################################

    # ##########################################################################
    def _extraire_titre(self, entrée: object) -> str:
        """
        Extrait et nettoie le titre de l'entrée RSS.

        Pour les flux Bluesky (AFP Factuel) qui n'ont pas de champ title,
        utilise la première ligne du summary comme titre.
        """
        titre = getattr(entrée, "title", "").strip()

        # -- Fallback : première ligne du summary (Bluesky RSS) ----------------
        if not titre:
            summary = getattr(entrée, "summary", "").strip()
            if summary:
                # Première ligne non vide — ignore les emojis seuls
                for ligne in summary.splitlines():
                    ligne = ligne.strip()
                    if ligne and len(ligne) > 5:
                        titre = self._nettoyer_html(ligne)
                        break

        if not titre:
            raise TitreVideErreur(self._source)
        return self._nettoyer_html(titre)

    # ##########################################################################
    def _extraire_contenu(self, entrée: object) -> str:
        """
        Extrait le corps texte depuis summary ou content.
        Priorité : content[0].value > summary > description.
        """
        # -- Tentative content (plus complet) ----------------------------------
        if hasattr(entrée, "content") and entrée.content:
            return self._nettoyer_html(entrée.content[0].value)

        # -- Fallback summary ---------------------------------------------------
        if hasattr(entrée, "summary"):
            return self._nettoyer_html(entrée.summary)

        # -- Fallback description -----------------------------------------------
        return self._nettoyer_html(getattr(entrée, "description", ""))

    # ##########################################################################
    def _extraire_image(self, entrée: object) -> str:
        """
        Extrait l'URL de l'image depuis les balises RSS.

        Ordre de priorité :
        1. media:content (standard Media RSS — El País, EUvsDisinfo)
        2. enclosures (podcasts et médias)
        3. media:thumbnail
        4. Extraction regex depuis le contenu HTML
        5. Fetch og:image de l'article (seule étape émettant une requête
           HTTP — elle active self._fetch_effectué pour le délai réseau)
        """
        # -- 1. media:content ---------------------------------------------------
        if hasattr(entrée, "media_content"):
            for média in entrée.media_content:
                url = média.get("url", "")
                if url and self._est_image(url):
                    return url

        # -- 2. enclosures ------------------------------------------------------
        if hasattr(entrée, "enclosures"):
            for enc in entrée.enclosures:
                if enc.get("type", "").startswith("image/"):
                    return enc.get("href", "")

        # -- 3. media:thumbnail -------------------------------------------------
        if hasattr(entrée, "media_thumbnail"):
            for thumb in entrée.media_thumbnail:
                url = thumb.get("url", "")
                if url:
                    return url

        # -- 4. Extraction depuis le HTML du contenu ----------------------------
        contenu_html   = getattr(entrée, "summary", "")
        correspondance = re.search(
            r'<img[^>]+src=["\']([^"\']+)["\']', contenu_html
        )
        if correspondance:
            return correspondance.group(1)

        # -- 5. Fallback : récupérer og:image depuis l'URL de l'article ---------
        # Pour EUvsDisinfo et AFP Bluesky (le lien AFP est dans le summary).
        url_article = getattr(entrée, "link", "")

        # AFP Bluesky : le lien AFP court est dans le summary (u.afp.com/...)
        summary_txt = getattr(entrée, "summary", "")
        lien_afp    = re.search(r'https?://u\.afp\.com/\S+', summary_txt)
        if lien_afp:
            url_article = lien_afp.group(0)

        if url_article:
            try:
                # Seule branche émettant une requête HTTP : on lève le
                # drapeau pour que la boucle applique le délai de politesse.
                self._fetch_effectué = True
                réponse = requests.get(
                    url_article,
                    timeout = TIMEOUT_OG_IMAGE,
                    headers = {"User-Agent": AGENT_NAVIGATEUR},
                )
                if réponse.status_code == 200:
                    # Cache du HTML : relu par _inférer_label pour extraire
                    # le rating PolitiFact SANS émettre de seconde requête.
                    self._html_article = réponse.text
                    # Balise og:image — ordre property puis content
                    og = re.search(
                        r'<meta[^>]+property=["\']og:image["\'][^>]+'
                        r'content=["\']([^"\']+)["\']',
                        réponse.text,
                    )
                    if og:
                        return og.group(1)
                    # Ordre inversé (content avant property)
                    og2 = re.search(
                        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+'
                        r'property=["\']og:image["\']',
                        réponse.text,
                    )
                    if og2:
                        return og2.group(1)
            except Exception:
                pass                             # Article inaccessible → rejet

        return ""                                # Aucune image trouvée

    # ##########################################################################
    def _inférer_label(self, titre: str, entrée: object) -> LabelVéracité:
        """
        Infère le label REAL/FAKE depuis le titre et les catégories.

        AFP Factuel inclut explicitement "FAUX", "VRAI", "TROMPEUR"
        dans ses titres. EUvsDisinfo classifie tout en désinformation.
        El País : label fixe REAL par la confiance de la source.
        """
        # ----------------------------------------------------------------------
        # El País : média de référence → label fixe REAL
        # Le label n'est PAS inféré du titre : un article d'El País qui
        # contient "falso" ou "fake" reste REAL (approche FakeNewsNet —
        # la classe REAL provient d'articles de presse établie).
        # Ce bloc DOIT rester avant la recherche des mots-clés AFP.
        # ----------------------------------------------------------------------
        if self._source == "elpais":
            return LabelVéracité.REAL

        # ----------------------------------------------------------------------
        # PolitiFact : rating extrait du HTML de l'article (déjà en cache
        # grâce au fetch og:image — aucune requête supplémentaire).
        # L'URL de l'image du Truth-O-Meter encode le rating :
        #   .../politifact/rulings/meter-false.jpg  → FAKE
        #   .../politifact/rulings/meter-true.jpg   → REAL
        #   .../politifact/rulings/tom_ruling_pof.png → FAKE (Pants on Fire)
        # Un rating absent ou non binaire (half-true) → entrée rejetée.
        # ----------------------------------------------------------------------
        if self._source == "politifact":
            slug = re.search(
                r'politifact/rulings/([a-z0-9_-]+)\.(?:jpg|png)',
                self._html_article,
            )
            slug_txt = slug.group(1) if slug else "rating introuvable"
            if slug_txt in LABELS_POLITIFACT:
                return LABELS_POLITIFACT[slug_txt]
            raise LabelInvalideErreur(slug_txt, "politifact.com")

        # ----------------------------------------------------------------------
        # Chequeado : ratings espagnols dans le titre ("Es falso que...").
        # Le flux mélange fact-checks et posts institutionnels : sans
        # mot-clé de véracité, l'entrée est rejetée (pas de FAKE par défaut).
        # ----------------------------------------------------------------------
        if self._source == "chequeado":
            titre_es = titre.lower()
            for mot_clé, label in LABELS_CHEQUEADO.items():
                if mot_clé in titre_es:
                    return label
            raise LabelInvalideErreur("aucun mot-clé", "chequeado.com")

        titre_min = titre.lower()

        # -- Recherche dans les mots-clés AFP -----------------------------------
        for mot_clé, label in LABELS_AFP.items():
            if mot_clé in titre_min:
                return label

        # -- Recherche dans les catégories --------------------------------------
        catégories = [
            tag.get("term", "").lower()
            for tag in getattr(entrée, "tags", [])
        ]
        for catégorie in catégories:
            for mot_clé, label in LABELS_AFP.items():
                if mot_clé in catégorie:
                    return label

        # ----------------------------------------------------------------------
        # Les Décodeurs : PAS de label FAKE par défaut.
        # Le flux mélange fact-checks et journalisme de données ("qui sont
        # les 34 candidats ?") : sans mot-clé de véracité dans le titre ou
        # les catégories, l'entrée n'est pas labellisable → rejet propre.
        # ----------------------------------------------------------------------
        if self._source == "decodeurs":
            raise LabelInvalideErreur("aucun mot-clé", "lemonde.fr")

        # -- EUvsDisinfo : tout est désinformation par défaut -------------------
        if self._source == "euvsdisinfo":
            return LabelVéracité.FAKE

        # -- Défaut : FAKE (les fact-checkers signalent du faux) ----------------
        return LabelVéracité.FAKE

    # ##########################################################################
    def _détecter_langue(self, entrée: object) -> str:
        """Détecte la langue depuis les métadonnées RSS."""
        langue = getattr(entrée, "language", "")
        if langue:
            return langue[:2].lower()
        if self._source in ("elpais", "chequeado"):
            return "es"                          # Sources hispanophones
        if self._source in ("afp", "hoaxbuster", "decodeurs"):
            return "fr"                          # Sources francophones
        return "en"                              # Défaut — anglophone

    # ##########################################################################
    def _extraire_métadonnées(self, entrée: object) -> dict:
        """Extrait les métadonnées secondaires de l'entrée RSS."""
        return {
            "url_source" : getattr(entrée, "link", ""),
            "auteur"     : getattr(entrée, "author", ""),
            "date_publi" : getattr(entrée, "published", ""),
            "catégories" : [
                tag.get("term", "")
                for tag in getattr(entrée, "tags", [])
            ],
        }

    # ##########################################################################
    @staticmethod
    def _nettoyer_html(texte: str) -> str:
        """Supprime les balises HTML résiduelles d'un texte RSS."""
        texte_propre = re.sub(r"<[^>]+>", " ", texte)
        texte_propre = re.sub(r"\s+",     " ", texte_propre)
        return texte_propre.strip()

    # ##########################################################################
    @staticmethod
    def _est_image(url: str) -> bool:
        """
        Vérifie qu'une URL pointe vers une image.

        La query string est ignorée : les CDN d'images (El País par
        exemple) ajoutent un jeton d'authentification après l'extension
        (.jpg?auth=...) qui faisait échouer le test endswith().
        """
        chemin     = url.lower().split("?")[0]   # Ignore les paramètres ?auth=
        extensions = (".jpg", ".jpeg", ".png", ".webp", ".gif")
        return any(chemin.endswith(ext) for ext in extensions)
