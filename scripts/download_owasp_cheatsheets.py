"""下载固定 Git commit 下的 OWASP Cheat Sheet Markdown，并生成哈希清单。"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY = "https://github.com/OWASP/CheatSheetSeries"
LICENSE_URL = f"{REPOSITORY}/blob/master/LICENSE.md"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_commit() -> str:
    output = subprocess.check_output(
        ["git", "ls-remote", f"{REPOSITORY}.git", "refs/heads/master"],
        text=True,
    )
    commit = output.split()[0]
    if len(commit) != 40:
        raise RuntimeError("无法解析 OWASP master commit")
    return commit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", default="knowledge/owasp_review_scope.json")
    parser.add_argument("--commit", help="固定 40 位 Git commit；缺省时解析官方 master")
    parser.add_argument("--output-root", default="knowledge/raw/owasp-cheatsheets")
    args = parser.parse_args()

    scope = json.loads(Path(args.scope).read_text(encoding="utf-8"))
    files = scope.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("OWASP scope 必须包含非空 files 数组")
    commit = args.commit or resolve_commit()
    if len(commit) != 40 or any(ch not in "0123456789abcdef" for ch in commit.lower()):
        raise ValueError("--commit 必须是 40 位十六进制 Git commit")

    output_dir = Path(args.output_root) / commit
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for filename in files:
        url = f"https://raw.githubusercontent.com/OWASP/CheatSheetSeries/{commit}/cheatsheets/{filename}"
        request = urllib.request.Request(url, headers={"User-Agent": "review-agent-rag-ingestion"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                content = response.read()
        except Exception as err:
            raise RuntimeError(f"下载 OWASP 文件失败: {filename} ({url})") from err
        (output_dir / filename).write_bytes(content)
        records.append({"file": filename, "url": url, "sha256": sha256(content)})

    manifest = {
        "source_id": "owasp-cheatsheet-series",
        "source_version": commit,
        "repository_url": REPOSITORY,
        "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "license": "CC BY-SA 4.0",
        "license_url": LICENSE_URL,
        "files": records,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"OWASP {commit[:12]}: {len(records)} files -> {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
