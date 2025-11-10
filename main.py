import os
import shutil
import zipfile
import subprocess
import tempfile
import re
import py_compile
from datetime import datetime
import csv

# TODO :
# Add csv exports
# pour obtenir les matricules (s'ils ne sont pas disponibles) ==>
# associer les noms de dossiers avec les matricules en regardant sur moodle

# ----- Configuration: edit these -----
PATH_ASSIGNMENTS = "INF1005D (20253)-Remise TP4-INF1005D_11L-776047"            # dossier contenant les zip des étudiants
PATH_TEST_CASES_DIR = "test_cases"          # dossier contenant vos exerciceN_tests.py

TEST_FILES = os.listdir(PATH_TEST_CASES_DIR)
TEST_FILES = [f for f in TEST_FILES if "test" in f and f.endswith(".py")]
print("Fichiers de test détectés : ", TEST_FILES)
# Points par exercice
EXERCISE_POINTS = {
    1: 2,
    2: 3,
    3: 4,
    4: 3,
    5: 3,
    6: 3,
    7: 2,
}

CSV_FILE = "grades.csv" 

# Pour avoir les matricules selon les noms des groupes 
GROUP_NUMBER = {
    
}

# Pondérations
RUN_WEIGHT = 0.25      # 25% pour "le code peut s'exécuter"
TEST_WEIGHT = 0.50     # 50% pour les tests
MANUAL_WEIGHT = 0.25   # 25% accordés pour la qualité du code et commentaires. Accordés par défaut 

PYTHON_EXE = "python"
TIMEOUT_PER_RUN = 20    # secondes pour tenter d'exécuter un exercice
TIMEOUT_PER_TEST = 30   # secondes pour exécuter pytest sur un test
CLEANUP_WORKDIR = False  # False pour garder les dossiers temporaires (débogage)

_STDIN_NEWLINES = 1
# ----- End Configuration -----

def unzip_folder(zip_path, extract_to):
    os.makedirs(extract_to, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(extract_to)

def copy_file(src, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    shutil.copy2(src, dest_dir)

def safe_name(s):
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in s)


def find_first_python_folder(parentFolder):
    """
    Parcours récursif pour trouver le premier dossier contenant un fichier .py.
    Retourne le chemin du dossier contenant le .py ou None si aucun trouvé.
    Ignore les dossiers contenant 'MAC' dans le chemin (convention macOS de zip).
    """
    try:
        for item in os.listdir(parentFolder):
            itemPath = os.path.join(parentFolder, item)
            if os.path.isdir(itemPath) and ("MAC" not in itemPath):
                pythonFolder = find_first_python_folder(itemPath)
                if pythonFolder:
                    return pythonFolder
            elif item.endswith(".py"):
                return parentFolder
    except Exception:
        return None
    return None

def pytest_available(python_exe=PYTHON_EXE):
    try:
        p = subprocess.run([python_exe, "-m", "pytest", "--version"],
                           capture_output=True, text=True, timeout=5)
        return p.returncode == 0
    except Exception:
        return False

TIMEOUT_PER_RUN = 10

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
    except Exception as e:
        return False, str(e)

def run_student_script_syntax_and_input_tolerant(script_path,
                                                 timeout=TIMEOUT_PER_RUN,
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

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        combined = stdout + "\n" + stderr

        passed = 0
        failed = 0
        skipped = 0
        total = 0

        # 1) style pytest : "X passed", "Y failed", "Z skipped"
        m_pass = re.search(r"(\d+)\s+passed", combined)
        m_failed = re.search(r"(\d+)\s+failed", combined)
        m_skipped = re.search(r"(\d+)\s+skipped", combined)
        if m_pass:
            passed = int(m_pass.group(1))
        if m_failed:
            failed = int(m_failed.group(1))
        if m_skipped:
            skipped = int(m_skipped.group(1))
        total = passed + failed

        # 2) style unittest : "Ran N tests in ...\n\nOK" ou "FAILED (failures=1, errors=0)"
        if total == 0:
            m_ran = re.search(r"Ran\s+(\d+)\s+tests?", combined)
            if m_ran:
                total = int(m_ran.group(1))
                if re.search(r"\bOK\b", combined):
                    passed = total
                    failed = 0
                else:
                    m_failures = re.search(r"failures?=(\d+)", combined)
                    m_errors = re.search(r"errors?=(\d+)", combined)
                    f = int(m_failures.group(1)) if m_failures else 0
                    e = int(m_errors.group(1)) if m_errors else 0
                    failed = f + e
                    passed = max(0, total - failed)

        # 3) heuristique fallback
        if total == 0:
            if proc.returncode == 0 and combined.strip():
                passed = 1
                total = 1

        ok = (proc.returncode == 0)
        return {
            "ok": ok,
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total": total
        }
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "returncode": None,
                "stdout": getattr(e, "stdout", "") or "", "stderr": f"TIMEOUT after {timeout}s",
                "passed": 0, "failed": 0, "skipped": 0, "total": 0}
    except Exception as e:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": f"Failed to run tests: {e}",
                "passed": 0, "failed": 0, "skipped": 0, "total": 0}


def find_student_ids(folder_name : str):
    """
    Extrait les numéros (matricules) d'un nom de dossier.
    Retourne une liste d'entiers.
    """
    numbers = re.findall(r'(\d{7})', folder_name)
    return [int(num) for num in numbers]

# ---------------- main ----------------
def main():
    path_assignments = PATH_ASSIGNMENTS
    path_test_cases = PATH_TEST_CASES_DIR
    utils_file = os.path.join(path_test_cases, "utils_ne_pas_supprimer.py")

    if not os.path.isdir(path_assignments):
        raise RuntimeError(f"Le dossier des remises n'existe pas : {path_assignments}")
    if not os.path.isdir(path_test_cases):
        raise RuntimeError(f"Le dossier des tests n'existe pas : {path_test_cases}")

    use_pytest = pytest_available()

    for folder in os.listdir(path_assignments):
        folder_path = os.path.join(path_assignments, folder)
        if not os.path.isdir(folder_path):
            continue

        
        for folder2 in os.listdir(folder_path):
            if not folder2.endswith(".zip"):
                continue

            zip_file_path = os.path.join(folder_path, folder2)
            extract_to = os.path.join(folder_path, folder2[:-4])

            # 1) décompression
            try:
                unzip_folder(zip_file_path, extract_to)
                print(f"Décompressé {zip_file_path} -> {extract_to}")
            except Exception as e:
                print(f"Échec de la décompression {zip_file_path} : {e}")
                continue

            # Préparer accumulators pour log et note
            log_lines = []
            grade_lines = []
            grade_lines.append(f"Correction de la soumission : {folder2}\n")
            log_lines.append(f"Log pour la soumission {folder2} (créé {datetime.now().isoformat()}):\n")

            
            # On exécute désormais les tests directement dans le dossier de l'étudiant.
            # Cherche éventuellement un sous-dossier contenant les .py (cas où le dossier dézipé contient un dossier racine)
            student_py_files = []
            student_code_folder = find_first_python_folder(extract_to) or extract_to
            log_lines.append(f"Dossier de code étudiant choisi pour l'exécution : {student_code_folder}\n")
            try:
                for item in os.listdir(student_code_folder):
                    if item.endswith(".py"):
                        # On enregistre la présence du fichier, sans le copier ailleurs
                        student_py_files.append(item)
                        log_lines.append(f"Trouvé fichier étudiant : {item}\n")
            except Exception as e:
                log_lines.append(f"Échec lecture du dossier étudiant {student_code_folder} : {e}\n")

            # 3) copier les fichiers de tests dans le dossier de l'étudiant et exécuter là-bas
            for testfile in TEST_FILES:
                test_src = os.path.join(path_test_cases, testfile)
                if os.path.exists(test_src):
                    try:
                        copy_file(test_src, student_code_folder)
                        log_lines.append(f"Copié fichier de test dans le dossier étudiant : {testfile}\n")
                    except Exception as e:
                        log_lines.append(f"Échec copie test {testfile} -> {student_code_folder} : {e}\n")
                else:
                    log_lines.append(f"Fichier de test manquant (non trouvé dans {path_test_cases}) : {testfile}\n")
            # ajouter le fichier utils s'il existe (dans le dossier de l'étudiant)
            if os.path.exists(utils_file):
                try:
                    copy_file(utils_file, student_code_folder)
                    log_lines.append(f"Copié utils_ne_pas_supprimer.py dans le dossier étudiant.\n")
                except Exception as e:
                    log_lines.append(f"Échec copie utils -> {student_code_folder} : {e}\n")

            # 4) Pour chaque exercice 1..n : vérification exécution + tests
            total_score = 0.0
            total_max = 0.0

            for ex_num in range(1, len(TEST_FILES) + 1):
                ex_name = f"exercice{ex_num}.py"
                test_name = TEST_FILES[ex_num - 1] if ex_num - 1 < len(TEST_FILES) else None
                max_points = EXERCISE_POINTS.get(ex_num, 0)
                total_max += max_points
                grade_lines.append(f"\nExercice {ex_num} (max {max_points} pts) :")

                # Vérifier si l'étudiant a fourni le fichier
                student_has_file = ex_name in student_py_files
                if not student_has_file:
                    grade_lines.append(f"\n - Fichier manquant : {ex_name} -> 0/{max_points} (seule la portion manuelle est attribuée ci-dessous)\n")
                    log_lines.append(f"[EX{ex_num}] Fichier manquant {ex_name}\n")
                    # exécution et tests = 0 ; portion manuelle donnée
                    run_awarded = 0.0
                    test_awarded = 0.0
                    manual_awarded = MANUAL_WEIGHT * max_points
                    awarded = run_awarded + test_awarded + manual_awarded
                    total_score += awarded
                    grade_lines.append(f"   exécution: {run_awarded:.2f}, tests: {test_awarded:.2f}, manuel: {manual_awarded:.2f} => {awarded:.2f}/{max_points}\n")
                    continue

                # 4.a) Vérification syntaxe / exécution tolérante input (dans le dossier de l'étudiant)
                script_path = os.path.join(student_code_folder, ex_name)
                run_res = run_student_script_syntax_and_input_tolerant(script_path, timeout=TIMEOUT_PER_RUN)
                if run_res["ran_ok"]:
                    run_awarded = RUN_WEIGHT * max_points
                    log_lines.append(f"[EX{ex_num}] Vérification exécution OK (returncode {run_res['returncode']}).\n")
                else:
                    run_awarded = 0.0
                    log_lines.append(f"[EX{ex_num}] Vérification exécution ÉCHEC. returncode={run_res['returncode']}; stderr:\n{run_res['stderr']}\n")
                grade_lines.append(f"\n - Vérification exécution : {'OK' if run_res['ran_ok'] else 'ÉCHEC'} (attribué {run_awarded:.2f}/{RUN_WEIGHT*max_points:.2f})")

                # 4.b) Exécuter les tests (si le fichier de test existe)
                test_awarded = 0.0
                if test_name:
                    test_path_in_student = os.path.join(student_code_folder, test_name)
                    if os.path.exists(test_path_in_student):
                        test_res = run_pytest_on_testfile(test_name, cwd=student_code_folder, timeout=TIMEOUT_PER_TEST)
                        log_lines.append(f"[EX{ex_num}] Sortie stdout des tests :\n{test_res['stdout']}\n")
                        log_lines.append(f"[EX{ex_num}] Sortie stderr des tests :\n{test_res['stderr']}\n")
                        # calculer fraction de tests passés
                        if test_res["total"] > 0:
                            fraction = test_res["passed"] / test_res["total"]
                        else:
                            # si aucun test détecté mais exit-code 0, on considère réussi ; sinon 0
                            fraction = 1.0 if test_res["ok"] else 0.0
                        test_awarded = TEST_WEIGHT * max_points * fraction
                        grade_lines.append(f"\n - Tests : {test_res['passed']}/{test_res['total']} réussis -> attribué {test_awarded:.2f}/{TEST_WEIGHT*max_points:.2f}")
                        log_lines.append(f"[Exercice{ex_num}] parsed: passed={test_res['passed']}, failed={test_res['failed']}, total={test_res['total']}\n")
                    else:
                        log_lines.append(f"[EX{ex_num}] Pas de fichier de test {test_name} dans workdir ; 0 pour les tests.\n")
                        grade_lines.append("\n - Tests : fichier de test absent (0 attribué)")
                else:
                    log_lines.append(f"[EX{ex_num}] Pas de mapping de test pour l'exercice {ex_num} ; 0 pour les tests.\n")
                    grade_lines.append("\n - Tests : pas de mapping (0 attribué)")

                # 4.c) Portion manuelle donnée automatiquement
                manual_awarded = MANUAL_WEIGHT * max_points

                # 4.d) Somme pour cet exercice
                awarded = run_awarded + test_awarded + manual_awarded
                total_score += awarded
                grade_lines.append(f"\n - Qualité du code et commentaires du code (attribué) : {manual_awarded:.2f}")
                grade_lines.append(f"\n => Exercice {ex_num} total attribué : {awarded:.2f}/{max_points}\n")

            # synthèse globale
            grade_lines.append(f"\nTOTAL : {total_score:.2f} / {total_max:.2f}\n")

            # 5) Écrire log et note dans extract_to
            log_path = os.path.join(extract_to, "log.txt")
            grade_path = os.path.join(extract_to, "grade.txt")
            try:
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(log_lines))
                with open(grade_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(grade_lines))
                #print(f"Écrit log -> {log_path}, note -> {grade_path}")
            except Exception as e:
                print(f"Échec écriture log/note dans {extract_to} : {e}")

            # écrire dans le CSV (uniquement la note finale)
            try:
                with open(CSV_FILE, "a", newline='', encoding="utf-8") as csvfile:
                    csvwriter = csv.writer(csvfile)
                    student_ids = find_student_ids(folder2)
                    for student_id in student_ids:
                        csvwriter.writerow([student_id, f"{total_score:.2f}"])
                    if not student_ids:
                        print(f"Aucun numéro d'étudiant trouvé dans le nom du dossier {folder2} pour le CSV.")
            except Exception as e:
                print(f"Échec écriture dans le CSV {CSV_FILE} : {e}")
            


            
            

# Si exécution directe :
if __name__ == "__main__":
    main()
