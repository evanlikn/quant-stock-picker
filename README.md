# Quant Stock Picker

Python + Streamlit 量化选股程序：自选 Walk-forward 逐股参数优化、多周期自动更新、邮件 + WPUSH 微信推送。

## 功能

- **即时分析**：输入股票代码，YAML 默认参数快速分析
- **自选 + Walk-forward**：逐股优化 MA/MACD/RSI 参数，OOS 样本外回测
- **定时调度**：日/时/分 K 线自动增量更新，达 WFO 周期自动再训练
- **推送**：收盘后自动同步自选、生成建议；买入/卖出/观望均邮件 + 微信提醒（`daily_summary` 模式，可改 `signal_change`）

## 安装

```bash
cd quant-stock-picker
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## 配置

1. 编辑 [`config/settings.yaml`](config/settings.yaml) — 资金、WFO、调度、**ATR 仓位**（`position_sizing`）
2. 编辑 [`config/strategies.yaml`](config/strategies.yaml) — 策略搜索空间
3. 复制 `config/.env.example` → `config/.env`，填写 SMTP / WPUSH / TickFlow（可选）
4. （推荐）配置 PostgreSQL，见下方「数据库」

```bash
cp config/.env.example config/.env
```

### ATR 动态仓位（默认）

`position_sizing` 控制实盘建议与回测仓位（默认 `atr_risk`）：

| 参数 | 默认 | 含义 |
|------|------|------|
| `risk_pct` | `0.01` | 每笔最多亏损总资金的 1% |
| `stop_atr_mult` | `2.0` | 止损距离 = 2×ATR |
| `atr_period` | `14` | ATR 计算周期 |

股数 ≈ `(total_capital × risk_pct) / (stop_atr_mult × ATR)`，再按 `lot_size` 取整，且不超过 `max_single_position_pct`。回测中触及止损或策略卖出信号时在下一根开盘价平仓。改回固定比例模式可设 `mode: fixed_pct`。

每日建议会读取各策略**持仓记录**（买入建议自动写入，可在自选详情手动修正）。当收盘价 ≤ 入场价 − `stop_atr_mult×ATR` 时，建议变为**卖出**，理由含「ATR止损」。

## 数据库

默认使用 SQLite（`data/quant_picker.db`），适合本地试用。自选较多、K 线数据量大时 **推荐使用 PostgreSQL**。

### PostgreSQL

使用项目专用账号与独立 schema（**勿**在 `config/.env` 中配置 `postgres` 超级用户）：

```bash
# 需本地已安装并运行 PostgreSQL；超级用户密码仅用于初始化脚本
PG_SUPERUSER_PASSWORD=你的postgres密码 ./scripts/init_postgres.sh
```

脚本会：创建数据库 `quant_picker`、角色 `quant_picker`、schema `quant_picker`、写入 `config/.env` 的 `DATABASE_URL`，并建表。

也可手动设置 `config/.env` 的 `DATABASE_URL`，或在 `config/settings.yaml` 的 `database.url` 中配置；首次启动也会自动建表。K 线数据写入 `bars` 表，并按 `(symbol, market, interval, bar_time)` 去重。

### 行情数据（TickFlow）

A 股 / 港股 / 美股统一使用 [TickFlow Python SDK](https://docs.tickflow.org/zh-Hans/sdk/python-quickstart)：

| 配置 | 能力 |
|------|------|
| 未设置 `TICKFLOW_API_KEY` | 免费服务：历史**日K**（适合回测） |
| 设置 `TICKFLOW_API_KEY` | 完整服务：日K + 60分/1分 K 线 |

```bash
# config/.env
TICKFLOW_API_KEY=your-api-key   # 可选；分钟级 K 线需要
```

### K 线增量同步

行情数据通过 `BarSyncService` + TickFlow 写入数据库：

| 场景 | 行为 |
|------|------|
| 本地无数据或不足 WFO 所需根数 | 全量拉取并入库 |
| 本地已有足够历史 | **仅增量**拉取最新 K 线并入库 |
| Walk-forward 再训练 | **优先读数据库**，仅补增量，不重复全量请求三方接口 |

同一 `(股票, 市场, 周期)` 的 K 线在库中共享，重复训练不会反复下载全量历史。

## 启动

```bash
# 终端 1：Web
export QUANT_PICKER_ROOT=$(pwd)
streamlit run src/quant_picker/web/首页.py

# 终端 2：定时调度（各市场收盘后分别更新日 K 自选）
export QUANT_PICKER_ROOT=$(pwd)
python -m quant_picker.scheduler.runner

# 手动执行一次收盘更新（全部市场，或 --once cn / hk / us）
python -m quant_picker.scheduler.runner --once
```

浏览器访问 http://localhost:8501

### 收盘自动提醒

1. 保持 **scheduler** 进程运行；日 K 按市场 **分开** 在收盘后更新并推送（均为北京时间）：
   - **A 股 (cn)**：工作日 15:35
   - **港股 (hk)**：工作日 16:35
   - **美股 (us)**：周二至周六 09:00（前一交易日深夜收盘后，次日上午更新）
2. 在 **自选管理** 中为需要提醒的股票勾选 **提醒**（`notify_enabled`）
3. 在 `config/.env` 配置邮件（SMTP）与微信（`WPUSH_APIKEY`）
4. `notifications.trigger` 默认为 `daily_summary`：每个交易日收盘更新后推送当日全部策略建议（买入/卖出/观望）

可在 `config/settings.yaml` 的 `scheduler.market_daily_run` 调整各市场时间。

```bash
# 手动执行一次全部市场收盘更新
python -m quant_picker.scheduler.runner --once

# 仅更新某一市场
python -m quant_picker.scheduler.runner --once cn
```

## 项目结构

```
src/quant_picker/
  data/          # TickFlow 行情（A股/港股/美股）
  strategies/    # MA/MACD/RSI
  backtest/      # 回测 + Walk-forward
  optimization/  # 逐股训练
  engine/        # 分析 + 更新
  scheduler/     # APScheduler
  notifications/ # 邮件 + 微信
  web/           # Streamlit
```

## 免责声明

**本程序仅供学习研究，不构成任何投资建议。** 历史回测与 Walk-forward OOS 表现不保证未来收益。不对接券商下单。
