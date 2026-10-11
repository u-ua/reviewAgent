"""ArtifactStore：内容寻址的证据袋（对应 src/stores/artifact-store.ts）。

大原文（代码摘录、diff）不塞进模型上下文，落盘到 artifacts/<taskId>/<hash>.<ext>，
账本和 Finding 只留 `artifact:<hash>` 编号 + 短 preview。规则等非定位证据
按内容去重；代码片段把来源范围纳入身份，避免相同文本在不同文件/行号间串证据。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from threading import RLock

from ..jsonutil import now_iso
from ..types import ArtifactRecord

EXT_BY_MEDIA = {
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/x-diff": ".diff",
    "application/json": ".json",
}


def _safe_dir_name(task_id: str) -> str:
    """taskId（如 task:security）里的冒号在 Windows 文件系统非法，清洗成目录名用。"""
    return re.sub(r"[^A-Za-z0-9._-]", "_", task_id)


class ArtifactStore:
    def __init__(self, artifacts_dir: str, run_id: str):
        self.artifacts_dir = Path(artifacts_dir)
        self.run_id = run_id
        self._lock = RLock()
        self.records: dict[str, ArtifactRecord] = {}
        # artifact identity hash -> 已记录 ref 的反查。
        self.hash_to_ref: dict[str, str] = {}
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        *,
        task_id: str,
        kind: str,
        media_type: str,
        content: str,
        preview_length: int | None = None,
        source_path: str | None = None,
        source_start_line: int | None = None,
        source_end_line: int | None = None,
    ) -> ArtifactRecord:
        with self._lock:
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            identity = content_hash
            if kind == "code":
                identity = "\0".join(
                    (kind, source_path or "", str(source_start_line), str(source_end_line), content_hash)
                )
            digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            ref = f"artifact:{digest}"

            # 同一内容：复用已有记录，不重复占盘
            existing_ref = self.hash_to_ref.get(digest)
            if existing_ref:
                return self.records[existing_ref]

            ext = EXT_BY_MEDIA.get(media_type, ".txt")
            dir_name = _safe_dir_name(task_id)
            task_dir = self.artifacts_dir / dir_name
            task_dir.mkdir(parents=True, exist_ok=True)
            rel_path = f"{dir_name}/{digest}{ext}"
            abs_path = self.artifacts_dir / rel_path
            abs_path.write_text(content, encoding="utf-8")

            preview_len = min(preview_length if preview_length is not None else 400, len(content))
            record = ArtifactRecord(
                artifactRef=ref,
                taskId=task_id,
                kind=kind,
                mediaType=media_type,
                path=rel_path,
                byteLength=len(content.encode("utf-8")),
                createdAt=now_iso(),
                preview=content[:preview_len],
                contentHash=content_hash,
                sourcePath=source_path,
                sourceStartLine=source_start_line,
                sourceEndLine=source_end_line,
            )
            self.records[ref] = record
            self.hash_to_ref[digest] = ref
            return record

    def has(self, ref: str) -> bool:
        with self._lock:
            return ref in self.records

    def get(self, ref: str) -> ArtifactRecord | None:
        with self._lock:
            return self.records.get(ref)

    def read_text(self, ref: str) -> str | None:
        """按 ref 读出原文。"""
        with self._lock:
            record = self.records.get(ref)
            if record is None:
                return None
            abs_path = self.artifacts_dir / record.path
        try:
            return abs_path.read_text(encoding="utf-8")
        except OSError:
            return None
