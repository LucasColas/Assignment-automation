import os
import zipfile
import shutil

folders_path = "./"

filesToUpdate = [
    "./exercice1_tests.py", # TODO: Change files to be replaced here
    "./exercice2_tests.py",
    "./exercice3_tests.py",
    "./exercice4_tests.py",
    "./exercice5_tests.py",
    "./exercice6_tests.py",
    "utils_ne_pas_supprimer.py",
    "run_tests.sh"
]


# Unzip all the folders in each group

folders = [folders_path + f for f in os.listdir(folders_path) if os.path.isdir(os.path.join(folders_path, f))]
for i in range(len(folders)):
    zipFilesOfGroup = [f for f in os.listdir(folders[i]) if f.endswith(".zip")]
    if (not len(zipFilesOfGroup)):
        continue
    zipFilePath = os.path.join(folders[i], zipFilesOfGroup[0])
    with zipfile.ZipFile(zipFilePath, 'r') as zip_ref:
        zip_ref.extractall(folders[i])
print("-----> All zip folders have been extracted")

# Get all the correct paths where the student's python files are situated
def find_first_python_file(parentFolder):
    for item in os.listdir(parentFolder):
        itemPath = os.path.join(parentFolder, item)
        
        if os.path.isdir(itemPath) and ("MAC" not in itemPath):
            pythonFolder = find_first_python_file(itemPath)
            
            if pythonFolder:
                return pythonFolder
        elif item.endswith(".py"):
            return parentFolder

codePathsEachGroup = []
for folder in folders :
    codePathsEachGroup.append(find_first_python_file(folder))

pythonFolderPaths = {}
for i in range(0, len(folders)):
    group = folders[i].split("_")[0][2::]
    pythonFolderPaths[group] = codePathsEachGroup[i]


# Replace all the files used for testing in each python folder
for group in pythonFolderPaths.keys():
    if (pythonFolderPaths[group]):
        for srcFile in filesToUpdate:
            shutil.copy(srcFile, pythonFolderPaths[group])
print("-----> All test files where replaced!")

