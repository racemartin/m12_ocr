# ==============================================================================
# scripts/test_bs4.py — Test individuel de l'adaptateur BeautifulSoup4
#
# Ce script teste Bs4Adapter sur les 3 fact-checkers HTML statiques :
#   - FullFact UK    (fullfact.org)
#   - Correctiv DE   (correctiv.org)
#   - Maldita ES     (maldita.es)
#
# Lancement :
#   python3 scripts/test_bs4.py
#   python3 scripts/test_bs4.py --source fullfact
# ==============================================================================

# --- Bibliothèque standard ---------------------------------------------------
import argparse   # arguments en ligne de commande
import json
import sys
from datetime import datetime
from pathlib  import Path

# --- Path projet -------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# --- Imports projet ----------------------------------------------------------
from src.adapters.outbound.scrapers.bs4_adapter import (
    Bs4Adapter,
    CONFIG_SOURCES,
)
from src.tools.rafael.log_tool import LogTool

DOSSIER_SORTIE = Path(__file__).resolve().parent.parent / "data" / "raw"
DOSSIER_SORTIE.mkdir(parents=True, exist_ok=True)

log = LogTool(origin="test_bs4")


# ##############################################################################
def main(source_cible: str = "") -> None:
    """
    Teste Bs4Adapter sur une source ou sur toutes les sources.

    Paramètres
    ----------
    source_cible : str
        Source spécifique à tester (vide = toutes les sources).
    """
    log.START_ACTION("test_bs4", "main", "début des tests BeautifulSoup4")

    sources_à_tester = (
        {source_cible: CONFIG_SOURCES[source_cible]}
        if source_cible and source_cible in CONFIG_SOURCES
        else CONFIG_SOURCES
    )

    tous_résultats = []
    statistiques   = {}

    # --------------------------------------------------------------------------
    # Test de chaque source HTML
    # --------------------------------------------------------------------------
    for nom_source, config in sources_à_tester.items():
        log.STEP(1, f"Test source : {nom_source}", config["url_liste"])

        try:
            adaptateur = Bs4Adapter(source=nom_source)
        except ValueError as erreur:
            log.LEVEL_4_ERROR("test_bs4", str(erreur))
            continue

        # -- Vérification disponibilité ---------------------------------------
        if not adaptateur.est_disponible(config["url_liste"]):
            log.LEVEL_5_WARNING(
                "test_bs4",
                f"Site {nom_source} inaccessible — ignoré",
            )
            statistiques[nom_source] = {
                "statut": "HORS LIGNE", "publications": 0
            }
            continue

        log.PARAMETER_VALUE("disponibilité...", "✅ en ligne")
        log.PARAMETER_VALUE("langue..........", config["langue"])
        log.PARAMETER_VALUE("domaine.........", config["domaine"])

        # -- Extraction -------------------------------------------------------
        publications = adaptateur.extraire_données(config["url_liste"])

        statistiques[nom_source] = {
            "statut"       : "OK",
            "publications" : len(publications),
            "langue"       : config["langue"],
        }

        # -- Affichage d'un exemple ------------------------------------------
        if publications:
            exemple = publications[0]
            log.STEP(2, "Exemple extrait")
            log.PARAMETER_VALUE("titre.....", exemple.title[:60])
            log.PARAMETER_VALUE("label.....", exemple.declared_label.value)
            log.PARAMETER_VALUE("langue....", exemple.lang)
            log.PARAMETER_VALUE("image.....", exemple.image_url[:60])
            log.PARAMETER_VALUE("valide....", exemple.est_valide())

            # Distribution des labels
            réels = sum(
                1 for p in publications
                if p.declared_label.value == "REAL"
            )
            faux  = len(publications) - réels
            log.PARAMETER_VALUE(
                "distribution....",
                f"REAL:{réels} FAKE:{faux}",
            )

        tous_résultats.extend(
            [pub.vers_dict() for pub in publications]
        )

    # --------------------------------------------------------------------------
    # Sauvegarde JSON
    # --------------------------------------------------------------------------
    if tous_résultats:
        horodatage     = datetime.now().strftime("%Y-%m-%d_%H-%M")
        fichier_sortie = DOSSIER_SORTIE / f"test_bs4_{horodatage}.json"
        with open(fichier_sortie, "w", encoding="utf-8") as f:
            json.dump(tous_résultats, f, ensure_ascii=False, indent=2)
        log.PARAMETER_VALUE("fichier sauvegardé", str(fichier_sortie))

    # --------------------------------------------------------------------------
    # Rapport final
    # --------------------------------------------------------------------------
    log.STEP(1, "RAPPORT FINAL BS4")
    for source, stats in statistiques.items():
        log.PARAMETER_VALUE(
            f"{source}",
            f"{stats['statut']} — {stats.get('publications',0)} publications"
            + (f" [{stats.get('langue','')}]" if stats.get('langue') else ""),
        )
    log.PARAMETER_VALUE("total publications", len(tous_résultats))
    log.FINISH_ACTION(
        "test_bs4", "main",
        f"{len(tous_résultats)} publications extraites"
    )


# ==============================================================================
if __name__ == "__main__":
    parseur = argparse.ArgumentParser(
        description="Test de l'adaptateur BeautifulSoup4"
    )
    parseur.add_argument(
        "--source",
        choices=list(CONFIG_SOURCES.keys()),
        default="",
        help="Source spécifique à tester (défaut : toutes)",
    )
    args = parseur.parse_args()
    main(source_cible=args.source)
