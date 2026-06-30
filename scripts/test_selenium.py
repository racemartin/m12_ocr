# ==============================================================================
# scripts/test_selenium.py — Test individuel de l'adaptateur Selenium
#
# Ce script teste SeleniumAdapter sur les 2 sites JavaScript dynamiques :
#   - Logically Facts (logically.ai) — fact-checker IA en anglais
#   - Decodex Le Monde (lemonde.fr)  — vérification française
#
# ⚠ Prérequis système : Google Chrome doit être installé.
#   Dans WSL2 Ubuntu :
#     sudo apt install -y chromium-browser
#   webdriver-manager télécharge automatiquement le bon ChromeDriver.
#
# ⚠ Selenium est l'adaptateur le plus lent — chaque page nécessite
#   un rendu JavaScript complet (3-5 secondes par page).
#
# Lancement :
#   python3 scripts/test_selenium.py
#   python3 scripts/test_selenium.py --source decodex
# ==============================================================================

# --- Bibliothèque standard ---------------------------------------------------
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib  import Path

# --- Path projet -------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# --- Imports projet ----------------------------------------------------------
from src.adapters.outbound.scrapers.selenium_adapter import (
    SeleniumAdapter,
    CONFIG_SOURCES,
)
from src.tools.rafael.log_tool import LogTool

DOSSIER_SORTIE = Path(__file__).resolve().parent.parent / "data" / "raw"
DOSSIER_SORTIE.mkdir(parents=True, exist_ok=True)

log = LogTool(origin="test_selenium")


# ##############################################################################
def main(source_cible: str = "") -> None:
    """
    Teste SeleniumAdapter sur une source ou sur toutes les sources.

    Paramètres
    ----------
    source_cible : str
        Source spécifique à tester (vide = toutes les sources).
    """
    log.START_ACTION(
        "test_selenium", "main", "début des tests Selenium"
    )
    log.LEVEL_6_NOTICE(
        "test_selenium",
        "Chrome headless requis — premier lancement peut être lent "
        "(téléchargement ChromeDriver)",
    )

    sources_à_tester = (
        {source_cible: CONFIG_SOURCES[source_cible]}
        if source_cible and source_cible in CONFIG_SOURCES
        else CONFIG_SOURCES
    )

    tous_résultats = []
    statistiques   = {}

    # --------------------------------------------------------------------------
    # Test de chaque source SPA
    # --------------------------------------------------------------------------
    for nom_source, config in sources_à_tester.items():
        log.STEP(1, f"Test source : {nom_source}", config["url_liste"])

        try:
            adaptateur = SeleniumAdapter(source=nom_source)
        except ValueError as erreur:
            log.LEVEL_4_ERROR("test_selenium", str(erreur))
            continue

        # -- Vérification disponibilité (HEAD — pas de Chrome) ----------------
        log.PARAMETER_VALUE("disponibilité...", "test en cours")
        if not adaptateur.est_disponible(config["url_liste"]):
            log.LEVEL_5_WARNING(
                "test_selenium",
                f"Site {nom_source} inaccessible — ignoré",
            )
            statistiques[nom_source] = {
                "statut": "HORS LIGNE", "publications": 0, "durée": 0
            }
            continue

        log.PARAMETER_VALUE("disponibilité...", "✅ en ligne")
        log.PARAMETER_VALUE("langue..........", config["langue"])

        # -- Extraction (lance Chrome headless) --------------------------------
        log.STEP(2, "Lancement Chrome headless + extraction")
        chrono_début = time.perf_counter()

        try:
            publications = adaptateur.extraire_données(config["url_liste"])
        except Exception as erreur:
            log.LEVEL_3_CRITICAL(
                "test_selenium",
                f"Échec extraction {nom_source} : {erreur}",
            )
            statistiques[nom_source] = {
                "statut": "ERREUR", "publications": 0, "durée": 0
            }
            continue

        durée = round(time.perf_counter() - chrono_début, 1)

        statistiques[nom_source] = {
            "statut"       : "OK",
            "publications" : len(publications),
            "durée"        : durée,
        }

        log.PARAMETER_VALUE("durée extraction", f"{durée}s")
        log.PARAMETER_VALUE("publications....", len(publications))

        # -- Affichage d'un exemple ---------------------------------------------
        if publications:
            exemple = publications[0]
            log.STEP(2, "Exemple extrait")
            log.PARAMETER_VALUE("titre.....", exemple.title[:60])
            log.PARAMETER_VALUE("label.....", exemple.declared_label.value)
            log.PARAMETER_VALUE("langue....", exemple.lang)
            log.PARAMETER_VALUE("image.....", exemple.image_url[:60])
            log.PARAMETER_VALUE("valide....", exemple.est_valide())

            réels = sum(
                1 for p in publications
                if p.declared_label.value == "REAL"
            )
            faux  = len(publications) - réels
            log.PARAMETER_VALUE(
                "distribution....", f"REAL:{réels} FAKE:{faux}"
            )
        else:
            log.LEVEL_5_WARNING(
                "test_selenium",
                f"Aucune publication extraite pour {nom_source} — "
                "vérifier les sélecteurs CSS (site possiblement modifié)",
            )

        tous_résultats.extend(
            [pub.vers_dict() for pub in publications]
        )

    # --------------------------------------------------------------------------
    # Sauvegarde JSON
    # --------------------------------------------------------------------------
    if tous_résultats:
        horodatage     = datetime.now().strftime("%Y-%m-%d_%H-%M")
        fichier_sortie = DOSSIER_SORTIE / f"test_selenium_{horodatage}.json"
        with open(fichier_sortie, "w", encoding="utf-8") as f:
            json.dump(tous_résultats, f, ensure_ascii=False, indent=2)
        log.PARAMETER_VALUE("fichier sauvegardé", str(fichier_sortie))

    # --------------------------------------------------------------------------
    # Rapport final
    # --------------------------------------------------------------------------
    log.STEP(1, "RAPPORT FINAL SELENIUM")
    for source, stats in statistiques.items():
        log.PARAMETER_VALUE(
            f"{source}",
            f"{stats['statut']} — {stats['publications']} publications "
            f"({stats['durée']}s)",
        )
    log.PARAMETER_VALUE("total publications", len(tous_résultats))
    log.FINISH_ACTION(
        "test_selenium", "main",
        f"{len(tous_résultats)} publications extraites"
    )


# ==============================================================================
if __name__ == "__main__":
    parseur = argparse.ArgumentParser(
        description="Test de l'adaptateur Selenium"
    )
    parseur.add_argument(
        "--source",
        choices=list(CONFIG_SOURCES.keys()),
        default="",
        help="Source spécifique à tester (défaut : toutes)",
    )
    args = parseur.parse_args()
    main(source_cible=args.source)
