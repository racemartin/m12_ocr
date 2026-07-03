# ==============================================================================
# src/application/transform_service.py — Pipeline de transformation (Étape 3)
#
# Livrable L3 : pipeline Python modulaire, reproductible et journalisé qui
# transforme les données brutes extraites (data/raw/*.json) en un format
# exploitable pour l'entraînement IA (data/processed/).
#
# Séquence du pipeline (recommandation OpenClassrooms) :
#   1. LECTURE    : chargement des fichiers JSON bruts
#   2. TRAITEMENT : nettoyage, normalisation, validation, dédoublonnage,
#                   génération de colonnes dérivées
#   3. EXPORT     : publications propres (JSON + CSV) + statistiques du run
#
# Fonctions modulaires exigées par la mission :
#   - nettoie_texte()     : balises HTML, espaces, caractères de contrôle
#   - valide_image()      : accessibilité HTTP + Content-Type + taille min
#   - normalise_label()   : variantes multilingues → REAL / FAKE
#   - génère_id()         : hash SHA-256 déterministe (dédoublonnage)
#
# Reproductibilité :
#   - Aucun état caché : mêmes fichiers d'entrée → mêmes sorties
#   - Paramètres explicites (dossiers, vérification HTTP on/off)
#   - Chaque transformation est journalisée via LogTool (RFC 5424)
#
# Place dans l'architecture hexagonale :
#   - Couche APPLICATION : orchestre les règles métier du domaine
#   - Lève les exceptions métier de src/domain/exceptions.py
#   - Les entrées/sorties fichiers passeront par StoragePort lors du
#     branchement final (ici : pathlib direct, documenté et remplaçable)
#
# Exécution directe (L3 exécutable) :
#   python3 -m src.application.transform_service
# ==============================================================================

# --- Bibliothèque standard : fichiers, hash, texte, horodatage ----------------
import csv                                 # Export tabulaire des publications
import hashlib                             # Hash SHA-256 → identifiant unique
import json                                # Lecture/écriture des fichiers JSON
import re                                  # Nettoyage des balises HTML
import sys                                 # Bootstrap du chemin projet (main)
import unicodedata                         # Normalisation Unicode (NFC)

from   datetime import datetime, timezone  # Horodatage UTC des publications
from   pathlib  import Path                # Manipulation portable des chemins
from   typing   import List, Tuple         # Annotations de types

# --- Dépendances externes : validation HTTP des images ------------------------
import requests                            # Vérification des URLs d'images

# --- Domaine : exceptions métier (zéro dépendance externe) --------------------
from   src.domain.exceptions import (
    CheckItErreur,                         # Base de toutes les erreurs métier
    ContenuVideErreur,                     # Corps texte absent → rejet
    ImageInaccessibleErreur,               # URL image invalide → rejet
    ImageUrlVideErreur,                    # URL image absente → rejet
    LabelInvalideErreur,                   # Label non normalisable → rejet
    TitreVideErreur,                       # Titre absent → rejet
)

# --- Outil de journalisation colorée en console (RFC 5424) --------------------
from   src.tools.rafael.log_tool import LogTool


# ==============================================================================
# CONFIGURATION — chemins, réseau et seuils de validation
# ==============================================================================
DOSSIER_BRUT      = Path("data/raw")       # Entrée : extractions brutes
DOSSIER_SORTIE    = Path("data/processed") # Sortie : dataset exploitable
TIMEOUT_IMAGE     = 10                     # s — validation HTTP d'une image
TAILLE_MIN_OCTETS = 1_000                  # octets — écarte pixels de tracking
TYPES_IMAGE_OK    = (                      # Content-Types image acceptés
    "image/jpeg", "image/png", "image/webp", "image/gif",
)

# User-Agent d'un navigateur réel : certains CDN refusent les clients Python.
AGENT_NAVIGATEUR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ==============================================================================
# MAPPAGE DES LABELS — variantes multilingues vers le binaire REAL / FAKE
# ==============================================================================
# La normalisation accepte les variantes produites par tous les adaptateurs
# (fr, en, es, de) ainsi que la sérialisation de l'énumération du domaine
# ("LabelVéracité.REAL" → suffixe "real"). Tout label hors mappage lève
# LabelInvalideErreur et l'entrée est rejetée (jamais de valeur devinée).
MAPPAGE_LABELS = {
    # -- Variantes → REAL --------------------------------------------------------
    "real"      : "REAL",
    "true"      : "REAL",
    "vrai"      : "REAL",
    "vérifié"   : "REAL",
    "verdadero" : "REAL",
    "richtig"   : "REAL",
    # -- Variantes → FAKE --------------------------------------------------------
    "fake"      : "FAKE",
    "false"     : "FAKE",
    "faux"      : "FAKE",
    "falso"     : "FAKE",
    "falsch"    : "FAKE",
    "trompeur"  : "FAKE",
    "engañoso"  : "FAKE",
}


# ##############################################################################
# CLASSE : TransformService
# ##############################################################################
class TransformService:
    """
    Pipeline de transformation des publications brutes (Étape 3 / L3).

    Orchestration en trois étapes journalisées : lecture des fichiers
    bruts, traitement entrée par entrée (nettoyage, validation,
    normalisation, dédoublonnage, colonnes dérivées), export du dataset
    propre accompagné des statistiques du run.

    Paramètres
    ----------
    dossier_brut : Path
        Dossier contenant les fichiers JSON bruts (défaut : data/raw).
    dossier_sortie : Path
        Dossier de destination du dataset propre (défaut : data/processed).
    vérifier_images : bool
        Si True, chaque image_url est validée par requête HTTP (lent mais
        exigé par la mission). False pour les tests rapides hors ligne.

    Utilisation
    -----------
    service = TransformService()
    stats   = service.exécuter()
    """

    # ##########################################################################
    def __init__(
        self,
        dossier_brut    : Path = DOSSIER_BRUT,
        dossier_sortie  : Path = DOSSIER_SORTIE,
        vérifier_images : bool = True,
    ) -> None:
        self._dossier_brut    = Path(dossier_brut)    # Source des bruts
        self._dossier_sortie  = Path(dossier_sortie)  # Destination du propre
        self._vérifier_images = vérifier_images       # Validation HTTP on/off
        self._log             = LogTool(origin="transform")  # Logger RFC 5424
        self._ids_vus         : set = set()           # Dédoublonnage par hash

    # ##########################################################################
    def exécuter(self) -> dict:
        """
        Exécute le pipeline complet : lecture → traitement → export.

        Retourne
        --------
        dict
            Statistiques du run (compteurs, taux d'intégrité, chemins).
        """
        self._log.START_ACTION(
            "TransformService", "exécuter", "pipeline de transformation"
        )
        self._ids_vus = set()                    # Reproductibilité : RAZ

        # ----------------------------------------------------------------------
        # ÉTAPE 1 — LECTURE des fichiers bruts
        # ----------------------------------------------------------------------
        self._log.STEP(1, "ÉTAPE 1 — LECTURE", str(self._dossier_brut))
        entrées = self._lire_données_brutes()
        self._log.PARAMETER_VALUE("entrées brutes lues", len(entrées))

        # ----------------------------------------------------------------------
        # ÉTAPE 2 — TRAITEMENT entrée par entrée
        # ----------------------------------------------------------------------
        self._log.STEP(1, "ÉTAPE 2 — TRAITEMENT", "nettoyage + validation")
        valides, rejets = self._transformer(entrées)

        # ----------------------------------------------------------------------
        # ÉTAPE 3 — EXPORT du dataset propre + statistiques
        # ----------------------------------------------------------------------
        self._log.STEP(1, "ÉTAPE 3 — EXPORT", str(self._dossier_sortie))
        stats = self._exporter(valides, rejets, total_brut=len(entrées))

        self._log.FINISH_ACTION(
            "TransformService", "exécuter",
            f"{len(valides)} publications propres"
        )
        return stats

    # ##########################################################################
    # ÉTAPE 1 — LECTURE
    # ##########################################################################

    # ##########################################################################
    def _lire_données_brutes(self) -> List[dict]:
        """
        Charge toutes les entrées de tous les fichiers JSON du dossier brut.

        Chaque fichier contient une liste de publications sérialisées par
        les adaptateurs d'extraction (Étape 2). Les fichiers illisibles
        sont journalisés puis ignorés — le pipeline ne s'arrête jamais
        sur un fichier corrompu (robustesse exigée en production).
        """
        entrées : List[dict] = []

        fichiers = sorted(self._dossier_brut.glob("*.json"))
        self._log.PARAMETER_VALUE("fichiers bruts trouvés", len(fichiers))

        for fichier in fichiers:
            try:
                contenu = json.loads(fichier.read_text(encoding="utf-8"))
                # Un fichier peut contenir une liste ou un objet unique
                lot = contenu if isinstance(contenu, list) else [contenu]
                entrées.extend(lot)
                self._log.PARAMETER_VALUE(fichier.name, f"{len(lot)} entrées")
            except (OSError, json.JSONDecodeError) as erreur:
                self._log.LEVEL_4_ERROR(
                    "TransformService",
                    f"Fichier illisible {fichier.name} : {erreur}",
                )
        return entrées

    # ##########################################################################
    # ÉTAPE 2 — TRAITEMENT
    # ##########################################################################

    # ##########################################################################
    def _transformer(
        self, entrées: List[dict]
    ) -> Tuple[List[dict], List[dict]]:
        """
        Applique la chaîne de transformations à chaque entrée brute.

        Chaîne appliquée (dans l'ordre) :
          1. nettoie_texte() sur title et content
          2. Validation des champs obligatoires (titre, contenu, image)
          3. normalise_label() → REAL / FAKE
          4. valide_image() — requête HTTP si vérifier_images est actif
          5. génère_id() + dédoublonnage
          6. Génération des colonnes dérivées (captured_at, nb_mots_contenu)

        Retourne
        --------
        (valides, rejets) : Tuple[List[dict], List[dict]]
            Publications propres et entrées rejetées (avec le motif).
        """
        valides : List[dict] = []
        rejets  : List[dict] = []

        for position, brut in enumerate(entrées):
            try:
                propre = self._transformer_une_entrée(brut)

                # -- Dédoublonnage par identifiant déterministe ----------------
                if propre["id"] in self._ids_vus:
                    raise CheckItErreur(
                        f"Doublon détecté : {propre['title'][:40]}"
                    )
                self._ids_vus.add(propre["id"])

                valides.append(propre)
                self._log.LEVEL_7_INFO(
                    "TransformService",
                    f"[{propre['declared_label']}] {propre['title'][:55]}",
                )

            except CheckItErreur as erreur:
                # Rejet métier : motif précis conservé pour le dashboard KPI
                rejets.append({
                    "position" : position,
                    "motif"    : str(erreur),
                    "titre"    : str(brut.get("title", ""))[:80],
                })
                self._log.LEVEL_5_WARNING("TransformService", str(erreur))

            except Exception as erreur:
                # Rejet technique : jamais de crash sur une entrée isolée
                rejets.append({
                    "position" : position,
                    "motif"    : f"Erreur inattendue : {erreur}",
                    "titre"    : str(brut.get("title", ""))[:80],
                })
                self._log.LEVEL_4_ERROR(
                    "TransformService", f"Erreur inattendue : {erreur}"
                )

        return valides, rejets

    # ##########################################################################
    def _transformer_une_entrée(self, brut: dict) -> dict:
        """
        Transforme UNE entrée brute en publication propre (schéma final).

        Lève une exception métier (CheckItErreur) au premier critère
        non satisfait — l'entrée sera rejetée et comptabilisée.
        """
        source = str(brut.get("source_domain", "")).strip()

        # -- 1. Nettoyage des champs textuels -----------------------------------
        titre   = self.nettoie_texte(str(brut.get("title",   "")))
        contenu = self.nettoie_texte(str(brut.get("content", "")))

        # -- 2. Validation des champs obligatoires ------------------------------
        if not titre:
            raise TitreVideErreur(source)
        if not contenu:
            raise ContenuVideErreur(source)

        image_url = str(brut.get("image_url", "")).strip()
        if not image_url:
            raise ImageUrlVideErreur(source)

        # -- 3. Normalisation du label vers le binaire REAL / FAKE --------------
        label = self.normalise_label(
            str(brut.get("declared_label", "")), source
        )

        # -- 4. Validation HTTP de l'image (association texte-image) ------------
        if self._vérifier_images:
            self.valide_image(image_url, source)

        # -- 5. Identifiant déterministe (hash du contenu) ----------------------
        identifiant = self.génère_id(titre, source)

        # -- 6. Mapping vers le schéma final + colonnes dérivées ----------------
        return {
            "id"              : identifiant,
            "title"           : titre,
            "content"         : contenu,
            "image_url"       : image_url,
            "source_domain"   : source,
            "declared_label"  : label,
            "lang"            : str(brut.get("lang", "fr"))[:2],
            "captured_at"     : brut.get(
                "captured_at",
                datetime.now(timezone.utc).isoformat(),
            ),
            "nb_mots_contenu" : len(contenu.split()),  # Colonne générée (NLP)
            "metadata"        : brut.get("metadata", {}),
        }

    # ##########################################################################
    # FONCTIONS MODULAIRES DE TRANSFORMATION (exigées par la mission)
    # ##########################################################################

    # ##########################################################################
    @staticmethod
    def nettoie_texte(texte: str) -> str:
        """
        Nettoie un champ textuel brut.

        Opérations appliquées :
          - Suppression des balises HTML résiduelles
          - Normalisation Unicode NFC (accents composés → précomposés)
          - Suppression des caractères de contrôle
          - Réduction des espaces multiples à un seul espace
        """
        texte = re.sub(r"<[^>]+>", " ", texte)         # Balises HTML
        texte = unicodedata.normalize("NFC", texte)    # Unicode canonique
        texte = "".join(                               # Caractères de contrôle
            c for c in texte if unicodedata.category(c)[0] != "C"
        )
        texte = re.sub(r"\s+", " ", texte)             # Espaces multiples
        return texte.strip()

    # ##########################################################################
    def valide_image(self, url: str, source: str = "") -> bool:
        """
        Valide une URL d'image par requête HTTP réelle.

        Critères (cf. spécifications techniques CheckIt.AI) :
          - Code HTTP 200
          - Content-Type dans TYPES_IMAGE_OK
          - Taille annoncée > TAILLE_MIN_OCTETS (écarte les pixels
            de tracking)

        Lève ImageInaccessibleErreur si un critère échoue.
        """
        try:
            réponse = requests.get(
                url,
                timeout = TIMEOUT_IMAGE,
                headers = {"User-Agent": AGENT_NAVIGATEUR},
                stream  = True,                # En-têtes seuls : pas le corps
            )
        except requests.RequestException as erreur:
            raise ImageInaccessibleErreur(url, str(erreur), source)

        if réponse.status_code != 200:
            raise ImageInaccessibleErreur(
                url, f"HTTP {réponse.status_code}", source
            )

        type_contenu = réponse.headers.get("Content-Type", "").split(";")[0]
        if type_contenu not in TYPES_IMAGE_OK:
            raise ImageInaccessibleErreur(
                url, f"Content-Type non image : {type_contenu}", source
            )

        taille = int(réponse.headers.get("Content-Length", "0") or "0")
        if 0 < taille < TAILLE_MIN_OCTETS:
            raise ImageInaccessibleErreur(
                url, f"Taille suspecte : {taille} octets", source
            )
        return True

    # ##########################################################################
    @staticmethod
    def normalise_label(brut: str, source: str = "") -> str:
        """
        Normalise un label brut vers le binaire REAL / FAKE.

        Accepte les variantes multilingues (MAPPAGE_LABELS) ainsi que la
        sérialisation de l'énumération du domaine ("LabelVéracité.REAL").
        Lève LabelInvalideErreur pour tout label non reconnu — aucune
        valeur n'est jamais devinée.
        """
        # Suffixe après le dernier point : "LabelVéracité.REAL" → "real"
        clé = brut.strip().lower().split(".")[-1]

        if clé in MAPPAGE_LABELS:
            return MAPPAGE_LABELS[clé]
        raise LabelInvalideErreur(brut, source)

    # ##########################################################################
    @staticmethod
    def génère_id(titre: str, source: str) -> str:
        """
        Génère l'identifiant déterministe d'une publication.

        Hash SHA-256 de "titre|source" : deux extractions du même article
        produisent le même id → dédoublonnage naturel entre les runs.
        """
        empreinte = f"{titre}|{source}".encode("utf-8")
        return hashlib.sha256(empreinte).hexdigest()

    # ##########################################################################
    # ÉTAPE 3 — EXPORT
    # ##########################################################################

    # ##########################################################################
    def _exporter(
        self,
        valides    : List[dict],
        rejets     : List[dict],
        total_brut : int,
    ) -> dict:
        """
        Exporte le dataset propre (JSON + CSV) et les statistiques du run.

        Trois fichiers produits dans le dossier de sortie :
          - publications_propres.json : dataset complet (metadata incluses)
          - publications_propres.csv  : vue tabulaire (sans metadata)
          - stats_transformation.json : compteurs et taux d'intégrité
        """
        self._dossier_sortie.mkdir(parents=True, exist_ok=True)

        # -- Export JSON (dataset complet) ---------------------------------------
        chemin_json = self._dossier_sortie / "publications_propres.json"
        chemin_json.write_text(
            json.dumps(valides, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # -- Export CSV (vue tabulaire, metadata exclues) -------------------------
        chemin_csv = self._dossier_sortie / "publications_propres.csv"
        colonnes   = [
            "id", "title", "content", "image_url", "source_domain",
            "declared_label", "lang", "captured_at", "nb_mots_contenu",
        ]
        with chemin_csv.open("w", encoding="utf-8", newline="") as flux:
            plume = csv.DictWriter(
                flux, fieldnames=colonnes, extrasaction="ignore"
            )
            plume.writeheader()
            plume.writerows(valides)

        # -- Statistiques du run (source du dashboard KPI L6) ---------------------
        répartition = {"REAL": 0, "FAKE": 0}
        for pub in valides:
            répartition[pub["declared_label"]] += 1

        taux  = round(len(valides) / total_brut * 100, 1) if total_brut else 0
        stats = {
            "exécuté_le"     : datetime.now(timezone.utc).isoformat(),
            "entrées_brutes" : total_brut,
            "valides"        : len(valides),
            "rejetées"       : len(rejets),
            "taux_intégrité" : taux,
            "répartition"    : répartition,
            "rejets"         : rejets,
            "sorties"        : {
                "json" : str(chemin_json),
                "csv"  : str(chemin_csv),
            },
        }
        chemin_stats = self._dossier_sortie / "stats_transformation.json"
        chemin_stats.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # -- Rapport console -------------------------------------------------------
        print("\n==========================================================")
        print("RAPPORT DE TRANSFORMATION — ÉTAPE 3")
        print("==========================================================")
        print(f"  Entrées brutes......: {total_brut}")
        print(f"  Publications valides: {len(valides)}")
        print(f"  Entrées rejetées....: {len(rejets)}")
        print(f"  Taux d'intégrité....: {taux}%")
        print(f"  REAL / FAKE.........: "
              f"{répartition['REAL']} / {répartition['FAKE']}")
        print(f"  Export JSON.........: {chemin_json}")
        print(f"  Export CSV..........: {chemin_csv}")
        print("==========================================================")

        return stats


# ==============================================================================
# POINT D'ENTRÉE : exécution directe du pipeline (livrable L3 exécutable)
# ==============================================================================
if __name__ == "__main__":
    # Bootstrap : ajoute la racine du projet au chemin des imports pour
    # permettre "python3 src/application/transform_service.py" direct.
    RACINE = Path(__file__).resolve().parents[2]
    if str(RACINE) not in sys.path:
        sys.path.insert(0, str(RACINE))

    service = TransformService(
        vérifier_images=False,               # True en production (plus lent)
    )
    service.exécuter()
