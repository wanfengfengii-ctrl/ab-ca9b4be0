#!/usr/bin/env python3
"""判读接口烟测：等待依赖健康后，经 API 直连与 nginx 代理各跑一组有解/无解散例。

以退出码报告结果（0 通过，非 0 失败），供 compose verify 一次性服务使用。
环境变量：
  API_URL   默认 http://api:8000
  WEB_URL   默认 http://web:8080
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

API_URL = os.environ.get("API_URL", "http://api:8000")
WEB_URL = os.environ.get("WEB_URL", "http://web:8080")

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def wait_health(url: str, timeout: float = 60.0,
                path: str = "/health") -> bool:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + path, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception as exc:  # noqa: BLE001 - 烟测需覆盖全部启动竞态
            last = str(exc)
        time.sleep(1.5)
    print(f"健康等待超时：{url}{path}（{last}）")
    return False


def post(base: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        base + "/api/interpret",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def feasible_payload() -> dict:
    times = sorted([0, 50, 100, 150, 200]
                   + [7, 44, 81, 118, 155, 192])
    spec = {"period_min": 10, "period_max": 200,
            "tolerance": 2, "max_missing": 2}
    return {"times": times, "machine_a": spec, "machine_b": spec}


def infeasible_payload() -> dict:
    spec = {"period_min": 10, "period_max": 12,
            "tolerance": 0, "max_missing": 0}
    return {"times": [0, 13, 26, 39, 52, 65, 78, 91],
            "machine_a": spec, "machine_b": spec}


def assert_feasible(base: str, where: str) -> None:
    code, data = post(base, feasible_payload())
    check(f"{where}: 有解用例 HTTP 200", code == 200, f"code={code}")
    check(f"{where}: feasible=true", data.get("feasible") is True)
    sols = data.get("solutions") or []
    check(f"{where}: 至少一套见证", len(sols) >= 1)
    if sols:
        s = sols[0]
        periods_ok = (10 <= s["periods"]["A"] <= 200
                      and 10 <= s["periods"]["B"] <= 200)
        check(f"{where}: 周期为区间内整数", periods_ok,
              str(s.get("periods")))
        check(f"{where}: 每条脉冲都有归属字段",
              all(p.get("assignment") in ("A", "B", "noise")
                  for p in s["pulses"]) and len(s["pulses"]) == 11)
        check(f"{where}: 每台至少两条采用脉冲",
              s["machines"]["A"]["adopted_count"] >= 2
              and s["machines"]["B"]["adopted_count"] >= 2)
        for m in ("A", "B"):
            for seg in s["machines"][m]["segments"]:
                check(
                    f"{where}: {m} 段误差不越限",
                    abs(seg["error"]) <= seg["error_limit"],
                    str(seg))
        check(f"{where}: 漏收合计等于两台之和",
              s["missing_total"]
              == s["machines"]["A"]["missing_total"]
              + s["machines"]["B"]["missing_total"])


def assert_infeasible(base: str, where: str) -> None:
    code, data = post(base, infeasible_payload())
    check(f"{where}: 无解用例 HTTP 200", code == 200, f"code={code}")
    check(f"{where}: feasible=false", data.get("feasible") is False)
    check(f"{where}: 无见证残留（旧报告被清除）",
          data.get("solutions") == [])
    d = data.get("diagnosis") or {}
    check(f"{where}: 给出首个断点脉冲",
          d.get("index") == 0 and d.get("time") == 0, str(d))
    check(f"{where}: 给出候选设备原因",
          bool(d.get("reasons")) and
          all(r.get("device") in ("A", "B", "noise", "all")
              and r.get("message") for r in d["reasons"]),
          str(d.get("reasons")))


def assert_bad_request() -> None:
    code, _data = post(API_URL, {
        "times": [1, 2, 3, 4, 5, 6, 7],  # 不足 8 条
        "machine_a": feasible_payload()["machine_a"],
        "machine_b": feasible_payload()["machine_b"]})
    check("非法输入返回 422", code == 422, f"code={code}")


def assert_web_serves() -> None:
    try:
        with urllib.request.urlopen(WEB_URL + "/", timeout=5) as r:
            body = r.read().decode("utf-8", "ignore")
            check("前端首页 200", r.status == 200)
            check("前端产物已内联（无外部 src 引用）",
                  'src="src/' not in body and "双应答机" in body)
    except Exception as exc:  # noqa: BLE001
        check("前端首页可访问", False, str(exc))


def main() -> int:
    print(f"等待 API 健康：{API_URL}")
    if not wait_health(API_URL, path="/health"):
        return 2
    print(f"等待 WEB 健康：{WEB_URL}")
    if not wait_health(WEB_URL, path="/"):
        return 2

    assert_feasible(API_URL, "API 直连")
    assert_infeasible(API_URL, "API 直连")
    assert_bad_request()
    assert_web_serves()
    assert_feasible(WEB_URL, "经 nginx 代理")
    assert_infeasible(WEB_URL, "经 nginx 代理")

    if FAILURES:
        print(f"\n烟测失败 {len(FAILURES)} 项：{FAILURES}")
        return 1
    print("\n全部烟测通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
