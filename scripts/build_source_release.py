"""Build a local source ZIP from audited Git files; never upload or publish."""
import argparse
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path
from release_audit import ROOT, audit

sys.path.insert(0, str(ROOT))
from version import __version__


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    subprocess.run(["git", "diff", "--exit-code"], cwd=ROOT, check=True)
    names = audit(ROOT)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"autosub-translator-{__version__}"
    output = args.output_dir / f"{prefix}-source.zip"
    manifest = []
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            data = (ROOT / name).read_bytes()
            archive.writestr(f"{prefix}/{name}", data)
            manifest.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
        archive.writestr(f"{prefix}/MANIFEST.sha256", "\n".join(manifest) + "\n")
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(f"{checksum}  {output.name}\n", encoding="utf-8")
    print(f"Created {output.name}; {len(names)} source files plus hash manifest")


if __name__ == "__main__":
    main()
