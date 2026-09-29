"""求解器单元测试与暴力交叉验证。"""
import random

import pytest

from app.solver import (interpret, feasible_k, MachineSpec, solve,
                        A, B, NOISE, LABEL_NAME)
from tests.brute import brute_optimal, brute_witness_keys


# --------------------------------------------------------------------------
# feasible_k 数学条件
# --------------------------------------------------------------------------

@pytest.mark.parametrize("gap,p,tol,cap,expected", [
    (50, 50, 0, 1, 1),
    (100, 50, 0, 2, 2),
    (101, 50, 0, 2, None),
    (52, 50, 2, 1, 1),
    (53, 50, 2, 1, None),
    (103, 50, 2, 2, 2),          # 误差按周期数线性累积
    (104, 50, 2, 2, 2),          # |104-100|=4 <= 2*2，边界等号成立
    (105, 50, 2, 2, None),       # 5 > 4
    (180, 60, 1, 3, 3),          # k=3, |180-180|=0；k=2 超差
    (182, 60, 1, 3, 3),          # |182-180|=2 <= 3
    (183, 60, 1, 3, 3),          # 边界等号：|183-180|=3 <= 3
    (184, 60, 1, 3, None),       # 4 > 3
    (500, 50, 0, 2, None),       # k=10 超过漏收额度（cap=2）
    (49, 50, 2, 1, 1),
])
def test_feasible_k(gap, p, tol, cap, expected):
    assert feasible_k(gap, p, tol, cap) == expected


# --------------------------------------------------------------------------
# 场景：两台干净应答机
# --------------------------------------------------------------------------

def test_two_clean_machines():
    ta = [0, 50, 100, 150, 200]
    tb = [7, 44, 81, 118, 155, 192]
    times = sorted(ta + tb)
    r = interpret(times,
                  dict(period_min=10, period_max=200, tolerance=2,
                       max_missing=1),
                  dict(period_min=10, period_max=200, tolerance=2,
                       max_missing=1))
    assert r.feasible
    s = r.solutions[0]
    assert s["noise_count"] == 0
    assert s["missing_total"] == 0
    assert set(s["periods"].values()) >= {35}  # 至少承认真实结构中的周期
    got = {p["time"]: p["assignment"] for p in s["pulses"]}
    assert len({v for v in got.values() if v != "noise"}) == 2
    # 每台 ≥2 条
    assert s["machines"]["A"]["adopted_count"] >= 2
    assert s["machines"]["B"]["adopted_count"] >= 2


def test_missing_pulses_long_gap_not_misassigned():
    """B: 0,60,[120 漏收],180,240（p≈59）；A: 5 起周期 43 全收。

    全局求解不得把 180 这条因长间隔就近错接到另一台设备；
    p=59 与 p=60 对该数据同为最优（误差边界等号），属真实并列。
    """
    times = sorted([0, 60, 180, 240]
                   + [5, 48, 91, 134, 177, 220, 263, 306])
    r = interpret(times,
                  dict(period_min=10, period_max=200, tolerance=1,
                       max_missing=2),
                  dict(period_min=10, period_max=200, tolerance=1,
                       max_missing=2))
    assert r.feasible
    s = r.solutions[0]
    assert s["noise_count"] == 0
    assert s["missing_total"] == 1
    periods = s["periods"]
    by_time = {p["time"]: p for p in s["pulses"]}
    # 0/60/180/240 必须同台，且 180 前补 1 个漏收（cycles=2）
    lab0 = by_time[0]["assignment"]
    for t in (60, 180, 240):
        assert by_time[t]["assignment"] == lab0
    assert by_time[180]["cycles"] == 2
    assert by_time[180]["missing_before"] == 1
    assert abs(by_time[180]["segment_error"]) <= 2
    # 另一台周期为 43（tol=1 下 42 同为最优见证，故 42/43 均可）
    other = "B" if lab0 == "A" else "A"
    assert periods[other] in (42, 43)
    # 真实并列仅周期不同：第一条归属分歧为空，但周期说明非空
    if r.tied:
        assert r.first_divergence["period_note"]


def test_noise_pulses_are_rejected():
    # 干净两机（各 7 条）+ 2 条贴近但错误的噪声
    ta = [100, 150, 200, 250, 300, 350, 400]
    tb = [112, 161, 210, 259, 308, 357, 406]
    times = sorted(ta + tb + [153, 403])
    r = interpret(times,
                  dict(period_min=10, period_max=200, tolerance=1,
                       max_missing=0),
                  dict(period_min=10, period_max=200, tolerance=1,
                       max_missing=0))
    assert r.feasible
    s = r.solutions[0]
    assert s["noise_count"] == 2
    noise_times = {p["time"] for p in s["pulses"]
                   if p["assignment"] == "noise"}
    assert noise_times == {153, 403}


def test_objective_noise_first_then_missing():
    """噪声最少优先于漏收最少：用小实例暴力核验目标层。"""
    times = [0, 10, 40, 70, 100, 130, 160, 190]
    specs = (MachineSpec(25, 45, 0, 5), MachineSpec(25, 45, 0, 5))
    r = solve(times, specs)
    s = r.solutions[0]
    brute = brute_optimal(times, specs)
    assert (s["noise_count"], s["missing_total"]) == brute
    assert s["noise_count"] == 0
    assert s["missing_total"] == 1


# --------------------------------------------------------------------------
# 并列：两套完整见证 + 第一条归属分歧
# --------------------------------------------------------------------------

def test_tie_reports_two_witnesses_and_divergence():
    # 交替等差数列天然有两种等优归属（周期 2 与周期 4 等）
    times = list(range(0, 32, 2))  # 16 条，间隔 2
    r = interpret(times,
                  dict(period_min=10, period_max=200, tolerance=0,
                       max_missing=0),
                  dict(period_min=10, period_max=200, tolerance=0,
                       max_missing=0))
    assert r.feasible
    assert r.tied
    assert len(r.solutions) == 2
    l1 = [p["assignment"] for p in r.solutions[0]["pulses"]]
    l2 = [p["assignment"] for p in r.solutions[1]["pulses"]]
    d = r.first_divergence
    assert d["index"] is not None
    i = d["index"]
    assert l1[i] != l2[i]
    assert all(l1[k] == l2[k] for k in range(i))
    assert d["labels"] == [l1[i], l2[i]]
    # 两套见证各自完整合法
    for sol in r.solutions:
        for m in ("A", "B"):
            assert sol["machines"][m]["adopted_count"] >= 2


def test_unique_solution_not_tied():
    # 取互质感强的周期与抖动，使周期唯一
    ta = [3, 53, 103, 153]
    tb = [11, 74, 137, 200]
    times = sorted(ta + tb)
    r = interpret(times,
                  dict(period_min=10, period_max=200, tolerance=0,
                       max_missing=0),
                  dict(period_min=10, period_max=200, tolerance=0,
                       max_missing=0))
    assert r.feasible
    assert not r.tied
    assert set(r.solutions[0]["periods"].values()) == {50, 63}


# --------------------------------------------------------------------------
# 无解诊断
# --------------------------------------------------------------------------

def test_infeasible_reports_first_blocking_pulse():
    # 8 条等间隔 13 的脉冲，周期区间只允许 10..12 且无误差、无漏收：
    # 任意两条脉冲都无法为任一台设备建立整数周期锚点，
    # 第一条脉冲起就不存在可延续的联合解释。
    times = [0, 13, 26, 39, 52, 65, 78, 91]
    r = interpret(times,
                  dict(period_min=10, period_max=12, tolerance=0,
                       max_missing=0),
                  dict(period_min=10, period_max=12, tolerance=0,
                       max_missing=0))
    assert not r.feasible
    d = r.diagnosis
    assert d["index"] == 0
    assert d["time"] == 0
    assert d["pulse_no"] == 1
    devices = {reason["device"] for reason in d["reasons"]}
    assert {"A", "B", "noise"} <= devices


def test_diagnosis_pulse_is_first_unextendible_in_time_order():
    # 0 可作首锚；到 t=50 时：与 0 形成 p=50 只够锚一台，另一台在其后的
    # 301..305 簇与前面任何脉冲都凑不出 45..55 的相容配对——
    # 无论把 50 归为噪声还是归属任一台，都无法延续，故断点为第 2 条。
    times = [0, 50, 100, 301, 302, 303, 304, 305]
    r = interpret(times,
                  dict(period_min=45, period_max=55, tolerance=0,
                       max_missing=0),
                  dict(period_min=45, period_max=55, tolerance=0,
                       max_missing=0))
    assert not r.feasible
    d = r.diagnosis
    assert d["index"] == 1
    assert d["time"] == 50
    assert d["pulse_no"] == 2
    devices = {reason["device"] for reason in d["reasons"]}
    assert {"A", "B", "noise"} <= devices
    for reason in d["reasons"]:
        assert reason["message"]


# --------------------------------------------------------------------------
# 输入校验
# --------------------------------------------------------------------------

@pytest.mark.parametrize("times,msg", [
    ([1, 2, 3, 4, 5, 6, 7], "8 至 16"),
    ([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17], "8 至 16"),
    ([1, 2, 2, 4, 5, 6, 7, 8], "严格递增"),
    ([1, 9, 3, 4, 5, 6, 7, 8], "严格递增"),
])
def test_invalid_pulse_inputs(times, msg):
    with pytest.raises(ValueError, match=msg):
        interpret(times,
                  dict(period_min=10, period_max=200, tolerance=1,
                       max_missing=1),
                  dict(period_min=10, period_max=200, tolerance=1,
                       max_missing=1))


@pytest.mark.parametrize("field,val", [
    ("period_min", 9), ("period_max", 201), ("period_max", 9),
    ("tolerance", -1), ("max_missing", -1), ("max_missing", 201),
])
def test_invalid_spec(field, val):
    spec = dict(period_min=10, period_max=200, tolerance=1, max_missing=1)
    spec[field] = val
    with pytest.raises(ValueError):
        interpret([0, 10, 20, 30, 40, 50, 60, 70], spec,
                  dict(period_min=10, period_max=200, tolerance=1,
                       max_missing=1))


# --------------------------------------------------------------------------
# 输出结构与逐段误差
# --------------------------------------------------------------------------

def test_solution_structure_and_segment_errors():
    times = sorted([0, 51, 100, 152, 201] + [7, 44, 82, 118, 155, 192])
    r = interpret(times,
                  dict(period_min=10, period_max=200, tolerance=2,
                       max_missing=1),
                  dict(period_min=10, period_max=200, tolerance=2,
                       max_missing=1))
    assert r.feasible
    s = r.solutions[0]
    assert len(s["pulses"]) == len(times)
    for p in s["pulses"]:
        assert p["assignment"] in ("A", "B", "noise")
    for m in ("A", "B"):
        mach = s["machines"][m]
        cum = 0
        for seg in mach["segments"]:
            assert seg["cycles"] >= 1
            assert seg["error"] == seg["gap"] - seg["cycles"] * mach["period"]
            assert abs(seg["error"]) <= seg["error_limit"]
            cum += seg["missing"]
        assert cum == mach["missing_total"] <= 1
    assert (s["machines"]["A"]["missing_total"]
            + s["machines"]["B"]["missing_total"]
            == s["missing_total"])


def test_deterministic():
    times = sorted([0, 50, 100, 150, 200] + [7, 44, 81, 118, 155, 192])
    kw = dict(period_min=10, period_max=200, tolerance=2, max_missing=1)
    r1 = interpret(times, dict(kw), dict(kw))
    r2 = interpret(times, dict(kw), dict(kw))
    key = lambda r: [(p["time"], p["assignment"]) for p in
                     r.solutions[0]["pulses"]]
    assert key(r1) == key(r2)


# --------------------------------------------------------------------------
# 暴力交叉验证（小规模随机实例）
# --------------------------------------------------------------------------

def test_random_instances_match_bruteforce():
    random.seed(42)
    spec_pair = (
        (MachineSpec(10, 24, 1, 2), MachineSpec(10, 24, 1, 2)),
        (MachineSpec(10, 22, 0, 1), MachineSpec(10, 22, 0, 1)),
        (MachineSpec(12, 28, 2, 3), MachineSpec(12, 28, 2, 3)),
        (MachineSpec(10, 24, 0, 0), MachineSpec(15, 30, 1, 2)),
    )
    for trial in range(8):
        specs = spec_pair[trial % len(spec_pair)]
        n = 8
        times = sorted(random.sample(range(0, 260), n))
        r = solve(times, specs)
        brute, wit_keys = brute_witness_keys(times, specs)
        if brute is None:
            assert not r.feasible, (times, "求解器报有解但暴力无解")
            assert r.diagnosis["index"] < n
            continue
        assert r.feasible, (times, "求解器无解但暴力有解", brute)
        s = r.solutions[0]
        assert (s["noise_count"], s["missing_total"]) == brute, (
            times, (s["noise_count"], s["missing_total"]), brute)
        # 并列标志必须与规范化后的暴力见证集一致
        assert r.tied == (len(wit_keys) >= 2), (
            times, len(wit_keys), r.tied)
        # 报告的每套见证都必须是暴力见证集的成员
        for sol in r.solutions:
            ia = tuple(p["index"] for p in sol["pulses"]
                       if p["assignment"] == "A")
            ib = tuple(p["index"] for p in sol["pulses"]
                       if p["assignment"] == "B")
            p1, p2 = sol["periods"]["A"], sol["periods"]["B"]
            if specs[0] == specs[1]:
                mach = sorted(((p1, ia), (p2, ib)),
                              key=lambda x: (x[0], x[1]))
                key = (mach[0][0], mach[1][0], mach[0][1], mach[1][1])
            else:
                key = (p1, p2, ia, ib)
            assert key in wit_keys, (times, key)
