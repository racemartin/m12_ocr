# ==============================================================================
# scripts/test_feedparser.py — Test individuel de l'adaptateur RSS
# ==============================================================================

import json
import sys
from datetime import datetime
from pathlib  import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.adapters.outbound.scrapers.feedparser_adapter import FeedparserAdapter
from src.tools.rafael.log_tool import LogTool

# --- AFP Bluesky remplace factuel.afp.com/feed (bloqué 403) -----------------
SOURCES_RSS = {
    "afp_bluesky"  : "https://bsky.app/profile/did:plc:4ks5wkubjfcbgxvphqkd3wxm/rss",
    "euvsdisinfo"  : "https://euvsdisinfo.eu/feed/",
    "hoaxbuster"   : "https://www.hoaxbuster.com/rss/",
    "elpais"       : "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada",
    "politifact"   : "https://www.politifact.com/rss/factchecks/",
    "decodeurs"    : "https://www.lemonde.fr/les-decodeurs/rss_full.xml",
    "chequeado"    : "https://chequeado.com/feed/",
}

DOSSIER_SORTIE = Path(__file__).resolve().parent.parent / "data" / "raw"
DOSSIER_SORTIE.mkdir(parents=True, exist_ok=True)

log = LogTool(origin="test_rss")


def main() -> None:
    log.START_ACTION("test_feedparser", "main", "début des tests RSS")

    tous_résultats = []
    statistiques   = {}

    for nom_source, url in SOURCES_RSS.items():
        log.STEP(1, f"Test source : {nom_source}", url)
        adaptateur = FeedparserAdapter(source=nom_source)

        if not adaptateur.est_disponible(url):
            log.LEVEL_5_WARNING(
                "test_feedparser",
                f"Source {nom_source} hors ligne — ignorée",
            )
            statistiques[nom_source] = {"statut": "HORS LIGNE", "total": 0}
            continue

        publications = adaptateur.extraire_données(url)

        nb    = len(publications)
        réels = sum(1 for p in publications if p.declared_label.value == "REAL")
        faux  = nb - réels

        statistiques[nom_source] = {
            "statut": "OK", "total": nb, "real": réels, "fake": faux
        }
        log.PARAMETER_VALUE(f"{nom_source} — total", nb)
        log.PARAMETER_VALUE(f"{nom_source} — REAL.", réels)
        log.PARAMETER_VALUE(f"{nom_source} — FAKE.", faux)

        if publications:
            ex = publications[0]
            log.STEP(2, "Exemple")
            log.PARAMETER_VALUE("titre.....", ex.title[:70])
            log.PARAMETER_VALUE("label.....", ex.declared_label.value)
            log.PARAMETER_VALUE("image.....", ex.image_url[:60])

        tous_résultats.extend([p.vers_dict() for p in publications])

    # -- Sauvegarde -----------------------------------------------------------
    horodatage     = datetime.now().strftime("%Y-%m-%d_%H-%M")
    fichier_sortie = DOSSIER_SORTIE / f"test_rss_{horodatage}.json"
    with open(fichier_sortie, "w", encoding="utf-8") as f:
        json.dump(tous_résultats, f, ensure_ascii=False, indent=2)

    log.PARAMETER_VALUE("fichier sauvegardé", str(fichier_sortie))
    log.PARAMETER_VALUE("total publications", len(tous_résultats))

    log.STEP(1, "RAPPORT FINAL")
    for source, stats in statistiques.items():
        log.PARAMETER_VALUE(
            f"{source}",
            f"{stats['statut']} — total:{stats.get('total',0)} "
            f"REAL:{stats.get('real',0)} FAKE:{stats.get('fake',0)}",
        )

    log.FINISH_ACTION("test_feedparser", "main",
                      f"{len(tous_résultats)} publications extraites")


if __name__ == "__main__":
    main()
