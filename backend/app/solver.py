"""Transponder de-interleaving core.

Two fixed-period transponders (integer periods inside per-machine ranges)
are jointly fitted to a strictly increasing list of pulse arrival times.

Each pulse belongs to at most one transponder (``"A"`` / ``"B"``) or is
noise.  Between two adjacent *adopted* pulses of one machine the gap must
be explainable as a positive integer number ``k`` of cycles:

    segment_error = gap - k * period

A cycle may last ``period +/- tol`` (the single-cycle timing error); over
``k`` cycles the residual accumulates, hence the segment is feasible when

    |gap - k * period| <= k * tol

and ``k - 1`` (the missed receptions on that segment) does not exceed the
machine's budget.  Each transponder must adopt at least two pulses and any
pulse is adopted by at most one machine.

Optimization order (lexicographic):

    1. minimum number of noise pulses;
    2. minimum total missed receptions across both machines.

When the optimum is attained by several complete interpretations, all of
them are returned as witnesses together with the first pulse index whose
ownership differs.

Dynamic program
---------------
Pulses are processed in arrival order.  A state is

    (j, iA, iB, cA, cB)

where pulse ``j`` is the next one to decide, ``iA`` / ``iB`` are the last
adopted pulse indices of each machine (``-1`` if it has not started) and
``cA`` / ``cB`` are adoption counts capped at 2.  Only the last adopted
pulse matters for future feasibility, so the state space is O(n^3 * 9),
tiny for n <= 16.

Transitions for pulse ``j``:

* noise:            (j+1, iA, iB, cA, cB), cost + (1, 0)
* adopted by A:     (j+1, j, iB, min(2,cA+1), cB)
      - cA == 0: first pulse, cost + 0
      - else:    needs a feasible cycle count from pulse iA to j,
                 cost + (0, k-1) with the smallest feasible k
* adopted by B: symmetric.

A numpy implementation runs the same DP for every (periodA, periodB) pair
simultaneously (chunked to bound memory) and yields the *exact* optimum per
pair.  Only pairs attaining the global optimum are replayed by a plain
Python DP that keeps all equal-cost back-pointers, reconstructing every
complete witness.  When no pair is feasible, a boolean forward/backward
grid DP locates the first pulse after which no pair can possibly lead to
both machines adopting two pulses.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy is mandatory in deployment
    np = None


INF = 2_000_000_000
BIG = 100_000         # lex encoding cost = noise * BIG + missed
EDGE_SENT = 10_000_000  # unreachable-edge addend (keeps int32 sums safe)
WITNESS_LIMIT = 10
PAIR_CHUNK = 4096


class ValidationError(ValueError):
    """Raised when the request payload is malformed."""


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MachineSpec:
    name: str
    p_min: int
    p_max: int
    tol: int
    max_missed: int


@dataclass(frozen=True)
class Problem:
    times: tuple[int, ...]
    a: MachineSpec
    b: MachineSpec


def _as_int(value, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValidationError(f"{field_name} must be an integer")
    if isinstance(value, float):
        if not value.is_integer():
            raise ValidationError(f"{field_name} must be an integer")
        value = int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field_name} must be an integer")


def build_problem(payload: dict) -> Problem:
    if not isinstance(payload, dict):
        raise ValidationError("request body must be a JSON object")

    raw_times = payload.get("times")
    if not isinstance(raw_times, list) or not (8 <= len(raw_times) <= 16):
        raise ValidationError("times must contain between 8 and 16 entries")
    times = [_as_int(v, f"times[{i}]") for i, v in enumerate(raw_times)]
    if any(times[i] <= times[i - 1] for i in range(1, len(times))):
        raise ValidationError("times must be strictly increasing integers")

    def machine(name: str) -> MachineSpec:
        m = payload.get(name)
        if not isinstance(m, dict):
            raise ValidationError(f"missing machine spec '{name}'")
        p_min = _as_int(m.get("p_min"), f"{name}.p_min")
        p_max = _as_int(m.get("p_max"), f"{name}.p_max")
        tol = _as_int(m.get("tol"), f"{name}.tol")
        max_missed = _as_int(m.get("max_missed"), f"{name}.max_missed")
        if not (10 <= p_min <= p_max <= 200):
            raise ValidationError(
                f"{name}: require 10 <= p_min <= p_max <= 200 (microseconds)")
        if tol < 0:
            raise ValidationError(f"{name}.tol must be >= 0")
        if max_missed < 0:
            raise ValidationError(f"{name}.max_missed must be >= 0")
        return MachineSpec(name, p_min, p_max, tol, max_missed)

    return Problem(tuple(times), machine("a"), machine("b"))


# ---------------------------------------------------------------------------
# Cycle feasibility
# ---------------------------------------------------------------------------

def cycles_for_gap(gap: int, p: int, tol: int, max_missed: int) -> tuple[int, ...]:
    """All positive cycle counts k with |gap-k*p| <= k*tol, k-1 <= budget."""
    lo = max(1, (gap + p + tol - 1) // (p + tol))   # ceil(gap/(p+tol))
    hi = max_missed + 1 if p <= tol else gap // (p - tol)
    hi = min(hi, max_missed + 1)
    return tuple(range(lo, hi + 1)) if lo <= hi else ()


def period_miss_table(times, m: MachineSpec):
    """numpy array (n_periods, n, n): minimal missed k-1 for edge i -> j.

    Entry is INF when no cycle count is feasible (also for i >= j and for
    the "no pulse" slot).  Period order matches range(m.p_min, m.p_max+1).
    """
    t = np.asarray(times, dtype=np.int64)
    n = len(t)
    periods = np.arange(m.p_min, m.p_max + 1, dtype=np.int64)
    gaps = (t[None, :] - t[:, None])                 # (n, n), gap[i,j]
    g = gaps[None, :, :]                             # (P, n, n)
    p = periods[:, None, None]
    lo = np.maximum(1, (g + p + m.tol - 1) // (p + m.tol))
    hi = np.where(p > m.tol,
                  g // np.maximum(p - m.tol, 1),
                  m.max_missed + 1)
    hi = np.minimum(hi, m.max_missed + 1)
    ok = (lo <= hi) & (gaps[None] > 0)
    return np.where(ok, lo - 1, INF).astype(np.int32), periods


# ---------------------------------------------------------------------------
# Exact vectorized DP over period pairs
# ---------------------------------------------------------------------------

def pair_optima(times, a: MachineSpec, b: MachineSpec):
    """Exact lex optimum for every (periodA, periodB) pair.

    Returns (pa_periods, pb_periods, costs[R,S]) with costs = noise*BIG+miss
    or INF when the pair cannot adopt >= 2 pulses on both machines.

    The DP grid C[pair, cA, cB, sA, sB] only carries active slots (a pulse
    adopted by a machine must be at least that machine's 2nd pulse, so the
    live slot ranges shrink as the scan proceeds); all reductions are
    fused minimum-adds.
    """
    n = len(times)
    n1 = n + 1
    ma, pa_vals = period_miss_table(times, a)
    mb, pb_vals = period_miss_table(times, b)
    R, S = len(pa_vals), len(pb_vals)

    pa_idx, pb_idx = np.meshgrid(np.arange(R), np.arange(S), indexing="ij")
    pa_flat, pb_flat = pa_idx.ravel(), pb_idx.ravel()
    out = np.full(R * S, INF, dtype=np.int32)

    for s0 in range(0, R * S, PAIR_CHUNK):
        s1 = min(s0 + PAIR_CHUNK, R * S)
        f = s1 - s0
        MA = ma[pa_flat[s0:s1]]                      # (F, n, n)
        MB = mb[pb_flat[s0:s1]]
        # C is the active window only: at the start of step j its slot axes
        # have width w = j+1 (reachable slots 0..j); afterwards w+1.
        C = np.zeros((f, 3, 3, 1, 1), dtype=np.int32)
        C[:] = INF
        C[:, 0, 0, 0, 0] = 0
        for j in range(n):
            w = j + 1
            NX = np.full((f, 3, 3, w + 1, w + 1), INF, dtype=np.int32)
            NX[:, :, :, :w, :w] = np.minimum(
                NX[:, :, :, :w, :w], C + BIG)       # noise
            # adopt pulse j by A ----------------------------------------
            # first pulse: (cA=0,sA=0) -> (cA=1,sA=j)
            NX[:, 1, :, w, :w] = np.minimum(
                NX[:, 1, :, w, :w], C[:, 0, :, 0, :])
            if j >= 1:
                # invalid edges collapse the candidate to EDGE_SENT, which
                # exceeds every real cost (<= n*BIG + n^2) but keeps int32
                # arithmetic inside the overflow-safe range
                ea = MA[:, :j, j]
                valid = ea < INF
                addc = np.minimum(ea, EDGE_SENT)
                srcA = C[:, 1:, :, 1:w, :]
                comb = np.where(valid.reshape(f, 1, 1, j, 1),
                                srcA + addc.reshape(f, 1, 1, j, 1),
                                EDGE_SENT)
                bestA = comb.min(axis=3).min(axis=1)
                reachA = (valid.reshape(f, 1, j, 1)
                          & (srcA < INF)).any(axis=(1, 3))
                bestA = np.where(reachA, np.minimum(bestA, INF), INF)
                NX[:, 2, :, w, :w] = np.minimum(
                    NX[:, 2, :, w, :w], bestA)
            # adopt pulse j by B ----------------------------------------
            NX[:, :, 1, :w, w] = np.minimum(
                NX[:, :, 1, :w, w], C[:, :, 0, :, 0])
            if j >= 1:
                eb = MB[:, :j, j]
                validB = eb < INF
                addcB = np.minimum(eb, EDGE_SENT)
                srcB = C[:, :, 1:, :, 1:w]
                comb = np.where(validB.reshape(f, 1, 1, 1, j),
                                srcB + addcB.reshape(f, 1, 1, 1, j),
                                EDGE_SENT)
                bestB = comb.min(axis=4).min(axis=2)
                reachB = (validB.reshape(f, 1, 1, j)
                          & (srcB < INF)).any(axis=(2, 4))
                bestB = np.where(reachB, np.minimum(bestB, INF), INF)
                NX[:, :, 2, :w, w] = np.minimum(
                    NX[:, :, 2, :w, w], bestB)
            C = NX
        final = C[:, 2, 2, :, :].reshape(f, -1).min(axis=1)
        out[s0:s1] = final
    return pa_vals, pb_vals, out.reshape(R, S)


# ---------------------------------------------------------------------------
# Witness reconstruction (exact, plain Python)
# ---------------------------------------------------------------------------

def _edge_miss_one(times, m: MachineSpec, period: int):
    n = len(times)
    miss = [[INF] * n for _ in range(n)]
    for j in range(1, n):
        for i in range(j):
            ks = cycles_for_gap(times[j] - times[i], period, m.tol,
                                m.max_missed)
            if ks:
                miss[j][i] = ks[0] - 1
    return miss


def trace_pair(times, a: MachineSpec, b: MachineSpec, pa: int, pb: int,
               target: int, limit=WITNESS_LIMIT + 30):
    """All assignments with exact cost == target for one period pair."""
    n = len(times)
    mA = _edge_miss_one(times, a, pa)
    mB = _edge_miss_one(times, b, pb)

    # state (iA, iB, cA, cB) at step j -> {cost: [link, ...]}
    # link = (prev_cost, choice, segment_missed, prev_state)
    layer = {(-1, -1, 0, 0): {0: []}}
    history = [layer]
    for j in range(n):
        nxt: dict = {}

        def put(state, cost, link):
            cur = nxt.get(state)
            if cur is None:
                nxt[state] = {cost: [link]}
            else:
                bucket = cur.get(cost)
                if bucket is None:
                    cur[cost] = [link]
                else:
                    bucket.append(link)

        for state, costs in layer.items():
            ia, ib, ca, cb = state
            for cost, _links in costs.items():
                # noise
                put((ia, ib, ca, cb), cost + BIG,
                    (cost, "N", 0, state))
                # adopt by A
                if ca == 0:
                    put((j, ib, 1, cb), cost,
                        (cost, "A", 0, state))
                elif mA[j][ia] < INF:
                    put((j, ib, 2, cb), cost + mA[j][ia],
                        (cost, "A", mA[j][ia], state))
                # adopt by B
                if cb == 0:
                    put((ia, j, ca, 1), cost,
                        (cost, "B", 0, state))
                elif mB[j][ib] < INF:
                    put((ia, j, ca, 2), cost + mB[j][ib],
                        (cost, "B", mB[j][ib], state))
        history.append(nxt)
        layer = nxt

    end_states = [(state, costs) for state, costs in layer.items()
                  if state[2] == 2 and state[3] == 2]
    starts = [(state, target) for state, costs in end_states
              if target in costs]
    if not starts:
        return []

    results = []
    seen = set()

    def walk(j, state, cost, choices, seg_miss):
        if len(results) >= limit:
            return
        if j == 0:
            asg = tuple(reversed(choices))
            sm = tuple(reversed(seg_miss))
            if asg not in seen:
                seen.add(asg)
                results.append((asg, sm))
            return
        for (pcost, choice, miss, pstate) in history[j][state][cost]:
            choices.append(choice)
            seg_miss.append(miss)
            walk(j - 1, pstate, pcost, choices, seg_miss)
            choices.pop()
            seg_miss.pop()

    for state, cost in starts:
        walk(n, state, cost, [], [])
        if len(results) >= limit:
            break
    return results


# ---------------------------------------------------------------------------
# Infeasibility diagnosis: first pulse that cannot lead to a solution
# ---------------------------------------------------------------------------

def first_failure(times, a: MachineSpec, b: MachineSpec) -> dict:
    """First pulse j after which no period pair can possibly finish.

    For every period pair a boolean grid DP computes reachable states
    forward and completable states backward; pulse j is the point of no
    return when, after consuming it, every pair's reachable state set is
    disjoint from its can-still-finish set.  Per-pair liveness is OR-ed
    across chunks, so the returned index is global over all period pairs.
    """
    n = len(times)
    n1 = n + 1
    ma, pa_vals = period_miss_table(times, a)
    mb, pb_vals = period_miss_table(times, b)
    R, S = len(pa_vals), len(pb_vals)
    pa_idx, pb_idx = np.meshgrid(np.arange(R), np.arange(S), indexing="ij")
    pa_flat, pb_flat = pa_idx.ravel(), pb_idx.ravel()
    total = R * S
    diag_chunk = 512

    alive_any = np.zeros(n, dtype=bool)

    for s0 in range(0, total, diag_chunk):
        s1 = min(s0 + diag_chunk, total)
        f = s1 - s0
        edgeA = ma[pa_flat[s0:s1]] < INF          # (F, n, n)
        edgeB = mb[pb_flat[s0:s1]] < INF

        # backward completability: bw[j] for states BEFORE processing j
        bw = [None] * (n + 1)
        G = np.zeros((f, 3, 3, n1, n1), dtype=bool)
        G[:, 2, 2, :, :] = True
        bw[n] = G
        for j in range(n - 1, -1, -1):
            nx = bw[j + 1]
            cur = nx.copy()                        # noise
            js = j + 1
            # first A pulse
            cur[:, 0, :, 0, :] |= nx[:, 1, :, js, :]
            # later A pulse (predecessor cA 1 or 2 -> resulting cA 2)
            if j >= 1:
                e = edgeA[:, :j, j].reshape(f, 1, 1, j, 1)
                tgt = nx[:, 2, :, js, :].reshape(f, 1, 3, 1, n1)
                cur[:, 1:, :, 1:j + 1, :] |= tgt & e
            # first B pulse
            cur[:, :, 0, :, 0] |= nx[:, :, 1, :, js]
            if j >= 1:
                e = edgeB[:, :j, j].reshape(f, 1, 1, 1, j)
                tgt = nx[:, :, 2, :, js].reshape(f, 3, 1, n1, 1)
                cur[:, :, 1:, :, 1:j + 1] |= tgt & e
            bw[j] = cur

        # forward reachability
        Fw = np.zeros((f, 3, 3, n1, n1), dtype=bool)
        Fw[:, 0, 0, 0, 0] = True
        for j in range(n):
            NX = Fw.copy()                         # noise
            js = j + 1
            NX[:, 1, :, js, :] |= Fw[:, 0, :, 0, :]
            if j >= 1:
                e = edgeA[:, :j, j].reshape(f, 1, 1, j, 1)
                src = Fw[:, 1:, :, 1:j + 1, :] & e
                NX[:, 2, :, js, :] |= src.any(axis=(1, 3))
            NX[:, :, 1, :, js] |= Fw[:, :, 0, :, 0]
            if j >= 1:
                e = edgeB[:, :j, j].reshape(f, 1, 1, 1, j)
                src = Fw[:, :, 1:, :, 1:j + 1] & e
                NX[:, :, 2, :, js] |= src.any(axis=(2, 4))
            Fw = NX
            alive = (Fw & bw[j + 1]).reshape(f, -1).any(axis=1)
            alive_any[j] = alive_any[j] or bool(alive.any())

    dead = np.argwhere(~alive_any).ravel()
    j = int(dead[0]) if len(dead) else n - 1
    return {"index": j, "time": times[j],
            "reasons": _reasons(times, j, a, b)}


def _candidate(cfg_time, other_time, gap: int, m: MachineSpec,
               forward: bool) -> dict:
    feasible = [p for p in range(m.p_min, m.p_max + 1)
                if cycles_for_gap(gap, p, m.tol, m.max_missed)]
    if not feasible:
        return None
    p0 = feasible[0]
    k = cycles_for_gap(gap, p0, m.tol, m.max_missed)[0]
    base = {"gap": gap, "period_min": feasible[0],
            "period_max": feasible[-1], "cycles": k,
            "missed": k - 1, "error": gap - k * p0}
    if forward:
        base.update({"successor_time": other_time,
                     "successor_index": None})
    else:
        base.update({"predecessor_time": other_time,
                     "predecessor_index": None})
    return base


def _reasons(times, j: int, a: MachineSpec, b: MachineSpec) -> list[dict]:
    """Candidate-machine reasons for the dead-end pulse ``j``.

    Reports both possible roles: earlier pulses the dead pulse could
    follow, and later pulses that could still continue from it (so a
    machine which has adopted the dead pulse as its first can never get
    a second adoption).
    """
    t = times[j]
    out = []
    for name, m in (("A", a), ("B", b)):
        predecessors = []
        for i in range(j):
            c = _candidate(t, times[i], t - times[i], m, forward=False)
            if c is not None:
                c["predecessor_index"] = i
                predecessors.append(c)
        successors = []
        for h in range(j + 1, len(times)):
            c = _candidate(t, times[h], times[h] - t, m, forward=True)
            if c is not None:
                c["successor_index"] = h
                successors.append(c)
        if predecessors:
            link_text = ("can follow an earlier pulse for some period(s), "
                         "but no jointly consistent prefix supports it")
        elif successors:
            link_text = ("has no earlier pulse it could follow for any "
                         "period in the range; adopting it as the first "
                         "pulse is possible, but the listed later pulses "
                         "cannot provide a second one under the same "
                         "period and budget")
        else:
            link_text = ("can neither follow any earlier pulse nor be "
                         "continued by any later pulse for any period in "
                         f"[{m.p_min}, {m.p_max}] us within +/-{m.tol} us "
                         f"per cycle and at most {m.max_missed} missed "
                         "receptions")
        out.append({
            "machine": name,
            "reason": f"machine {name}: pulse {t} {link_text}",
            "candidate_predecessors": predecessors,
            "candidate_successors": successors,
            "period_range": [m.p_min, m.p_max],
            "tol": m.tol,
            "max_missed": m.max_missed,
        })
    return out


# ---------------------------------------------------------------------------
# Witness assembly and orchestration
# ---------------------------------------------------------------------------

@dataclass
class Witness:
    pa: int
    pb: int
    assign: tuple[str, ...]
    seg_miss: tuple[int, ...]
    missed_total: int
    noise_count: int


def witness_payload(prob: Problem, w: Witness) -> dict:
    pulses = []
    segments = {"A": [], "B": []}
    last = {"A": None, "B": None}
    cum = {"A": 0, "B": 0}
    for idx, (t, who, mm) in enumerate(zip(prob.times, w.assign, w.seg_miss)):
        if who == "N":
            pulses.append({"index": idx, "time": t, "label": "N",
                           "noise": True, "period": None,
                           "missed_before": None, "error": None})
            continue
        period = w.pa if who == "A" else w.pb
        prev = last[who]
        if prev is None:
            err, mb = None, 0
        else:
            k = mm + 1
            err = t - prev - k * period
            mb = mm
            cum[who] += mb
            segments[who].append({
                "from": prev, "to": t, "gap": t - prev,
                "cycles": k, "period": period, "error": err,
                "missed": mb,
            })
        pulses.append({"index": idx, "time": t, "label": who,
                       "noise": False, "period": period,
                       "missed_before": mb, "error": err})
        last[who] = t
    return {
        "periods": {"A": w.pa, "B": w.pb},
        "missed": {"A": cum["A"], "B": cum["B"]},
        "noise_count": w.noise_count,
        "missed_total": w.missed_total,
        "assignment": list(w.assign),
        "pulses": pulses,
        "segments": segments,
    }


def solve(prob: Problem) -> dict:
    times = prob.times
    pa_vals, pb_vals, matrix = pair_optima(times, prob.a, prob.b)

    best = int(matrix.min())
    if best >= INF:
        return {"feasible": False, "diagnosis": first_failure(
            times, prob.a, prob.b)}

    rs, ss = np.nonzero(matrix == best)
    witnesses: list[Witness] = []
    for r, s in zip(rs.tolist(), ss.tolist()):
        pa, pb = int(pa_vals[r]), int(pb_vals[s])
        for assign, seg_miss in trace_pair(times, prob.a, prob.b,
                                           pa, pb, best):
            missed_total = sum(seg_miss)
            witnesses.append(Witness(
                pa, pb, assign, seg_miss, missed_total,
                assign.count("N")))

    uniq = {}
    for w in witnesses:
        key = (w.pa, w.pb, w.assign, w.seg_miss)
        if key not in uniq:
            uniq[key] = w
    witnesses = sorted(uniq.values(),
                       key=lambda w: (w.pa, w.pb, w.assign))
    truncated = len(witnesses) > WITNESS_LIMIT
    witnesses = witnesses[:WITNESS_LIMIT]

    first_diff = None
    if len(witnesses) >= 2:
        for i, t in enumerate(times):
            labels = sorted({w.assign[i] for w in witnesses})
            if len(labels) > 1:
                first_diff = {"index": i, "time": t, "labels": labels}
                break

    return {
        "feasible": True,
        "optimal": {"noise_count": best // BIG,
                    "missed_total": best % BIG},
        "optimal_pair_count": int((matrix == best).sum()),
        "witness_count": len(witnesses),
        "truncated": truncated,
        "witnesses": [witness_payload(prob, w) for w in witnesses],
        "first_disagreement": first_diff,
    }
