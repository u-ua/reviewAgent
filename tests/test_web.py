from review_agent.web import _safe_session_name, list_sessions, read_session


def test_web_reads_only_a_single_session_directory(tmp_path):
    session = tmp_path / "demo"
    session.mkdir()
    (session / "execution.jsonl").write_text('{"seq": 1, "eventType": "run_started"}\n', encoding="utf-8")
    (session / "findings.json").write_text("[]", encoding="utf-8")

    assert [item["id"] for item in list_sessions(tmp_path)] == ["demo"]
    assert read_session(tmp_path, "demo")["events"][0]["seq"] == 1
    assert _safe_session_name("../secret") is None
    assert _safe_session_name("demo/child") is None
