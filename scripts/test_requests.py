# ==============================================================================
# scripts/test_requests.py — Test individuel de l'adaptateur API REST
#
# Ce script teste RequestsAdapter de façon autonome.
# Il valide l'extraction depuis NewsData.io et le scoring ClaimBuster.
#
# Prérequis :
#   Créer un fichier .env à la racine du projet (hors Git) avec :
#     NEWSDATA_API_KEY=votre_clé_ici
#     CLAIMBUSTER_API_KEY=votre_clé_ici  (optionnel)
#   Voir scripts/.env.example pour le modèle
#
# Lancement :
#   python3 scripts/test_requests.py
# ==============================================================================

# --- Bibliothèque standard ---------------------------------------------------
import json
import os
import sys
from datetime import datetime
from pathlib  import Path

# --- Dépendance externe -------------------------------------------------------
from dotenv import load_dotenv  # chargement du fichier .env

# --- Path projet -------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# --- Chargement des variables d'environnement --------------------------------
# Lit le fichier .env à la racine du projet — jamais commité (.gitignore)
load_dotenv()

# --- Imports projet ----------------------------------------------------------
from src.adapters.outbound.scrapers.requests_adapter import RequestsAdapter
from src.tools.rafael.log_tool                       import LogTool

# --- Configuration -----------------------------------------------------------
# URL NewsData.io avec paramètres de recherche
# Documentation : https://newsdata.io/documentation
REQUÊTES_NEWSDATA = [
    # Articles politiques français — mix fiable/non fiable
    "https://newsdata.io/api/1/news"
    "?apikey={clé}&country=fr&language=fr&category=politics&size=10",

    # Thèmes santé — riche en désinformation potentielle
    "https://newsdata.io/api/1/news"
    "?apikey={clé}&language=fr&q=vaccin+santé&size=10",
]

DOSSIER_SORTIE = Path(__file__).resolve().parent.parent / "data" / "raw"
DOSSIER_SORTIE.mkdir(parents=True, exist_ok=True)

log = LogTool(origin="test_api")


# ##############################################################################
def main() -> None:
    """Test complet de l'adaptateur API REST NewsData.io + ClaimBuster."""
    log.START_ACTION("test_requests", "main", "début des tests API REST")

    # -- Vérification clé API -------------------------------------------------
    clé = os.environ.get("NEWSDATA_API_KEY", "")
    if not clé:
        log.LEVEL_3_CRITICAL(
            "test_requests",
            "NEWSDATA_API_KEY manquante — "
            "définir avec : export NEWSDATA_API_KEY=votre_clé",
        )
        log.STEP(1, "Mode démonstration sans clé API")
        _démonstration_sans_clé()
        return

    log.PARAMETER_VALUE("clé API NewsData", clé[:8] + "..." + clé[-4:])

    adaptateur     = RequestsAdapter()
    tous_résultats = []

    # --------------------------------------------------------------------------
    # Test disponibilité
    # --------------------------------------------------------------------------
    url_test = f"https://newsdata.io/api/1/news?apikey={clé}&size=1"
    log.PARAMETER_VALUE("disponibilité...", "test en cours")

    if not adaptateur.est_disponible(url_test):
        log.LEVEL_4_ERROR(
            "test_requests", "API NewsData.io inaccessible"
        )
        return

    log.PARAMETER_VALUE("disponibilité...", "✅ API en ligne")

    # --------------------------------------------------------------------------
    # Extraction articles politiques FR
    # --------------------------------------------------------------------------
    log.STEP(1, "Extraction articles politiques français")
    url_politique = (
        f"https://newsdata.io/api/1/news"
        f"?apikey={clé}&country=fr&language=fr&category=politics&size=10"
    )
    publications_politique = adaptateur.extraire_données(url_politique)
    log.PARAMETER_VALUE(
        "articles politiques", len(publications_politique)
    )
    tous_résultats.extend(
        [pub.vers_dict() for pub in publications_politique]
    )

    # --------------------------------------------------------------------------
    # Extraction articles santé (riche en désinformation)
    # --------------------------------------------------------------------------
    log.STEP(1, "Extraction articles santé")
    url_santé = (
        f"https://newsdata.io/api/1/news"
        f"?apikey={clé}&language=fr&q=vaccin+santé&size=10"
    )
    publications_santé = adaptateur.extraire_données(url_santé)
    log.PARAMETER_VALUE(
        "articles santé.......", len(publications_santé)
    )
    tous_résultats.extend(
        [pub.vers_dict() for pub in publications_santé]
    )

    # --------------------------------------------------------------------------
    # Test ClaimBuster sur un exemple
    # --------------------------------------------------------------------------
    log.STEP(1, "Test ClaimBuster (scoring affirmations)")
    texte_test = (
        "Le gouvernement affirme que 95% des hospitalisations "
        "concernent des personnes non vaccinées."
    )
    score = adaptateur.scorer_affirmation(texte_test)
    log.PARAMETER_VALUE("texte test........", texte_test[:60])
    log.PARAMETER_VALUE("score ClaimBuster.", f"{score:.3f}")
    log.PARAMETER_VALUE(
        "interprétation....",
        "vérifiable" if score > 0.5 else "opinion/non vérifiable",
    )

    # --------------------------------------------------------------------------
    # Affichage d'exemples extraits
    # --------------------------------------------------------------------------
    if tous_résultats:
        log.STEP(1, "Exemples extraits")
        for i, pub_dict in enumerate(tous_résultats[:3]):
            log.PARAMETER_VALUE(
                f"[{i+1}] titre.....",
                pub_dict["title"][:60],
            )
            log.PARAMETER_VALUE(
                f"[{i+1}] label.....",
                pub_dict["declared_label"],
            )
            log.PARAMETER_VALUE(
                f"[{i+1}] source....",
                pub_dict["source_domain"],
            )

    # --------------------------------------------------------------------------
    # Sauvegarde JSON
    # --------------------------------------------------------------------------
    horodatage     = datetime.now().strftime("%Y-%m-%d_%H-%M")
    fichier_sortie = DOSSIER_SORTIE / f"test_api_{horodatage}.json"

    with open(fichier_sortie, "w", encoding="utf-8") as f:
        json.dump(tous_résultats, f, ensure_ascii=False, indent=2)

    log.PARAMETER_VALUE("fichier sauvegardé", str(fichier_sortie))
    log.PARAMETER_VALUE("total publications", len(tous_résultats))
    log.FINISH_ACTION(
        "test_requests", "main",
        f"{len(tous_résultats)} publications extraites"
    )


# ==============================================================================
def _démonstration_sans_clé() -> None:
    """
    Démonstration du fonctionnement sans clé API réelle.
    Affiche la structure attendue des publications extraites.
    """
    log.STEP(1, "Structure d'une Publication NewsData.io")
    structure = {
        "id"            : "sha256_64_chars...",
        "title"         : "Le gouvernement annonce une nouvelle mesure",
        "content"       : "Corps de l'article...",
        "image_url"     : "https://newsdata.io/images/article.jpg",
        "source_domain" : "lefigaro",
        "declared_label": "REAL",
        "lang"          : "fr",
        "captured_at"   : datetime.now().isoformat(),
        "metadata"      : {
            "url_source" : "https://lefigaro.fr/...",
            "auteur"     : ["Jean Dupont"],
            "date_publi" : "2026-06-30T08:00:00Z",
            "catégories" : ["politics"],
            "pays"       : ["fr"],
            "score_mbfc" : "évalué",
        },
    }
    log.LOG_DICT(structure, "Publication")
    log.STEP(1, "Clé API nécessaire pour une extraction réelle")
    log.PARAMETER_VALUE(
        "inscription gratuite", "https://newsdata.io/register"
    )
    log.PARAMETER_VALUE(
        "quota gratuit.......", "200 requêtes/jour"
    )


# ==============================================================================
if __name__ == "__main__":
    main()
