"""独立暴力枚举器：穷举全部归属串 × 周期对，与 DP 结果交叉验证。"""
from itertools import product
from app.solver import feasible_k, A, B, NOISE


def _enumerate(times, specs):
    """返回 (best_obj, witness_keys)；witness 与求解器同样规范化标签。"""
    n = len(times)
    best = None
    wits = set()
    symmetric = specs[0] == specs[1]
    p1s = range(specs[0].lo, specs[0].hi + 1)
    p2s = range(specs[1].lo, specs[1].hi + 1)
    for labels in product((A, B, NOISE), repeat=n):
        ia = tuple(i for i, l in enumerate(labels) if l == A)
        ib = tuple(i for i, l in enumerate(labels) if l == B)
        if len(ia) < 2 or len(ib) < 2:
            continue
        for p1 in p1s:
            for p2 in p2s:
                ok = True
                miss_total = 0
                for idx, p, sp in ((ia, p1, specs[0]),
                                   (ib, p2, specs[1])):
                    mt = 0
                    for u, v in zip(idx, idx[1:]):
                        k = feasible_k(times[v] - times[u], p, sp.tol,
                                       sp.max_missing + 1)
                        if k is None:
                            ok = False
                            break
                        mt += k - 1
                    if not ok or mt > sp.max_missing:
                        ok = False
                        break
                    miss_total += mt
                if not ok:
                    continue
                obj = (n - len(ia) - len(ib), miss_total)
                if symmetric:
                    # 机器无序：按（周期、采用下标串）排序
                    mach = sorted(((p1, ia), (p2, ib)),
                                  key=lambda x: (x[0], x[1]))
                    key = (mach[0][0], mach[1][0],
                           mach[0][1], mach[1][1])
                else:
                    key = (p1, p2, ia, ib)
                if best is None or obj < best:
                    best, wits = obj, {key}
                elif obj == best:
                    wits.add(key)
    return best, wits


def brute_optimal(times, specs):
    """仅返回最优目标 (noise, miss) 或 None。"""
    return _enumerate(times, specs)[0]


def brute_witness_keys(times, specs):
    """返回 (best_obj, 规范化见证集合)，供并列逻辑交叉验证。"""
    return _enumerate(times, specs)

