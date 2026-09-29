"""API 层测试（使用 FastAPI TestClient，无需真实端口）。"""
from fastapi.testclient import TestClient

from app.api import app

client = TestClient(app)


def spec(lo=10, hi=200, tol=1, miss=1):
    return {"period_min": lo, "period_max": hi, "tolerance": tol,
            "max_missing": miss}


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_interpret_success_structure():
    times = sorted([0, 50, 100, 150, 200] + [7, 44, 81, 118, 155, 192])
    r = client.post("/api/interpret", json={
        "times": times, "machine_a": spec(), "machine_b": spec()})
    assert r.status_code == 200
    data = r.json()
    assert data["feasible"]
    s = data["solutions"][0]
    assert set(s["periods"]) == {"A", "B"}
    assert len(s["pulses"]) == len(times)
    for p in s["pulses"]:
        assert set(p) >= {"index", "time", "assignment", "cycles",
                          "missing_before", "segment_error"}
        assert p["assignment"] in ("A", "B", "noise")
    assert {"A", "B"} <= set(s["machines"])
    for m in ("A", "B"):
        mach = s["machines"][m]
        assert mach["adopted_count"] >= 2
        for seg in mach["segments"]:
            assert seg["cycles"] >= 1
            assert abs(seg["error"]) <= seg["error_limit"]


def test_interpret_tie_fields():
    times = list(range(0, 32, 2))  # 16 条，多种等优归属
    r = client.post("/api/interpret", json={
        "times": times, "machine_a": spec(tol=0, miss=0),
        "machine_b": spec(tol=0, miss=0)})
    data = r.json()
    assert data["feasible"] and data["tied"]
    assert len(data["solutions"]) == 2
    if data["first_divergence"]["index"] is not None:
        d = data["first_divergence"]
        l1 = [p["assignment"] for p in data["solutions"][0]["pulses"]]
        l2 = [p["assignment"] for p in data["solutions"][1]["pulses"]]
        i = d["index"]
        assert l1[i] != l2[i]


def test_interpret_infeasible_diagnosis():
    times = [0, 13, 26, 39, 52, 65, 78, 91]
    r = client.post("/api/interpret", json={
        "times": times,
        "machine_a": spec(lo=10, hi=12, tol=0, miss=0),
        "machine_b": spec(10, 12, 0, 0)})
    assert r.status_code == 200
    data = r.json()
    assert not data["feasible"]
    assert data["solutions"] == []
    d = data["diagnosis"]
    assert d["index"] == 0
    assert d["time"] == 0
    assert len(d["reasons"]) >= 1
    for reason in d["reasons"]:
        assert reason["message"]


def test_bad_payloads():
    base = {"machine_a": spec(), "machine_b": spec()}

    # 脉冲数不足
    r = client.post("/api/interpret",
                    json={**base, "times": [1, 2, 3, 4, 5, 6, 7]})
    assert r.status_code == 422

    # 非严格递增
    r = client.post("/api/interpret",
                    json={**base, "times": [1, 2, 2, 4, 5, 6, 7, 8]})
    strict_r = client.post("/api/interpret",
                           json={**base, "times": [1, 2, 2, 4, 5, 6, 7, 8]})
    assert strict_r.status_code == 422

    # 周期区间反向
    bad_spec = spec()
    bad_spec["period_max"] = 9
    r = client.post("/api/interpret",
                    json={"times": [0, 10, 20, 30, 40, 50, 60, 70],
                          "machine_a": bad_spec, "machine_b": spec()})
    assert r.status_code == 422

    # 字段越界
    bad2 = spec()
    bad2["max_missing"] = 999
    r = client.post("/api/interpret",
                    json={"times": [0, 10, 20, 30, 40, 50, 60, 70],
                          "machine_a": bad2, "machine_b": spec()})
    assert r.status_code == 422
