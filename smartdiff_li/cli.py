import sys
from pathlib import Path

list_commands = ["analyze"]

def validate_terminal():
    if (len(sys.argv) < 2):
        print("Error count of arguments, you need 2 or more args")
        return False

    return True

# Функция для анализа проекта 
def analyze_project(proj_path):
    if proj_path.exists():
        if proj_path.is_dir():
            print(f"Analyzing {proj_path}")
            analyze_directory(proj_path)
        else:
            print("Not is project")
    else:
        print("Unknown path")

# Анализируем все файлы в репозитории и в подкатегориях
def analyze_directory(path: Path):
    py_files = path.rglob('*.py')
    files = []
    for path_obj in py_files:
        files.append(path_obj)

    print_directory(files)

def print_directory(directory):
    for py_obj in directory:
        print(py_obj)
        print('\n')
              

def main():
    if validate_terminal():
        command = sys.argv[1]
        if (command == "analyze"):
            if len(sys.argv) < 3:
                print("Error: required direction")
            else:
               project_path = Path(sys.argv[2])
               analyze_project(proj_path=project_path)
        else:
            print(f"Undefined command {command}")



if __name__ == "__main__":
    main()