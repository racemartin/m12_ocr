# =============================================================================
# src/tools/rafael/log_tool.py — Outil de journalisation colorée en console
#
# Équivalent Python du LogTool.php (RFC 5424 — The Syslog Protocol)
#
# Niveaux de log :
#   1  EMERGENCY  : le système est inutilisable
#   2  ALERT      : une action immédiate est requise
#   3  CRITICAL   : conditions critiques
#   4  ERROR      : conditions d'erreur
#   5  WARNING    : conditions d'avertissement           (PRODUCTION)
#   6  NOTICE     : condition normale mais significative (PRODUCTION)
#   7  INFO        : messages informatifs                (DÉVELOPPEMENT)
#   8  DEBUG       : messages de débogage               (DÉVELOPPEMENT DEBUG)
#
# Configuration via variable d'environnement :
#   LOG_LEVEL=8   → affiche tous les niveaux
#   LOG_LEVEL=5   → affiche uniquement WARNING et au-dessus
#
# Utilisation :
#   from src.tools.rafael.log_tool import LogTool
#   log = LogTool()
#   log.LEVEL_7_INFO("MonModule", "Message informatif")
#   log.STEP(1, "Étape 1", "début du traitement")
#   log.PARAMETER_VALUE("clé", "valeur")
#   -----
#   from src.tools.rafael.log_tool import LogTool
#   log = LogTool(origin="mon_module")
#   log.START_ACTION("MonService", "traiter", "début du traitement")
#   log.PARAMETER_VALUE("fichier", "data.csv")
#   log.LEVEL_7_INFO("MonService", "chargement terminé")
#   log.FINISH_ACTION("MonService", "traiter", "OK")
# =============================================================================

# --- Bibliothèques standard ---------------------------------------------------
import json     # Sérialisation des objets pour LOG_DICT et DUMP_VARIABLE
import os       # Lecture des variables d'environnement (LOG_LEVEL)
import sys      # Écriture sur stderr (équivalent de error_log PHP)
import time     # Mesure du temps d'exécution pour START/FINISH_ACTION
from   pathlib import Path  # Manipulation des chemins pour update_env_log_level
from datetime import datetime

# =============================================================================
# CLASSE : LogTool
# =============================================================================
class LogTool:
    """
    Outil de journalisation colorée en console, conforme RFC 5424.

    Chaque méthode publique correspond à son équivalent PHP.
    Le niveau de log est lu depuis la variable d'environnement LOG_LEVEL.
    Toutes les sorties vont sur stderr (comme error_log() en PHP).

    Attributs de classe
    -------------------
    ACTIF : bool
        Active ou désactive globalement toutes les sorties de log.
    _log_level : int
        Niveau de log actif (1–8). Lu depuis LOG_LEVEL dans l'environnement.
    """

    # -- Codes de couleur ANSI ------------------------------------------------
    _COLOR_WHITE                = "\033[97m"
    _COLOR_BOLD                 = "\033[1m"
    _COLOR_0_BRIGHT_RED         = "\033[1;31m"
    _COLOR_1_BRIGHT_YELLOW      = "\033[1;33m"
    _COLOR_2_RED                = "\033[31m"
    _COLOR_3_RED                = "\033[31m"
    _COLOR_4_YELLOW             = "\033[33m"
    _COLOR_5_CYAN               = "\033[36m"
    _COLOR_6_GREEN              = "\033[32m"
    _COLOR_7_MAGENTA            = "\033[35m"
    _COLOR_RESET                = "\033[0m"
    _COLOR_GREY                 = "\033[90m"
    _COLOR_WHITE_ON_RED         = "\033[37;41m"   # Blanc sur fond rouge
    _COLOR_YELLOW_ON_RED        = "\033[33;41m"
    _COLOR_BRIGHT_YELLOW_ON_RED = "\033[93;41m"   # Jaune vif sur fond rouge
    _COLOR_BROWNLIGHT           = "\033[38;5;180m" # Marron clair
    _COLOR_BLACK_ON_GREEN       = "\033[30;42m"   # Texte noir sur fond vert

    ACTIF      = True
    _log_level = 8  # Valeur par défaut : tous les niveaux affichés

    # -------------------------------------------------------------------------
    def __init__(self, origin: str = "command") -> None:
        """
        Initialise l'outil de log.

        Paramètres
        ----------
        origin : str
            Préfixe affiché entre crochets dans chaque ligne de log.
            Ex. : "command", "api", "worker".
        """
        # -- Lecture du niveau de log depuis l'environnement -----------------
        env_level = os.environ.get("LOG_LEVEL")
        if env_level is not None:
            try:
                LogTool._log_level = int(env_level)
            except ValueError:
                pass  # Valeur invalide → on conserve la valeur par défaut

        self._origin          = origin      # Préfixe affiché dans les logs
        self._timestart       = None        # Horodatage de début (START_ACTION)
        self._animation       = ['|', '/', '-', '\\', '|', '/', '-', '\\', '|']
        self._animation_index = 0
        self._progress_width  = 50          # Largeur de la barre de progression
        self._progress_char   = '='         # Caractère de remplissage
        self._total_items     = 0           # Nombre total d'éléments
        self._processed_items = 0           # Éléments déjà traités


    # ##########################################################################
    # MÉTHODES DE CONFIGURATION
    # ##########################################################################

    # =========================================================================
    def update_env_log_level(self, project_dir: str, input_value: str) -> bool:
        """
        Met à jour la valeur de LOG_LEVEL dans le fichier .env du projet.

        Paramètres
        ----------
        project_dir : str
            Répertoire racine du projet (contenant le fichier .env).
        input_value : str
            Nom du niveau de log à définir
            (ex. : "DEBUG", "INFO", "WARNING"…).

        Retourne
        --------
        bool
            True si la mise à jour a réussi.

        Lève
        ----
        ValueError
            Si input_value n'est pas un nom de niveau valide.
        IOError
            Si le fichier .env ne peut pas être lu ou écrit.
        """
        # -- Correspondance nom → valeur numérique RFC 5424 ------------------
        log_levels = {
            "EMERGENCY" : 1,
            "ALERT"     : 2,
            "CRITICAL"  : 3,
            "ERROR"     : 4,
            "WARNING"   : 5,
            "NOTICE"    : 6,
            "INFO"      : 7,
            "DEBUG"     : 8,
        }

        # -- Validation de la valeur fournie ---------------------------------
        if input_value not in log_levels:
            self.STEP(1, "Valeurs possibles de LOG_LEVEL :")
            for level, code in log_levels.items():
                self.PARAMETER_VALUE(str(code), level)
            raise ValueError(
                f"Valeur invalide : '{input_value}'. "
                f"Valeurs acceptées : {', '.join(log_levels.keys())}"
            )

        new_value  = log_levels[input_value]
        key        = "LOG_LEVEL"
        env_file   = Path(project_dir) / ".env"

        # -- Lecture du fichier .env -----------------------------------------
        try:
            content = env_file.read_text(encoding="utf-8")
        except OSError as e:
            raise IOError(f"Impossible de lire le fichier .env : {e}") from e

        # -- Remplacement ou ajout de la ligne LOG_LEVEL ---------------------
        lines   = content.splitlines()
        updated = False

        for i, line in enumerate(lines):
            if line.startswith(key + "="):
                lines[i] = f"{key}={new_value}"
                updated  = True
                break

        if not updated:
            lines.append(f"{key}={new_value}")   # Ajout si absent

        # -- Sauvegarde du fichier .env --------------------------------------
        try:
            env_file.write_text("\n".join(lines), encoding="utf-8")
        except OSError as e:
            raise IOError(f"Impossible d'écrire dans le fichier .env : {e}") from e

        # -- Affichage du résultat -------------------------------------------
        self.STEP(1, "Valeurs possibles de LOG_LEVEL :")
        for level, code in log_levels.items():
            self.PARAMETER_VALUE(str(code), level)

        self.PARAMETER_VALUE(
            "LOG_LEVEL mis à jour",
            f"{new_value} ({input_value})",
        )
        return True


    # ##########################################################################
    # BARRE DE PROGRESSION
    # ##########################################################################

    # =========================================================================
    def progressStart(self, total_items: int) -> None:
        """
        Initialise la barre de progression.

        Paramètres
        ----------
        total_items : int
            Nombre total d'éléments à traiter.
        """
        self._processed_items = 0
        self._total_items     = total_items

    # =========================================================================
    def progressAdvance(self, processed: int, message: str) -> None:
        """
        Met à jour la barre de progression sur la même ligne (\\r).

        Paramètres
        ----------
        processed : int
            Nombre d'éléments traités jusqu'à présent.
        message : str
            Message court affiché à la fin de la barre.
        """
        pct        = round(processed / self._total_items * 100) if self._total_items else 0
        bar_length = round(pct / 100 * self._progress_width)

        self._animation_index = (self._animation_index + 1) % len(self._animation)
        anim_char  = self._animation[self._animation_index]
        bar        = self._progress_char * bar_length

        line = (
            f"\r {anim_char} [{bar:<{self._progress_width}}] "
            f"{pct:3d}% ({processed}/{self._total_items})"
            f"[{message}]" + " " * 50
        )
        sys.stderr.write(line)
        sys.stderr.flush()

    # =========================================================================
    def progressAdvanceNewLine(self, processed: int, message: str) -> None:
        """Met à jour la barre de progression et passe à la ligne suivante."""
        self.progressAdvance(processed, message)
        sys.stderr.write("\n")
        sys.stderr.flush()

    # =========================================================================
    def progressFinish(self) -> None:
        """Termine la barre de progression et remet les compteurs à zéro."""
        sys.stderr.write(f"[{self._origin}]\n\r")
        sys.stderr.flush()
        self._processed_items = 0
        self._total_items     = 0


    # ##########################################################################
    # NIVEAUX DE LOG RFC 5424
    # ##########################################################################

    # =========================================================================
    def LEVEL_1_EMERGENCY(self, where: str, message: str) -> None:
        """Niveau 1 — EMERGENCY : le système est inutilisable."""
        if not self.ACTIF or 1 > self._log_level:
            return
        label   = f"[{'EMERGENCY':<9}]"
        content = (
            self._COLOR_RESET + self._COLOR_WHITE + f" {where}" +
            self._COLOR_RESET + " " +
            self._COLOR_BRIGHT_YELLOW_ON_RED + message + self._COLOR_RESET
        )
        self._split_and_log(0, label + content, self._COLOR_BRIGHT_YELLOW_ON_RED)

    # =========================================================================
    def LEVEL_2_ALERT(self, where: str, message: str) -> None:
        """Niveau 2 — ALERT : une action immédiate est requise."""
        if not self.ACTIF or 2 > self._log_level:
            return
        label   = f"[{'ALERT':<9}]"
        content = (
            self._COLOR_RESET + self._COLOR_WHITE + f" {where}" +
            self._COLOR_RESET + " " +
            self._COLOR_BRIGHT_YELLOW_ON_RED + message + self._COLOR_RESET
        )
        self._split_and_log(1, label + content, self._COLOR_BRIGHT_YELLOW_ON_RED)

    # =========================================================================
    def LEVEL_3_CRITICAL(self, where: str, message: str) -> None:
        """Niveau 3 — CRITICAL : conditions critiques."""
        if not self.ACTIF or 3 > self._log_level:
            return
        label   = f"[{'CRITICAL':<9}]"
        content = (
            self._COLOR_RESET + self._COLOR_WHITE + f" {where}" +
            self._COLOR_RESET + " " +
            self._COLOR_WHITE_ON_RED + message + self._COLOR_RESET
        )
        self._split_and_log(2, label + content, self._COLOR_WHITE_ON_RED)

    # =========================================================================
    def LEVEL_4_ERROR(self, where: str, message: str) -> None:
        """Niveau 4 — ERROR : conditions d'erreur."""
        if not self.ACTIF or 4 > self._log_level:
            return
        label   = f"[{'ERROR':<9}]"
        content = (
            self._COLOR_RESET + self._COLOR_WHITE + f" {where}" +
            self._COLOR_RESET + " " +
            self._COLOR_WHITE_ON_RED + message + self._COLOR_RESET
        )
        self._split_and_log(3, label + content, self._COLOR_WHITE_ON_RED)

    # =========================================================================
    def LEVEL_5_WARNING(self, where: str, message: str) -> None:
        """Niveau 5 — WARNING : conditions d'avertissement."""
        if not self.ACTIF or 5 > self._log_level:
            return
        label   = f"           [{'WARNING':<9}]"
        content = (
            self._COLOR_RESET + self._COLOR_WHITE + f" {where}" +
            self._COLOR_RESET + " " +
            self._COLOR_4_YELLOW + message + self._COLOR_RESET
        )
        self._split_and_log(4, label + content, self._COLOR_4_YELLOW)

    # =========================================================================
    def LEVEL_6_NOTICE(self, where: str, message: str) -> None:
        """Niveau 6 — NOTICE : condition normale mais significative."""
        if not self.ACTIF or 6 > self._log_level:
            return
        label   = f"[{'NOTICE':<9}]"
        content = (
            self._COLOR_RESET + self._COLOR_WHITE + f" {where}" +
            self._COLOR_RESET + " " +
            self._COLOR_5_CYAN + message + self._COLOR_RESET
        )
        self._split_and_log(5, label + content, self._COLOR_5_CYAN)

    # =========================================================================
    def LEVEL_7_INFO(self, where: str, message: str) -> None:
        """Niveau 7 — INFO : messages informatifs."""
        if not self.ACTIF or 7 > self._log_level:
            return
        label   = f"[{'INFO':<9}]"
        content = (
            self._COLOR_RESET + self._COLOR_WHITE + f" {where}" +
            self._COLOR_RESET + " " +
            self._COLOR_BLACK_ON_GREEN + message + self._COLOR_RESET
        )
        #self._split_and_log(6, label + content, self._COLOR_BLACK_ON_GREEN)
        self._log( "           " + label + content, self._COLOR_BLACK_ON_GREEN)

    # =========================================================================
    def LEVEL_8_DEBUG(self, where: str, message: str) -> None:
        """Niveau 8 — DEBUG : messages de débogage."""
        if not self.ACTIF or 8 > self._log_level:
            return
        label   = f"[{'DEBUG':<9}]"
        content = (
            self._COLOR_RESET + self._COLOR_WHITE + f" {where}" +
            self._COLOR_RESET + " " +
            self._COLOR_7_MAGENTA + message + self._COLOR_RESET
        )
        self._split_and_log(7, label + content, self._COLOR_7_MAGENTA)


    # ##########################################################################
    # NIVEAUX INDENTÉ (flux d'appels imbriqués)
    # ##########################################################################

    # =========================================================================
    def START_INDETED_LEVEL(
        self,
        tab_size     : int,
        class_name   : str,
        function_name: str,
        information  : str,
    ) -> None:
        """
        Affiche le début d'un bloc indenté (entrée dans une fonction).   ┌

        Affichage conditionnel selon le niveau de log :
          - tab_size == 2 : affiché seulement si log_level >= 7
          - tab_size  > 2 : affiché seulement si log_level >= 8   
        """
        if not self.ACTIF:
            return
        if tab_size == 2 and self._log_level < 7:
            return
        if tab_size > 2 and self._log_level < 8:
            return

        prefix       = " " * tab_size + "┌["
        class_padded = (class_name + "]").ljust(36 - tab_size, ".") + ": ["
        func_padded  = (function_name + "] ").ljust(36, "-")

        self._error_log(
            f"{prefix}{class_padded}{func_padded} [{information}]"
        )

    # =========================================================================
    def FINISH_INDETED_LEVEL(
        self,
        tab_size     : int,
        class_name   : str,
        function_name: str,
        information  : str,
    ) -> None:
        """
        Affiche la fin d'un bloc indenté (sortie d'une fonction).  ╚ 

        Affichage conditionnel selon le niveau de log :
          - tab_size == 2 : affiché seulement si log_level >= 7
          - tab_size  > 2 : affiché seulement si log_level >= 8
        """
        if not self.ACTIF:
            return
        if tab_size == 2 and self._log_level < 7:
            return
        if tab_size > 2 and self._log_level < 8:
            return

        prefix       = " " * tab_size + "└["
        class_padded = (class_name + "]").ljust(36 - tab_size, ".") + ": ["
        func_padded  = (function_name + "] ").ljust(36, "-")

        self._error_log(
            f"{prefix}{class_padded}{func_padded} [{information}]"
        )


    # ##########################################################################
    # ACTIONS (niveau 1 — haut niveau)
    # ##########################################################################

    # =========================================================================
    def START_ACTION(
        self,
        class_name   : str,
        function_name: str,
        information  : str,
    ) -> None:
        """
        Marque le début d'une action et démarre le chronomètre.
        Correspond au niveau d'indentation 1 (plus haut niveau).
        """
        if not self.ACTIF:
            return
        self._timestart = time.perf_counter()

 
        line        = "#" * 38
        self._error_log(self._COLOR_BROWNLIGHT  + line + self._COLOR_RESET )
        
        self.START_INDETED_LEVEL(1, class_name, function_name, information)

    # =========================================================================
    def FINISH_ACTION(
        self,
        class_name   : str,
        function_name: str,
        information  : str,
    ) -> None:
        """
        Marque la fin d'une action et affiche le temps d'exécution.
        """
        if not self.ACTIF:
            return

        elapsed      = time.perf_counter() - (self._timestart or 0)
        hours, rem   = divmod(elapsed, 3600)
        minutes, sec = divmod(rem, 60)
        exec_time    = f"{int(hours):02d}:{int(minutes):02d}:{sec:09.6f}"

        self.FINISH_INDETED_LEVEL(
            1, class_name, function_name,
            f"{information} Exec: {exec_time}",
        )
        line        = "*" * 38
        self._error_log(self._COLOR_BROWNLIGHT  + line + self._COLOR_RESET )

    # =========================================================================
    def START_CALL_CONTROLLER_FUNCTION(
        self,
        class_name   : str,
        function_name: str,
        information  : str,
    ) -> None:
        """Marque le début d'un appel de fonction contrôleur (niveau 2)."""
        if not self.ACTIF:
            return
        self.START_INDETED_LEVEL(2, class_name, function_name, information)

    # =========================================================================
    def FINISH_CALL_CONTROLLER_FUNCTION(
        self,
        class_name   : str,
        function_name: str,
        information  : str,
    ) -> None:
        """Marque la fin d'un appel de fonction contrôleur (niveau 2)."""
        if not self.ACTIF:
            return
        self.FINISH_INDETED_LEVEL(2, class_name, function_name, information)

    # =========================================================================
    def START_CALL_MANAGER_FUNCTION(
        self,
        class_name   : str,
        function_name: str,
        information  : str,
    ) -> None:
        """Marque le début d'un appel de fonction manager (niveau 3)."""
        if not self.ACTIF:
            return
        self.START_INDETED_LEVEL(3, class_name, function_name, information)

    # =========================================================================
    def FINISH_CALL_MANAGER_FUNCTION(
        self,
        class_name   : str,
        function_name: str,
        information  : str,
    ) -> None:
        """Marque la fin d'un appel de fonction manager (niveau 3)."""
        if not self.ACTIF:
            return
        self.FINISH_INDETED_LEVEL(3, class_name, function_name, information)

    # =========================================================================
    def START_CALL_ENTITY_FUNCTION(
        self,
        class_name   : str,
        function_name: str,
        information  : str,
    ) -> None:
        """Marque le début d'un appel de fonction entité (niveau 4)."""
        if not self.ACTIF:
            return
        self.START_INDETED_LEVEL(4, class_name, function_name, information)

    # =========================================================================
    def FINISH_CALL_ENTITY_FUNCTION(
        self,
        class_name   : str,
        function_name: str,
        information  : str,
    ) -> None:
        """Marque la fin d'un appel de fonction entité (niveau 4)."""
        if not self.ACTIF:
            return
        self.FINISH_INDETED_LEVEL(4, class_name, function_name, information)


    # ##########################################################################
    # AFFICHAGE DE PARAMÈTRES ET DE STRUCTURES
    # ##########################################################################

    # =========================================================================
    def PARAMETER_VALUE(self, param_name: str, param_value: object) -> None:
        """
        Affiche une paire clé / valeur alignée avec des points.

        Paramètres
        ----------
        param_name  : str    Nom du paramètre (clé).
        param_value : object Valeur du paramètre (convertie en chaîne).
        """
        if not self.ACTIF:
            return

        prefix  = " " * 10
        dotted  = (str(param_name)).ljust(28, ".") + ":"
        self._error_log(f"{prefix}{dotted} {param_value}")

    # =========================================================================
    def DEBUG_PARAMETER_VALUE(
        self,
        param_name : str,
        param_value: object,
    ) -> None:
        """
        Affiche une paire clé / valeur uniquement si log_level >= 8 (DEBUG).

        Paramètres
        ----------
        param_name  : str    Nom du paramètre.
        param_value : object Valeur du paramètre.
        """
        if not self.ACTIF or self._log_level <= 7:
            return
        self.PARAMETER_VALUE(param_name, param_value)

    # =========================================================================
    def STEP(
        self,
        tab_size : int,
        step_name: str,
        info     : str = "",
    ) -> None:
        """
        Affiche un séparateur visuel marquant une étape du traitement.

        Paramètres
        ----------
        tab_size  : int  Niveau d'indentation (1 = moins indenté).
        step_name : str  Nom de l'étape.
        info      : str  Information complémentaire optionnelle.
        """
        if not self.ACTIF:
            return

        prefix      = " " * (tab_size - 1)
        line_length = 38 - tab_size
        line        = "-" * line_length
        info_txt    = f" ({info})" if info else ""

        self._error_log(
            self._COLOR_BROWNLIGHT + prefix + line + self._COLOR_RESET
        )
        self._error_log(
            self._COLOR_BROWNLIGHT + prefix + step_name + info_txt +
            self._COLOR_RESET
        )

    # =========================================================================
    def LOG_DICT(self, data: dict, dict_name: str) -> None:
        """
        Affiche le contenu d'un dictionnaire (équivalent de LOG_ARRAY).

        Gère un niveau d'imbrication : les valeurs de type dict ou list
        sont sérialisées en JSON sur une seule ligne.

        Paramètres
        ----------
        data      : dict  Dictionnaire à afficher.
        dict_name : str   Nom affiché en en-tête et en pied.
        """
        self.PARAMETER_VALUE(
            f"DICT {dict_name}", "──────────────────────────────────────┐"
        )
        for key, value in data.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if isinstance(sub_value, (dict, list, object)) and \
                       not isinstance(sub_value, (str, int, float, bool)):
                        self.PARAMETER_VALUE(
                            f"  {key}.{sub_key}", json.dumps(sub_value, default=str)
                        )
                    else:
                        self.PARAMETER_VALUE(f"  {key}.{sub_key}", sub_value)
            elif isinstance(value, (dict, list)) or (
                not isinstance(value, (str, int, float, bool, type(None)))
            ):
                self.PARAMETER_VALUE(f"  {key}", json.dumps(value, default=str))
            else:
                self.PARAMETER_VALUE(f"  {key}", value)

        self.PARAMETER_VALUE(
            f"DICT {dict_name}", "──────────────────────────────────────┘"
        )

    # =========================================================================
    def DUMP_VARIABLE(self, variable: object, variable_name: str) -> None:
        """
        Affiche la représentation complète d'une variable (équivalent var_dump).

        Paramètres
        ----------
        variable      : object  Variable à inspecter.
        variable_name : str     Nom de la variable affiché en entête.
        """
        self.PARAMETER_VALUE("DUMP", f"{variable_name} BEGIN")
        self._error_log(repr(variable))
        self.PARAMETER_VALUE("DUMP", f"{variable_name} FINISH")

    # =========================================================================
    def log_io_functions(self) -> None:
        """
        Démontre toutes les méthodes de log disponibles.
        Équivalent de log_io_funtions() en PHP — utile pour tester le rendu.
        """
        self._error_log(
            "         1         2         3         4         5         6"
        )
        self._error_log(
            "123456789012345678901234567890123456789012345678901234567890"
        )

        self.STEP(1, "STEP 1", "Début ...")
        self.STEP(3, "STEP 3", "Début ...")
        self.STEP(5, "STEP 5", "Début ...")
        self.STEP(7, "STEP 7", "Début ...")

        self.STEP(1, "SHOW INDETED_LEVEL", "Début ...")
        for lvl in range(1, 9):
            self.START_INDETED_LEVEL(
                lvl, "MaClasse", "maFonction", f"START_INDETED_LEVEL {lvl}"
            )

        self.PARAMETER_VALUE("Param 1", "PARAMETER_VALUE 1")
        self.PARAMETER_VALUE("Param 2", "PARAMETER_VALUE 2")

        for lvl in range(8, 0, -1):
            self.FINISH_INDETED_LEVEL(
                lvl, "MaClasse", "maFonction", f"FINISH_INDETED_LEVEL {lvl}"
            )

        self.STEP(1, "SHOW ACTION CALLS", "Début ...")
        self.START_ACTION("WEB", "ACTION", "START_ACTION BEGIN")
        self.START_CALL_CONTROLLER_FUNCTION(
            "CONTROLLER", "FUNCTION", "START_CALL_CONTROLLER_FUNCTION BEGIN"
        )
        self.START_CALL_MANAGER_FUNCTION(
            "MANAGER", "FUNCTION", "START_CALL_MANAGER_FUNCTION BEGIN"
        )
        self.START_CALL_ENTITY_FUNCTION(
            "ENTITY", "FUNCTION", "START_CALL_ENTITY_FUNCTION BEGIN"
        )
        self.PARAMETER_VALUE("Param 1", "PARAMETER_VALUE 1")
        self.PARAMETER_VALUE("Param 2", "PARAMETER_VALUE 2")
        self.FINISH_CALL_ENTITY_FUNCTION(
            "ENTITY", "FUNCTION", "FINISH_CALL_ENTITY_FUNCTION FINISH"
        )
        self.FINISH_CALL_MANAGER_FUNCTION(
            "MANAGER", "FUNCTION", "FINISH_CALL_MANAGER_FUNCTION FINISH"
        )
        self.FINISH_CALL_CONTROLLER_FUNCTION(
            "CONTROLLER", "FUNCTION", "FINISH_CALL_CONTROLLER_FUNCTION FINISH"
        )
        self.FINISH_ACTION("WEB", "ACTION", "FINISH_ACTION FINISH")

        self.STEP(1, "SHOW STANDARD LOGS", "Début ...")
        self.LEVEL_1_EMERGENCY("LogTool", "LEVEL_1_EMERGENCY  Système inutilisable")
        self.LEVEL_2_ALERT    ("LogTool", "LEVEL_2_ALERT      Action immédiate requise")
        self.LEVEL_3_CRITICAL ("LogTool", "LEVEL_3_CRITICAL   Conditions critiques")
        self.LEVEL_4_ERROR    ("LogTool", "LEVEL_4_ERROR      Conditions d'erreur")
        self.LEVEL_5_WARNING  ("LogTool", "LEVEL_5_WARNING    Avertissement")
        self.LEVEL_6_NOTICE   ("LogTool", "LEVEL_6_NOTICE     Condition significative")
        self.LEVEL_7_INFO     ("LogTool", "LEVEL_7_INFO       Message informatif")
        self.LEVEL_8_DEBUG    ("LogTool", "LEVEL_8_DEBUG      Message de débogage")


    # ##########################################################################
    # MÉTHODES PRIVÉES
    # ##########################################################################

    # =========================================================================
    def _error_log(self, message: str) -> None:
        """
        Écrit une ligne sur stderr avec le préfixe d'origine.
        Équivalent de error_log() en PHP.

        Paramètres
        ----------
        message : str  Ligne à écrire (couleurs ANSI incluses si présentes).
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        sys.stderr.write(f"{now} [{self._origin}] {message}\n")
        sys.stderr.flush()

    # =========================================================================
    def _log(self, message: str, color: str) -> None:
        """
        Écrit un message coloré sur stderr.

        Paramètres
        ----------
        message : str  Texte du message.
        color   : str  Code couleur ANSI à appliquer.
        """
        self._error_log(f"{color}{message.strip()}{self._COLOR_RESET}")

    # =========================================================================
    def _split_and_log_V0(self, tab_size: int, message: str, color: str) -> None:
        """
        Découpe un message multi-lignes et journalise chaque ligne.

        Normalise les fins de ligne (\\r\\n, \\n\\r, \\r → \\n),
        puis aligne toutes les lignes sur la longueur de la plus longue.

        Paramètres
        ----------
        tab_size : int  Taille d'indentation (non utilisée visuellement ici).
        message  : str  Message pouvant contenir des retours à la ligne.
        color    : str  Code couleur ANSI à appliquer.
        """
        # -- Normalisation des fins de ligne ---------------------------------
        message = message.replace("\r\n", "\n").replace("\n\r", "\n").replace("\r", "\n")
        lines = [line for line in message.split("\n") if line.strip()]

        if not lines:
            return

        # -- Alignement sur la ligne la plus longue --------------------------
        max_len = max(len(line.strip()) for line in lines)
        for line in lines:
            self._log(line.strip().ljust(max_len), color)


    def _split_and_log(self, tab_size: int, message: str, color: str) -> None:
        message = message.replace("\r\n", "\n").replace("\n\r", "\n").replace("\r", "\n")
        
        # CAMBIO: Quitamos el .strip() de la lista para mantener la sangría
        lines = [line for line in message.split("\n") if line]

        if not lines:
            return

        # Calculamos el máximo sin strip para que el ljust sea correcto
        max_len = max(len(line) for line in lines)
        for line in lines:
            # CAMBIO: Quitamos el .strip() aquí también
            self._log(line.ljust(max_len), color)
            
# =============================================================================
# POINT D'ENTRÉE : démonstration en ligne de commande
# =============================================================================
if __name__ == "__main__":
    log = LogTool(origin="demo")
    log.log_io_functions()
