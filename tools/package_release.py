"""Package the committed runtime and synthetic ASC examples for Windows."""
from pathlib import Path
import re
import subprocess


def main():
    root = Path(__file__).resolve().parent.parent
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]", version):
        raise SystemExit("VERSION must use X.Y with one decimal digit.")
    name = f"SRAM Analysis Tool v{version}"
    folder = root / "releases"
    folder.mkdir(exist_ok=True)
    destination = folder / (name + ".zip")
    draft = destination.with_suffix(".zip.tmp")
    files = (
        "README.md", "VERSION", "Start SRAM Wafer Studio.cmd", "requirements.txt", "defaults.json",
        "app.py", "engine.py", "exports.py", "pattern_reports.py", "workbook_results.py", "workbook_settings.py",
        "web/app.js", "web/index.html", "web/style.css", "examples/sim128/Config_TNO.csv",
        "examples/sim128/SIM128_WT1.asc", "examples/sim128/SIM128_WT2.asc", "examples/sim128/SIM128_WT3.asc",
    )
    try:
        subprocess.run(
            ["git", "archive", "--format=zip", f"--prefix={name}/", f"--output={draft}", "HEAD", "--", *files],
            cwd=root, check=True,
        )
        draft.replace(destination)
    finally:
        draft.unlink(missing_ok=True)
    print(destination)


if __name__ == "__main__":
    main()
