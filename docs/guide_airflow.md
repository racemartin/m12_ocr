# Guide Quick Step — Apache Airflow pour CheckIt.AI (Étape 4)

> **Objectif** : partir de votre installation actuelle (login admin fait,
> rien d'autre) et arriver à un DAG `checkit_etl` exécuté avec preuves
> (logs + captures d'écran) pour le livrable L5.
>
> Environnement cible : WSL2 Ubuntu 24.04 · Python 3.12 · Airflow 2.10.5
> · projet dans `/mnt/c/Users/Public/IAE_DELL/pra_dell/m12_ocr/`

---

## 1. Principe de fonctionnement d'Airflow

Airflow est un **orchestrateur** : il ne transforme pas les données
lui-même, il **déclenche, ordonne, surveille et rejoue** des tâches
écrites en Python. Quatre composants coopèrent :

| Composant | Rôle |
|---|---|
| **Webserver** | Interface web (port 8080) : visualiser, déclencher, lire les logs |
| **Scheduler** | Le cœur : scanne le `dags_folder`, planifie et lance les tâches dues |
| **Base de métadonnées** | SQLite par défaut : état de chaque tâche, historique des runs |
| **Executor** | Exécute réellement les tâches (SequentialExecutor en local) |

Les concepts clés :

- **DAG** (Directed Acyclic Graph) : un fichier Python déclarant des
  tâches et leurs dépendances (`A >> B` = "B après A"). Pas de cycle
  possible — le flux va toujours vers l'avant.
- **Tâche / Operator** : l'unité atomique. Nous utilisons uniquement
  `PythonOperator` (une fonction Python = une tâche), le plus simple,
  comme exigé par la mission.
- **DAG Run** : une exécution datée du DAG (planifiée `@daily` ou
  déclenchée à la main).
- **XCom** : petit canal de communication entre tâches. **Règle d'or** :
  on n'y passe que des chemins de fichiers, jamais les données
  (limité à ~48 Ko).
- **Variables** : paires clé/valeur stockées dans Airflow — c'est là
  que vivent nos credentials PostgreSQL (jamais en dur dans le code).

Cycle de vie d'une tâche : `scheduled → queued → running → success`
(ou `failed → up_for_retry` selon les `retries` configurés).

## 2. Notre adaptation — Airflow dans l'architecture hexagonale

Le DAG est un **adaptateur inbound** : Airflow est un déclencheur
technique interchangeable (demain, un cron ou une API ferait le même
travail sans toucher au domaine). Le fichier
`src/adapters/inbound/airflow_dag.py` :

1. n'implémente **aucune logique métier** ;
2. invoque les adaptateurs outbound (`FeedparserAdapter`) et le service
   d'application (`TransformService`) ;
3. chaîne cinq tâches atomiques :

```
extraction >> validation_brute >> transformation >> chargement >> notification
```

| Tâche | Couche invoquée | Sortie (XCom) |
|---|---|---|
| `extraction` | Adaptateurs scrapers (7 sources RSS) | chemin du JSON brut |
| `validation_brute` | Contrôle d'intégrité du lot | nb d'entrées |
| `transformation` | `TransformService` (Étape 3) | chemin du JSON propre |
| `chargement` | PostgreSQL (INSERT idempotent) | nb insérées |
| `notification` | Rapport final dans les logs | — |

## 3. Configuration pas à pas

### 3.1 Localiser AIRFLOW_HOME et le dags_folder

```bash
# Où Airflow s'est installé (défaut : ~/airflow)
echo $AIRFLOW_HOME          # vide = ~/airflow
ls ~/airflow                # airflow.cfg, airflow.db, logs/
```

Ouvrir `~/airflow/airflow.cfg` et vérifier la ligne `dags_folder` :

```ini
[core]
dags_folder = /home/rafael/airflow/dags
```

### 3.2 Rendre le DAG visible — le lien symbolique

Plutôt que copier le fichier (risque de versions divergentes), on
crée un lien symbolique du dossier dags vers l'adaptateur du projet :

```bash
mkdir -p ~/airflow/dags
ln -sf /mnt/c/Users/Public/IAE_DELL/pra_dell/m12_ocr/src/adapters/inbound/airflow_dag.py \
       ~/airflow/dags/airflow_dag.py
```

> Le fichier reste dans le projet (versionné Git), Airflow le voit
> à travers le lien. Toute modification est prise en compte au
> prochain scan (~30 s à 5 min selon `dag_dir_list_interval`).

### 3.3 Le PYTHONPATH — l'erreur classique

Le DAG importe `src.application...` : le scheduler doit connaître la
racine du projet. Le DAG contient déjà un `sys.path.insert` de
sécurité, mais ajoutez aussi la variable d'environnement :

```bash
echo 'export PYTHONPATH="/mnt/c/Users/Public/IAE_DELL/pra_dell/m12_ocr:$PYTHONPATH"' >> ~/.bashrc
source ~/.bashrc
```

### 3.4 Dépendances dans l'environnement d'Airflow

Airflow exécute les tâches avec SON interpréteur : les paquets du
projet doivent y être visibles. Depuis l'environnement où Airflow
est installé :

```bash
uv pip install feedparser requests psycopg2-binary
```

### 3.5 Les Variables Airflow (credentials PostgreSQL)

Interface web → **Admin → Variables → +** , ou en ligne de commande :

```bash
airflow variables set checkit_pg_host      localhost
airflow variables set checkit_pg_port      5432
airflow variables set checkit_pg_db        checkit
airflow variables set checkit_pg_user      checkit
airflow variables set checkit_pg_password  '<votre_mot_de_passe>'
airflow variables set checkit_verifier_images False
```

> **Sécurité (point de vigilance L5)** : les credentials vivent dans
> la base de métadonnées d'Airflow, pas dans le code. Toute clé dont
> le nom contient `password` est automatiquement masquée dans l'UI.

### 3.6 Préparer PostgreSQL

```bash
sudo service postgresql start
sudo -u postgres psql -c "CREATE USER checkit WITH PASSWORD '<votre_mot_de_passe>';"
sudo -u postgres psql -c "CREATE DATABASE checkit OWNER checkit;"
```

La table `publications` est créée par la tâche `chargement`
elle-même (`CREATE TABLE IF NOT EXISTS`) — rien d'autre à faire.

### 3.7 Démarrer Airflow

Deux terminaux WSL (ou `airflow standalone` qui lance tout) :

```bash
# Terminal 1
airflow scheduler
# Terminal 2
airflow webserver --port 8080
```

Puis http://localhost:8080 avec votre login admin.

## 4. Vérifier, tester, exécuter

### 4.1 Le DAG est-il détecté ?

```bash
airflow dags list | grep checkit
airflow dags list-import-errors        # DOIT être vide
```

Si `checkit_etl` n'apparaît pas → §6 Dépannage.

### 4.2 Tester chaque tâche isolément (sans scheduler)

C'est LA commande d'apprentissage — elle exécute une tâche seule,
dans votre terminal, sans toucher à la base de métadonnées :

```bash
airflow tasks test checkit_etl extraction       2026-07-03
airflow tasks test checkit_etl validation_brute 2026-07-03
airflow tasks test checkit_etl transformation   2026-07-03
airflow tasks test checkit_etl chargement       2026-07-03
airflow tasks test checkit_etl notification     2026-07-03
```

### 4.3 Exécuter le DAG complet

Dans l'UI : activer l'interrupteur du DAG (à gauche du nom), puis
bouton **▶ Trigger DAG**. Ou en CLI :

```bash
airflow dags trigger checkit_etl
```

Suivre l'exécution dans l'onglet **Grid** : chaque carré passe de
vert clair (running) à vert foncé (success).

## 5. Preuves d'exécution pour le livrable L5

Capturer (Windows : `Win+Maj+S`) :

1. **Vue Grid** : les 5 tâches en vert (succès du run)
2. **Vue Graph** : le chaînage extraction → ... → notification
3. **Log de `notification`** : clic sur le carré → Logs → le
   "RAPPORT ETL — CHECKIT.AI" avec les compteurs
4. La table remplie :

```bash
sudo -u postgres psql -d checkit \
  -c "SELECT declared_label, COUNT(*) FROM publications GROUP BY 1;"
```

## 6. Dépannage express

| Symptôme | Cause probable | Remède |
|---|---|---|
| DAG absent de l'UI | scan pas encore passé | attendre 30 s–5 min ou redémarrer le scheduler |
| DAG absent + import error | `ModuleNotFoundError: src` | §3.3 PYTHONPATH, puis `airflow dags list-import-errors` |
| `psycopg2` introuvable | paquet absent de l'env Airflow | §3.4 |
| Tâche `chargement` échoue | PostgreSQL arrêté / Variables absentes | §3.5, §3.6 |
| Tâches lentes (>5 min) | `checkit_verifier_images=True` | mettre `False` pour les démos |
| Fuseau horaire décalé | Airflow travaille en UTC | normal — noté pour la démo au mentor |

---

*CheckIt.AI — Étape 4 · Guide rédigé pour accompagner le livrable L5*
