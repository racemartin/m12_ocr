# ==============================================================================
# scripts/test_requests.py — Test individuel de l'adaptateur API REST
#
# Ce script teste RequestsAdapter de façon autonome.
# Il valide l'extraction depuis NewsData.io, Mediastack et le scoring ClaimBuster.
#
# Prérequis :
#   Créer un fichier .env à la racine du projet (hors Git) avec :
#     NEWSDATA_API_KEY=votre_clé_ici
#     MEDIASTACK_API_KEY=votre_clé_ici
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
DOSSIER_SORTIE = Path(__file__).resolve().parent.parent / "data" / "raw"
DOSSIER_SORTIE.mkdir(parents=True, exist_ok=True)

log = LogTool(origin="test_api")


# ##############################################################################
def main() -> None:
    """Test complet de l'adaptateur API REST NewsData.io + Mediastack + ClaimBuster."""
    log.START_ACTION("test_requests", "main", "début des tests API REST")

    # -- Vérification des clés API --------------------------------------------
    cle_newsdata = os.environ.get("NEWSDATA_API_KEY", "")
    cle_mediastack = os.environ.get("MEDIASTACK_API_KEY", "")

    if not cle_newsdata and not cle_mediastack:
        log.LEVEL_3_CRITICAL(
            "test_requests",
            "Clés API manquantes (NEWSDATA_API_KEY et MEDIASTACK_API_KEY) — "
            "veuillez configurer votre fichier .env",
        )
        log.STEP(1, "Mode démonstration sans clés API")
        _démonstration_sans_clé()
        return

    adaptateur = RequestsAdapter()
    tous_résultats = []

    # ==========================================================================
    # SECTION I : EXTRACTION NEWSDATA.IO
    # ==========================================================================
    if cle_newsdata:
        log.PARAMETER_VALUE("clé API NewsData", cle_newsdata[:8] + "..." + cle_newsdata[-4:])

        # Test disponibilité NewsData
        url_test_nd = f"https://newsdata.io/api/1/news?apikey={cle_newsdata}&size=1"
        log.PARAMETER_VALUE("disponibilité NewsData...", "test en cours")
        
        if adaptateur.est_disponible(url_test_nd):
            log.PARAMETER_VALUE("disponibilité NewsData...", "✅ API en ligne")

            # Extraction articles politiques FR
            log.STEP(1, "Extraction NewsData : articles politiques français")
            url_politique_nd = (
                f"https://newsdata.io/api/1/news"
                f"?apikey={cle_newsdata}&country=fr&language=fr&category=politics&size=10"
            )
            pub_pol_nd = adaptateur.extraire_données(url_politique_nd)
            log.PARAMETER_VALUE("articles politiques (ND)", len(pub_pol_nd))
            tous_résultats.extend([pub.vers_dict() for pub in pub_pol_nd])

            # Extraction articles santé
            log.STEP(1, "Extraction NewsData : articles santé")
            url_santé_nd = (
                f"https://newsdata.io/api/1/news"
                f"?apikey={cle_newsdata}&language=fr&q=vaccin+santé&size=10"
            )
            pub_sante_nd = adaptateur.extraire_données(url_santé_nd)
            log.PARAMETER_VALUE("articles santé (ND).......", len(pub_sante_nd))
            tous_résultats.extend([pub.vers_dict() for pub in pub_sante_nd])
        else:
            log.LEVEL_4_ERROR("test_requests", "API NewsData.io inaccessible")
    else:
        log.LEVEL_2_WARNING("test_requests", "NEWSDATA_API_KEY manquante, section ignorée.")

    # ==========================================================================
    # SECTION II : EXTRACTION MEDIASTACK
    # ==========================================================================
    if cle_mediastack:
        log.PARAMETER_VALUE("clé API Mediastack", cle_mediastack[:8] + "..." + cle_mediastack[-4:])

        # Test disponibilité Mediastack
        url_test_ms = f"http://api.mediastack.com/v1/news?access_key={cle_mediastack}&limit=1"
        log.PARAMETER_VALUE("disponibilité Mediastack...", "test en cours")

        if adaptateur.est_disponible(url_test_ms):
            log.PARAMETER_VALUE("disponibilité Mediastack...", "✅ API en ligne")

            # Extraction alternative politique FR
            log.STEP(1, "Extraction Mediastack : articles politiques français")
            url_politique_ms = (
                f"http://api.mediastack.com/v1/news"
                f"?access_key={cle_mediastack}&countries=fr&languages=fr&categories=politics&limit=10"
            )
            pub_pol_ms = adaptateur.extraire_données(url_politique_ms)
            log.PARAMETER_VALUE("articles politiques (MS)", len(pub_pol_ms))
            tous_résultats.extend([pub.vers_dict() for pub in pub_pol_ms])

            # Extraction alternative santé/vaccins
            log.STEP(1, "Extraction Mediastack : articles santé")
            url_santé_ms = (
                f"http://api.mediastack.com/v1/news"
                f"?access_key={cle_mediastack}&languages=fr&keywords=vaccin+santé&limit=10"
            )
            pub_sante_ms = adaptateur.extraire_données(url_santé_ms)
            log.PARAMETER_VALUE("articles santé (MS).......", len(pub_sante_ms))
            tous_résultats.extend([pub.vers_dict() for pub in pub_sante_ms])
        else:
            log.LEVEL_4_ERROR("test_requests", "API Mediastack inaccessible")
    else:
        log.LEVEL_2_WARNING("test_requests", "MEDIASTACK_API_KEY manquante, section ignorée.")

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
                pub_dict["title"][:60] if pub_dict.get("title") else "Pas de titre",
            )
            log.PARAMETER_VALUE(
                f"[{i+1}] label.....",
                pub_dict.get("declared_label", "UNKNOWN"),
            )
            log.PARAMETER_VALUE(
                f"[{i+1}] source....",
                pub_dict.get("source_domain", "UNKNOWN"),
            )

    # --------------------------------------------------------------------------
    # Sauvegarde JSON
    # --------------------------------------------------------------------------
    if tous_résultats:
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
    else:
        log.LEVEL_3_CRITICAL("test_requests", "Aucune donnée n'a pu être extraite.")


# ==============================================================================
def _démonstration_sans_clé() -> None:
    """
    Démonstration du fonctionnement sans clé API réelle.
    Affiche la structure attendue des publications extraites.
    """
    log.STEP(1, "Structure d'une Publication type (NewsData/Mediastack)")
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
    log.STEP(1, "Clés API nécessaires pour une extraction réelle")
    log.PARAMETER_VALUE("NewsData (Gratuit)", "https://newsdata.io/register (200 req/jour)")
    log.PARAMETER_VALUE("Mediastack (Gratuit)", "https://mediastack.com/signup (500 req/mois)")


# ==============================================================================
if __name__ == "__main__":
    main()


