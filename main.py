"""
Automated grading script for student assignments.

This script unzips student submissions, runs tests, and generates grades.
"""
import os
import shutil
import zipfile
import subprocess
import re
import py_compile
from datetime import datetime
import csv
import sys

from utils import UnzipError, CopyError

# ----- Configuration: edit these -----
# chemin du dossier contenant les zip des étudiants
PATH_ASSIGNMENTS = "INF1005D (20261)-Remise TP3-INF1005D_03L-852078"
# chemin du dossier contenant vos exerciceN_tests.py
PATH_TEST_CASES_DIR = "test_cases"

TEST_FILES = os.listdir(PATH_TEST_CASES_DIR)
TEST_FILES = [f for f in TEST_FILES if "test" in f and f.endswith(".py")]
#print("Fichiers de test détectés : ", TEST_FILES)
# Points par exercice
EXERCISE_POINTS = {
    1: 4,
    2: 4,
    3: 4,
    4: 4,
    5: 4,

}

# dossier contenant les fichiers de données supplémentaires
# (si nécessaires) aux tests / scripts python
DATA_FOLDER = "data"
CSV_FILE = "notes_TP3.csv"

# Pour avoir les matricules selon les noms des groupes (optionnel)
# Utile (pour le CSV) si on a besoin de toujours associer
# une remise à un étudiant même si le zip n'inclut pas son numéro
GROUP_NUMBER = {}

# Pondérations
RUN_WEIGHT = 0.25      # 25% pour "le code peut s'exécuter"
TEST_WEIGHT = 0.50     # 50% pour les tests
# 25% accordés pour la qualité du code et commentaires. Accordés par défaut
MANUAL_WEIGHT = 0.25

PYTHON_EXE = sys.executable
TIMEOUT_PER_RUN = 20    # secondes pour tenter d'exécuter un exercice
TIMEOUT_PER_TEST = 30   # secondes pour exécuter pytest sur un test
CLEANUP_WORKDIR = False  # False pour garder les dossiers temporaires (débogage)

_STDIN_NEWLINES = 1

# if the csv file already exists, overwrite it
if os.path.exists(CSV_FILE):
    try:
        os.remove(CSV_FILE)
    except OSError as e:
        print(f"Échec suppression ancien CSV {CSV_FILE} : {e}")

# ----- End Configuration -----




def unzip_folder(zip_path, extract_to):
    """Extract a zip file to the specified directory."""
    os.makedirs(extract_to, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(extract_to)
    except zipfile.BadZipFile as e:
        raise UnzipError(f"Fichier zip corrompu : {zip_path} : {e}") from e
    except zipfile.LargeZipFile as e:
        raise UnzipError(f"Fichier zip trop grand (Zip64 non supporté) : {zip_path} : {e}") from e

def copy_file(src, dest_dir):
    """Copy a file to the destination directory."""
    try:
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(src, dest_dir)
    except (IOError, OSError) as e:
        raise CopyError(f"Erreur copie fichier {src} -> {dest_dir} : {e}") from e

def safe_name(s):
    """Convert a string to a safe filename by replacing special characters."""
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in s)


def find_first_python_folder(parent_folder):
    """
    Parcours récursif pour trouver le premier dossier contenant un fichier .py.
    Retourne le chemin du dossier contenant le .py ou None si aucun trouvé.
    Ignore les dossiers contenant 'MAC' dans le chemin (convention macOS de zip).
    """
    try:
        for item in os.listdir(parent_folder):
            item_path = os.path.join(parent_folder, item)
            if os.path.isdir(item_path) and ("MAC" not in item_path):
                python_folder = find_first_python_folder(item_path)
                if python_folder:
                    return python_folder
            elif item.endswith(".py"):
                return parent_folder
    except (OSError, PermissionError) as e:
        raise RuntimeError(f"Erreur accès dossier {parent_folder} : {e}") from e

    return None

def pytest_available(python_exe=PYTHON_EXE):
    """Check if pytest is available in the given Python executable."""
    try:
        p = subprocess.run([python_exe, "-m", "pytest", "--version"],
                           capture_output=True, text=True, timeout=5, check=False)
        return p.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False

def check_syntax(script_path):
    """
    Retourne (ok:bool, message:str).
    ok == True signifie que le fichier compile (pas d'erreur de syntaxe).
    """
    try:
        py_compile.compile(script_path, doraise=True)
        return True, ""
    except py_compile.PyCompileError as e:
        return False, str(e)
    #except Exception as e:
    #    return False, str(e)

def run_student_script_syntax_and_input_tolerant(script_path,
                                                 python_exe=None):
    """
    1) Vérifie la syntaxe (pas d'erreur de compilation).
    2) Si la syntaxe est OK, retourne immédiatement ran_ok True (on ne lance
       plus le script complet ici pour éviter les input bloquants).
       (Ajustement : on considère la vérification d'exécution satisfaite si la
       syntaxe est correcte — tu peux modifier si tu veux lancer le script.)
    Retourne un dict avec les champs:
      "syntax_ok", "syntax_msg", "ran_ok", "only_input_error", "returncode", "stdout", "stderr"
    """
    if python_exe is None:
        python_exe = shutil.which("python3") or shutil.which("python") or "python"

    # 1) vérification de la syntaxe seulement
    syntax_ok, syntax_msg = check_syntax(script_path)
    # Si la syntaxe est mauvaise : on renvoie l'erreur
    if not syntax_ok:
        return {
            "syntax_ok": False,
            "syntax_msg": syntax_msg,
            "ran_ok": False,
            "only_input_error": False,
            "returncode": None,
            "stdout": "",
            "stderr": syntax_msg,
        }

    # Si la syntaxe est OK, on considère la vérification "peut s'exécuter" comme réussie
    # (on évite d'exécuter le script qui pourrait demander des input spécifiques).
    return {
        "syntax_ok": True,
        "syntax_msg": "",
        "ran_ok": True,
        "only_input_error": False,
        "returncode": 0,
        "stdout": "",
        "stderr": "",
    }


def parse_pytest_output(combined):
    """Parse pytest-style output for test counts."""
    passed = 0
    failed = 0
    skipped = 0

    m_pass = re.search(r"(\d+)\s+passed", combined)
    m_failed = re.search(r"(\d+)\s+failed", combined)
    m_skipped = re.search(r"(\d+)\s+skipped", combined)

    if m_pass:
        passed = int(m_pass.group(1))
    if m_failed:
        failed = int(m_failed.group(1))
    if m_skipped:
        skipped = int(m_skipped.group(1))

    return passed, failed, skipped


def parse_unittest_output(combined):
    """Parse unittest-style output for test counts."""
    m_ran = re.search(r"Ran\s+(\d+)\s+tests?", combined)
    if not m_ran:
        return 0, 0

    total = int(m_ran.group(1))
    if re.search(r"\bOK\b", combined):
        return total, 0

    m_failures = re.search(r"failures?=(\d+)", combined)
    m_errors = re.search(r"errors?=(\d+)", combined)
    f = int(m_failures.group(1)) if m_failures else 0
    e = int(m_errors.group(1)) if m_errors else 0
    failed = f + e
    passed = max(0, total - failed)
    return passed, failed


def _execute_test_command(cmd, cwd, timeout):
    """Execute test command and return process result."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout, check=False
        )
        return {
            "success": True,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "returncode": proc.returncode
        }
    except subprocess.TimeoutExpired as e:
        return {
            "success": False,
            "stdout": getattr(e, "stdout", "") or "",
            "stderr": f"TIMEOUT after {timeout}s",
            "returncode": None
        }
    except (OSError, subprocess.SubprocessError) as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Failed to run tests: {e}",
            "returncode": None
        }


def _parse_test_counts(combined, returncode):
    """Parse test output and return test counts."""
    # Try pytest-style parsing
    passed, failed, skipped = parse_pytest_output(combined)
    total = passed + failed

    # Try unittest-style parsing if pytest didn't find anything
    if total == 0:
        passed, failed = parse_unittest_output(combined)
        total = passed + failed

    # Fallback heuristic
    if total == 0 and returncode == 0 and combined.strip():
        passed = 1
        total = 1
        skipped = 0

    return passed, failed, skipped, total


def run_pytest_on_testfile(testfile_path, cwd, timeout=TIMEOUT_PER_TEST, python_exe=PYTHON_EXE):
    """
    Exécute pytest (ou le fichier de test directement).
    Parse les sorties pytest et unittest.

    Retourne dict: ok, returncode, stdout, stderr, passed, failed, skipped, total
    """
    use_pytest = pytest_available(python_exe)
    if use_pytest:
        cmd = [python_exe, "-m", "pytest", "-q", testfile_path]
    else:
        cmd = [python_exe, testfile_path]

    result = _execute_test_command(cmd, cwd, timeout)

    if not result["success"]:
        return {
            "ok": False,
            "returncode": result["returncode"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "total": 0
        }

    combined = result["stdout"] + "\n" + result["stderr"]
    passed, failed, skipped, total = _parse_test_counts(combined, result["returncode"])

    return {
        "ok": result["returncode"] == 0,
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "total": total
    }


def find_student_ids(folder_name: str):
    """
    Extrait les numéros (matricules) d'un nom de dossier.
    Retourne une liste d'entiers.
    """
    numbers = re.findall(r'(\d{7})', folder_name)
    return [int(num) for num in numbers]


def find_student_ids_in_python_files(student_code_folder, student_py_files, log_lines):
    """Extract student IDs from the contents of student Python files."""
    ids = set()
    for py_file in student_py_files:
        py_path = os.path.join(student_code_folder, py_file)
        try:
            with open(py_path, "r", encoding="utf-8", errors="ignore") as file:
                content = file.read()
            matches = re.findall(r'(\d{7})', content)
            for match in matches:
                ids.add(int(match))
        except (IOError, OSError) as error:
            log_lines.append(
                f"Échec lecture du fichier {py_file} pour extraction des matricules : "
                f"{error}\n"
            )
    return sorted(ids)


def resolve_student_ids(folder2, extract_to, student_code_folder, log_lines):
    """Resolve student IDs from folder names/paths, then Python files as fallback."""
    ids = set()
    candidate_sources = [
        folder2,
        os.path.basename(folder2),
        extract_to,
        os.path.basename(extract_to),
        student_code_folder,
        os.path.basename(student_code_folder),
    ]

    for source in candidate_sources:
        ids.update(find_student_ids(source))

    if ids:
        log_lines.append(f"Matricules trouvés dans les noms de dossiers : {sorted(ids)}\n")
        return ids

    print("Aucun matricule trouvé dans les noms de dossiers...")
    return []


def collect_student_files(student_code_folder, log_lines):
    """Collect all Python files from the student's code folder."""
    student_py_files = []
    try:
        for item in os.listdir(student_code_folder):
            if item.endswith(".py"):
                student_py_files.append(item)
                log_lines.append(f"Trouvé fichier étudiant : {item}\n")
    except (OSError, PermissionError) as e:
        log_lines.append(
            f"Échec lecture du dossier étudiant {student_code_folder} : {e}\n"
        )
    return student_py_files


def copy_test_files(student_code_folder, path_test_cases, utils_file, log_lines):
    """Copy test files and utils to the student's code folder."""
    # Copy test files
    for testfile in TEST_FILES:
        test_src = os.path.join(path_test_cases, testfile)
        if os.path.exists(test_src):
            try:
                copy_file(test_src, student_code_folder)
                log_lines.append(
                    f"Copié fichier de test dans le dossier étudiant : {testfile}\n"
                )
            except CopyError as e:
                log_lines.append(
                    f"Échec copie test {testfile} -> {student_code_folder} : {e}\n"
                )
        else:
            log_lines.append(
                f"Fichier de test manquant (non trouvé dans {path_test_cases}) : "
                f"{testfile}\n"
            )

    # Copy utils file if it exists
    if os.path.exists(utils_file):
        try:
            copy_file(utils_file, student_code_folder)
            log_lines.append(
                "Copié utils_ne_pas_supprimer.py dans le dossier étudiant.\n"
            )
        except CopyError as e:
            log_lines.append(f"Échec copie utils -> {student_code_folder} : {e}\n")


def copy_data_files(student_code_folder, log_lines):
    """Copy data files/folders to the student's code folder."""
    if not os.path.exists(DATA_FOLDER):
        return

    for data in os.listdir(DATA_FOLDER):
        data_src = os.path.join(DATA_FOLDER, data)
        try:
            if os.path.isdir(data_src):
                shutil.copytree(
                    data_src,
                    os.path.join(student_code_folder, data),
                    dirs_exist_ok=True
                )
            else:
                shutil.copy2(
                    data_src, os.path.join(student_code_folder, data)
                )
            log_lines.append(
                f"Copié donnée nécessaire {data} dans le dossier étudiant.\n"
            )
        except (IOError, OSError) as e:
            log_lines.append(
                f"Échec copie donnée {data} -> {student_code_folder} : {e}\n"
            )


def _check_execution(ex_num, script_path, max_points, log_lines, grade_lines):
    """Check syntax/execution and return awarded points and execution result."""
    run_res = run_student_script_syntax_and_input_tolerant(script_path)
    if run_res["ran_ok"]:
        run_awarded = RUN_WEIGHT * max_points
        log_lines.append(
            f"[EX{ex_num}] Vérification exécution OK "
            f"(returncode {run_res['returncode']}).\n"
        )
    else:
        run_awarded = 0.0
        log_lines.append(
            f"[EX{ex_num}] Vérification exécution ÉCHEC. "
            f"returncode={run_res['returncode']}; stderr:\n{run_res['stderr']}\n"
        )
    grade_lines.append(
        f"\n - Vérification exécution : "
        f"{'OK' if run_res['ran_ok'] else 'ÉCHEC'} "
        f"(attribué {run_awarded:.2f}/{RUN_WEIGHT*max_points:.2f})"
    )
    return run_awarded, run_res


def _run_tests(ex_num, test_name, student_code_folder, max_points, logs):
    """Run tests for an exercise and return awarded points."""
    log_lines, grade_lines = logs["log_lines"], logs["grade_lines"]

    if not test_name:
        log_lines.append(
            f"[EX{ex_num}] Pas de mapping de test pour l'exercice {ex_num} ; "
            f"0 pour les tests.\n"
        )
        grade_lines.append("\n - Tests : pas de mapping (0 attribué)")
        return 0.0

    test_path_in_student = os.path.join(student_code_folder, test_name)
    if not os.path.exists(test_path_in_student):
        log_lines.append(
            f"[EX{ex_num}] Pas de fichier de test {test_name} dans workdir ; "
            f"0 pour les tests.\n"
        )
        grade_lines.append("\n - Tests : fichier de test absent (0 attribué)")
        return 0.0

    test_res = run_pytest_on_testfile(
        test_name, cwd=student_code_folder, timeout=TIMEOUT_PER_TEST
    )
    log_lines.append(
        f"[EX{ex_num}] Sortie stderr des tests :\n{test_res['stderr']}\n"
    )

    fraction = test_res["passed"] / test_res["total"] if test_res["total"] > 0 else (
        1.0 if test_res["ok"] else 0.0
    )
    test_awarded = TEST_WEIGHT * max_points * fraction
    grade_lines.append(
        f"\n - Tests : {test_res['passed']}/{test_res['total']} réussis -> "
        f"attribué {test_awarded:.2f}/{TEST_WEIGHT*max_points:.2f}"
    )
    log_lines.append(
        f"[Exercice{ex_num}] parsed: passed={test_res['passed']}, "
        f"failed={test_res['failed']}, total={test_res['total']}\n"
    )
    return test_awarded
def grade_exercise(ex_num, student_code_folder, student_py_files, log_lines, grade_lines):
    """Grade a single exercise and return the score awarded."""
    ex_name = f"exercice{ex_num}.py"
    test_name = TEST_FILES[ex_num - 1] if ex_num - 1 < len(TEST_FILES) else None
    max_points = EXERCISE_POINTS.get(ex_num, 0)

    grade_lines.append(f"\nExercice {ex_num} (max {max_points} pts) :")

    # Check if student provided the file
    if ex_name not in student_py_files:
        grade_lines.append(
            f"\n - Fichier manquant : {ex_name} -> 0/{max_points}\n"
        )
        log_lines.append(f"[EX{ex_num}] Fichier manquant {ex_name}\n")
        grade_lines.append(
            f"   exécution: 0.00, tests: 0.00, manuel: 0.00 => 0.00/{max_points}\n"
        )
        return 0.0, max_points

    # Check syntax/execution
    script_path = os.path.join(student_code_folder, ex_name)
    run_awarded, run_res = _check_execution(
        ex_num, script_path, max_points, log_lines, grade_lines
    )

    # Run tests
    logs = {"log_lines": log_lines, "grade_lines": grade_lines}
    test_awarded = _run_tests(
        ex_num, test_name, student_code_folder, max_points, logs
    )

    # Manual portion - only award if code compiles
    if run_res["ran_ok"]:
        manual_awarded = MANUAL_WEIGHT * max_points
    else:
        manual_awarded = 0.0
        log_lines.append(
            f"[EX{ex_num}] Pas de points de qualité : code ne compile pas.\n"
        )

    # Total for this exercise
    awarded = run_awarded + test_awarded + manual_awarded
    grade_lines.append(
        f"\n - Qualité du code et commentaires du code (attribué) : "
        f"{manual_awarded:.2f}"
    )
    grade_lines.append(
        f"\n => Exercice {ex_num} total attribué : "
        f"{awarded:.2f}/{max_points}\n"
    )

    return awarded, max_points


def _write_log_files(path_assignments, extract_to, student_code_folder, log_lines, grade_lines):
    """Write log and grade files to disk."""
    logs_dir = os.path.join(path_assignments, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    student_folder_name = os.path.basename(student_code_folder)
    log_path = os.path.join(logs_dir, f"log_{student_folder_name}.txt")
    grade_path = os.path.join(extract_to, "grade.txt")

    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(log_lines))
        with open(grade_path, "w", encoding="utf-8") as f:
            f.write("\n".join(grade_lines))
    except (IOError, OSError) as e:
        print(f"Échec écriture log/note : {e}")


def _write_csv_entry(student_ids, folder2, total_score):
    """Write a CSV entry for the graded submission."""
    try:
        with open(CSV_FILE, "a", newline='', encoding="utf-8") as csvfile:
            csvwriter = csv.writer(csvfile)
            for student_id in student_ids:
                csvwriter.writerow([student_id, f"{total_score:.2f}"])
            if not student_ids:
                print(
                    f"Aucun numéro d'étudiant trouvé dans le nom du dossier "
                    f"{folder2} pour le CSV."
                )
    except (IOError, OSError) as e:
        print(f"Échec écriture dans le CSV {CSV_FILE} : {e}")


def save_results(paths, logs, folder2, total_score, student_ids):
    """Save log and grade files, and write to CSV."""
    _write_log_files(
        paths["assignments"], paths["extract"], paths["student"],
        logs["log_lines"], logs["grade_lines"]
    )
    _write_csv_entry(student_ids, folder2, total_score)


def _initialize_submission(folder2):
    """Initialize log and grade lines for a submission."""
    log_lines = []
    grade_lines = []
    grade_lines.append(f"Correction de la soumission : {folder2}\n")
    log_lines.append(
        f"Log pour la soumission {folder2} (créé {datetime.now().isoformat()}):\n"
    )
    return log_lines, grade_lines


def _setup_student_environment(extract_to, path_test_cases, log_lines):
    """Find student code folder and set up test environment."""
    student_code_folder = find_first_python_folder(extract_to) or extract_to
    log_lines.append(
        f"Dossier de code étudiant choisi pour l'exécution : {student_code_folder}\n"
    )

    student_py_files = collect_student_files(student_code_folder, log_lines)
    utils_file = os.path.join(path_test_cases, "utils_ne_pas_supprimer.py")
    copy_test_files(student_code_folder, path_test_cases, utils_file, log_lines)
    copy_data_files(student_code_folder, log_lines)

    return student_code_folder, student_py_files


def process_submission(zip_file_path, folder_path, folder2, path_assignments, path_test_cases):
    """Process a single student submission."""
    extract_to = os.path.join(folder_path, folder2[:-4])

    # Unzip
    try:
        unzip_folder(zip_file_path, extract_to)
        print(f"Décompressé {zip_file_path} -> {extract_to}")
    except UnzipError as e:
        print(f"Échec de la décompression {zip_file_path} : {e}")
        return

    # Initialize
    log_lines, grade_lines = _initialize_submission(folder2)

    # Setup environment
    student_code_folder, student_py_files = _setup_student_environment(
        extract_to, path_test_cases, log_lines
    )

    # Grade all exercises
    total_score = 0.0

    for ex_num in range(1, len(TEST_FILES) + 1):
        total_score += grade_exercise(
            ex_num, student_code_folder, student_py_files, log_lines, grade_lines
        )[0]

    # Add total summary
    total_max = sum(EXERCISE_POINTS.get(i, 0) for i in range(1, len(TEST_FILES) + 1))
    grade_lines.append(f"\nTOTAL : {total_score:.2f} / {total_max:.2f}\n")

    student_ids = resolve_student_ids(
        folder2, extract_to, student_code_folder, log_lines
    )

    # Save results
    paths = {
        "assignments": path_assignments,
        "extract": extract_to,
        "student": student_code_folder
    }
    logs = {"log_lines": log_lines, "grade_lines": grade_lines}
    save_results(paths, logs, folder2, total_score, student_ids)


# ---------------- main ----------------

def main():
    """Main function to process student assignments and generate grades."""
    path_assignments = PATH_ASSIGNMENTS
    path_test_cases = PATH_TEST_CASES_DIR

    if not os.path.isdir(path_assignments):
        raise RuntimeError(f"Le dossier des remises n'existe pas : {path_assignments}")
    if not os.path.isdir(path_test_cases):
        raise RuntimeError(f"Le dossier des tests n'existe pas : {path_test_cases}")

    for folder in os.listdir(path_assignments):
        folder_path = os.path.join(path_assignments, folder)
        if not os.path.isdir(folder_path):
            continue

        for folder2 in os.listdir(folder_path):
            if not folder2.endswith(".zip"):
                continue

            zip_file_path = os.path.join(folder_path, folder2)
            process_submission(
                zip_file_path, folder_path, folder2, path_assignments, path_test_cases
            )

    print("Correction terminée.")


# Si exécution directe :
if __name__ == "__main__":
    main()
