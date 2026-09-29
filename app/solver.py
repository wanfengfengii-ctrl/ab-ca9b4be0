"""固定双整数周期联合判读的分支限界搜索，以及无解时的首个断点诊断。

状态机（单台设备）：
  ac=0 尚未采用任何脉冲
  ac=1 已采用 1 条脉冲（首锚），周期尚未固定
  ac=2 已采用 ≥2 条脉冲，周期在第二锚点一次性固定，此后不可更改

同一台相邻采用脉冲 (t_u, t_v) 必须存在正整数 k（周期个数）满足
    |(t_v - t_u) - k*p| <= tol * k
且该台累计漏收 Σ(k-1) 不超过 max_missing。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

A, B, NOISE = 0, 1, 2
LABEL_NAME = {A: "A", B: "B", NOISE: "noise"}


@dataclass(frozen=True)
class MachineSpec:
    lo: int
    hi: int
    tol: int
    max_missing: int


@dataclass
class InterpretationResult:
    feasible: bool
    solutions: list[dict] = field(default_factory=list)
    tied: bool = False
    first_divergence: Optional[dict] = None
    diagnosis: Optional[dict] = None


# --------------------------------------------------------------------------
# 基本工具
# --------------------------------------------------------------------------

def feasible_k(gap: int, p: int, tol: int, k_cap: int) -> Optional[int]:
    """满足 |gap - k*p| <= tol*k 的最小正整数 k，且 k <= k_cap；无解 None。

    条件等价于 gap/(p+tol) <= k <= gap/(p-tol)（p<=tol 时上界为无穷）。
    """
    if k_cap < 1 or gap <= 0:
        return None
    k = max(1, (gap + p + tol - 1) // (p + tol))
    if k > k_cap:
        return None
    if p - tol > 0 and gap < k * (p - tol):
        return None
    return k


def candidate_periods(n: int, pair_gaps: list[list[Optional[int]]],
                      spec: MachineSpec) -> list[int]:
    """存在某对脉冲可为该周期建立两个锚点的周期（否则该周期不可能参与解）。"""
    out = []
    cap = spec.max_missing + 1
    for p in range(spec.lo, spec.hi + 1):
        for u in range(n):
            for v in range(u + 1, n):
                g = pair_gaps[u][v]
                if g is not None and feasible_k(g, p, spec.tol, cap):
                    out.append(p)
                    break
            else:
                continue
            break
    return out


def single_machine_coverage(n, gaps, p, spec) -> int:
    """放宽为单机（忽略另一台）时，周期 p 最多能采用多少条脉冲。"""
    best = [1] * n  # 以 j 结尾的最长采用链
    for j in range(n):
        for u in range(j):
            if feasible_k(gaps[u][j], p, spec.tol,
                          spec.max_missing + 1) is not None:
                if best[u] + 1 > best[j]:
                    best[j] = best[u] + 1
    return max(best) if n else 0


# --------------------------------------------------------------------------
# 固定周期对的分层 DP
# --------------------------------------------------------------------------
# 规范化状态键：(ac1,last1, ac2,last2)，last=-1 表示尚无锚点
# 每个键挂一条三维帕累托前沿，记录 (assigned, m1, m2, ...)：
# assigned 更大、某机漏收更小且另一维不更大者占优。同锚点位置上，把中间
# 脉冲改为噪声只会增加噪声而不改变后续可行转移，故该前沿对最优解完备。

def solve_pair(times, gaps, trans1, trans2, specs,
               incumbent: Optional[tuple[int, int]]
               ) -> Optional[list[tuple[list[int], dict]]]:
    """固定周期对的分层 DP；返回至多两套目标并列的最优归属，无解 None。"""
    n = len(times)
    trans = (trans1, trans2)
    start_key = (0, -1, 0, -1)
    # rec: (assigned, m1, m2, prev_key, prev_rec_idx, action, k)
    layers = [{start_key: [(0, 0, 0, None, -1, NOISE, 0)]}]

    for j in range(n):
        prev = layers[-1]
        bucket: dict[tuple, list[tuple]] = {}

        for key, recs in prev.items():
            ac1, l1, ac2, l2 = key
            for ri, rec in enumerate(recs):
                assigned, m1, m2 = rec[0], rec[1], rec[2]
                # 动作 1：作为噪声，状态不变
                bucket.setdefault(key, []).append(
                    (assigned, m1, m2, key, ri, NOISE, 0))
                # 动作 2/3：归属某台
                _try_attach(bucket, key, ri, rec, j, A, ac1, l1, m1,
                            gaps, trans[0], specs[0])
                _try_attach(bucket, key, ri, rec, j, B, ac2, l2, m2,
                            gaps, trans[1], specs[1])

        cur: dict[tuple, list[tuple]] = {}
        b_noise = incumbent[0] if incumbent else None
        b_miss = incumbent[1] if incumbent else None
        for key, recs in bucket.items():
            # 三维帕累托前沿；同一等优点保留至多 2 条记录，使前缀处分歧的
            # 两套等优归属都能回溯（记录各自指向不同父记录）。
            front: list[tuple] = []
            for r in recs:
                equal = None
                dominated = False
                for q in front:
                    if q[0] == r[0] and q[1] == r[1] and q[2] == r[2]:
                        equal = q
                    if q[0] >= r[0] and q[1] <= r[1] and q[2] <= r[2]:
                        dominated = True
                if equal is not None:
                    if sum(1 for q in front
                           if q[0] == r[0] and q[1] == r[1]
                           and q[2] == r[2]) < 2:
                        front.append(r)
                    continue
                if dominated:
                    continue
                front = [q for q in front
                         if not (r[0] >= q[0] and r[1] <= q[1]
                                 and r[2] <= q[2])]
                front.append(r)
            if b_noise is not None:
                front = [r for r in front
                         if (j + 1 - r[0]) < b_noise
                         or ((j + 1 - r[0]) == b_noise
                             and r[1] + r[2] <= b_miss)]
                if not front:
                    continue
            # 锚点余量剪枝：剩余脉冲不够两台补齐两个锚点
            remaining = n - (j + 1)
            ac1, _l1, ac2, _l2 = key
            need = ((2 if ac1 == 0 else 1 if ac1 == 1 else 0)
                    + (2 if ac2 == 0 else 1 if ac2 == 1 else 0))
            if remaining < need:
                continue
            cur[key] = front
        layers.append(cur)

    finals = [r for key, recs in layers[n].items()
              if key[0] == 2 and key[2] == 2 for r in recs]
    if not finals:
        return None

    def score(r):
        return (n - r[0], r[1] + r[2])

    best_score = min(score(r) for r in finals)
    best_recs = [r for r in finals if score(r) == best_score][:2]
    out = []
    for best_rec in best_recs:
        best_key = next(k for k, recs in layers[n].items()
                        if best_rec in recs)
        labels = [0] * n
        seg_k: dict[tuple, int] = {}
        key, rec = best_key, best_rec
        for j in range(n - 1, -1, -1):
            action, k = rec[5], rec[6]
            labels[j] = action
            if action in (A, B) and k:
                seg_k[(action, j)] = k
            key, rec_idx = rec[3], rec[4]
            rec = layers[j][key][rec_idx] if rec_idx >= 0 else None
        out.append((labels, seg_k))
    return out


def _try_attach(bucket, key, ri, rec, j, m, ac, last, miss,
                gaps, trans, spec):
    assigned = rec[0]
    nk = list(key)
    if ac == 0:
        nk[2 * m] = 1
        nk[2 * m + 1] = j
        new_key = tuple(nk)
        if m == A:
            new = (assigned + 1, miss, rec[2], key, ri, m, 0)
        else:
            new = (assigned + 1, rec[1], miss, key, ri, m, 0)
        bucket.setdefault(new_key, []).append(new)
        return
    cap = (spec.max_missing + 1) if ac == 1 else \
        (spec.max_missing - miss + 1)
    # trans 以间隔值为键，给出最小可行 k
    k = trans_get(trans, gaps[last][j], cap)
    if k is None:
        return
    nk[2 * m] = 2
    nk[2 * m + 1] = j
    new_miss = miss + (k - 1)
    new_key = tuple(nk)
    if m == A:
        new = (assigned + 1, new_miss, rec[2], key, ri, m, k)
    else:
        new = (assigned + 1, rec[1], new_miss, key, ri, m, k)
    bucket.setdefault(new_key, []).append(new)


def trans_get(trans, gap, cap):
    """trans: dict gap->最小可行 k；再与 cap 比较。"""
    k = trans.get(gap)
    if k is None or k > cap:
        return None
    return k


def build_transition(gaps, p, spec):
    """对实际出现的间隔预计算最小可行 k（cap=max_missing+1）。"""
    cap = spec.max_missing + 1
    out = {}
    seen = set()
    for row in gaps:
        for g in row:
            if g is None or g in seen:
                continue
            seen.add(g)
            k = feasible_k(g, p, spec.tol, cap)
            if k is not None:
                out[g] = k
    return out


# --------------------------------------------------------------------------
# 解的装配
# --------------------------------------------------------------------------

def build_solution(times, p1, p2, labels, seg_k, specs) -> dict:
    periods = (p1, p2)
    machines = {}
    for m in (A, B):
        spec = specs[m]
        idx = [i for i, l in enumerate(labels) if l == m]
        segments = []
        missing_total = 0
        for u, v in zip(idx, idx[1:]):
            k = seg_k[(m, v)]
            missing = k - 1
            missing_total += missing
            segments.append({
                "from_index": u,
                "to_index": v,
                "from_time": times[u],
                "to_time": times[v],
                "gap": times[v] - times[u],
                "cycles": k,
                "expected_gap": k * periods[m],
                "error": times[v] - times[u] - k * periods[m],
                "error_limit": spec.tol * k,
                "missing": missing,
            })
        machines[m] = {
            "period": periods[m],
            "adopted_indices": idx,
            "adopted_count": len(idx),
            "missing_total": missing_total,
            "segments": segments,
        }

    pulses = []
    for i, t in enumerate(times):
        row = {"index": i, "time": t, "assignment": LABEL_NAME[labels[i]]}
        if labels[i] == NOISE:
            row["cycles"] = None
            row["missing_before"] = None
            row["segment_error"] = None
        else:
            m = labels[i]
            seg = next((s for s in machines[m]["segments"]
                        if s["to_index"] == i), None)
            row["cycles"] = seg["cycles"] if seg else None
            row["missing_before"] = seg["missing"] if seg else 0
            row["segment_error"] = seg["error"] if seg else None
        pulses.append(row)

    return {
        "periods": {"A": p1, "B": p2},
        "pulses": pulses,
        "machines": {"A": machines[A], "B": machines[B]},
        "noise_count": sum(1 for l in labels if l == NOISE),
        "missing_total": machines[A]["missing_total"]
        + machines[B]["missing_total"],
    }


# --------------------------------------------------------------------------
# 顶层搜索
# --------------------------------------------------------------------------

def solve(times: list[int], specs: tuple[MachineSpec, MachineSpec]
          ) -> InterpretationResult:
    n = len(times)
    gaps = [[None] * n for _ in range(n)]
    for u in range(n):
        for v in range(u + 1, n):
            gaps[u][v] = times[v] - times[u]

    cand = (candidate_periods(n, gaps, specs[0]),
            candidate_periods(n, gaps, specs[1]))
    if not cand[0] or not cand[1]:
        return InterpretationResult(False, diagnosis=diagnose(times, specs))

    # 单机最大覆盖（并集上界）+ 直接相邻可解释对数，用于剪枝与搜索顺序
    def stats(p, spec):
        cover = single_machine_coverage(n, gaps, p, spec)
        direct = 0
        for u in range(n):
            for v in range(u + 1, n):
                if feasible_k(gaps[u][v], p, spec.tol, 1) is not None:
                    direct += 1
        return cover, direct

    info = [{p: stats(p, specs[m]) for p in cand[m]} for m in (A, B)]
    # 每个候选周期的间隔转移表只建一次
    trans = [{p: build_transition(gaps, p, specs[m]) for p in cand[m]}
             for m in (A, B)]
    cand[0].sort(key=lambda p: (info[0][p][0], info[0][p][1], -p),
                 reverse=True)
    cand[1].sort(key=lambda p: (info[1][p][0], info[1][p][1], -p),
                 reverse=True)

    best_obj: Optional[tuple[int, int]] = None
    # 同目标层只保留确定性排序（周期对、归属串字典序）下最小的两套见证；
    # 候选逐个到达时有序插入即可，无需缓存全部并列解。
    store: list[tuple] = []

    def keep_witness(wit: tuple) -> None:
        sig = (wit[0], wit[1], wit[2])
        if any((w[0], w[1], w[2]) == sig for w in store):
            return  # 规范化标签后可能与已有见证完全相同
        for i, w in enumerate(store):
            if sig < (w[0], w[1], w[2]):
                store.insert(i, wit)
                break
        else:
            store.append(wit)
        if len(store) > 2:
            store.pop()

    # 同参数时标签可互换：只枚举无序周期对 p1<=p2（不加首锚约束，允许任意
    # 归属），标签互换解自然去重；参数不同时枚举全部有序对。
    symmetric = specs[0] == specs[1]
    for p1 in cand[0]:
        c1 = info[0][p1][0]
        for p2 in cand[1]:
            if symmetric and p2 < p1:
                continue
            c2 = info[1][p2][0]
            # 单机覆盖并集上界：不可能击败现任最优则跳过
            if best_obj is not None and c1 + c2 < n - best_obj[0]:
                continue
            res = solve_pair(times, gaps, trans[0][p1], trans[1][p2],
                             specs, best_obj)
            if res is None:
                continue
            for labels, seg_k in res:
                labels = list(labels)
                # 同周期且两台参数相同：按“首条采用脉冲归 A”规范化标签，
                # 消除 A/B 标签互换造成的伪并列。
                if symmetric and p1 == p2:
                    first_adopt = next((i for i, l in enumerate(labels)
                                        if l != NOISE), None)
                    if first_adopt is not None and labels[first_adopt] == B:
                        labels = [B if l == A else A if l == B else l
                                  for l in labels]
                        seg_k = {(B if m == A else A if m == B else m, i): k
                                 for (m, i), k in seg_k.items()}
                noise = labels.count(NOISE)
                miss = sum(kv - 1 for _key, kv in seg_k.items())
                obj = (noise, miss)
                wit = (p1, p2, tuple(labels),
                       tuple(sorted(seg_k.items())))
                if best_obj is None or obj < best_obj:
                    best_obj = obj
                    store = [wit]
                elif obj == best_obj:
                    keep_witness(wit)

    if best_obj is None:
        return InterpretationResult(False, diagnosis=diagnose(times, specs))

    # store 已按（周期对、归属串）字典序保持前两套，直接取用
    picks = store
    solutions = []
    for p1, p2, lab, sk in picks:
        seg_k = {tuple(kkey): kv for kkey, kv in sk}
        solutions.append(build_solution(times, p1, p2, list(lab),
                                        seg_k, specs))

    divergence = None
    if len(picks) >= 2:
        l1, l2 = picks[0][2], picks[1][2]
        idx = next((i for i in range(n)
                    if LABEL_NAME[l1[i]] != LABEL_NAME[l2[i]]), None)
        if (picks[0][0], picks[0][1]) != (picks[1][0], picks[1][1]):
            period_note = ("两套见证周期不同：A=%d/B=%d 对比 A=%d/B=%d"
                           % (picks[0][0], picks[0][1],
                              picks[1][0], picks[1][1]))
        else:
            period_note = None
        divergence = {
            "index": idx,
            "time": times[idx] if idx is not None else None,
            "labels": ([LABEL_NAME[l1[idx]], LABEL_NAME[l2[idx]]]
                       if idx is not None else None),
            "period_note": period_note,
        }
    return InterpretationResult(True, solutions=solutions,
                                tied=len(picks) >= 2,
                                first_divergence=divergence)


# --------------------------------------------------------------------------
# 无解诊断：前向 DP + 后缀独立可行性，找首个“无法延续”的脉冲
# --------------------------------------------------------------------------

def _advance(ms, j, m, times, spec):
    """脉冲 j 归属设备 m 后可能的新单机状态列表（仅局部转移条件）。"""
    if not ms:
        return [(1, j)]
    if ms[0] == 1:
        gap = times[j] - times[ms[1]]
        out = []
        for p in range(spec.lo, spec.hi + 1):
            k = feasible_k(gap, p, spec.tol, spec.max_missing + 1)
            if k is not None:
                out.append((2, p, j, k - 1))
        return out
    _, p, last, miss = ms
    k = feasible_k(times[j] - times[last], p, spec.tol,
                   spec.max_missing - miss + 1)
    return [(2, p, j, miss + k - 1)] if k is not None else []


def diagnose(times, specs) -> dict:
    """前向 DP + 后缀独立可行性剪枝，找首个无法延续的脉冲。

    每条脉冲只能：作为噪声 / 归 A / 归 B；归属须满足局部周期转移。
    剪枝（精确必要条件，逐机独立、只是对联合分配的松弛）：
      无锚机器的后缀中必须还存在任意一对相容脉冲；
      单锚机器的后缀中必须还存在一条与其首锚相容的第二锚脉冲；
      已立双锚的机器恒满足。
    首个使全部动作都失败的脉冲即按到达顺序的第一个断点。
    """
    n = len(times)

    def any_period_pair(u, v, spec):
        g = times[v] - times[u]
        return any(feasible_k(g, p, spec.tol, spec.max_missing + 1)
                   is not None for p in range(spec.lo, spec.hi + 1))

    # suffix_anchor[m][a][j]：首锚 a 在后缀 j..n-1 有无相容第二锚
    suffix_anchor = [[[False] * (n + 1) for _ in range(n)]
                     for _ in (A, B)]
    # suffix_any[m][j]：后缀 j..n-1 有无任意相容脉冲对
    suffix_any = [[False] * (n + 1) for _ in (A, B)]
    for m in (A, B):
        spec = specs[m]
        for a in range(n):
            ok = False
            for j in range(n - 1, -1, -1):
                if (j > a and any_period_pair(a, j, spec)):
                    ok = True
                suffix_anchor[m][a][j] = ok
        for j in range(n - 1, -1, -1):
            suffix_any[m][j] = suffix_any[m][j + 1] or any(
                any_period_pair(j, v, spec) for v in range(j + 1, n))

    def suffix_ok(m, ms, j):
        if not ms:
            return suffix_any[m][j]
        if ms[0] == 1:
            return suffix_anchor[m][ms[1]][j]
        return True

    EMPTY = ()
    current = {(EMPTY, EMPTY)}

    for j in range(n):
        nxt = set()
        for s1, s2 in current:
            # 动作 1：噪声跳过
            if suffix_ok(A, s1, j + 1) and suffix_ok(B, s2, j + 1):
                nxt.add((s1, s2))
            # 动作 2/3：归属
            for m in (A, B):
                ms, other = (s1, s2) if m == A else (s2, s1)
                for ns in _advance(ms, j, m, times, specs[m]):
                    ns1, ns2 = (ns, other) if m == A else (other, ns)
                    if suffix_ok(A, ns1, j + 1) and \
                            suffix_ok(B, ns2, j + 1):
                        nxt.add((ns1, ns2))
        if not nxt:
            return {"index": j, "time": times[j], "pulse_no": j + 1,
                    "reasons": _diagnosis_reasons(times, specs, j, current,
                                                  suffix_ok)}
        current = nxt

    # 不可达兜底（本 DP 走通即存在真实可行解，与 solve 无解前提矛盾）
    return {"index": n - 1, "time": times[n - 1], "pulse_no": n,
            "reasons": [{"device": "all",
                         "message": "两台应答机无法都由至少两条脉冲锚定。"}]}


def _local_block(ms, j, times, spec, m) -> dict:
    """归属动作局部不可行的原因。"""
    t = times[j]
    if not ms:
        return {"code": "first_anchor",
                "detail": "该脉冲作为首锚后剩余脉冲不足"}
    if ms[0] == 1:
        gap = t - times[ms[1]]
        return {"code": "no_period",
                "detail": (f"与首锚 t={times[ms[1]]} 相隔 {gap}，在周期区间 "
                           f"[{spec.lo},{spec.hi}]、±{spec.tol}/周期、"
                           f"漏收≤{spec.max_missing} 下不存在整数周期个数 k")}
    _, p, last, miss = ms
    gap = t - times[last]
    budget = spec.max_missing - miss
    return {"code": "attach_fail", "p": p,
            "detail": _why_blocked(gap, p, spec, budget)}


def _diagnosis_reasons(times, specs, j, prev_states, suffix_ok) -> list:
    n = len(times)
    remaining = n - j - 1
    reasons = []

    # ---- 噪声 ----
    skip_fail_machines = set()
    for s1, s2 in prev_states:
        if not suffix_ok(A, s1, j + 1):
            skip_fail_machines.add("A")
        if not suffix_ok(B, s2, j + 1):
            skip_fail_machines.add("B")
    if skip_fail_machines and all(
            not (suffix_ok(A, s1, j + 1) and suffix_ok(B, s2, j + 1))
            for s1, s2 in prev_states):
        who = "、".join(sorted(skip_fail_machines))
        reasons.append({
            "device": "noise",
            "message": (f"脉冲 #{j + 1}（t={times[j]}）若作为噪声跳过，剩余 "
                        f"{remaining} 条脉冲中，应答机 {who} 再也找不到与其"
                        f"已采用锚点相容的后续脉冲（或凑不出两个锚点）。"),
        })

    # ---- 归属 A / B ----
    for m, name in ((A, "A"), (B, "B")):
        spec = specs[m]
        local_details = []
        suffix_failed = False
        for st in prev_states:
            ms, other = st[m], st[1 - m]
            new_states = _advance(ms, j, m, times, spec)
            if not new_states:
                d = _local_block(ms, j, times, spec, m)["detail"]
                if d not in local_details:
                    local_details.append(d)
                continue
            for ns in new_states:
                ns1, ns2 = (ns, other) if m == A else (other, ns)
                if not (suffix_ok(A, ns1, j + 1)
                        and suffix_ok(B, ns2, j + 1)):
                    suffix_failed = True
        msgs = list(local_details)
        if suffix_failed:
            msgs.append(f"即使该脉冲能按某个候选周期接上，剩余 {remaining} "
                        f"条脉冲也无法让两台设备各自锚定（至少一台在后缀中"
                        f"找不到相容配对）")
        if msgs:
            reasons.append({"device": name,
                            "message": f"归属应答机 {name} 不可行："
                                       + "；".join(dict.fromkeys(msgs)) + "。"})

    if not reasons:
        reasons.append({
            "device": "all",
            "message": (f"脉冲 #{j + 1}（t={times[j]}）处无法延续任何联合"
                        f"解释（跳过或归属任一台都不成立）。"),
        })
    return reasons


def _why_blocked(gap, p, spec, budget) -> str:
    k_any = feasible_k(gap, p, spec.tol, 10 ** 9)
    if k_any is not None and k_any - 1 > budget:
        return (f"间隔 {gap} 对应 k={k_any} 个周期，需补漏收 {k_any - 1}，"
                f"超过该台剩余额度 {budget}")
    k_lo = max(1, (gap + p + spec.tol - 1) // (p + spec.tol))
    # 从 k_lo-1 起在邻近范围找残差最小的 k（gap<p 时真实最近 k 可能是 1）
    best = min(range(max(1, k_lo - 1), k_lo + 4),
               key=lambda kk: abs(gap - kk * p) - spec.tol * kk)
    resid = gap - best * p
    return (f"间隔 {gap} 与 k={best} 个周期的期望 {best * p} 相差 "
            f"{resid}，超出 ±{spec.tol}×{best} = ±{spec.tol * best} "
            f"的累计计时误差")


# --------------------------------------------------------------------------
# 入口与校验
# --------------------------------------------------------------------------

def interpret(times: list[int], machine_a: dict,
              machine_b: dict) -> InterpretationResult:
    def spec(d):
        lo = int(d["period_min"])
        hi = int(d["period_max"])
        tol = int(d["tolerance"])
        mm = int(d["max_missing"])
        if not (10 <= lo <= hi <= 200):
            raise ValueError("周期区间必须满足 10 ≤ 下限 ≤ 上限 ≤ 200（微秒）")
        if not (0 <= tol <= 1000):
            raise ValueError("单周期计时误差须为 0..1000 微秒")
        if not (0 <= mm <= 200):
            raise ValueError("最多漏收数须为 0..200")
        return MachineSpec(lo, hi, tol, mm)

    t = [int(x) for x in times]
    if not (8 <= len(t) <= 16):
        raise ValueError("需要粘贴 8 至 16 条到达时刻")
    if any(t[i + 1] <= t[i] for i in range(len(t) - 1)):
        raise ValueError("到达时刻必须严格递增的整数")
    if any(x < 0 for x in t):
        raise ValueError("到达时刻不能为负")

    return solve(t, (spec(machine_a), spec(machine_b)))
