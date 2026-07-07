# ==============================================================================
# src/application/monitoring_service.py — Service de calcul des KPIs (L6/L7)
#
# Règle absolue (architecture hexagonale) : ce fichier n'importe JAMAIS
# streamlit, ni aucune bibliothèque de visualisation. Il calcule des KPIs
# à partir du contrat PersistencePort et retourne des dictionnaires/listes
# purs — n'importe quel adaptateur de présentation (Streamlit, Grafana,
# API REST, export PDF...) peut les consommer sans modification ici.
#
# Trois familles de KPI, conformes à la mission (Étape 5) :
#   - PRÉCISION : taux d'intégrité, répartition REAL/FAKE
#   - RAPIDITÉ  : durée par run, durée moyenne, tendance
#   - COÛT      : requêtes HTTP consommées (proxy), temps CPU cumulé
#
# Statut par source (vert/orange/rouge) : détecte les sources tombées à
# zéro publication ou dont la fraîcheur dépasse le seuil — c'est le KPI
# le plus utile en exploitation (voir plan de monitoring, L7).
# ==============================================================================

# --- Bibliothèque standard : dates et types ------------------------------------
from   datetime import datetime, timezone  # Calcul de fraîcheur et durées
from   typing   import Dict, List          # Annotations de types

# --- Port consommé : contrat de persistance défini par le domaine -------------
from   src.ports.outbound.persistence_port import PersistencePort


# ==============================================================================
# CONFIGURATION — seuils d'alerte par défaut (repris du plan de monitoring L7)
# ==============================================================================
SEUIL_INTÉGRITÉ_CRITIQUE     = 70.0   # %  — taux d'intégrité < seuil = rouge
SEUIL_INTÉGRITÉ_AVERTISSEMENT = 85.0  # %  — en dessous = orange
SEUIL_FRAÎCHEUR_HEURES        = 48    # h  — source muette au-delà = alerte
TEMPS_MOYEN_PAR_REQUÊTE_S     = 1.2   # s  — proxy de coût (délai de politesse)


# ##############################################################################
# CLASSE : MonitoringService
# ##############################################################################
class MonitoringService:
    """
    Calcule les indicateurs de performance du pipeline ETL CheckIt.AI.

    Paramètres
    ----------
    persistence : PersistencePort
        Adaptateur de persistance INJECTÉ (PostgresqlAdapter en
        production). Ce service ignore la technologie de stockage.
    seuil_intégrité_critique : float
        Taux d'intégrité (%) en dessous duquel un run est classé rouge.
    seuil_fraîcheur_heures : int
        Ancienneté (heures) au-delà de laquelle une source est
        considérée muette (alerte).

    Utilisation
    -----------
    service  = MonitoringService(persistence=PostgresqlAdapter(...))
    rapport  = service.générer_rapport_complet()
    """

    # ##########################################################################
    def __init__(
        self,
        persistence              : PersistencePort,
        seuil_intégrité_critique : float = SEUIL_INTÉGRITÉ_CRITIQUE,
        seuil_fraîcheur_heures   : int   = SEUIL_FRAÎCHEUR_HEURES,
    ) -> None:
        self._persistence     = persistence               # Port injecté
        self._seuil_critique  = seuil_intégrité_critique   # % — alerte rouge
        self._seuil_fraîcheur = seuil_fraîcheur_heures     # h — source muette

    # ##########################################################################
    # KPI FAMILLE 1 — PRÉCISION DES DONNÉES
    # ##########################################################################
    def calculer_précision(self) -> dict:
        """
        Précision globale du dataset : répartition REAL/FAKE et taux
        d'intégrité du dernier run (proportion d'entrées valides).
        """
        labels    = self._persistence.compter_par_label()
        total     = sum(labels.values())
        runs      = self._persistence.obtenir_runs(limite=1)
        dernier   = runs[0] if runs else None

        return {
            "total_publications" : total,
            "nb_real"            : labels.get("REAL", 0),
            "nb_fake"             : labels.get("FAKE", 0),
            "ratio_real_pct"     : (
                round(labels.get("REAL", 0) / total * 100, 1)
                if total else 0.0
            ),
            "dernier_taux_intégrité" : (
                dernier["taux_intégrité"] if dernier else None
            ),
            "dernier_run_id"     : dernier["run_id"] if dernier else None,
        }

    # ##########################################################################
    # KPI FAMILLE 2 — RAPIDITÉ (temps par tâche / par run)
    # ##########################################################################
    def calculer_rapidité(self, limite_runs: int = 20) -> dict:
        """
        Durée de chaque run et moyenne mobile — détecte un
        ralentissement progressif du pipeline (source lente, quota...).
        """
        runs      = self._persistence.obtenir_runs(limite=limite_runs)
        durées    = []

        for run in runs:
            début = run.get("started_at")
            fin   = run.get("finished_at")
            if début and fin:
                durées.append({
                    "run_id"        : run["run_id"],
                    "durée_secondes": (fin - début).total_seconds(),
                    "nb_valides"    : run["nb_valides"],
                })

        moyenne = (
            round(sum(d["durée_secondes"] for d in durées) / len(durées), 1)
            if durées else 0.0
        )
        return {
            "durées_par_run"       : durées,
            "durée_moyenne_s"      : moyenne,
            "nb_runs_mesurés"      : len(durées),
        }

    # ##########################################################################
    # KPI FAMILLE 3 — COÛT (ressources consommées)
    # ##########################################################################
    def calculer_coût(self, limite_runs: int = 20) -> dict:
        """
        Estimation du coût en ressources (proxy, pas de facturation
        cloud sur ce projet) : nombre de requêtes HTTP émises et temps
        CPU cumulé, dérivés du volume extrait et du délai de politesse.

        Hypothèse documentée : une entrée extraite ≈ une requête HTTP
        (fetch RSS + éventuel fetch og:image). Volontairement prudent
        (surestime plutôt que sous-estime le coût réel).
        """
        runs           = self._persistence.obtenir_runs(limite=limite_runs)
        nb_extraites   = sum(run["nb_extraites"] for run in runs)
        temps_estimé_s = round(nb_extraites * TEMPS_MOYEN_PAR_REQUÊTE_S, 1)

        return {
            "nb_requêtes_estimées" : nb_extraites,
            "temps_cpu_estimé_s"   : temps_estimé_s,
            "temps_cpu_estimé_min" : round(temps_estimé_s / 60, 1),
            "hypothèse"            : (
                f"{TEMPS_MOYEN_PAR_REQUÊTE_S}s / entrée extraite "
                "(délai de politesse HTTP)"
            ),
        }

    # ##########################################################################
    # KPI PAR SOURCE — statut vert / orange / rouge
    # ##########################################################################
    def calculer_statut_sources(self) -> List[dict]:
        """
        État de chaque source avec un statut de surveillance :
          - rouge  : 0 publication ou jamais extraite
          - orange : dernière extraction plus ancienne que le seuil
          - vert   : fraîche et productive

        C'est le KPI le plus actionnable du tableau de bord — il
        remplace la lecture manuelle des logs pour détecter une
        source cassée (cf. plan de monitoring, L7).
        """
        sources     = self._persistence.obtenir_sources()
        maintenant  = datetime.now(timezone.utc)
        résultat    = []

        for source in sources:
            dernière = source.get("dernière_extraction")
            if dernière is not None and dernière.tzinfo is None:
                dernière = dernière.replace(tzinfo=timezone.utc)

            âge_heures = (
                (maintenant - dernière).total_seconds() / 3600
                if dernière else None
            )

            # -- Détermination du statut ----------------------------------------
            muette   = âge_heures is not None and âge_heures > self._seuil_fraîcheur
            if source["nb_publications"] == 0 or dernière is None:
                statut = "rouge"
            elif muette:
                statut = "orange"
            else:
                statut = "vert"

            résultat.append({
                "nom_domaine"     : source["nom_domaine"],
                "type_source"     : source["type_source"],
                "nb_publications" : source["nb_publications"],
                "âge_heures"      : (
                    round(âge_heures, 1) if âge_heures is not None else None
                ),
                "statut"          : statut,
            })

        # Sources en alerte en premier (visibilité immédiate au dashboard)
        ordre = {"rouge": 0, "orange": 1, "vert": 2}
        résultat.sort(key=lambda s: ordre[s["statut"]])
        return résultat

    # ##########################################################################
    # RAPPORT COMPLET — agrège les trois familles de KPI + statut sources
    # ##########################################################################
    def générer_rapport_complet(self) -> dict:
        """
        Point d'entrée unique pour un adaptateur de présentation :
        un seul appel retourne tout ce qu'il faut afficher.
        """
        return {
            "généré_le"       : datetime.now(timezone.utc).isoformat(),
            "précision"       : self.calculer_précision(),
            "rapidité"        : self.calculer_rapidité(),
            "coût"            : self.calculer_coût(),
            "statut_sources"  : self.calculer_statut_sources(),
            "seuils"          : {
                "intégrité_critique"      : self._seuil_critique,
                "intégrité_avertissement" : SEUIL_INTÉGRITÉ_AVERTISSEMENT,
                "fraîcheur_heures"        : self._seuil_fraîcheur,
            },
        }
