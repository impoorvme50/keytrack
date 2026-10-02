"""Copy redistribution notices for the components included in the helper."""
import importlib.metadata
import shutil
import sys
import sysconfig
from pathlib import Path

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
notes = ["Keytrack 0.4.4 — bundled runtime components", "", "The native interface and local helper run on this Mac.", "No AIME or Qingjian source code is included in this bundle.", ""]
notes.append("Local candidate glosses: 120 original introductory Chinese-English-Japanese entries, MIT (project LICENSE.txt); metadata in data/annotations.")
prediction_licenses = Path(__file__).resolve().parent.parent / "data/prediction/licenses"
if prediction_licenses.is_dir():
    shutil.copytree(prediction_licenses, out / "PublicPrediction", dirs_exist_ok=True)
    notes.append("Public next-word pairs: LCCC (MIT), segmented offline with jieba 0.42.1 (MIT); notices in PublicPrediction.")
for name in ("pyobjc-core", "pyobjc-framework-Cocoa", "pyobjc-framework-Quartz", "pyinstaller"):
    dist = importlib.metadata.distribution(name)
    notes.append(f"{name} {dist.version}")
    for relative in dist.files or []:
        path = Path(str(relative))
        if "licenses" in path.parts and path.name.lower().startswith(("license", "copying")):
            source = Path(dist.locate_file(relative))
            if source.is_file():
                target = out / name / path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
# The PyObjC core wheel omits the shared MIT license file; use the same
# project license shipped by the Cocoa framework distribution.
core_notice = out / "pyobjc-core" / "LICENSE.txt"
core_notice.parent.mkdir(exist_ok=True)
shutil.copy2(out / "pyobjc-framework-Cocoa" / "LICENSE.txt", core_notice)
for name, files in {
    "OpenSSL": ["/opt/homebrew/opt/openssl@3/LICENSE.txt"],
    "zstd": ["/opt/homebrew/opt/zstd/LICENSE", "/opt/homebrew/opt/zstd/COPYING"],
    "mpdecimal": ["/opt/homebrew/opt/mpdecimal/COPYRIGHT.txt"],
}.items():
    destination = out / name
    destination.mkdir(exist_ok=True)
    for source in files:
        shutil.copy2(source, destination / Path(source).name)
notes.append("SQLite: public domain — https://www.sqlite.org/copyright.html")
notes.append(f"Python {sys.version.split()[0]} (PSF license)")
license_path = Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"
if not license_path.exists():
    license_path = Path(sys.base_prefix) / "Resources" / "English.lproj" / "License.rtf"
if not license_path.exists():
    raise SystemExit("Python redistribution license was not found")
shutil.copy2(license_path, out / ("Python-" + license_path.name))
(out / "NOTICE.txt").write_text("\n".join(notes) + "\n")
