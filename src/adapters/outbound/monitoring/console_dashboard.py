# ==============================================================================
# src/adapters/outbound/monitoring/console_dashboard.py
# Adaptateur de présentation console (test rapide du MonitoringService)
#
# Architecture hexagonale — DEUXIÈME ADAPTATEUR DE PRÉSENTATION :
#   Ce fichier consomme EXACTEMENT le même MonitoringService que
#   streamlit_dashboard.py, sans aucune duplication de logique métier.
#   Il ne fait qu'imprimer ce que le service lui retourne — la preuve
#   concrète que remplacer (ou ajouter) un adaptateur de présentation
#   ne coûte que ce fichier, jamais les couches inférieures.
#
# Utilité : permet de vérifier tous les KPI en ligne de commande, sans
# lancer de serveur web, avant de committer l'adaptateur Streamlit.
#
# Lancement :
#   uv run python3 src/adapters/outbound/monitoring/console_dashboard.py
# ==============================================================================

# --- Bibliothèque standard : chemin projet et types ----------------------------
import os                                  # Lecture des variables du .env
import sys                                 # Bootstrap du chemin projet

from   pathlib import Path                 # Chemins portables
from   typing  import List                 # Annotations de types

# --- Racine du projet : indispensable AVANT les imports src.* ------------------
RACINE_PROJET = Path(__file__).resolve().parents[4]
if str(RACINE_PROJET) not in sys.path:
    sys.path.insert(0, str(RACINE_PROJET))

# --- Couches du projet : composition root de CET adaptateur --------------------
from   src.adapters.outbound.persistence.postgresql_adapter import (
    PostgresqlAdapter,                     # Implémentation du port persistance
)
from   src.application.monitoring_service import MonitoringService


# ==============================================================================
# CONFIGURATION — largeur du rapport et symboles de statut
# ==============================================================================
LARGEUR_RAPPORT = 80                          # Largeur totale des encadrés
BORDURE_DOUBLE  = "=" * LARGEUR_RAPPORT        # Marges de section (haut/bas)
SÉPARATEUR      = "-" * LARGEUR_RAPPORT        # Séparation interne (sous-titres)

ÉMOJI_STATUT = {                              # Symboles pour les lignes d'alerte
    "vert"   : "✅",                           # (texte libre — largeur variable
    "orange" : "⚠️",                            #  selon terminal, sans impact)
    "rouge"  : "🔴",
}

SYMBOLE_TABLEAU = {                           # Étiquettes ASCII pour le tableau
    "vert"   : "[OK]",                        # — largeur fixe garantie, aucun
    "orange" : "[!!]",                        #   décalage de colonne quel que
    "rouge"  : "[XX]",                        #   soit le rendu des emojis
}


# ##############################################################################
# COMPOSITION ROOT DE L'ADAPTATEUR — chargement .env et injection
# ##############################################################################
def construire_service() -> MonitoringService:
    """
    Construit le MonitoringService avec ses dépendances injectées.

    Même mécanisme que streamlit_dashboard.py (chargement .env puis
    injection du PostgresqlAdapter) — chaque adaptateur possède son
    propre point de composition, sans dépendre d'Airflow ni d'un
    autre adaptateur.
    """
    from dotenv import load_dotenv         # Chargement du fichier .env

    load_dotenv(RACINE_PROJET / ".env")

    persistance = PostgresqlAdapter(config={
        "host"     : os.environ.get("CHECKIT_PG_HOST", "localhost"),
        "port"     : os.environ.get("CHECKIT_PG_PORT", "5432"),
        "dbname"   : os.environ.get("CHECKIT_PG_DB",   "checkit"),
        "user"     : os.environ.get("CHECKIT_PG_USER", "checkit"),
        "password" : os.environ["CHECKIT_PG_PASSWORD"],
    })
    return MonitoringService(persistence=persistance)


# ##############################################################################
# SECTION 1 — Précision des données
# ##############################################################################
def afficher_précision(précision: dict, seuils: dict) -> None:
    """Imprime les KPIs de précision : répartition et taux d'intégrité."""
    print(BORDURE_DOUBLE)
    print("SECTION 1 — PRÉCISION DES DONNÉES")
    print(BORDURE_DOUBLE)

    print(f"  Publications totales................: "
          f"{précision['total_publications']}")
    print(f"  REAL.................................: "
          f"{précision['nb_real']}")
    print(f"  FAKE.................................: "
          f"{précision['nb_fake']}")
    print(f"  Ratio REAL...........................: "
          f"{précision['ratio_real_pct']} %")

    taux = précision["dernier_taux_intégrité"]
    print(SÉPARATEUR)
    if taux is None:
        print("  Aucun run enregistré pour le moment.")
    elif taux < seuils["intégrité_critique"]:
        print(f"  🔴 ALERTE CRITIQUE — taux d'intégrité....: {taux} % "
              f"(seuil : {seuils['intégrité_critique']} %)")
    elif taux < seuils["intégrité_avertissement"]:
        print(f"  ⚠️  AVERTISSEMENT — taux d'intégrité......: {taux} % "
              f"(seuil : {seuils['intégrité_avertissement']} %)")
    else:
        print(f"  ✅ OK — taux d'intégrité du dernier run..: {taux} %")
    print()


# ##############################################################################
# SECTION 2 — Rapidité du pipeline
# ##############################################################################
def afficher_rapidité(rapidité: dict) -> None:
    """Imprime la durée des runs successifs et leur moyenne."""
    print(BORDURE_DOUBLE)
    print("SECTION 2 — RAPIDITÉ DU PIPELINE")
    print(BORDURE_DOUBLE)

    print(f"  Durée moyenne par run................: "
          f"{rapidité['durée_moyenne_s']} s")
    print(f"  Runs mesurés.........................: "
          f"{rapidité['nb_runs_mesurés']}")

    durées = rapidité["durées_par_run"]
    if durées:
        print(SÉPARATEUR)
        print("  Détail des 5 derniers runs mesurés :")
        # -- Affichage tabulaire aligné sur les points (convention projet) -----
        for run in durées[:5]:
            print(f"    {run['run_id']:<26}"
                  f"{'.' * (28 - len(run['run_id']))}: "
                  f"{run['durée_secondes']:>7.1f} s "
                  f"({run['nb_valides']} valides)")
    else:
        print("  Aucun run complet mesuré pour le moment.")
    print()


# ##############################################################################
# SECTION 3 — Coût estimé (ressources consommées)
# ##############################################################################
def afficher_coût(coût: dict) -> None:
    """Imprime l'estimation de coût en ressources consommées."""
    print(BORDURE_DOUBLE)
    print("SECTION 3 — COÛT ESTIMÉ (RESSOURCES)")
    print(BORDURE_DOUBLE)

    print(f"  Requêtes HTTP estimées...............: "
          f"{coût['nb_requêtes_estimées']}")
    print(f"  Temps CPU estimé.....................: "
          f"{coût['temps_cpu_estimé_min']} min")
    print(SÉPARATEUR)
    print(f"  Hypothèse : {coût['hypothèse']}")
    print()


# ##############################################################################
# SECTION 4 — Statut des sources (KPI le plus actionnable)
# ##############################################################################
def afficher_statut_sources(sources: List[dict]) -> None:
    """
    Imprime le tableau des sources avec un statut visuel, trié par
    criticité (rouge en premier — cohérent avec MonitoringService).
    """
    print(BORDURE_DOUBLE)
    print("SECTION 4 — STATUT DES SOURCES")
    print(BORDURE_DOUBLE)

    if not sources:
        print("  Aucune source enregistrée pour le moment.")
        print()
        return

    nb_rouge  = sum(1 for s in sources if s["statut"] == "rouge")
    nb_orange = sum(1 for s in sources if s["statut"] == "orange")
    if nb_rouge:
        print(f"  🔴 {nb_rouge} source(s) à 0 publication ou "
              "jamais extraite(s)")
    if nb_orange:
        print(f"  ⚠️  {nb_orange} source(s) muette(s) depuis plus de 48h")
    if not nb_rouge and not nb_orange:
        print("  ✅ Toutes les sources sont fraîches et productives.")
    print(SÉPARATEUR)

    # -- En-tête du tableau (alignement fixe des colonnes) ---------------------
    print(f"  {'':<5}{'Source':<28}{'Type':<10}"
          f"{'Publications':>13}{'Âge (h)':>10}")
    print(f"  {'-'*5}{'-'*28}{'-'*10}{'-'*13}{'-'*10}")

    for source in sources:
        symbole = SYMBOLE_TABLEAU[source["statut"]]
        âge     = (
            f"{source['âge_heures']:.1f}"
            if source["âge_heures"] is not None else "—"
        )
        print(f"  {symbole:<5}{source['nom_domaine']:<28}"
              f"{source['type_source']:<10}"
              f"{source['nb_publications']:>13}"
              f"{âge:>10}")
    print()


# ##############################################################################
# POINT D'ENTRÉE — assemblage du rapport console complet
# ##############################################################################
def main() -> None:
    """Génère le rapport console complet (équivalent texte du L6)."""
    # -- Encadré de titre (marges en lignes doubles) ----------------------------
    print(BORDURE_DOUBLE)
    print("CheckIt.AI — TABLEAU DE BORD ETL (RAPPORT CONSOLE)".center(
        LARGEUR_RAPPORT
    ))
    print("Équivalent texte du livrable L6 — mêmes KPIs, même service".center(
        LARGEUR_RAPPORT
    ))
    print(BORDURE_DOUBLE)
    print()

    service = construire_service()
    rapport = service.générer_rapport_complet()

    afficher_précision(rapport["précision"], rapport["seuils"])
    afficher_rapidité(rapport["rapidité"])
    afficher_coût(rapport["coût"])
    afficher_statut_sources(rapport["statut_sources"])

    print(BORDURE_DOUBLE)
    print(f"  Rapport généré le....................: "
          f"{rapport['généré_le']}")
    print(BORDURE_DOUBLE)


if __name__ == "__main__":
    main()
