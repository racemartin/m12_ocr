# ==============================================================================
# src/domain/exceptions.py — Exceptions métier du domaine CheckIt.AI
#
# Règle absolue : ZÉRO import externe dans ce fichier.
# Ces exceptions représentent des erreurs métier pures —
# indépendantes de toute technologie (HTTP, SQL, réseau...).
#
# Hiérarchie des exceptions :
#
#   CheckItErreur                   ← base de toutes les erreurs métier
#   │
#   ├── PublicationInvalideErreur   ← données de publication incorrectes
#   │   ├── TitreVideErreur
#   │   ├── ContenuVideErreur
#   │   ├── ImageUrlVideErreur
#   │   └── SourceDomainVideErreur
#   │
#   ├── LabelInvalideErreur         ← label non normalisable
#   │
#   └── ImageInaccessibleErreur     ← URL image non valide ou inaccessible
# ==============================================================================


# ==============================================================================
# EXCEPTION DE BASE
# ==============================================================================
class CheckItErreur(Exception):
    """
    Exception de base pour toutes les erreurs métier CheckIt.AI.

    Toutes les exceptions du domaine héritent de cette classe.
    Permet d'attraper toutes les erreurs métier en un seul bloc :

        try:
            ...
        except CheckItErreur as e:
            log.LEVEL_4_ERROR("Pipeline", str(e))
    """


# ==============================================================================
# EXCEPTIONS DE PUBLICATION
# ==============================================================================
class PublicationInvalideErreur(CheckItErreur):
    """
    Levée quand une publication ne satisfait pas les contraintes
    minimales pour être intégrée dans le dataset d'entraînement.

    Une publication invalide est rejetée par validate_raw_task
    et comptabilisée dans le KPI taux_de_rejet du dashboard.
    """


# ------------------------------------------------------------------------------
class TitreVideErreur(PublicationInvalideErreur):
    """
    Levée quand le titre d'une publication est absent ou vide.

    Le titre est obligatoire — il constitue la première modalité
    textuelle utilisée par le modèle de détection.

    Exemple
    -------
    raise TitreVideErreur("Reddit post sans titre détecté")
    """

    def __init__(self, source_domain: str = "") -> None:
        super().__init__(
            f"Titre vide ou absent "
            f"{'pour la source : ' + source_domain if source_domain else ''}"
        )


# ------------------------------------------------------------------------------
class ContenuVideErreur(PublicationInvalideErreur):
    """
    Levée quand le corps texte d'une publication est absent ou vide.

    Le contenu textuel est la modalité principale d'analyse —
    une publication sans contenu ne peut pas être labellisée.

    Exemple
    -------
    raise ContenuVideErreur("newsdata.io")
    """

    def __init__(self, source_domain: str = "") -> None:
        super().__init__(
            f"Contenu texte vide ou absent "
            f"{'pour la source : ' + source_domain if source_domain else ''}"
        )


# ------------------------------------------------------------------------------
class ImageUrlVideErreur(PublicationInvalideErreur):
    """
    Levée quand l'URL image d'une publication est absente ou vide.

    L'association texte–image est une contrainte fondamentale
    du dataset multimodal CheckIt.AI — toute entrée sans image
    est rejetée par le pipeline de transformation.

    Exemple
    -------
    raise ImageUrlVideErreur("snopes.com")
    """

    def __init__(self, source_domain: str = "") -> None:
        super().__init__(
            f"URL image vide ou absente "
            f"{'pour la source : ' + source_domain if source_domain else ''}"
        )


# ------------------------------------------------------------------------------
class SourceDomainVideErreur(PublicationInvalideErreur):
    """
    Levée quand le domaine source d'une publication est absent.

    Le source_domain est requis pour la traçabilité des données
    et le calcul des statistiques par source dans le dashboard.

    Exemple
    -------
    raise SourceDomainVideErreur()
    """

    def __init__(self) -> None:
        super().__init__("Domaine source vide ou absent")


# ==============================================================================
# EXCEPTION DE LABEL
# ==============================================================================
class LabelInvalideErreur(CheckItErreur):
    """
    Levée quand un label brut ne peut pas être normalisé
    vers REAL ou FAKE par normalize_label().

    Les variantes reconnues sont définies dans le pipeline
    de transformation — tout label inconnu lève cette exception.

    Exemple
    -------
    raise LabelInvalideErreur("uncertain", "politifact.com")
    """

    def __init__(self, label_brut: str, source_domain: str = "") -> None:
        self.label_brut    = label_brut     # valeur brute non reconnue
        self.source_domain = source_domain  # source d'origine pour le log
        super().__init__(
            f"Label non normalisable : '{label_brut}' "
            f"{'(source : ' + source_domain + ')' if source_domain else ''}"
        )


# ==============================================================================
# EXCEPTION D'IMAGE
# ==============================================================================
class ImageInaccessibleErreur(CheckItErreur):
    """
    Levée quand une URL image ne répond pas aux critères de validité
    définis par validate_image() dans le pipeline de transformation :
      - code HTTP non 200
      - Content-Type non image (image/jpeg, image/png, image/webp)
      - taille inférieure au minimum (pixel de tracking)
      - timeout dépassé

    Exemple
    -------
    raise ImageInaccessibleErreur(
        url        = "https://example.com/img.jpg",
        raison     = "HTTP 404",
        source_dom = "reddit.com",
    )
    """

    def __init__(
        self,
        url        : str,
        raison     : str = "",
        source_dom : str = "",
    ) -> None:
        self.url        = url         # URL qui a échoué la validation
        self.raison     = raison      # motif d'échec (HTTP code, timeout...)
        self.source_dom = source_dom  # source d'origine pour le log
        super().__init__(
            f"Image inaccessible : {url} "
            f"{'— ' + raison if raison else ''} "
            f"{'(source : ' + source_dom + ')' if source_dom else ''}"
        )
