# 双应答机雷达脉冲联合判读

海上搜救演练结束后，通信分析员将接收机记录的混合雷达脉冲粘贴进页面，
系统**联合**还原两台可能同时工作的应答机：为两台设备分别选出固定的整数
重复周期，并决定每条脉冲归属应答机 A / 应答机 B / 噪声，补出漏收、给出
逐段计时误差；若不存在联合解释，则清除旧报告并指出按到达时刻顺序的首个
无法延续脉冲及候选设备原因。

## 判读规则

- 输入 8–16 条**严格递增**的整数微秒到达时刻；两台应答机各填写：
  重复周期整数区间 `[10, 200]` µs、单周期计时误差 `tolerance`（µs）、
  最多漏收数 `max_missing`。
- 同台相邻两条被采用脉冲的时刻间隔 `gap` 必须解释为正整数 `k` 个周期：

  `|gap − k·period| ≤ tolerance · k`

  （计时误差随周期数线性累积），该段补出的漏收数为 `k − 1`；
  每台累计漏收不得超过 `max_missing`。
- 每台设备至少由两条脉冲锚定（周期在第二个锚点一次性固定，之后不可更改）；
  每条脉冲只能归属一台，或成为噪声。
- 求解器枚举全部候选周期对，对每个周期对做精确的分层动态规划
  （帕累托前沿剪枝），按以下字典序择优：
  1. 噪声脉冲最少；
  2. 两台漏收总数最少。
- 目标值仍并列时，返回**两套完整见证**，并给出两套见证的第一条归属分歧
  （若归属完全一致、仅推得周期不同，则单独说明）。
- 无联合解释时返回首个无法延续的脉冲（前向 DP 配合后缀相容配对的精确
  必要条件剪枝）及它作为噪声 / 归属 A / 归属 B 各自失败的原因。

## 目录结构

```
app/solver.py        核心算法：候选周期、联合 DP、并列见证、无解诊断
app/api.py           FastAPI 业务接口（POST /api/interpret，GET /health）
web/                 零依赖原生前端（HTML/CSS/JS）
scripts/build_web.py 前端构建：内联为单文件 web/dist/index.html
scripts/smoke.py     判读接口烟测（有解 / 无解 / 422 / 代理路径）
tests/               pytest 单元测试（含独立暴力枚举器交叉验证最优性）
Dockerfile           api / web / verify 三个构建目标
docker-compose.yml   api、web 服务 + verify 一次性服务
```

## 快速开始（Docker Compose）

```bash
cp .env.example .env        # 可选：修改 WEB_PORT / API_PORT
docker compose up -d --build api web
# 打开 http://localhost:${WEB_PORT:-8080}
# API 文档：http://localhost:${API_PORT:-8010}/docs
```

端口均通过环境变量配置（`.env` 或 shell 导出）：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `WEB_PORT` | 8080 | 宿主机访问前端（nginx，同源反代 `/api/`） |
| `API_PORT` | 8010 | 宿主机访问业务 API |

两个服务均配置了健康检查（API 探 `/health`，web 探首页）。

## 一次性验证服务

`verify` 服务在 `api`、`web` **健康检查通过后**才启动，顺序执行：

1. `pytest` 全部代码测试（含与暴力枚举器的随机交叉验证）；
2. `scripts/build_web.py` 前端构建；
3. `scripts/smoke.py` 判读接口烟测（直连 API 与经 nginx 代理各一组
   有解 / 无解散例，外加 422 与首页检查）。

```bash
# run 会把 verify 容器内的退出码原样返回，适合 CI / 本地验收
docker compose build api web verify
docker compose up -d api web        # 或直接 run（会自动拉起并等待依赖健康）
docker compose run --rm verify
echo "verify exit code: $?"         # 0 表示全部通过；非 0 时查看日志
docker compose logs verify
```

## 本地开发（无需 Docker）

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest httpx

python -m pytest -q                    # 代码测试
python scripts/build_web.py            # 生成 web/dist/index.html
uvicorn app.api:app --port 8000        # 业务 API
# 任意静态服务器托管 web/dist 即可；生产路径由 nginx 同源反代
python scripts/smoke.py                # 烟测（可用 API_URL/WEB_URL 指向本地）
```

## 接口示例

```bash
curl -s -X POST http://localhost:8010/api/interpret \
  -H 'Content-Type: application/json' \
  -d '{
    "times": [0, 7, 44, 50, 81, 100, 118, 150, 155, 192, 200],
    "machine_a": {"period_min": 10, "period_max": 200, "tolerance": 2, "max_missing": 2},
    "machine_b": {"period_min": 10, "period_max": 200, "tolerance": 2, "max_missing": 2}
  }'
```

成功响应包含 `feasible: true`、一至两套 `solutions`（每套含每条脉冲的
`assignment/cycles/missing_before/segment_error`、两台设备的推得周期与
逐段明细、噪声数与漏收合计）以及并列时的 `first_divergence`；
无解时 `feasible: false`、`solutions: []` 与 `diagnosis`
（首个断点脉冲的序号、时刻及候选设备原因）。
