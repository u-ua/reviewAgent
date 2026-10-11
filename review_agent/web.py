"""只读本地审查工作台：展示 ``runs/<session>`` 中的审计产物。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import uuid
import base64
import mimetypes
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


STATIC_DIR = Path(__file__).with_name("static")
PROJECT_ROOT = STATIC_DIR.parent.parent


def _safe_session_name(value: str) -> str | None:
    """只接受 runs 下的一层目录名，避免 API 被用来读取任意文件。"""
    path = Path(value)
    if not value or path.name != value or value in {".", ".."}:
        return None
    return value


def list_sessions(runs_dir: Path) -> list[dict]:
    if not runs_dir.is_dir():
        return []
    result = []
    for path in sorted(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_dir() or not (path / "execution.jsonl").is_file():
            continue
        result.append({"id": path.name, "modifiedAt": int(path.stat().st_mtime * 1000)})
    return result


def read_session(runs_dir: Path, session_id: str) -> dict:
    safe_name = _safe_session_name(session_id)
    if safe_name is None:
        raise FileNotFoundError(session_id)
    directory = runs_dir / safe_name
    if not directory.is_dir():
        raise FileNotFoundError(session_id)

    def read_json(name: str, fallback):
        file = directory / name
        return json.loads(file.read_text(encoding="utf-8")) if file.is_file() else fallback

    events = []
    log_file = directory / "execution.jsonl"
    if log_file.is_file():
        for line in log_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    return {
        "id": safe_name,
        "tasks": read_json("tasks.json", []),
        "findings": read_json("findings.json", []),
        "metrics": read_json("metrics.json", {}),
        "events": events,
    }


class JobRegistry:
    def __init__(self, runs_dir: Path):
        self.runs_dir, self.jobs, self.lock = runs_dir, {}, threading.Lock()

    def review(self, body: dict) -> dict:
        repo, goal = Path(str(body.get("repo") or "")).expanduser().resolve(), str(body.get("goal") or "").strip()
        if not repo.is_dir() or not goal:
            raise ValueError("仓库路径必须存在，且审查目标不能为空")
        job = {"id": uuid.uuid4().hex, "status": "running", "message": "正在审查…"}
        self.jobs[job["id"]] = job
        def run():
            try:
                from .controller import ReviewController
                from .providers.fake import FakeAgentProvider
                scope = [x.strip() for x in str(body.get("scope") or "").split(",") if x.strip()]
                result = ReviewController({"repoRoot": str(repo), "scope": scope, "goal": goal, "maxCycles": 6, "provider": "fake"}, FakeAgentProvider(), session_dir=str(self.runs_dir / f"web-{job['id']}")).run_until_done()
                job.update(status="completed", message=f"完成：{len(result.findings)} 条 Finding", sessionId=Path(result.sessionDir).name)
            except Exception as err: job.update(status="failed", message=f"运行失败：{err}")
        threading.Thread(target=run, daemon=True).start()
        return job

    def uploaded_review(self, body: dict) -> dict:
        files = body.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError("请至少上传一个文件")
        upload_root = self.runs_dir / "uploads" / uuid.uuid4().hex
        total = 0
        for item in files:
            name, content = str(item.get("name") or ""), str(item.get("content") or "")
            relative = Path(name.replace("\\", "/"))
            if not name or relative.is_absolute() or ".." in relative.parts:
                raise ValueError("上传文件名不合法")
            data = base64.b64decode(content, validate=True)
            total += len(data)
            if total > 5 * 1024 * 1024:
                raise ValueError("单次上传总大小不能超过 5 MB")
            target = upload_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return self.review({"repo": str(upload_root), "scope": body.get("scope", ""), "goal": body.get("goal")})

    def rule(self, body: dict) -> dict:
        from .rag.models import RuleDocument
        rule = RuleDocument.from_dict({"rule_id": body.get("ruleId"), "title": body.get("title"), "text": body.get("text"), "languages": [x.strip() for x in str(body.get("languages") or "").split(",") if x.strip()], "category": body.get("category", "security"), "severity": body.get("severity", "medium"), "source": body.get("source", "local-workbench"), "source_url": body.get("sourceUrl", "")})
        file = PROJECT_ROOT / "knowledge" / "review_rules.json"; rules = json.loads(file.read_text(encoding="utf-8"))
        if any(x.get("rule_id") == rule.rule_id for x in rules): raise ValueError("rule_id 已存在")
        rules.append(rule.hash_payload()); file.write_text(json.dumps(rules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        job = {"id": uuid.uuid4().hex, "status": "running", "message": "规则已保存，正在索引…"}; self.jobs[job["id"]] = job
        def run():
            p = subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "index_rules.py")], cwd=PROJECT_ROOT, text=True, capture_output=True)
            job.update(status="completed" if p.returncode == 0 else "failed", message=(p.stdout or p.stderr).strip()[-500:])
        threading.Thread(target=run, daemon=True).start(); return job


def make_handler(runs_dir: Path):
    jobs = JobRegistry(runs_dir)
    class ReviewHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

        def _write_json(self, payload, status=HTTPStatus.OK):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/sessions":
                return self._write_json(list_sessions(runs_dir))
            if path.startswith("/api/sessions/"):
                session_id = unquote(path.removeprefix("/api/sessions/"))
                try:
                    return self._write_json(read_session(runs_dir, session_id))
                except (FileNotFoundError, json.JSONDecodeError):
                    return self._write_json({"error": "审查会话不存在或审计产物损坏"}, HTTPStatus.NOT_FOUND)
            if path == "/":
                self.path = "/index.html"
            return super().do_GET()

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8"))
                if self.path == "/api/reviews": return self._write_json(jobs.review(body), HTTPStatus.ACCEPTED)
                if self.path == "/api/reviews/upload": return self._write_json(jobs.uploaded_review(body), HTTPStatus.ACCEPTED)
                if self.path == "/api/rules": return self._write_json(jobs.rule(body), HTTPStatus.ACCEPTED)
                if self.path.startswith("/api/jobs/"):
                    value = jobs.jobs.get(self.path.removeprefix("/api/jobs/")); return self._write_json(value or {"error":"作业不存在"}, HTTPStatus.OK if value else HTTPStatus.NOT_FOUND)
                return self._write_json({"error":"未知接口"}, HTTPStatus.NOT_FOUND)
            except (ValueError, json.JSONDecodeError) as err: return self._write_json({"error":str(err)}, HTTPStatus.BAD_REQUEST)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, format, *args):
            return

    return ReviewHandler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动 review-agent 本地只读工作台")
    parser.add_argument("--runs-dir", default="runs", help="审查会话目录，默认 runs")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认仅本机访问")
    parser.add_argument("--port", type=int, default=8765, help="端口，默认 8765")
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(Path(args.runs_dir).resolve()))
    print(f"Review Agent 工作台：http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
