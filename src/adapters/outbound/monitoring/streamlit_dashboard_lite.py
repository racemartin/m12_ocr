# ==============================================================================
# src/adapters/outbound/monitoring/streamlit_dashboard.py
# Adaptateur de présentation Streamlit (Étape 5 / L6)
#
# Architecture hexagonale — ADAPTATEUR MINCE :
#   Ce fichier ne contient AUCUN calcul de KPI. Il compose (charge le
#   .env, construit PostgresqlAdapter + MonitoringService) puis AFFICHE
#   ce que MonitoringService lui retourne. Remplacer Streamlit par
#   Grafana, une API REST ou un export PDF ne change rien au reste du
#   projet — seul ce fichier serait réécrit.
#
# Lancement :
#   uv run streamlit run src/adapters/outbound/monitoring/streamlit_dashboard.py
# ==============================================================================

# --- Bibliothèque standard : chemin projet et types ----------------------------
import sys                                 # Bootstrap du chemin projet
from   pathlib import Path                 # Chemins portables

# --- Racine du projet : indispensable AVANT les imports src.* ------------------
RACINE_PROJET = Path(__file__).resolve().parents[4]
if str(RACINE_PROJET) not in sys.path:
    sys.path.insert(0, str(RACINE_PROJET))

# --- Dépendances externes : interface web et manipulation tabulaire ------------
import pandas   as pd                      # DataFrames pour st.dataframe/charts
import streamlit as st                     # Framework de dashboard (UI pure)

# --- Couches du projet : composition root de CET adaptateur --------------------
from   src.adapters.outbound.persistence.postgresql_adapter import (
    PostgresqlAdapter,                     # Implémentation du port persistance
)
from   src.application.monitoring_service import MonitoringService


# ==============================================================================
# COMPOSITION ROOT DE L'ADAPTATEUR — chargement .env et injection
# ==============================================================================
@st.cache_resource
def construire_service() -> MonitoringService:
    """
    Construit le MonitoringService avec ses dépendances injectées.

    @st.cache_resource : la connexion PostgreSQL est créée UNE fois par
    session Streamlit, pas à chaque interaction utilisateur.
    """
    from dotenv import load_dotenv         # Chargement du fichier .env

    load_dotenv(RACINE_PROJET / ".env")
    import os

    persistance = PostgresqlAdapter(config={
        "host"     : os.environ.get("CHECKIT_PG_HOST", "localhost"),
        "port"     : os.environ.get("CHECKIT_PG_PORT", "5432"),
        "dbname"   : os.environ.get("CHECKIT_PG_DB",   "checkit"),
        "user"     : os.environ.get("CHECKIT_PG_USER", "checkit"),
        "password" : os.environ["CHECKIT_PG_PASSWORD"],
    })
    return MonitoringService(persistence=persistance)


# ==============================================================================
# MISE EN PAGE — traduction des couleurs de statut en émojis (lisibilité)
# ==============================================================================
ÉMOJI_STATUT = {"vert": "✅", "orange": "⚠️", "rouge": "🔴"}


# ##############################################################################
# SECTION 1 — Précision des données
# ##############################################################################
def afficher_précision(précision: dict, seuils: dict) -> None:
    """Affiche les KPIs de précision : répartition et taux d'intégrité."""
    st.header("📊 Précision des données")

    colonne_1, colonne_2, colonne_3, colonne_4 = st.columns(4)
    colonne_1.metric("Publications totales", précision["total_publications"])
    colonne_2.metric("REAL", précision["nb_real"])
    colonne_3.metric("FAKE", précision["nb_fake"])
    colonne_4.metric("Ratio REAL", f"{précision['ratio_real_pct']} %")

    taux = précision["dernier_taux_intégrité"]
    if taux is not None:
        if taux < seuils["intégrité_critique"]:
            st.error(f"🔴 Taux d'intégrité du dernier run : {taux} % "
                      "— sous le seuil critique "
                      f"({seuils['intégrité_critique']} %)")
        elif taux < seuils["intégrité_avertissement"]:
            st.warning(f"⚠️ Taux d'intégrité du dernier run : {taux} % "
                        "— sous le seuil d'avertissement "
                        f"({seuils['intégrité_avertissement']} %)")
        else:
            st.success(f"✅ Taux d'intégrité du dernier run : {taux} %")

    # -- Graphique de répartition (bibliothèque native Streamlit) --------------
    df_répartition = pd.DataFrame({
        "Classe"    : ["REAL", "FAKE"],
        "Effectif"  : [précision["nb_real"], précision["nb_fake"]],
    }).set_index("Classe")
    st.bar_chart(df_répartition)


# ##############################################################################
# SECTION 2 — Rapidité (temps par run)
# ##############################################################################
def afficher_rapidité(rapidité: dict) -> None:
    """Affiche l'évolution de la durée des runs successifs."""
    st.header("⏱️ Rapidité du pipeline")

    colonne_1, colonne_2 = st.columns(2)
    colonne_1.metric("Durée moyenne par run",
                      f"{rapidité['durée_moyenne_s']} s")
    colonne_2.metric("Runs mesurés", rapidité["nb_runs_mesurés"])

    if rapidité["durées_par_run"]:
        df_durées = pd.DataFrame(rapidité["durées_par_run"])
        df_durées = df_durées.set_index("run_id")[["durée_secondes"]]
        st.line_chart(df_durées)
    else:
        st.info("Aucun run complet mesuré pour le moment.")


# ##############################################################################
# SECTION 3 — Coût estimé (ressources consommées)
# ##############################################################################
def afficher_coût(coût: dict) -> None:
    """Affiche l'estimation de coût en ressources consommées."""
    st.header("💰 Coût estimé (ressources)")

    colonne_1, colonne_2 = st.columns(2)
    colonne_1.metric("Requêtes HTTP estimées", coût["nb_requêtes_estimées"])
    colonne_2.metric("Temps CPU estimé", f"{coût['temps_cpu_estimé_min']} min")
    st.caption(f"Hypothèse de calcul : {coût['hypothèse']}")


# ##############################################################################
# SECTION 4 — Statut des sources (KPI le plus actionnable)
# ##############################################################################
def afficher_statut_sources(sources: list) -> None:
    """
    Affiche le tableau des sources avec un statut visuel (✅/⚠️/🔴).

    Lisible par un public non technique (point de vigilance de la
    mission) : une ligne rouge = une source à investiguer, sans avoir
    à lire le moindre log.
    """
    st.header("🛰️ Statut des sources")

    if not sources:
        st.info("Aucune source enregistrée pour le moment.")
        return

    nb_rouge  = sum(1 for s in sources if s["statut"] == "rouge")
    nb_orange = sum(1 for s in sources if s["statut"] == "orange")
    if nb_rouge:
        st.error(f"🔴 {nb_rouge} source(s) à 0 publication ou "
                  "jamais extraite(s)")
    if nb_orange:
        st.warning(f"⚠️ {nb_orange} source(s) muette(s) depuis "
                    "plus de 48 heures")

    df_sources = pd.DataFrame(sources)
    df_sources["État"]  = df_sources["statut"].map(ÉMOJI_STATUT)
    df_sources          = df_sources[[
        "État", "nom_domaine", "type_source",
        "nb_publications", "âge_heures",
    ]]
    df_sources.columns = [
        "État", "Source", "Type", "Publications", "Âge (h)",
    ]
    st.dataframe(df_sources, use_container_width=True, hide_index=True)


# ##############################################################################
# POINT D'ENTRÉE — mise en page de la page Streamlit
# ##############################################################################
def main() -> None:
    """Assemble les quatre sections du tableau de bord."""
    st.set_page_config(
        page_title = "CheckIt.AI — Tableau de bord ETL",
        page_icon  = "📰",
        layout     = "wide",
    )
    st.title("📰 CheckIt.AI — Tableau de bord du pipeline ETL")
    st.caption("Livrable L6 — indicateurs de précision, rapidité et coût")

    if st.button("🔄 Rafraîchir les données"):
        st.cache_resource.clear()

    service  = construire_service()
    rapport  = service.générer_rapport_complet()

    afficher_précision(rapport["précision"], rapport["seuils"])
    st.divider()
    afficher_rapidité(rapport["rapidité"])
    st.divider()
    afficher_coût(rapport["coût"])
    st.divider()
    afficher_statut_sources(rapport["statut_sources"])

    st.caption(f"Rapport généré le {rapport['généré_le']}")


if __name__ == "__main__":
    main()
