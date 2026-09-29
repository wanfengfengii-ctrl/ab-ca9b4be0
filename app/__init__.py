"""双应答机雷达脉冲联合判读核心算法。

输入：严格递增的脉冲到达时刻（整数微秒）、两台应答机各自的候选周期区间
[lo, hi]（整数微秒）、单周期计时误差 tolerance（微秒）与每台最多漏收数
max_missing。

输出：最优联合解释 —— 两条具有固定整数周期的脉冲序列，每条序列至少由两条
脉冲锚定；每条输入脉冲至多归属一台（其余为噪声）；同台相邻采用脉冲的间隔可
解释为正整数个周期（间隔与 k 个周期之差不超过单周期误差，且误差按周期数线性
累积）；每台漏收总数不超过 max_missing。

目标（字典序）：噪声最少 → 两台漏收总数最少。仍并列时，返回两套完整见证及
第一条归属分歧。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from .solver import interpret, InterpretationResult

__all__ = ["interpret", "InterpretationResult"]
