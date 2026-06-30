# ==============================================================================
# scripts/test_feedparser.py — Test individuel de l'adaptateur RSS
#
# Ce script teste FeedparserAdapter de façon autonome —
# sans Airflow, sans base de données, sans autres dépendances.
# Il valide que l'extraction RSS fonctionne sur les 4 sources.
#
# Lancement :
#   cd /mnt/c/Users/Public/IAE_DELL/pra_dell/m12_ocr
#   source .venv/bin/activate
#   python3 scripts/test_feedparser.py
#
# Résultat attendu :
#   - Affichage coloré LogTool pour chaque source
#   - Fichier JSON de sortie dans data/raw/test_rss_YYYY-MM-DD.json
#   - Taux d'intégrité affiché pour chaque source
# ==============================================================================

# --- Bibliothèque standard ---------------------------------------------------
import json      # sauvegarde résultats en JSON
import sys       # manipulation du path Python
from datetime import datetime  # horodatage du fichier de sortie
from pathlib  import Path      # chemins portables

# --- Path projet -------------------------------------------------------------
# Ajout de la racine du projet au path pour les imports src.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# --- Imports projet ----------------------------------------------------------
from src.adapters.outbound.scrapers.feedparser_adapter import (
    FeedparserAdapter,
)
from src.tools.rafael.log_tool import LogTool

# --- Configuration des sources à tester -------------------------------------
SOURCES_RSS = {
    "afp"         : "https://factuel.afp.com/feed",
    "euvsdisinfo" : "https://euvsdisinfo.eu/feed/",
    "hoaxbuster"  : "https://www.hoaxbuster.com/rss/", 
}

# --- Chemin de sortie --------------------------------------------------------
DOSSIER_SORTIE = Path(__file__).resolve().parent.parent / "data" / "raw"
DOSSIER_SORTIE.mkdir(parents=True, exist_ok=True)

# --- Logger principal -------------------------------------------------------
log = LogTool(origin="test_rss")


# ##############################################################################
# POINT D'ENTRÉE PRINCIPAL
# ##############################################################################
def main() -> None:
    """
    Lance les tests d'extraction RSS sur toutes les sources configurées.

    Pour chaque source :
    1. Vérifie la disponibilité
    2. Extrait les publications
    3. Affiche les statistiques
    4. Sauvegarde en JSON
    """
    log.START_ACTION("test_feedparser", "main", "début des tests RSS")

    tous_résultats = []   # agrégation de toutes les sources
    statistiques   = {}   # stats par source pour le rapport final

    # --------------------------------------------------------------------------
    # Test de chaque source RSS
    # --------------------------------------------------------------------------
    for nom_source, url in SOURCES_RSS.items():

        log.STEP(1, f"Test source : {nom_source}", url)

        adaptateur = FeedparserAdapter(source=nom_source)

        # -- Vérification disponibilité ---------------------------------------
        log.PARAMETER_VALUE("disponibilité...", "test en cours")
        if not adaptateur.est_disponible(url):
            log.LEVEL_5_WARNING(
                "test_feedparser",
                f"Source {nom_source} hors ligne — ignorée",
            )
            statistiques[nom_source] = {
                "statut"              : "HORS LIGNE",
                "publications_valides": 0,
                "taux_intégrité"      : 0,
            }
            continue

        log.PARAMETER_VALUE("disponibilité...", "✅ en ligne")

        # -- Extraction -------------------------------------------------------
        publications = adaptateur.extraire_données(url)

        # -- Statistiques -----------------------------------------------------
        nb_valides = len(publications)
        statistiques[nom_source] = {
            "statut"              : "OK",
            "publications_valides": nb_valides,
            "taux_intégrité"      : nb_valides,
        }

        log.PARAMETER_VALUE(
            f"{nom_source} — valides", nb_valides
        )

        # -- Affichage d'un exemple ------------------------------------------
        if publications:
            exemple = publications[0]
            log.STEP(2, "Exemple extrait")
            log.PARAMETER_VALUE("id............", exemple.id[:16] + "...")
            log.PARAMETER_VALUE("titre.........", exemple.title[:60])
            log.PARAMETER_VALUE("label.........", exemple.declared_label.value)
            log.PARAMETER_VALUE("langue........", exemple.lang)
            log.PARAMETER_VALUE("image_url.....", exemple.image_url[:60])
            log.PARAMETER_VALUE("est_valide....", exemple.est_valide())

        # -- Agrégation -------------------------------------------------------
        tous_résultats.extend(
            [pub.vers_dict() for pub in publications]
        )

    # --------------------------------------------------------------------------
    # Sauvegarde JSON
    # --------------------------------------------------------------------------
    log.STEP(1, "Sauvegarde des résultats")
    horodatage   = datetime.now().strftime("%Y-%m-%d_%H-%M")
    fichier_sortie = DOSSIER_SORTIE / f"test_rss_{horodatage}.json"

    with open(fichier_sortie, "w", encoding="utf-8") as f:
        json.dump(tous_résultats, f, ensure_ascii=False, indent=2)

    log.PARAMETER_VALUE("fichier sauvegardé", str(fichier_sortie))
    log.PARAMETER_VALUE("total publications", len(tous_résultats))

    # --------------------------------------------------------------------------
    # Rapport final
    # --------------------------------------------------------------------------
    log.STEP(1, "RAPPORT FINAL")
    for source, stats in statistiques.items():
        log.PARAMETER_VALUE(
            f"{source}",
            f"{stats['statut']} — "
            f"{stats['publications_valides']} publications",
        )

    log.FINISH_ACTION(
        "test_feedparser", "main",
        f"{len(tous_résultats)} publications extraites au total"
    )


# ==============================================================================
if __name__ == "__main__":
    main()
