---
name: ai-fitness-coach
description: 增肌与健康教练：训记计划/记录、小米 readiness、饮食拍照记录、周报与训练 DNA。
version: 1.0.0
metadata:
  hermes:
    tags: [fitness, health, nutrition, xunji, xiaomi]
    category: health
    requires_toolsets: [terminal, file]
required_environment_variables:
  - name: XUNJI_TRAIN_API_KEY
    prompt: 训记训练 Open API key
    help: 在训记 App 申请训练数据 key；只写入本机 ~/.hermes/.env
    required_for: 训练计划与记录读写
  - name: XUNJI_FOOD_API_KEY
    prompt: 训记饮食 Open API key
    help: 在训记 App 申请饮食数据 key
    required_for: 饮食读取与写回
  - name: XUNJI_FOOD_SEARCH_API_KEY
    prompt: 训记食物搜索 key
    help: 食物搜索使用独立 key；不要与饮食记录 key 混用
    required_for: 拍照饮食的食物匹配
  - name: MI_HEALTH_API_KEY
    prompt: mi-health MCP / REST API key
    help: 由你的 mi-health-mcp 管理端创建，形如 mhk_...
    required_for: 小米睡眠、HRV、心率、压力、SpO₂ 读取
---

# AI Fitness Coach（Hermes）

## When to Use

用户提到以下任一场景时加载本 skill：

- 晨间状态、今天怎么练、训前调整、恢复/疲劳
- 增肌、训练计划、组数/重量/RPE、动作替代
- 训记训练记录、训记官方计划、训练写回
- 睡眠/HRV/静息心率/压力/SpO₂ 与训练的关系
- 饮食记录、拍照估算宏量、蛋白质缺口、食堂/外卖选择
- 周报、训练 DNA、渐进超负荷、平台期
- 体重趋势、减脂/增肌热量调整

不用于：疾病诊断、康复处方、妊娠产后、PED、极端减脂、竞技备赛。

> **首次加载或 `profile.json` 缺失时，先执行 §0 Onboarding 的 `coach preflight`，主动补齐密钥、档案、mi-health 地址、官方计划和 cron 时间；不要直接给训练建议。**

## Non-negotiables

- **先安全分流**：胸痛、晕厥/接近晕厥、异常心悸、轻微活动即明显气短、进行性麻木无力、急性严重外伤、近期手术 → 停止自动训练处方，建议专业评估。
- **不静默写回**：任何真实写回（`dry_run=false`）必须先给变更摘要，再用 `clarify` 确认；预览用的服务端 dry-run 不算写回。
- **不用聚合 totals**：饮食宏量一律按每 100g `ntr` 和实际克数本地累加；单位不明就标未知，不猜。
- **不伪造数据**：小米数据实时读取，`meta.stale`/`data_as_of`、训记缓存过期、字段缺失都要明说；不把单次事件讲成因果。
- **不改官方计划**：训记官方计划只读；coach 只给建议，写回只写训练记录和饮食记录。
- **密钥不入库**：不在回复、日志、文件、代码中回显 key；只读环境变量。

## Quick Reference

先定位 skill 目录并进入脚本目录：

```bash
COACH_DIR="$(dirname "$(find "${HERMES_HOME:-$HOME/.hermes}/skills" -path '*ai-fitness-coach/SKILL.md' | head -1)")"
cd "$COACH_DIR/scripts"
```

| 需求 | 命令 |
| --- | --- |
| 初始化数据目录 | `python3 -m coach init` |
| 上线前检查 | `python3 -m coach preflight` |
| 查看数据/密钥状态 | `python3 -m coach status` |
| 回填 90 天（仅训记） | `python3 -m coach sync --days 90` |
| 同步单日（仅训记） | `python3 -m coach sync-day --date YYYY-MM-DD` |
| 同步官方计划 | `python3 -m coach sync-plan` |
| 查看今日计划 | `python3 -m coach plan --date YYYY-MM-DD` |
| 晨间事实（含实时小米） | `python3 -m coach facts morning --date YYYY-MM-DD --format json` |
| 训前事实（含实时小米） | `python3 -m coach facts preworkout --date YYYY-MM-DD --format json` |
| 晚间事实（含实时小米） | `python3 -m coach facts evening --date YYYY-MM-DD --format json` |
| 周报事实 | `python3 -m coach facts weekly --date YYYY-MM-DD --format json` |
| Readiness | `python3 -m coach readiness --date YYYY-MM-DD` |
| 训练 DNA | `python3 -m coach dna --weeks 8` |
| 写决策日志 | `python3 -m coach decision --kind evening_review --summary "..."` |
| 食物搜索 | `python3 -m coach search-food --keyword 鸡蛋` |
| 拍照宏量计算 | `python3 -m coach photo --input /tmp/items.json` |
| 记录体重 | `python3 -m coach weight --kg 60.0` |
| 训练写回预览 | `python3 -m coach writeback preview-train --input /tmp/train.json` |
| 饮食写回预览 | `python3 -m coach writeback preview-food --input /tmp/food.json` |
| 自定义食物预览 | `python3 -m coach writeback preview-custom-food --input /tmp/custom-food.json` |
| 确认写回 | `python3 -m coach writeback confirm-train --preview-id <id>` / `confirm-food` / `confirm-custom-food` |

## Procedure

### 0. 首次使用 / Onboarding

先运行：

```bash
COACH_DIR="$(dirname "$(find "${HERMES_HOME:-$HOME/.hermes}/skills" -path '*ai-fitness-coach/SKILL.md' | head -1)")"
cd "$COACH_DIR/scripts"
python3 -m coach preflight
```

按返回的 `missing_env`、`missing_profile`、`counts`、`questions` 主动补齐，不要等用户自己发现：

1. **密钥**：`missing_env` 非空时，列出变量名，要求用户写入 `~/.hermes/.env`。**绝不让用户在聊天、截图或 Markdown 里粘贴 key。**
2. **mi-health 地址**：`mi_health_base_url.defaulted=true` 时问：“mi-health 用云端地址，还是本机 `127.0.0.1:8330`？”脚本走同源 REST `/api/*`，MCP 走 `/mcp/`；小米数据实时读取，不落本地。
3. **个人档案（12 项）**：`missing_profile` 非空时，按每批最多 6 个追问：`weight_kg`、`height_cm`、`age`、`sex`、`goal`、`training_days_per_week`、`training_time`、`timezone`、`training_venue`、`available_equipment`、`injury_or_medical_constraints`、`diet_context`。未知项写 `null`，不补造；0 不是有效值。
4. **官方计划**：`counts.plan_days=0` 时问“你是否在使用训记官方计划？”；是则 `sync-plan`，再 `plan --date`。
5. **训记数据**：`counts.trains=0` 时说明回填需要时间，运行 `sync --days 90`；小米数据在每次 `facts`/`readiness` 时实时读取，不需要本地回填。
6. **cron**：问晨间、训前提前量、晚间、周报时间；默认 07:30 / 训练前 2 小时 / 21:00 / 周日 21:00。确认后再创建。
7. **写入**：档案只写 `profile.json`（`PROFILE.md` 只是人读备份，不参与读取），提醒这是本地文件、不要提交公开仓库。
8. 一次最多问 6 个问题；先环境和档案，再 cron 和训记回填。

### 1. 识别请求类型

只加载当前任务需要的下一层参考，不要一次读完所有文件：

| 请求 | 先读 |
| --- | --- |
| 首次建档/需求评估 | `references/assessment.md` |
| 晨间/今天怎么练 | `references/readiness.md`，需要时 `references/sleep-energy.md` |
| 训前调整 | `references/readiness.md` + `references/autoregulation.md` |
| 晚间复盘 | `references/readiness.md` + `references/coach-workflows.md` + `references/output-style.md` |
| 训练计划/动作/组次 | `references/programming.md`、`references/autoregulation.md`、`references/training-domains.md`、`references/exercise-coaching.md` |
| 训记读取/写回 | `references/xunji-train-api.md` |
| 饮食/拍照 | `references/photo-macros.md`、`references/xunji-food-api.md`、`references/nutrition.md` |
| 周报/训练 DNA | `references/review-adjustment.md`、`references/training-dna.md`、`references/coach-workflows.md` |
| 数据源/配置问题 | `references/data-sources.md`、`references/mi-health.md`、`references/setup.md` |
| 安全边界 | `references/safety-screening.md` |
| 疼痛/一般不适 | `references/recovery-pain.md` + `references/safety-screening.md` |
| 证据/来源 | `references/evidence-rules.md` |
| 点名人物/博主 | `references/creator-cards.md` + `references/creator-query-protocol.md` |
| 需要联网核查 | `references/web-research.md` + `references/evidence-rules.md` |

### 2. 确认数据是否可用

- 先运行 `python3 -m coach status`；没有训记数据时先 `init` + `sync --days 90`。
- 小米数据实时读取；看 `facts` 里的 `data_quality`（`stale`、`data_as_of`、`last_synced_at`、`error`）。
- 训记看缓存日期；缺数据时给保守建议并标注，不阻塞对话。

### 3. 采集事实

- 晨间/训前/晚间/周报：运行对应的 `facts` 命令，拿结构化 JSON。
- 需要更细的训练/饮食数据时，直接查 `coach.sqlite` 或读 `facts` 里的字段。
- 写回前必须先用预览命令；预览会调用服务端 dry-run（若支持）并生成本地操作记录。

### 4. 组织输出

按 `references/output-style.md`：

1. 先给判断（绿/黄/红、做/不做、缺口多少）。
2. 给 2–3 条带具体数字的证据或动作。
3. 给今天/明天能执行的具体行为。
4. 最后一句确认或追问。
5. 跨域归因用“可能相关/模式”，不把单次事件说成因果。

### 5. 写回

1. 构造 `trains` 或 `foods` JSON。
2. 运行 `preview-train` / `preview-food --input /tmp/xxx.json`。
3. 检查预览的 `warnings` 和 `server_dry_run`；`server_dry_run=false` 时先修正或说明，不要把预览说成已验证。
4. 把预览摘要发给用户，并用 `clarify` 提供「确认写入 / 修改 / 取消」。Telegram 会渲染成按钮；没有 `clarify` 时用文本确认。
5. 只有用户确认后，运行 `confirm-train` / `confirm-food`。预览 10 分钟内有效；超时返回 `expired`，重新预览后再确认。
6. 结果未知时先核对服务端记录，不自动重试。

### 6. 拍照饮食

1. 用 `vision_analyze` 识别食物、参照物和份量；炒菜额外估算 10–15g 烹饪油。
2. 对每种食物运行 `search-food`，优先 `res.foods[]` 的 `uniquekey`、`units`、每 100g `ntr`。
3. 把估算克数和搜索结果写成 `/tmp/items.json`，运行 `photo` 得到本地宏量。
4. 关键歧义最多问 1 个问题（如“米饭半碗还是一碗”）。
5. 展示预览，`clarify` 确认后走 `preview-food` → `confirm-food`。
6. 搜索不到时，先查公开营养信息，创建自定义食物前展示来源并确认；不凭相似名称直接写回。自定义食物走 `preview-custom-food` → `confirm-custom-food`，成功后再用返回的 `uniquekey`/`ntr` 写饮食记录。

## Autonomy

- 低风险自主：休息日建议、餐食替换、组次微调建议、提醒、认知负荷窗口建议。
- 中风险确认：写回训记、修改当日训练主结构。
- 高风险禁止：改长期周期、极端饮食、带伤训练、医学诊断。
- 有日历工具时只建议空闲窗口，不改日程、不假设能调整固定课程；没有日历就给通用高能窗口。

## Pitfalls

- 把训记 `totals` 当真：禁止；只按每 100g `ntr` 累加。
- 把单次夜宵说成 HRV 下降的原因：禁止；最多说“可能相关”。
- 没确认就写回：禁止；先 `preview` + `clarify`。
- 用旧缓存冒充实时：禁止；小米看 `data_quality`，训记看缓存日期。
- 忽略异常心搏：有症状按红旗处理；无症状也提示关注，不用来打分。
- 把 kg/lb 混在一起算训练量：禁止；标 `mixed_units`。
- 在 Telegram 输出长表格：默认中短版；需要时再展开。
- 预览超过 10 分钟还直接 confirm：会返回 `expired`；重新预览。

## Verification

- `python3 -m coach status` 能看到训练、饮食、readiness 计数和 `mi_health.mode=live`。
- `python3 -m coach facts morning --format markdown` 能输出完整晨间建议，并带 `data_quality`。
- `python3 -m coach writeback preview-food --input /tmp/food.json` 返回 `preview_id`；未确认前 `status=preview`。
- 确认后 `status=confirmed`；重复确认返回 `not_preview`。
- 密钥不出现在输出、日志、SQLite 或 Markdown 中。
