"""Build one archive usable by both legacy add-ons and Blender extensions."""

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "blender_mcp_bridge"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / f"{PACKAGE}.zip")
    output = parser.parse_args().output
    output.parent.mkdir(parents=True, exist_ok=True)
    files = [*(ROOT / "addon").glob("*.py"), ROOT / "addon" / "blender_manifest.toml"]
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, f"{PACKAGE}/{path.name}")
    print(f"Created {output}")


if __name__ == "__main__":
    main()
