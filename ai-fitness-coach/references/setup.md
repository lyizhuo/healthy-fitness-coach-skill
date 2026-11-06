# 安装与配置

## 1. 安装 skill

推荐用 GitHub 安装，Hermes 会记录来源和内容 hash，之后可 `hermes skills update`：

```bash
hermes skills inspect lyizhuo/healthy-fitness-coach-skill/ai-fitness-coach
hermes skills install lyizhuo/healthy-fitness-coach-skill/ai-fitness-coach
hermes skills list --source hub
```

会话内也可以 `/skills install lyizhuo/healthy-fitness-coach-skill/ai-fitness-coach`。前提是该路径已推送到 GitHub 默认分支。

更新：

```bash
hermes skills check
hermes skills update ai-fitness-coach
```

本地开发时可以把仓库里的 `ai-fitness-coach/` 手工复制到 skills 目录：

```bash
mkdir -p "${HERMES_HOME:-$HOME/.hermes}/skills/health"
cp -R ai-fitness-coach "${HERMES_HOME:-$HOME/.hermes}/skills/health/ai-fitness-coach"
```

确认 `SKILL.md` 在：

```text
${HERMES_HOME:-$HOME/.hermes}/skills/health/ai-fitness-coach/SKILL.md
```

## 2. 配置密钥

写入 `${HERMES_HOME:-$HOME/.hermes}/.env`（不要提交到 Git）：

```bash
# 云端（你的 mi-health）：
MI_HEALTH_BASE_URL=https://your-mi-health.example.com
# 本机则改成 http://127.0.0.1:8330
MI_HEALTH_API_KEY=mhk_...
XUNJI_TRAIN_API_KEY=xjllm_...
XUNJI_FOOD_API_KEY=xjfood_...
XUNJI_FOOD_SEARCH_API_KEY=...
AI_COACH_TZ=Asia/Shanghai
```

注意：

- 训练 key、饮食记录 key、食物搜索 key 是三个不同的 key。
- 不要把这些值写进 SKILL.md、README、日志或聊天。
- 如果 key 曾经出现在聊天/截图/公开文件里，到训记 App 重新申请。

## 3. 配置 mi-health MCP

在 `${HERMES_HOME:-$HOME/.hermes}/config.yaml` 加入：

```yaml
mcp_servers:
  mi-health:
    url: "https://your-mi-health.example.com/mcp/"   # 本机用 http://127.0.0.1:8330/mcp/
    headers:
      Authorization: "Bearer ${MI_HEALTH_API_KEY}"
```

小米数据实时读取，不落本地 SQLite；脚本走同源 REST `/api/*`，Hermes 对话走 MCP `/mcp/`。确保 Hermes 主机能访问该地址。

重启 Hermes 或 `/reload-mcp` 后验证：

```bash
hermes mcp configure mi-health
```

## 4. 让 cron 脚本拿到密钥

no-agent cron 脚本不会自动继承 skill 的 `required_environment_variables`，需要在 `config.yaml` 声明：

```yaml
terminal:
  env_passthrough:
    - MI_HEALTH_BASE_URL
    - MI_HEALTH_API_KEY
    - XUNJI_TRAIN_API_KEY
    - XUNJI_FOOD_API_KEY
    - XUNJI_FOOD_SEARCH_API_KEY
    - AI_COACH_HOME
    - AI_COACH_TZ
```

## 5. 初始化与回填

```bash
COACH_DIR="${HERMES_HOME:-$HOME/.hermes}/skills/health/ai-fitness-coach"
cd "$COACH_DIR/scripts"
python3 -m coach init
python3 -m coach preflight
python3 -m coach sync-plan
python3 -m coach sync --days 90
python3 -m coach status
```

回填 90 天只同步训记训练/饮食，默认轻量读取（约 20–25 分钟）；需要历史 RPE/备注/未完成组时加 `--full`（约 45 分钟）。小米数据不需要回填，`facts`/`readiness` 每次实时读取。每天 `sync-day` 默认完整读取，覆盖当天最新数据。中断后重跑会按日期覆盖，不产生重复。

## 6. 填写个人档案

推荐让 agent 用 onboarding 写入 `${HERMES_HOME:-$HOME/.hermes}/data/ai-coach/profile.json`：

```json
{
  "weight_kg": null,
  "height_cm": null,
  "age": null,
  "sex": null,
  "goal": "hypertrophy",
  "training_days_per_week": 5,
  "training_time": "18:30",
  "timezone": "Asia/Shanghai",
  "training_venue": "gym",
  "available_equipment": ["barbell", "dumbbell", "machines"],
  "injury_or_medical_constraints": "none",
  "diet_context": "canteen / takeout"
}
```

12 项必需字段；未知写 `null`，不要写 `0`（`0` 会被视为缺失）。可选字段 `dietary_restrictions`、`usual_breakfast/lunch/dinner` 可以额外加。`height_cm`/`age` 缺失时，热量目标只给区间，不强行算 TDEE。个人档案不要提交到公开仓库。

## 7. 创建 cron

### 7.1 每日同步（no-agent）

每日同步只处理训记；小米在每次 `facts`/`readiness` 时实时读取，不需要本地同步任务。

创建 `~/.hermes/scripts/ai-coach-sync.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail
COACH_DIR="$(dirname "$(find "${HERMES_HOME:-$HOME/.hermes}/skills" -path '*ai-fitness-coach/SKILL.md' | head -1)")"
cd "$COACH_DIR/scripts"
YESTERDAY="$(python3 -c 'import os, datetime; from zoneinfo import ZoneInfo; tz=ZoneInfo(os.environ.get("AI_COACH_TZ","Asia/Shanghai")); print((datetime.datetime.now(tz).date()-datetime.timedelta(days=1)).isoformat())')"
exec python3 -m coach sync-day --date "$YESTERDAY"
```

```bash
chmod +x ~/.hermes/scripts/ai-coach-sync.sh
hermes cron create "10 0 * * *" --no-agent --script ai-coach-sync.sh --name "ai-coach-sync"
```

### 7.2 晨间 / 训前 / 晚间 / 周报

默认时间（按你的时区改）：

```bash
hermes cron create "30 7 * * *" "运行 ai-fitness-coach 的晨间工作流：读取今天的小米和训记数据，按 readiness 给出今天训练、营养和高能窗口建议。按 references/output-style.md 输出。" --skill ai-fitness-coach --deliver telegram --name "ai-coach-morning"

hermes cron create "30 16 * * *" "运行 ai-fitness-coach 的训前工作流：读取今日计划、readiness、今日饮食和活动，给出具体到动作/组数/重量/RPE 的调整，以及训前 1 小时进食建议。" --skill ai-fitness-coach --deliver telegram --name "ai-coach-preworkout"

hermes cron create "0 21 * * *" "运行 ai-fitness-coach 的晚间复盘：核对今日训练量和宏量缺口，给 1–2 条明天调整，并写入决策日志。" --skill ai-fitness-coach --deliver telegram --name "ai-coach-evening"

hermes cron create "0 21 * * 0" "运行 ai-fitness-coach 的周报：训练频率/组数/训练量、部位覆盖、主要动作表现、蛋白执行率、readiness 趋势、下周 1–2 个调整；更新训练 DNA。" --skill ai-fitness-coach --deliver telegram --name "ai-coach-weekly"
```

训前时间按你的实际训练时间减 2 小时；晨间/晚间按作息改。先只开晨间和晚间，稳定后再加训前/周报也可以。

## 8. 验证

```bash
cd "$COACH_DIR/scripts"
python3 -m unittest discover -s tests -v
python3 -m coach status
python3 -m coach preflight
python3 -m coach facts morning --date "$(date +%F)" --format markdown
python3 -m coach facts evening --date "$(date +%F)" --format markdown
```

在 Hermes 中：

- `/ai-fitness-coach` 能加载 skill。
- 问“今天怎么练”能触发晨间/训前工作流。
- 拍照发食物图能触发 Photo-to-Macros 预览。
- 任何写回都出现 `clarify` 确认。

## 9. 常见问题

- **MCP 连不上**：确认 `MI_HEALTH_BASE_URL` 末尾没有多余路径；MCP 是 `/mcp/`，REST 是 `/api/*`。小米数据不落本地，`facts` 报 `小米接口不可用` 时先查这个地址和 key。
- **401/403**：key 失效或 scope 不对；只读 key 不能 `sync_data`。
- **训记 too frequent**：等待 `retry_after_ms`；不要连续重试。
- **饮食宏量全是未知**：检查 `units` 是否能换算到克；不能换算时先问用户份量。
- **cron 没跑**：确认 gateway 在运行、`terminal.env_passthrough` 已配置、脚本在 `~/.hermes/scripts/`。
- **重装/升级**：skill 目录覆盖后，`profile.json`、`coach.sqlite`、`DECISIONS.md` 在 `${HERMES_HOME:-~/.hermes}/data/ai-coach/`，不会被覆盖。
