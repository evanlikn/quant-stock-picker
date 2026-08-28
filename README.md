# Quant Stock Picker

Python + Streamlit 量化选股程序：自选 Walk-forward 逐股参数优化、多周期自动更新、邮件 + WPUSH 微信推送。

## 功能

- **即时分析**：输入股票代码，YAML 默认参数快速分析
- **自选 + Walk-forward**：逐股优化 MA/MACD/RSI 参数，OOS 样本外回测
- **定时调度**：日/时/分 K 线自动增量更新，达 WFO 周期自动再训练
- **推送**：收盘后自动同步自选、生成建议；买入/卖出/观望均邮件 + 微信提醒（`daily_summary` 模式，可改 `signal_change`）
- **多用户**：每人一套自选与推送凭据，行情与训练参数全局共享

## 安装

需要 **Python 3.11 或更高**（`python3 --version`）。低于 3.11 时 `pip install` 会报 `No matching distribution found for streamlit>=1.30`，那是 pip 按当前解释器过滤掉了新版本，不是镜像缺包。

```bash
cd quant-stock-picker
python3.11 -m venv .venv   # 或 python3.12
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## 配置

配置分两层，换机器部署时只需要动第一层：

| 文件 | 内容 | 迁移部署时 |
|------|------|-----------|
| [`config/.env`](config/.env.example) | 数据库、密钥、API Key、时区、日志（不含推送凭据） | **每个环境各配一份** |
| [`config/settings.yaml`](config/settings.yaml) | 资金、仓位、WFO、回测、调度时刻表 | 跨环境通用，直接复用 |
| [`config/strategies.yaml`](config/strategies.yaml) | 策略搜索空间 | 跨环境通用，直接复用 |

```bash
cp config/.env.example config/.env   # 按注释逐项填写即可
```

`config/.env.example` 里列全了所有可配项并带默认值，`.env` 中没写的项会自动回落到它，因此 `.env` 只需要写你要改的部分。优先级：真实环境变量 > `config/.env` > `config/.env.example` > `settings.yaml`。

### ATR 动态仓位（默认）

`position_sizing` 控制实盘建议与回测仓位（默认 `atr_risk`）：

| 参数 | 默认 | 含义 |
|------|------|------|
| `risk_pct` | `0.01` | 每笔最多亏损总资金的 1% |
| `stop_atr_mult` | `2.0` | 止损距离 = 2×ATR |
| `atr_period` | `14` | ATR 计算周期 |

股数 ≈ `(total_capital × risk_pct) / (stop_atr_mult × ATR)`，再按 `lot_size` 取整，且不超过 `max_single_position_pct`。回测中触及止损或策略卖出信号时在下一根开盘价平仓。改回固定比例模式可设 `mode: fixed_pct`。

每日建议会读取各策略**持仓记录**（买入建议自动写入，可在自选详情手动修正）。当收盘价 ≤ 入场价 − `stop_atr_mult×ATR` 时，建议变为**卖出**，理由含「ATR止损」。

## 用户体系

平台支持多人共用一套部署。**自选、持仓、建议、推送记录按用户隔离**；**K 线、Walk-forward 参数、回测快照、选股结果全局共享**，同一只股票不会被重复下载或重复训练。

### 首次启动

首次运行会自动完成三件事（全新部署和老库升级都一样）：

1. 建表；老库额外给 `watchlist_items` 补 `user_id`
2. 创建管理员账号；老库的已有自选全部归属给它
3. 生成 `QUANT_PICKER_SECRET_KEY` 写入 `config/.env`（用于加密用户填写的推送凭据）

管理员的初始密码写在 `data/bootstrap_admin_password.txt`，**登录后请立即在「账号管理」修改密码并删除该文件**。也可以提前指定：

```bash
# config/.env
QUANT_PICKER_ADMIN_USERNAME=admin
QUANT_PICKER_ADMIN_PASSWORD=你的密码
```

> ⚠️ `QUANT_PICKER_SECRET_KEY` 丢失后，各用户已保存的 SMTP 密码与 WPUSH APIKEY 将无法解密（需要重新填写）。请连同 `config/.env` 一起备份。

### 密钥丢失会怎样

这个密钥有两个用途：加密各用户存在库里的推送凭据，以及给登录 cookie 签名。它在首次启动时自动生成写入 `config/.env`，不需要人工记忆，唯一的风险是**只恢复了数据库、没恢复 `config/.env`**。

一旦密钥对不上，系统会主动报出来而不是默默降级：

| 位置 | 表现 |
|------|------|
| scheduler 启动 | 日志与终端列出受影响的用户名 |
| 推送设置页 | 顶部红色横幅指出哪一项无法解密 |
| 推送行为 | 相关通道**自动停用**，并提示重新填写 |
| 登录状态 | cookie 失效，所有人需要重新登录 |

关键在于解密失败不能被当成「该用户没配过」而静默略过——用户会以为推送正常，实际一条都没发出去。所以这里宁可显式停用并报错，也不猜。

恢复方式只有一个——受影响的用户在「推送设置」页重新填写凭据并保存，密文会用当前密钥重写。已保存的旧密文无法找回。

### 账号与权限

| 页面 | 谁可以用 | 作用 |
|------|---------|------|
| 账号管理 | 所有人 | 修改自己的密码 |
| 账号管理 · 用户列表 / 新建用户 | 仅管理员 | 创建账号、重置密码、停用账号 |
| 推送设置 | 所有人 | 填写**本人**的 SMTP 与 WPUSH 凭据、开关与推送策略 |

新用户由管理员在「账号管理」创建，没有自助注册入口。密码使用 bcrypt 存库，登录状态存 cookie（30 天），刷新页面不掉线。

### 推送配置

推送凭据**只按用户存在数据库里**，登录后在「推送设置」页填写；SMTP 密码与 WPUSH APIKEY 加密存储，页面上只回显掩码。

`config/.env` 里**没有** `SMTP_*` / `WPUSH_APIKEY`，这是有意为之。这些变量一旦存在就是全局共享的，新账号会继承别人的发件邮箱和 APIKEY，提醒会发到不属于自己的邮箱去。所以配置入口只有一个：每个用户自己的设置页。

新账号创建后两个通道默认关闭，填完凭据并打开开关才会推送。`config/settings.yaml` 的 `notifications` 只提供推送策略（`trigger` / `intraday_trigger`）的初始默认值，不含任何凭据。

## 数据库

两种后端由 `config/.env` 切换，代码无需改动，首次启动都会自动建表。

### SQLite（默认，小服务器推荐）

不配置任何东西即可运行，数据落在 `data/quant_picker.db`：

```bash
# config/.env
QUANT_PICKER_DB_PATH=data/quant_picker.db
QUANT_PICKER_SQLITE_TIMEOUT=30
```

Web 与 scheduler 是两个进程且都会写库，因此连接会自动开启 **WAL**：写入期间读不再被阻塞，同步行情时刷新页面不会报 `database is locked`。剩余的写-写冲突由 `QUANT_PICKER_SQLITE_TIMEOUT` 秒的等待吸收，冲突频繁可调大。

从**多用户改造之前**的 SQLite 老库升级时，首次启动会自动重建 `watchlist_items`：SQLite 没有 `DROP CONSTRAINT`，只能整表替换，把唯一约束从 `(symbol, market, interval)` 换成 `(user_id, symbol, market, interval)`，原有自选归属到初始管理员。整个过程在一个事务里完成，中途失败会回滚，不需要手动干预。

### PostgreSQL（可选）

自选很多、K 线数据量大时更合适。取消 `config/.env` 中两行注释即可切换：

```bash
# config/.env
DATABASE_URL=postgresql+psycopg://quant_picker:密码@127.0.0.1:5432/quant_picker
QUANT_PICKER_DB_SCHEMA=quant_picker
```

建库使用项目专用账号与独立 schema（**勿**配置 `postgres` 超级用户）：

```bash
# 需本地已安装并运行 PostgreSQL；超级用户密码仅用于初始化脚本
PG_SUPERUSER_PASSWORD=你的postgres密码 ./scripts/init_postgres.sh
```

脚本会创建数据库 `quant_picker`、角色 `quant_picker`、schema `quant_picker`，写入 `config/.env` 的 `DATABASE_URL` 并建表。

K 线数据写入 `bars` 表，两种后端都按 `(symbol, market, interval, bar_time)` 去重。

### 行情数据

日 K 与 A 股分钟线走 [TickFlow](https://docs.tickflow.org/zh-Hans/sdk/python-quickstart)；**港股 / 美股的 1 小时、1 分钟 K 线走 [长桥 OpenAPI](https://open.longbridge.com)**。

| 市场 | 日K | 1h / 1m |
|------|-----|---------|
| A 股 | TickFlow | TickFlow（需 `TICKFLOW_API_KEY`） |
| 港股、美股 | TickFlow | 长桥（需 App Key + Secret + Access Token） |

```bash
# config/.env
TICKFLOW_API_KEY=your-api-key          # A 股分钟线；三市日K 免费档也可用
LONGBRIDGE_APP_KEY=                    # 长桥开发者中心
LONGBRIDGE_APP_SECRET=
LONGBRIDGE_ACCESS_TOKEN=               # 与 Key/Secret 一起发放，三项缺一不可
```

长桥按自然月限制可查询的标的数量（开户约 100 只，资产越高额度越大），同一标的当月重复拉取只计一次。接口限制约每 30 秒 60 次。历史分钟 K 单次最多 1000 根，首次全量会自动翻页。

### K 线增量同步

行情数据通过 `BarSyncService` 写入数据库（TickFlow 或长桥，按市场与周期路由）：

| 场景 | 行为 |
|------|------|
| 本地无数据或不足 WFO 所需根数 | 全量拉取并入库 |
| 本地已有足够历史 | **仅增量**拉取最新 K 线并入库 |
| Walk-forward 再训练 | **优先读数据库**，仅补增量，不重复全量请求三方接口 |

同一 `(股票, 市场, 周期)` 的 K 线在库中共享，重复训练不会反复下载全量历史。Walk-forward 参数同样按 `(股票, 市场, 周期, 策略)` 共享：第二个用户收藏一只别人已训练过的股票时会直接复用结果，几秒内完成而不是重跑一遍优化。

## 启动

```bash
# 终端 1：Web
./scripts/run_web.sh

# 终端 2：定时调度（各市场收盘后分别更新日 K 自选）
export QUANT_PICKER_ROOT=$(pwd)
python -m quant_picker.scheduler.runner

# 手动执行一次收盘更新（全部市场，或 --once cn / hk / us）
python -m quant_picker.scheduler.runner --once
```

浏览器访问 `http://<QUANT_PICKER_WEB_HOST>:<QUANT_PICKER_WEB_PORT>`；监听地址和端口统一在 `config/.env` 配置。

### 收盘自动提醒

1. 保持 **scheduler** 进程运行；日 K 按市场 **分开** 在收盘后更新并推送（均为北京时间）：
   - **A 股 (cn)**：工作日 15:35
   - **港股 (hk)**：工作日 16:35
   - **美股 (us)**：周二至周六 09:00（前一交易日深夜收盘后，次日上午更新）
2. 在 **自选管理** 中为需要提醒的股票勾选 **提醒**（`notify_enabled`）
3. 在 **推送设置** 页填写自己的 SMTP 与 WPUSH 凭据，并打开对应开关
4. 推送策略默认日 K 用 `daily_summary`（收盘后推送当日全部策略建议），时 K/分 K 用 `signal_change`（仅在 buy/hold/sell 变化时推送，避免刷屏）；两者都可在推送设置页按用户调整，`config/settings.yaml` 的 `notifications` 仅作为默认值

可在 `config/settings.yaml` 的 `scheduler.market_daily_run` 调整各市场时间。

```bash
# 手动执行一次全部市场收盘更新
python -m quant_picker.scheduler.runner --once

# 仅更新某一市场
python -m quant_picker.scheduler.runner --once cn
```

## 部署到服务器

在一台干净的 1C2G 机器上从零跑起来。**1. 装依赖**。先确认 `python3 --version` 是 3.11+；阿里云默认镜像经常是 3.6，需要另装：

```bash
# Alibaba Cloud Linux 3 / 较新系统
dnf install -y python3.11 python3.11-devel gcc
# 或 Ubuntu
# apt install -y python3.11 python3.11-venv python3.11-dev build-essential

git clone <repo> && cd quant-stock-picker
python3.11 -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt && pip install -e .
```

**2. 配环境**。只需要改 `.env`，`settings.yaml` 等跟着仓库走：

```bash
cp config/.env.example config/.env
# 编辑 config/.env：填 TICKFLOW_API_KEY 与 QUANT_PICKER_ADMIN_PASSWORD，其余保持默认
```

**3. 初始化**。跑一次即可，会建库、生成 `QUANT_PICKER_SECRET_KEY`、创建管理员：

```bash
quant-picker-init
```

不需要迁移任何本地数据。各用户的推送凭据登录后在页面里填。没设 `QUANT_PICKER_ADMIN_PASSWORD` 的话，随机密码会写进 `data/bootstrap_admin_password.txt` 并在这一步打印出来。

**4. 前台验证**：

```bash
./scripts/run_web.sh
python -m quant_picker.scheduler.runner --once
```

**5. 转 systemd 常驻**，两个服务共用同一个 `config/.env`：

```ini
# /etc/systemd/system/quant-web.service
[Unit]
Description=Quant Stock Picker Web
After=network.target

[Service]
User=quant
WorkingDirectory=/opt/quant-stock-picker
Environment=QUANT_PICKER_ROOT=/opt/quant-stock-picker
ExecStart=/opt/quant-stock-picker/scripts/run_web.sh
Restart=always

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/quant-scheduler.service
[Unit]
Description=Quant Stock Picker Scheduler
After=network.target

[Service]
User=quant
WorkingDirectory=/opt/quant-stock-picker
Environment=QUANT_PICKER_ROOT=/opt/quant-stock-picker
ExecStart=/opt/quant-stock-picker/.venv/bin/python -m quant_picker.scheduler.runner
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now quant-web quant-scheduler
```

2G 内存下的注意事项：

- `QUANT_PICKER_AUTO_SYNC_INTERVALS` 保持 `1d`。加入 `1h`/`1m` 会让 K 线量和 walk-forward 开销成倍上升，容易 OOM。
- `QUANT_PICKER_WEB_HOST` 建议保持 `127.0.0.1`，外部访问用 Nginx 反代加 HTTPS，不要把 Web 端口直接暴露公网。
- 需要备份的只有两样：数据库（`data/quant_picker.db`）和 `config/.env`。**密钥丢失后已保存的推送凭据无法解密。**

迁移到另一台机器：拷走 `data/` 和 `config/.env`，重新 `pip install`，其余配置文件跟着仓库走。已有数据库不用再跑 `quant-picker-init`，服务启动时会自行完成结构升级。

> 跳过第 3 步也能用：两个服务启动时都会自己建库，且已用锁串行化，同时拉起不会互相踩。单独跑一次只是为了让初始密码显示在终端而不是埋进服务日志。

## 项目结构

```
src/quant_picker/
  auth/          # 账号、密码哈希、登录闸门
  security/      # 推送凭据加解密
  data/          # TickFlow 行情（A股/港股/美股）
  strategies/    # MA/MACD/RSI
  backtest/      # 回测 + Walk-forward
  optimization/  # 逐股训练
  engine/        # 分析 + 更新
  scheduler/     # APScheduler
  notifications/ # 邮件 + 微信
  web/           # Streamlit
tests/           # pytest（用户隔离、推送配置、页面冒烟）
```

## 测试

```bash
pip install -e ".[dev]"
pytest -q
```

测试固定使用临时 SQLite，不会连接你配置的 PostgreSQL。

## 免责声明

**本程序仅供学习研究，不构成任何投资建议。** 历史回测与 Walk-forward OOS 表现不保证未来收益。不对接券商下单。
