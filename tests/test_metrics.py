from review_agent.metrics import build_metrics


def event(kind, payload=None, **extra):
    return {"eventType": kind, "role": "executor", "payload": payload or {}, **extra}


def finding(kind, **args):
    return event(kind, {"args": args, "dimension": args.get("dimension", "security"), "rejectionReason": args.get("reason")})


def test_finding_acceptance_and_rejection_are_attempts():
    m = build_metrics([finding("finding_accepted", severity="high", path="a.py", dimension="security"), finding("finding_rejected", reason="missing_evidence")])
    assert m["findings"]["total"] == 1
    assert m["findings"]["bySeverity"] == {"high": 1}
    assert m["evidenceValidity"]["attempts"] == 2
    assert m["evidenceValidity"]["rate"] == 0.5


def test_no_finding_attempt_means_null_evidence_rate():
    assert build_metrics([])["evidenceValidity"]["rate"] is None


def test_authorization_interception_and_no_attempt_na():
    m = build_metrics([event("tool_access_decision", {"reason": "path_traversal", "allowed": False, "blocked": True})])
    assert m["authorizationInterception"]["rate"] == 1
    assert m["authorizationInterception"]["byReason"]["path_traversal"]["attempts"] == 1
    assert build_metrics([])["authorizationInterception"]["rate"] is None


def test_authorization_rate_uses_decisions_not_blocks_as_its_denominator():
    events = [
        event("tool_access_decision", {"reason": "outside_scope", "allowed": False, "blocked": True}),
        event("tool_access_decision", {"reason": "outside_scope", "allowed": False, "blocked": False}),
        event("tool_access_blocked", {"reason": "outside_scope", "blocked": True}),
    ]
    m = build_metrics(events)["authorizationInterception"]
    assert (m["attempts"], m["blocked"], m["rate"]) == (2, 1, 0.5)


def test_task_duration_aggregates_by_dimension():
    events = [event("task_started", taskId="a", epochId="1", elapsedMs=10), event("task_finished", {"dimension":"security"}, taskId="a", epochId="1", elapsedMs=30), event("task_started", taskId="b", epochId="2", elapsedMs=40), event("task_finished", {"dimension":"logic"}, taskId="b", epochId="2", elapsedMs=70)]
    m = build_metrics(events)
    assert m["durationsMs"]["averageTask"] == 25
    assert m["durationsMs"]["byDimensionAverageTask"] == {"security": 20, "logic": 30}


def test_provider_usage_pricing_and_missing_usage():
    events = [event("llm_call", {"success":True,"model":"m","usage":{"promptTokens":100,"completionTokens":50,"totalTokens":150},"durationMs":8}), event("llm_call", {"success":True,"model":"unknown","usage":None,"durationMs":9}), event("llm_call", {"success":False,"model":"m","usage":{"promptTokens":999,"completionTokens":999,"totalTokens":1998}})]
    m = build_metrics(events, {"m":{"inputPer1K":2,"outputPer1K":4}})
    assert m["tokens"]["promptTokens"] == 100
    assert m["tokens"]["totalTokens"] == 150
    assert m["cost"]["total"] is None
    only_priced = build_metrics(events[:1], {"m":{"inputPer1K":2,"outputPer1K":4}})
    assert only_priced["cost"]["total"] == 0.4
    assert build_metrics(events[:1])["cost"]["total"] is None


def test_all_successful_calls_missing_usage_are_null_not_zero():
    m = build_metrics([event("llm_call", {"success": True, "model": "m", "usage": None})])
    assert m["tokens"]["status"] == "unavailable"
    assert m["tokens"]["promptTokens"] is None
    assert m["tokens"]["completionTokens"] is None
    assert m["tokens"]["totalTokens"] is None


def test_no_llm_calls_has_no_cost_fact():
    assert build_metrics([])["cost"]["total"] is None


def test_partial_usage_keeps_known_sum_and_marks_partial():
    events = [
        event("llm_call", {"success": True, "model": "m", "usage": {"promptTokens": 10, "completionTokens": 5, "totalTokens": 15}}),
        event("llm_call", {"success": True, "model": "m", "usage": None}),
    ]
    m = build_metrics(events)["tokens"]
    assert (m["promptTokens"], m["completionTokens"], m["totalTokens"]) == (10, 5, 15)
    assert m["status"] == "partial"
    assert m["usageAvailableCalls"] == {"promptTokens": 1, "completionTokens": 1, "totalTokens": 1}


def test_legacy_events_produce_partial_metrics():
    m = build_metrics([{"eventType":"tool_call", "role":"executor"}])
    assert m["findings"]["total"] == 0
    assert m["durationsMs"]["session"] is None
