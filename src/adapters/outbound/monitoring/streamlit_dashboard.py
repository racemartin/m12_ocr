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
# Navigation : un seul fichier avec menu latéral (4 vues) — le système
# multipage natif de Streamlit exigerait un répertoire pages/ avec un
# fichier par page, ce qui éclaterait l'adaptateur en plusieurs modules.
#
#   - Vue d'ensemble : synthèse des 4 familles de KPI + alertes
#   - Rapidité       : durée des runs, tendance, détail
#   - Coût           : ressources consommées (proxy documenté)
#   - Sources        : statut vert/orange/rouge par source
#
# Lancement :
#   uv run streamlit run src/adapters/outbound/monitoring/streamlit_dashboard.py
# ==============================================================================

# --- Bibliothèque standard : chemin projet, encodage et types -----------------
import base64                              # Encodage du logo pour le HTML
import os                                  # Lecture des variables du .env
import sys                                 # Bootstrap du chemin projet

from   pathlib import Path                 # Chemins portables
from   typing  import List, Optional       # Annotations de types

# --- Racine du projet : indispensable AVANT les imports src.* -----------------
RACINE_PROJET = Path(__file__).resolve().parents[4]
if str(RACINE_PROJET) not in sys.path:
    sys.path.insert(0, str(RACINE_PROJET))

# --- Dépendances externes : interface web et graphiques -----------------------
import altair    as alt                    # Graphiques à barres colorées
import pandas    as pd                     # DataFrames pour tables/graphes
import streamlit as st                     # Framework de dashboard (UI pure)

# --- Couches du projet : composition root de CET adaptateur -------------------
from   src.adapters.outbound.persistence.postgresql_adapter import (
    PostgresqlAdapter,                     # Implémentation du port persistance
)
from   src.application.monitoring_service import MonitoringService


# ==============================================================================
# CONFIGURATION — palette, logo et libellés de navigation
# ==============================================================================
CHEMIN_LOGO      = RACINE_PROJET / "docs" / "images" / "CheckIt_AI.png"

COULEUR_SIDEBAR  = "#0F2439"               # Bleu marine du menu latéral
COULEUR_TEXTE_SB = "#E8EEF5"               # Texte clair sur fond marine
COULEUR_VERT     = "#12B886"               # Statut OK / classe REAL
COULEUR_ORANGE   = "#F59F00"               # Avertissement / fraîcheur
COULEUR_ROUGE    = "#E5484D"               # Critique / classe FAKE
COULEUR_NEUTRE   = "#94A3B8"               # Valeurs inconnues / axes

COULEURS_STATUT  = {
    "vert"    : COULEUR_VERT,
    "orange"  : COULEUR_ORANGE,
    "rouge"   : COULEUR_ROUGE,
    "inconnu" : COULEUR_NEUTRE,
}

ÉMOJI_STATUT     = {"vert": "✅", "orange": "⚠️", "rouge": "🔴"}

PAGES            = ["Vue d'ensemble", "Rapidité", "Coût", "Sources"]


# ==============================================================================
# COMPOSITION ROOT DE L'ADAPTATEUR — chargement .env et injection
# ==============================================================================
@st.cache_resource
def construire_service() -> MonitoringService:
    """
    Construit le MonitoringService avec ses dépendances injectées.

    @st.cache_resource : la connexion PostgreSQL est créée UNE fois par
    session Streamlit, pas à chaque interaction utilisateur. Le rapport,
    lui, est bien recalculé à chaque rechargement de page.
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


# ==============================================================================
# STYLE GLOBAL — menu latéral bleu marine + carte blanche pour le logo
# ==============================================================================
def injecter_style() -> None:
    """
    Injecte le CSS du thème : le menu latéral passe en bleu marine avec
    texte clair, la zone de contenu reste claire (lisibilité des
    graphiques pour un public non technique).
    """
    st.markdown(
        f"""
        <style>
        /* --- Menu latéral : fond marine, texte clair ------------------ */
        [data-testid="stSidebar"] {{
            background-color: {COULEUR_SIDEBAR};
        }}
        [data-testid="stSidebar"] * {{
            color: {COULEUR_TEXTE_SB};
        }}
        /* --- Option de navigation sélectionnée : pastille teal -------- */
        [data-testid="stSidebar"] label[data-baseweb="radio"]
        div:first-child {{
            border-color: {COULEUR_VERT};
        }}
        /* --- Carte blanche du logo (le PNG a un fond blanc : on
               l'assume comme un badge, au lieu de le poser nu sur le
               fond marine) ------------------------------------------- */
        .carte-logo {{
            background    : #FFFFFF;
            border-radius : 12px;
            border-top    : 4px solid {COULEUR_VERT};
            padding       : 14px 10px 10px 10px;
            text-align    : center;
            box-shadow    : 0 3px 10px rgba(0, 0, 0, 0.35);
            margin-bottom : 4px;
        }}
        .sous-titre-sb {{
            text-align     : center;
            font-size      : 0.78rem;
            letter-spacing : 0.18em;
            text-transform : uppercase;
            opacity        : 0.75;
            margin-bottom  : 1.2rem;
        }}
        /* --- Cartes de statut des sources ------------------------------ */
        .carte-source {{
            background    : #FFFFFF;
            border        : 1px solid #E2E8F0;
            border-radius : 10px;
            padding       : 12px 14px;
            margin-bottom : 12px;
            box-shadow    : 0 1px 3px rgba(15, 36, 57, 0.08);
        }}
        .carte-source * {{
            color: #1E293B;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------------------------
def logo_en_base64() -> Optional[str]:
    """Retourne le logo encodé en base64, ou None s'il est introuvable."""
    if not CHEMIN_LOGO.exists():
        return None
    return base64.b64encode(CHEMIN_LOGO.read_bytes()).decode("ascii")


# ------------------------------------------------------------------------------
def afficher_entête_sidebar() -> None:
    """
    Affiche le logo dans une carte blanche arrondie (liseré teal) : le
    fond blanc du PNG devient un choix graphique assumé au lieu d'un
    rectangle blanc brut posé sur le bleu marine.
    """
    logo = logo_en_base64()
    if logo:
        st.sidebar.markdown(
            f"""
            <div class="carte-logo">
                <img src="data:image/png;base64,{logo}" width="120">
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.sidebar.markdown("## CheckIt.AI")
    st.sidebar.markdown(
        '<div class="sous-titre-sb">Monitoring ETL</div>',
        unsafe_allow_html=True,
    )


# ==============================================================================
# OUTILS GRAPHIQUES — barres horizontales colorées par statut (Altair)
# ==============================================================================
def statut_selon_taux(taux: Optional[float], seuils: dict) -> str:
    """Traduit un taux d'intégrité en statut vert/orange/rouge."""
    if taux is None:
        return "inconnu"
    if taux < seuils["intégrité_critique"]:
        return "rouge"
    if taux < seuils["intégrité_avertissement"]:
        return "orange"
    return "vert"


# ------------------------------------------------------------------------------
def graphique_durées(durées: List[dict], seuils: dict) -> alt.Chart:
    """
    Barres horizontales : une barre par run, longueur = durée (s).
    Si le taux d'intégrité du run est disponible (clé optionnelle
    'taux_intégrité'), la barre est colorée par statut ; sinon elle
    reste neutre teal.
    """
    df = pd.DataFrame(durées)
    df["statut"] = [
        statut_selon_taux(run.get("taux_intégrité"), seuils)
        for run in durées
    ]
    if (df["statut"] == "inconnu").all():
        df["statut"] = "vert"

    return (
        alt.Chart(df)
        .mark_bar(cornerRadiusEnd=4, height=16)
        .encode(
            y     = alt.Y("run_id:N", sort=None, title=None),
            x     = alt.X("durée_secondes:Q", title="Durée (s)"),
            color = alt.Color(
                "statut:N",
                scale  = alt.Scale(
                    domain = list(COULEURS_STATUT.keys()),
                    range  = list(COULEURS_STATUT.values()),
                ),
                legend = None,
            ),
            tooltip = [
                alt.Tooltip("run_id:N",         title="Run"),
                alt.Tooltip("durée_secondes:Q", title="Durée (s)"),
                alt.Tooltip("nb_valides:Q",     title="Valides"),
            ],
        )
        .properties(height=max(120, 30 * len(durées)))
    )


# ------------------------------------------------------------------------------
def graphique_répartition(nb_real: int, nb_fake: int) -> alt.Chart:
    """Barre horizontale empilée REAL (vert) / FAKE (rouge)."""
    df = pd.DataFrame({
        "Classe"   : ["REAL", "FAKE"],
        "Effectif" : [nb_real, nb_fake],
    })
    return (
        alt.Chart(df)
        .mark_bar(cornerRadius=4, height=34)
        .encode(
            x     = alt.X("Effectif:Q", stack="zero",
                          title="Publications"),
            color = alt.Color(
                "Classe:N",
                scale  = alt.Scale(
                    domain = ["REAL", "FAKE"],
                    range  = [COULEUR_VERT, COULEUR_ROUGE],
                ),
                legend = alt.Legend(orient="bottom", title=None),
            ),
            tooltip = ["Classe:N", "Effectif:Q"],
        )
        .properties(height=80)
    )


# ------------------------------------------------------------------------------
def graphique_valides_par_run(durées: List[dict]) -> alt.Chart:
    """Barres horizontales teal : publications valides par run."""
    df = pd.DataFrame(durées)
    return (
        alt.Chart(df)
        .mark_bar(cornerRadiusEnd=4, height=14, color=COULEUR_VERT)
        .encode(
            y       = alt.Y("run_id:N", sort=None, title=None),
            x       = alt.X("nb_valides:Q", title="Publications valides"),
            tooltip = [
                alt.Tooltip("run_id:N",     title="Run"),
                alt.Tooltip("nb_valides:Q", title="Valides"),
            ],
        )
        .properties(height=max(120, 26 * len(durées)))
    )


# ------------------------------------------------------------------------------
def bandeau_intégrité(taux: Optional[float], seuils: dict) -> None:
    """Bandeau d'alerte selon le taux d'intégrité du dernier run."""
    if taux is None:
        st.info("Aucun run enregistré pour le moment.")
        return
    statut = statut_selon_taux(taux, seuils)
    if statut == "rouge":
        st.error(f"🔴 Taux d'intégrité du dernier run : {taux} % "
                 f"— sous le seuil critique "
                 f"({seuils['intégrité_critique']} %)")
    elif statut == "orange":
        st.warning(f"⚠️ Taux d'intégrité du dernier run : {taux} % "
                   f"— sous le seuil d'avertissement "
                   f"({seuils['intégrité_avertissement']} %)")
    else:
        st.success(f"✅ Taux d'intégrité du dernier run : {taux} %")


# ##############################################################################
# PAGE 1 — VUE D'ENSEMBLE (synthèse des quatre familles de KPI)
# ##############################################################################
def page_vue_densemble(rapport: dict) -> None:
    """Synthèse : métriques clés, alerte, historique, sources, classes."""
    st.title("Vue d'ensemble")

    précision = rapport["précision"]
    rapidité  = rapport["rapidité"]
    coût      = rapport["coût"]
    sources   = rapport["statut_sources"]
    seuils    = rapport["seuils"]

    # -- Rangée de métriques principales (comme la maquette) -------------------
    nb_actives = sum(1 for s in sources if s["statut"] != "rouge")
    col_1, col_2, col_3, col_4 = st.columns(4)
    col_1.metric("Publications",
                 précision["total_publications"])
    col_2.metric("Taux REAL",
                 f"{précision['ratio_real_pct']} %")
    col_3.metric("Intégrité dernier run",
                 f"{précision['dernier_taux_intégrité']} %"
                 if précision["dernier_taux_intégrité"] is not None
                 else "—")
    col_4.metric("Sources actives",
                 f"{nb_actives} / {len(sources)}")

    bandeau_intégrité(précision["dernier_taux_intégrité"], seuils)

    # -- Historique des runs + statut des sources (deux colonnes) --------------
    col_runs, col_sources = st.columns([3, 2])

    with col_runs:
        st.subheader("Historique des runs")
        if rapidité["durées_par_run"]:
            st.altair_chart(
                graphique_durées(rapidité["durées_par_run"][:8], seuils),
                use_container_width=True,
            )
        else:
            st.info("Aucun run complet mesuré pour le moment.")
        st.caption(
            f"Coût estimé : {coût['temps_cpu_estimé_min']} min CPU "
            f"({coût['nb_requêtes_estimées']} requêtes HTTP estimées)"
        )

    with col_sources:
        st.subheader("Statut des sources")
        for source in sources[:6]:
            st.markdown(
                f"{ÉMOJI_STATUT[source['statut']]} "
                f"**{source['nom_domaine']}** : "
                f"{source['nb_publications']} publication(s)"
            )
        if len(sources) > 6:
            st.caption(f"+ {len(sources) - 6} autres sources : "
                       "voir la page Sources")

    # -- Répartition des classes -----------------------------------------------
    st.subheader("Répartition REAL / FAKE")
    st.altair_chart(
        graphique_répartition(précision["nb_real"], précision["nb_fake"]),
        use_container_width=True,
    )


# ##############################################################################
# PAGE 2 — RAPIDITÉ DU PIPELINE
# ##############################################################################
def page_rapidité(rapport: dict) -> None:
    """Durée des runs : moyenne, extrêmes, historique et détail."""
    st.title("Rapidité du pipeline")

    rapidité = rapport["rapidité"]
    seuils   = rapport["seuils"]
    durées   = rapidité["durées_par_run"]

    if not durées:
        st.info("Aucun run complet mesuré pour le moment.")
        return

    dernier     = durées[0]
    plus_rapide = min(durées, key=lambda d: d["durée_secondes"])
    écart       = round(
        dernier["durée_secondes"] - rapidité["durée_moyenne_s"], 1
    )

    col_1, col_2, col_3, col_4 = st.columns(4)
    col_1.metric("Durée moyenne",
                 f"{rapidité['durée_moyenne_s']} s")
    col_2.metric("Dernier run",
                 f"{dernier['durée_secondes']:.1f} s",
                 delta       = f"{écart:+.1f} s vs moyenne",
                 delta_color = "inverse")
    col_3.metric("Run le plus rapide",
                 f"{plus_rapide['durée_secondes']:.1f} s")
    col_4.metric("Runs mesurés",
                 rapidité["nb_runs_mesurés"])

    st.subheader("Historique complet des runs")
    st.altair_chart(
        graphique_durées(durées, seuils),
        use_container_width=True,
    )

    # -- Détail tabulaire (lisible par un public non technique) ----------------
    st.subheader("Détail des runs récents")
    df_détail = pd.DataFrame(durées)
    colonnes  = {
        "run_id"         : "Run",
        "durée_secondes" : "Durée (s)",
        "nb_valides"     : "Publications valides",
    }
    df_détail = df_détail[list(colonnes.keys())].rename(columns=colonnes)
    st.dataframe(df_détail, use_container_width=True, hide_index=True)


# ##############################################################################
# PAGE 3 — COÛT ESTIMÉ (RESSOURCES)
# ##############################################################################
def page_coût(rapport: dict) -> None:
    """Coût en ressources : proxy documenté, jamais présenté en euros."""
    st.title("Coût estimé (ressources)")

    coût      = rapport["coût"]
    rapidité  = rapport["rapidité"]
    précision = rapport["précision"]

    nb_runs   = rapidité["nb_runs_mesurés"]
    nb_pubs   = précision["total_publications"]
    coût_run  = (
        round(coût["temps_cpu_estimé_min"] / nb_runs, 1) if nb_runs else 0.0
    )
    coût_pub  = (
        round(coût["temps_cpu_estimé_s"] / nb_pubs, 2) if nb_pubs else 0.0
    )

    col_1, col_2, col_3, col_4 = st.columns(4)
    col_1.metric("Requêtes HTTP estimées", coût["nb_requêtes_estimées"])
    col_2.metric("Temps CPU estimé", f"{coût['temps_cpu_estimé_min']} min")
    col_3.metric("Coût moyen / run",  f"{coût_run} min")
    col_4.metric("Coût / publication", f"{coût_pub} s")

    # -- Volume traité par run (proxy visuel du coût) --------------------------
    if rapidité["durées_par_run"]:
        st.subheader("Publications valides par run")
        st.altair_chart(
            graphique_valides_par_run(rapidité["durées_par_run"]),
            use_container_width=True,
        )

    st.info(
        "**Hypothèse de calcul** — une entrée extraite ≈ une requête "
        "HTTP (fetch RSS + éventuel fetch og:image). "
        f"Formule : {coût['hypothèse']}. Estimation volontairement "
        "prudente : elle surestime plutôt qu'elle ne sous-estime le "
        "coût réel — aucune facturation cloud sur ce projet."
    )


# ##############################################################################
# PAGE 4 — STATUT DES SOURCES (KPI le plus actionnable)
# ##############################################################################
def carte_source_html(source: dict) -> str:
    """Construit la carte HTML d'une source (liseré coloré par statut)."""
    couleur = COULEURS_STATUT[source["statut"]]
    âge     = (
        f"{source['âge_heures']} h"
        if source["âge_heures"] is not None else "jamais extraite"
    )
    return (
        f'<div class="carte-source" '
        f'style="border-left: 5px solid {couleur};">'
        f'<strong>{source["nom_domaine"]}</strong><br>'
        f'<span style="font-size:0.8rem; opacity:0.7;">'
        f'{source["type_source"]}</span><br>'
        f'{source["nb_publications"]} publication(s) · '
        f'fraîcheur : {âge}'
        f'</div>'
    )


# ------------------------------------------------------------------------------
def page_sources(rapport: dict) -> None:
    """Cartes de statut par source, triées rouge → orange → vert."""
    st.title("Statut des sources")

    sources = rapport["statut_sources"]
    seuils  = rapport["seuils"]

    if not sources:
        st.info("Aucune source enregistrée pour le moment.")
        return

    nb_rouge  = sum(1 for s in sources if s["statut"] == "rouge")
    nb_orange = sum(1 for s in sources if s["statut"] == "orange")
    nb_vert   = len(sources) - nb_rouge - nb_orange
    nb_pubs   = sum(s["nb_publications"] for s in sources)

    col_1, col_2, col_3, col_4 = st.columns(4)
    col_1.metric("Sources actives", f"{nb_vert + nb_orange} / {len(sources)}")
    col_2.metric("En alerte",  nb_orange)
    col_3.metric("Cassées",    nb_rouge)
    col_4.metric("Publications", nb_pubs)

    if nb_rouge:
        st.error(f"🔴 {nb_rouge} source(s) à 0 publication ou "
                 "jamais extraite(s)")
    if nb_orange:
        st.warning(f"⚠️ {nb_orange} source(s) muette(s) depuis plus de "
                   f"{seuils['fraîcheur_heures']} heures")
    if not nb_rouge and not nb_orange:
        st.success("✅ Toutes les sources sont fraîches et productives.")

    # -- Grille de cartes (3 par rangée, ordre de criticité conservé) ----------
    for début in range(0, len(sources), 3):
        colonnes = st.columns(3)
        rangée   = sources[début:début + 3]
        for colonne, source in zip(colonnes, rangée):
            colonne.markdown(
                carte_source_html(source), unsafe_allow_html=True
            )


# ##############################################################################
# POINT D'ENTRÉE — navigation latérale et routage des pages
# ##############################################################################
def main() -> None:
    """Assemble le menu latéral et route vers la page sélectionnée."""
    st.set_page_config(
        page_title            = "CheckIt.AI — Monitoring ETL",
        page_icon             = "📰",
        layout                = "wide",
        initial_sidebar_state = "expanded",
    )
    injecter_style()
    afficher_entête_sidebar()

    page = st.sidebar.radio("Navigation", PAGES, label_visibility="collapsed")

    st.sidebar.divider()
    if st.sidebar.button("🔄 Rafraîchir les données"):
        st.cache_resource.clear()
        st.rerun()

    service = construire_service()
    rapport = service.générer_rapport_complet()

    # -- Routage : une fonction de rendu par entrée du menu --------------------
    routes = {
        "Vue d'ensemble" : page_vue_densemble,
        "Rapidité"       : page_rapidité,
        "Coût"           : page_coût,
        "Sources"        : page_sources,
    }
    routes[page](rapport)

    # st.sidebar.caption(
    #     f"Livrable L6 — rapport généré le "
    #     f"{rapport['généré_le'][:16].replace('T', ' ')} UTC"
    # )


if __name__ == "__main__":
    main()
