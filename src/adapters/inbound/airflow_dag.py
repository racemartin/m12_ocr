# ==============================================================================
# src/adapters/inbound/airflow_dag.py — Flux ETL Airflow (Étape 4)
#
# Livrable L5 : DAG Apache Airflow orchestrant le pipeline ETL CheckIt.AI.
#
# Place dans l'architecture hexagonale — ADAPTATEUR INBOUND MINCE :
#   - Le DAG ne connaît QUE le contrat OrchestreurPort (couche PORTS),
#     implémenté par PipelineService (couche APPLICATION).
#   - Chaque tâche Airflow délègue à UNE méthode du port :
#       extraction       → exécuter_extraction()
#       validation_brute → exécuter_validation(chemin)
#       transformation   → exécuter_transformation()
#       chargement       → exécuter_chargement(chemin)
#       notification     → exécuter_notification(insérées)
#   - Ce qui reste ici est UNIQUEMENT technique et propre à Airflow :
#     lecture des Variables, plomberie XCom, planification, retries.
#     Demain, un cron ou une API remplacerait ce fichier sans toucher
#     ni au port, ni au service, ni au domaine.
#
# Prérequis d'exécution (cf. docs/guide_airflow.md) :
#   - dags_folder pointant vers ce fichier (lien symbolique)
#   - PYTHONPATH incluant la racine du projet
#   - Variables Airflow : checkit_pg_* (connexion PostgreSQL)
# ==============================================================================

# --- Bibliothèque standard : dates et chemin projet ----------------------------
import sys                                 # Injection de la racine projet

from   datetime import datetime, timedelta # Planification et retries
from   pathlib  import Path                # Chemins portables

# --- Racine du projet : indispensable AVANT les imports src.* ------------------
# Airflow importe ce fichier depuis son dags_folder : le paquet src n'est
# pas visible sans ajouter explicitement la racine du projet au sys.path.
RACINE_PROJET = Path("/mnt/c/Users/Public/IAE_DELL/pra_dell/m12_ocr")
if str(RACINE_PROJET) not in sys.path:
    sys.path.insert(0, str(RACINE_PROJET))

# --- Apache Airflow : DAG, opérateur Python et Variables ------------------------
from   airflow                   import DAG
from   airflow.models            import Variable
from   airflow.operators.python  import PythonOperator

# --- Couches du projet : le port, son implémentation et la persistance ----------
from   src.adapters.outbound.persistence.postgresql_adapter import (
    PostgresqlAdapter,                     # Adaptateur de persistance
)
from   src.application.pipeline_service     import PipelineService
from   src.ports.inbound.orchestrateur_port import OrchestreurPort


# ##############################################################################
# FABRIQUE DU SERVICE — configuration technique injectée par l'adaptateur
# ##############################################################################
def _construire_orchestrateur() -> OrchestreurPort:
    """
    Construit le PipelineService avec la configuration lue des
    Variables Airflow.

    C'est ICI (et seulement ici) que le monde Airflow rencontre la
    couche application : le PostgresqlAdapter est construit avec les
    credentials des Variables puis INJECTÉ — ni le service ni le
    domaine n'importent jamais airflow ou psycopg2.
    """
    persistance = PostgresqlAdapter(config={
        "host"     : Variable.get("checkit_pg_host", default_var="localhost"),
        "port"     : Variable.get("checkit_pg_port", default_var="5432"),
        "dbname"   : Variable.get("checkit_pg_db",   default_var="checkit"),
        "user"     : Variable.get("checkit_pg_user", default_var="checkit"),
        "password" : Variable.get("checkit_pg_password"),
    })
    vérifier = Variable.get(
        "checkit_verifier_images", default_var="False"
    ).lower() == "true"

    return PipelineService(
        racine_projet   = RACINE_PROJET,
        persistence     = persistance,
        vérifier_images = vérifier,
    )


# ##############################################################################
# ENVELOPPES DES TÂCHES — une tâche = un appel au contrat du port
# ##############################################################################
# La seule responsabilité de ces fonctions est la plomberie XCom
# (mécanisme propre à Airflow) : récupérer/transmettre les chemins et
# compteurs entre tâches. Toute la logique vit dans PipelineService.

def tâche_extraction(**contexte) -> str:
    """extraction → OrchestreurPort.exécuter_extraction()"""
    return _construire_orchestrateur().exécuter_extraction()   # → XCom


def tâche_validation_brute(**contexte) -> int:
    """validation_brute → OrchestreurPort.exécuter_validation()"""
    chemin = contexte["ti"].xcom_pull(task_ids="extraction")
    return _construire_orchestrateur().exécuter_validation(chemin)


def tâche_transformation(**contexte) -> str:
    """transformation → OrchestreurPort.exécuter_transformation()"""
    return _construire_orchestrateur().exécuter_transformation()


def tâche_chargement(**contexte) -> int:
    """chargement → OrchestreurPort.exécuter_chargement()"""
    chemin = contexte["ti"].xcom_pull(task_ids="transformation")
    return _construire_orchestrateur().exécuter_chargement(chemin)


def tâche_notification(**contexte) -> None:
    """notification → OrchestreurPort.exécuter_notification()"""
    insérées = contexte["ti"].xcom_pull(task_ids="chargement")
    _construire_orchestrateur().exécuter_notification(insérées)


# ==============================================================================
# DÉFINITION DU DAG — planification, retries et chaînage des tâches
# ==============================================================================
paramètres_défaut = {
    "owner"                     : "rafael",
    "retries"                   : 3,        # 3 tentatives sur échec
    "retry_delay"               : timedelta(minutes=2),
    "retry_exponential_backoff" : True,     # Délai croissant entre essais
    "execution_timeout"         : timedelta(minutes=30),
}

with DAG(
    dag_id       = "checkit_etl",
    description  = "ETL multimodal CheckIt.AI — fake news detector",
    default_args = paramètres_défaut,
    schedule     = "@daily",                # Un run quotidien planifié
    start_date   = datetime(2026, 7, 1),
    catchup      = False,                   # Pas de rattrapage historique
    tags         = ["checkit", "etl", "multimodal"],
) as dag:

    # -- Déclaration des 5 tâches atomiques -------------------------------------
    extraction = PythonOperator(
        task_id         = "extraction",
        python_callable = tâche_extraction,
    )
    validation = PythonOperator(
        task_id         = "validation_brute",
        python_callable = tâche_validation_brute,
    )
    transformation = PythonOperator(
        task_id         = "transformation",
        python_callable = tâche_transformation,
    )
    chargement = PythonOperator(
        task_id         = "chargement",
        python_callable = tâche_chargement,
    )
    notification = PythonOperator(
        task_id         = "notification",
        python_callable = tâche_notification,
    )

    # -- Chaînage séquentiel : E → V → T → L → N ---------------------------------
    extraction >> validation >> transformation >> chargement >> notification
