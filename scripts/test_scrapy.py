# ==============================================================================
# scripts/test_scrapy.py — Test individuel de l'adaptateur Scrapy
#
# Ce script teste ScrapyAdapter de façon autonome — crawling
# multi-pages sur PolitiFact avec pagination.
#
# ⚠ Scrapy est plus lent que les autres adaptateurs — le crawl
# respecte robots.txt et un délai entre requêtes (AUTOTHROTTLE).
#
# Lancement :
#   python3 scripts/test_scrapy.py
# ==============================================================================

# --- Bibliothèque standard ---------------------------------------------------
import json
import sys
import time
from datetime import datetime
from pathlib  import Path

# --- Path projet -------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# --- Imports projet ----------------------------------------------------------
from src.adapters.outbound.scrapers.scrapy_adapter import ScrapyAdapter
from src.tools.rafael.log_tool                      import LogTool

# --- Configuration -----------------------------------------------------------
URL_POLITIFACT  = "https://www.politifact.com/factchecks/"
DOSSIER_SORTIE  = Path(__file__).resolve().parent.parent / "data" / "raw"
DOSSIER_SORTIE.mkdir(parents=True, exist_ok=True)

log = LogTool(origin="test_scrapy")


# ##############################################################################
def main() -> None:
    """
    Lance le test du crawler Scrapy sur PolitiFact.

    Le crawl Scrapy est synchrone et bloquant — ce script attend
    la fin complète du processus avant d'afficher les résultats.
    Durée typique : 30-90 secondes selon le nombre d'articles.
    """
    log.START_ACTION("test_scrapy", "main", "début du test Scrapy")

    adaptateur = ScrapyAdapter(source="politifact")

    # --------------------------------------------------------------------------
    # Vérification disponibilité
    # --------------------------------------------------------------------------
    log.STEP(1, "Vérification disponibilité", URL_POLITIFACT)
    log.PARAMETER_VALUE("disponibilité...", "test en cours")

    if not adaptateur.est_disponible(URL_POLITIFACT):
        log.LEVEL_4_ERROR(
            "test_scrapy", "PolitiFact inaccessible — arrêt du test"
        )
        return

    log.PARAMETER_VALUE("disponibilité...", "✅ en ligne")
    log.PARAMETER_VALUE("nom_source......", adaptateur.nom_source)

    # --------------------------------------------------------------------------
    # Lancement du crawl (bloquant)
    # --------------------------------------------------------------------------
    log.STEP(1, "Lancement du crawl Scrapy", "ceci peut prendre 30-90s")
    chrono_début = time.perf_counter()

    publications = adaptateur.extraire_données(URL_POLITIFACT)

    durée = round(time.perf_counter() - chrono_début, 1)
    log.PARAMETER_VALUE("durée du crawl....", f"{durée}s")

    # --------------------------------------------------------------------------
    # Statistiques
    # --------------------------------------------------------------------------
    log.STEP(1, "Statistiques d'extraction")
    log.PARAMETER_VALUE("publications valides", len(publications))

    if not publications:
        log.LEVEL_5_WARNING(
            "test_scrapy",
            "Aucune publication extraite — vérifier les sélecteurs CSS "
            "(PolitiFact peut avoir changé sa structure HTML)",
        )
        log.FINISH_ACTION(
            "test_scrapy", "main", "0 publications — voir avertissement"
        )
        return

    # -- Distribution des labels -----------------------------------------------
    réels = sum(1 for p in publications if p.declared_label.value == "REAL")
    faux  = len(publications) - réels
    log.PARAMETER_VALUE(
        "distribution labels", f"REAL:{réels} FAKE:{faux}"
    )

    # --------------------------------------------------------------------------
    # Affichage d'exemples
    # --------------------------------------------------------------------------
    log.STEP(1, "Exemples extraits")
    for i, pub in enumerate(publications[:3]):
        log.PARAMETER_VALUE(f"[{i+1}] titre.....", pub.title[:60])
        log.PARAMETER_VALUE(f"[{i+1}] label.....", pub.declared_label.value)
        log.PARAMETER_VALUE(f"[{i+1}] image.....", pub.image_url[:60])
        log.PARAMETER_VALUE(f"[{i+1}] valide....", pub.est_valide())

    # --------------------------------------------------------------------------
    # Sauvegarde JSON
    # --------------------------------------------------------------------------
    horodatage     = datetime.now().strftime("%Y-%m-%d_%H-%M")
    fichier_sortie = DOSSIER_SORTIE / f"test_scrapy_{horodatage}.json"

    with open(fichier_sortie, "w", encoding="utf-8") as f:
        json.dump(
            [pub.vers_dict() for pub in publications],
            f, ensure_ascii=False, indent=2,
        )

    log.PARAMETER_VALUE("fichier sauvegardé", str(fichier_sortie))
    log.FINISH_ACTION(
        "test_scrapy", "main",
        f"{len(publications)} publications extraites en {durée}s"
    )


# ==============================================================================
if __name__ == "__main__":
    main()
