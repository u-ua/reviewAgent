"""下载并快照 MITRE CWE 官方完整 XML ZIP。"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_URL = "https://cwe.mitre.org/data/xml/cwec_latest.xml.zip"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-root", default="knowledge/raw/cwe")
    args = parser.parse_args()

    root = Path(args.output_root)
    root.mkdir(parents=True, exist_ok=True)
    zip_path = root / "cwec_latest.xml.zip"
    urllib.request.urlretrieve(args.url, zip_path)

    with zipfile.ZipFile(zip_path) as archive:
        xml_names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
        if len(xml_names) != 1:
            raise RuntimeError(f"预期 ZIP 中只有一个 XML，实际为 {xml_names}")
        xml_name = xml_names[0]
        archive.extract(xml_name, root)
    xml_path = root / xml_name

    import xml.etree.ElementTree as ET

    catalog = ET.parse(xml_path).getroot()
    version = catalog.attrib.get("Version") or "unknown"
    version_dir = root / version
    version_dir.mkdir(parents=True, exist_ok=True)
    final_zip = version_dir / zip_path.name
    final_xml = version_dir / xml_path.name
    zip_path.replace(final_zip)
    xml_path.replace(final_xml)

    manifest = {
        "source_id": "mitre-cwe",
        "source_version": version,
        "source_url": args.url,
        "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "license": "CWE Terms of Use",
        "license_url": "https://cwe.mitre.org/about/termsofuse.html",
        "zip_file": final_zip.name,
        "zip_sha256": sha256_file(final_zip),
        "xml_file": final_xml.name,
        "xml_sha256": sha256_file(final_xml),
    }
    manifest_path = version_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"CWE {version}: {final_xml} sha256:{manifest['xml_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
