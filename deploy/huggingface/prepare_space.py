"""Copy the backend into a cloned Hugging Face Space repository, ready to commit and push.

Usage (from the repository root):
    python deploy/huggingface/prepare_space.py ../my-space

Works on Windows, macOS and Linux. Binary files and local runtime data are left out: Spaces
reject plain-git binaries, and the database is created and seeded on startup.
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
HERE = Path(__file__).resolve().parent

# Top-level backend entries that must not ship: local secrets/venvs, tests, and runtime data
# (storage/ is recreated and seeded by scripts/start.sh).
SKIP_TOP_LEVEL = {".env", ".venv", "venv", "tests", "storage", ".pytest_cache"}
# Anywhere in the tree.
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.db", "*.pdf", "*.png", "*.jpg")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python deploy/huggingface/prepare_space.py <path-to-cloned-space-repo>")
    target = Path(sys.argv[1]).resolve()
    if not (target / ".git").exists():
        sys.exit(f"{target} is not a git repository. Clone your Space first: git clone https://huggingface.co/spaces/<user>/<space>")

    # Remove everything except the Space's own git metadata, then copy the backend in.
    for child in target.iterdir():
        if child.name != ".git":
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    for child in BACKEND.iterdir():
        if child.name in SKIP_TOP_LEVEL or IGNORE(str(BACKEND), [child.name]):
            continue
        destination = target / child.name
        if child.is_dir():
            shutil.copytree(child, destination, ignore=IGNORE)
        else:
            shutil.copy2(child, destination)
    shutil.copy2(HERE / "Dockerfile", target / "Dockerfile")
    shutil.copy2(HERE / "README.md", target / "README.md")
    print(f"Space prepared in {target}. Next: cd {target} && git add -A && git commit -m 'Deploy' && git push")


if __name__ == "__main__":
    main()
