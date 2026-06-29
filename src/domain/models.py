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
# ==============================================================================

# --- Bibliothèque standard uniquement ---------------------------------------
import hashlib    # calcul de l'identifiant SHA-256 unique
from dataclasses import dataclass, field  # déclaration d'entités sans boilerplate
from datetime    import datetime          # horodatage de capture
from enum        import Enum             # énumération typée des labels
from typing      import Optional         # champs optionnels typés


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
