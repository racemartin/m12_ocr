# ==============================================================================
# src/domain/models.py — Entités métier du domaine CheckIt.AI
#
# Règle absolue : ZÉRO import externe dans ce fichier.
# Ce module ne dépend que de la bibliothèque standard Python.
# Toute dépendance externe (requests, pydantic, sqlalchemy...)
# appartient aux adaptateurs, jamais au domaine.
#
# Entités définies :
#   LabelVéracité  — énumération REAL / FAKE
#   Publication    — entité centrale du pipeline ETL
#   Source         — configuration d'une source de données
#   ExtractionRun  — statistiques d'une exécution du pipeline
# ==============================================================================

# --- Bibliothèque standard uniquement ---------------------------------------
import hashlib    # calcul de l'identifiant SHA-256 unique
from dataclasses import dataclass, field  # déclaration d'entités sans boilerplate
from datetime    import datetime          # horodatage de capture
from enum        import Enum             # énumération typée des labels
from typing      import List, Optional   # champs optionnels et listes typées


# ==============================================================================
# ÉNUMÉRATION : LabelVéracité
# ==============================================================================
class LabelVéracité(str, Enum):
    """
    Étiquette de véracité normalisée pour une publication.

    Hérite de str pour permettre la sérialisation JSON directe
    sans conversion manuelle (ex. : json.dumps(label) → "REAL").

    Valeurs
    -------
    REAL : contenu vérifié comme authentique.
    FAKE : contenu identifié comme désinformation.
    """

    REAL = "REAL"   # contenu authentique — vérifié
    FAKE = "FAKE"   # désinformation — détectée ou déclarée


# ==============================================================================
# ENTITÉ : Publication
# ==============================================================================
@dataclass
class Publication:
    """
    Entité centrale du pipeline ETL CheckIt.AI.

    Représente une publication multimodale (texte + image) extraite
    depuis une source quelconque (API, RSS, scraping, dataset).
    Toutes les sources produisent des instances de cette même entité —
    c'est le contrat commun garanti par l'architecture hexagonale.

    Attributs obligatoires
    ----------------------
    title          : titre ou headline de la publication.
    content        : corps texte principal (article, post, description).
    image_url      : URL de l'image associée — validée par validate_image().
    source_domain  : domaine d'origine (ex. : "reddit.com", "snopes.com").
    declared_label : étiquette de véracité normalisée REAL ou FAKE.

    Attributs calculés automatiquement
    -----------------------------------
    id             : hash SHA-256 unique calculé depuis title + source_domain.
    captured_at    : horodatage UTC de création de l'instance.

    Attributs optionnels
    --------------------
    lang           : code langue ISO 639-1 (ex. : "fr", "en", "es").
    metadata       : dictionnaire secondaire libre (auteur, URL source,
                     score communautaire, date de publication originale...).

    Exemple d'utilisation
    ---------------------
    pub = Publication(
        title         = "Vaccins : une étude prouve...",
        content       = "Une étude récente affirme que...",
        image_url     = "https://example.com/image.jpg",
        source_domain = "snopes.com",
        declared_label= LabelVéracité.FAKE,
        lang          = "fr",
        metadata      = {"auteur": "John Doe", "url_source": "https://..."},
    )
    """

    # --- Champs obligatoires -------------------------------------------------
    title          : str            # titre de la publication
    content        : str            # corps texte principal
    image_url      : str            # URL image associée (validée)
    source_domain  : str            # domaine source d'extraction
    declared_label : LabelVéracité  # étiquette REAL ou FAKE normalisée

    # --- Champs optionnels ---------------------------------------------------
    lang           : str            = "fr"   # langue ISO 639-1
    metadata       : dict           = field(default_factory=dict)

    # --- Champs calculés automatiquement -------------------------------------
    id             : str            = field(init=False)  # hash SHA-256
    captured_at    : datetime       = field(init=False)  # horodatage UTC

    # --------------------------------------------------------------------------
    def __post_init__(self) -> None:
        """
        Calcule les champs dérivés après initialisation.

        Appelé automatiquement par @dataclass après __init__.
        Génère l'identifiant unique et l'horodatage de capture.
        """
        # -- Calcul de l'identifiant SHA-256 ----------------------------------
        # Basé sur title + source_domain pour garantir l'unicité
        # indépendamment de la langue ou du label déclaré.
        contenu_hash   = f"{self.title}{self.source_domain}".encode("utf-8")
        self.id        = hashlib.sha256(contenu_hash).hexdigest()

        # -- Horodatage UTC de capture ----------------------------------------
        self.captured_at = datetime.utcnow()

    # --------------------------------------------------------------------------
    def est_valide(self) -> bool:
        """
        Vérifie que la publication possède tous les champs obligatoires
        non vides requis pour l'entraînement du modèle IA.

        Une publication invalide est rejetée par le pipeline de
        transformation (étape validate_raw_task du DAG Airflow).

        Retourne
        --------
        bool
            True si title, content, image_url et source_domain
            sont tous renseignés et non vides.
        """
        return all([
            bool(self.title.strip()),
            bool(self.content.strip()),
            bool(self.image_url.strip()),
            bool(self.source_domain.strip()),
        ])

    # --------------------------------------------------------------------------
    def vers_dict(self) -> dict:
        """
        Sérialise la publication en dictionnaire Python.

        Utilisé par les adaptateurs de persistence (PostgreSQL, MongoDB)
        et par le stockage brut (JSON/CSV dans data/raw/).

        Retourne
        --------
        dict
            Dictionnaire avec tous les champs sérialisables,
            compatible JSON (datetime converti en ISO 8601).
        """
        return {
            "id"            : self.id,
            "title"         : self.title,
            "content"       : self.content,
            "image_url"     : self.image_url,
            "source_domain" : self.source_domain,
            "declared_label": self.declared_label.value,
            "lang"          : self.lang,
            "captured_at"   : self.captured_at.isoformat(),
            "metadata"      : self.metadata,
        }

    # --------------------------------------------------------------------------
    def __repr__(self) -> str:
        """Représentation lisible pour les logs et le débogage."""
        return (
            f"Publication("
            f"id={self.id[:8]}..., "
            f"source={self.source_domain}, "
            f"label={self.declared_label.value}, "
            f"lang={self.lang})"
        )


# ==============================================================================
# ENTITÉ : Source
# ==============================================================================
@dataclass
class Source:
    """
    Configuration d'une source de données du pipeline CheckIt.AI.

    Représente une source d'extraction qualifiée — fact-checker,
    API ou flux RSS — avec ses caractéristiques techniques et
    ses droits d'usage vérifiés.

    Correspond à l'entité SOURCE du modèle conceptuel (L4).
    Les sélecteurs CSS spécifiques restent dans les adaptateurs
    (infrastructure) — seule la configuration métier vit ici.

    Exemple d'utilisation
    ---------------------
    source = Source(
        nom_domaine        = "fullfact.org",
        type_source        = "html",
        langue             = "en",
        url_base           = "https://fullfact.org/latest/",
        méthode_extraction = "bs4",
        droits_usage       = "scraping académique autorisé",
    )
    """

    # --- Champs obligatoires -------------------------------------------------
    nom_domaine        : str   # domaine identifiant la source
    type_source        : str   # "rss" | "api" | "html" | "scrapy" | "selenium"
    langue             : str   # code ISO 639-1 principal de la source
    url_base           : str   # URL d'entrée de l'extraction
    méthode_extraction : str   # adaptateur utilisé
    droits_usage       : str   # statut légal vérifié

    # --- Champs optionnels ---------------------------------------------------
    quota_journalier   : Optional[int] = None   # limite API/jour (None = illimité)
    nécessite_clé_api  : bool          = False  # True si clé API requise

    # --------------------------------------------------------------------------
    def vers_dict(self) -> dict:
        """Sérialise la source en dictionnaire compatible JSON."""
        return {
            "nom_domaine"       : self.nom_domaine,
            "type_source"       : self.type_source,
            "langue"            : self.langue,
            "url_base"          : self.url_base,
            "méthode_extraction": self.méthode_extraction,
            "droits_usage"      : self.droits_usage,
            "quota_journalier"  : self.quota_journalier,
            "nécessite_clé_api" : self.nécessite_clé_api,
        }

    # --------------------------------------------------------------------------
    def __repr__(self) -> str:
        """Représentation lisible pour les logs."""
        return (
            f"Source("
            f"domaine={self.nom_domaine}, "
            f"type={self.type_source}, "
            f"langue={self.langue})"
        )


# ==============================================================================
# ENTITÉ : ExtractionRun
# ==============================================================================
@dataclass
class ExtractionRun:
    """
    Statistiques d'une exécution complète du pipeline ETL.

    Enregistre les métriques de chaque run du DAG Airflow —
    utilisées par le dashboard Streamlit (L6) et le plan de
    monitoring (L7) pour calculer les KPIs en temps réel.

    Correspond à l'entité EXTRACTION_RUN du modèle conceptuel (L4).
    Un run couvre plusieurs sources simultanément — le DAG Airflow
    appelle tous les adaptateurs dans un même extract_task.

    Attributs calculés automatiquement
    -----------------------------------
    taux_intégrité : pourcentage d'entrées valides sur le total extrait.
    durée_secondes : durée totale du run en secondes.

    Exemple d'utilisation
    ---------------------
    run = ExtractionRun(
        run_id          = "checkit_pipeline__2026-07-01T08:00:00",
        started_at      = datetime(2026, 7, 1, 8, 0, 0),
        finished_at     = datetime(2026, 7, 1, 8, 12, 34),
        nb_extraites    = 150,
        nb_valides      = 132,
        nb_rejetées     = 18,
        sources_domains = ["afp.com", "fullfact.org", "politifact.com"],
    )
    """

    # --- Champs obligatoires -------------------------------------------------
    run_id          : str        # identifiant du DAG run Airflow
    started_at      : datetime   # horodatage de début
    finished_at     : datetime   # horodatage de fin
    nb_extraites    : int        # total d'entrées extraites
    nb_valides      : int        # entrées passant la validation
    nb_rejetées     : int        # entrées rejetées (texte ou image manquant)
    sources_domains : List[str]  = field(default_factory=list)
                                   # domaines extraits dans ce run

    # --- Champs calculés automatiquement -------------------------------------
    taux_intégrité : float = field(init=False)  # % entrées valides
    durée_secondes : float = field(init=False)  # durée totale en secondes

    # --------------------------------------------------------------------------
    def __post_init__(self) -> None:
        """Calcule les métriques dérivées après initialisation."""
        # -- Taux d'intégrité -------------------------------------------------
        total = self.nb_extraites or 1  # évite la division par zéro
        self.taux_intégrité = round(self.nb_valides / total * 100, 2)

        # -- Durée totale en secondes -----------------------------------------
        self.durée_secondes = (
            self.finished_at - self.started_at
        ).total_seconds()

    # --------------------------------------------------------------------------
    @property
    def est_sain(self) -> bool:
        """
        Indique si le run respecte le seuil d'intégrité minimum.

        Le seuil de 85% est défini dans les specs techniques (section 7.1).
        En dessous, une alerte CRITIQUE est déclenchée dans le dashboard.

        Retourne
        --------
        bool
            True si taux_intégrité >= 85%.
        """
        return self.taux_intégrité >= 85.0

    # --------------------------------------------------------------------------
    def vers_dict(self) -> dict:
        """Sérialise le run en dictionnaire compatible JSON."""
        return {
            "run_id"          : self.run_id,
            "started_at"      : self.started_at.isoformat(),
            "finished_at"     : self.finished_at.isoformat(),
            "nb_extraites"    : self.nb_extraites,
            "nb_valides"      : self.nb_valides,
            "nb_rejetées"     : self.nb_rejetées,
            "sources_domains" : self.sources_domains,
            "taux_intégrité"  : self.taux_intégrité,
            "durée_secondes"  : self.durée_secondes,
            "est_sain"        : self.est_sain,
        }

    # --------------------------------------------------------------------------
    def __repr__(self) -> str:
        """Représentation lisible pour les logs."""
        return (
            f"ExtractionRun("
            f"run_id={self.run_id[:20]}..., "
            f"intégrité={self.taux_intégrité}%, "
            f"sain={self.est_sain})"
        )
