import os
import ast
from collections import defaultdict

# Ordner für die Ausgaben
OUTPUT_DIR = "Abhängigkeiten"
os.makedirs(OUTPUT_DIR, exist_ok=True)

PIP_COMMANDS_FILE = os.path.join(OUTPUT_DIR, "Pip-Befehle.txt")
DEPENDENCIES_FILE = os.path.join(OUTPUT_DIR, "Abhängigkeiten.txt")

# Liste der zu prüfenden Python-Dateien
PYTHON_FILES = [
    "/home/personalpeak360/Webseite/Frontend/main.py",
    "/home/personalpeak360/Webseite/CDN/main.py",
    "/home/personalpeak360/Webseite/Authentication/main.py",
    "/home/personalpeak360/Webseite/Admin-Panel/main.py",
]

def extract_imports_from_file(filepath):
    """Extrahiert Imports aus einer Python-Datei."""
    with open(filepath, "r", encoding="utf-8") as file:
        try:
            tree = ast.parse(file.read(), filename=filepath)
        except SyntaxError as e:
            print(f"Fehler beim Parsen der Datei {filepath}: {e}")
            return []
    
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split('.')[0])
    return imports

def main():
    # Alle Abhängigkeiten sammeln
    dependencies = set()
    for python_file in PYTHON_FILES:
        if os.path.isfile(python_file):
            dependencies.update(extract_imports_from_file(python_file))
        else:
            print(f"Datei nicht gefunden: {python_file}")

    # Abhängigkeiten sortieren und speichern
    dependencies = sorted(dependencies)
    with open(DEPENDENCIES_FILE, "w") as dep_file, open(PIP_COMMANDS_FILE, "w") as pip_file:
        for dep in dependencies:
            dep_file.write(f"{dep}\n")
            pip_file.write(f"pip install {dep}\n")

    print(f"Abhängigkeiten exportiert nach: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
