# Hermes AI Fitness Coach — 需求与设计共识稿

日期：2026-11-04  
状态：已实现（2026-11-06 修订：小米改为实时读取）  
目标运行时：Hermes Agent（远程，skills-only 交付）

## 1. 目标与边界

### 1.1 目标

做一个跑在 Hermes 上的私人 AI 健身与健康教练：

- 以训记官方计划为训练基线，读取实际训练记录，按增肌科学和当天恢复状态提出具体调整建议。
- 以小米运动健康数据（睡眠、HRV、静息/日间心率、压力、SpO₂、异常心搏、步数）做跨域 readiness。
- 以训记饮食 Open API 做食物搜索、记录读取、营养计算和确认后写回。
- 支持拍照记录饮食：视觉估算 → 食物库匹配 → 本地宏量计算 → 预览确认 → 写回。
- 每天主动运行晨间、训前、晚间三个工作流；每周日生成周报并更新训练 DNA。

### 1.2 非目标

- 不做医学诊断、疾病康复、妊娠产后处方、PED 指导、极端减脂。
- 不自动修改训记官方计划（官方计划接口只读）。
- 不做多用户/SaaS。
- 不建 PostgreSQL；不复制小米数据到第二套 ETL。
- 不做分享图、视觉海报、动作三帧图卡（v1 不带）。
- 不静默写回任何数据；写回必须预览并确认。

## 2. 运行时与部署形态

```text
Hermes Agent
├── skill: ai-fitness-coach
│   ├── SKILL.md                  # 路由、安全门、自主边界、输出规范
│   ├── references/               # 训练/营养/readiness/睡眠/训记 API/证据卡
│   └── scripts/                  # Python 3.11+ 标准库
├── HTTP MCP / REST: mi-health   # 小米数据，实时读取；worker 只刷新服务端
└── HTTP: 训记 Open API          # 训练 + 饮食，Bearer key
```

### 2.1 数据面

- 小米：`mi-health-mcp`，Hermes 可走 Streamable HTTP MCP；脚本走同源 REST `/api/*`，两者共用查询层。脚本每次请求当天 + 28 天基线，不落本地库。
- 训记：直接调用 `https://trains.xunjiapp.cn` 和 `https://eatings.xunjiapp.cn`，不经过本机 connector。
- 脚本运行时：Python 3.11+ 标准库（`urllib`、`sqlite3`、`json`、`statistics`），不依赖 Node。

### 2.2 本地数据

数据目录：`${HERMES_HOME:-~/.hermes}/data/ai-coach/`

- `coach.sqlite`：训记训练/饮食归一化缓存、readiness 快照、训练 DNA、决策日志、写回操作日志。
- `profile.json`：个人档案（12 项必需字段，不入 Git）；`PROFILE.md` 只是人读备份。
- `DECISIONS.md`：人类可读的决策日志（与 SQLite 同步）。
- `raw/`：训记原始 JSON 留存，便于审计和字段变化排查。

小米数据不落本地；每次读取的 `data_quality` 带 `data_as_of`、`last_synced_at`、`stale`、`error`。

## 3. 数据契约与归一化

### 3.1 小米（mi-health）

使用工具/端点：

- `get_daily_summary(start_date, end_date)`
- `query_heart_rate(start_date, end_date, sample_type)`
- `query_sleep(start_date, end_date)`
- `query_workouts(start_date, end_date)`
- `query_spo2` / `query_stress` / `query_abnormal_heart_beat`
- `get_data_coverage` / `get_connection_status`

字段以 `mi_health.models` 为准，包括 `SleepSession.stages` 的 `deep/light/rem/awake` 与整晚 HRV 聚合。**不按 PRD 的“无 deep 深睡”旧假设写死**；缺失时标注未知。

数据新鲜度：

- `stale=true` 时必须说明“数据可能不新”，不得把旧数据包装成实时结论。
- 异常心搏事件只触发安全提示，不参与 readiness 加权。

### 3.2 训记训练

- 读取：`POST /api_trains_for_llm_v2`，`schema_version: train_open_api_v2`，按 `datestr` 读取。
- 需要心率、RPE、休息、未完成组、左右侧重量时使用 `include_full_data: true`。
- 计划读取：`POST https://api.xunjiapp.cn/open/plan/query_gzip`，`plan_open_api_v1`，先 `list` 再 `get`；只读。
- 写回：`POST /api_upsert_trains_for_llm_v2`，`client_request_id`、`dry_run`、`res`；保留 `localid`、`start`、`end`；单次最多 4 条训练、同一天、每条最多 15 个动作、每个动作最多 20 组。
- 限频：轻量读 15s、完整读 30s、写回 45s；`too frequent` 按 `retry_after_ms` 等待。

归一化：

- `trains`、`movements`、`sets` 三张表；保留原始 JSON。
- 训练量：`weight × reps`；自重动作使用体重 × reps；计时/有氧使用时长、距离、心率。
- 混合单位（kg/lb）标记 `mixed_units`，不合并计算。
- 部位映射沿用上游 `training-dna-engine.js` 的中文肌群规则，移植到 Python。

### 3.3 训记饮食

- 查询：`POST /open/food/query_gzip`，日期范围限制在过去一年到未来 3 个月。
- 搜索：`POST https://api.xunjiapp.cn/open_agent/food/search_gzip`，优先 `res.foods[]`；`ntr` 是每 100g 营养，`units` 是单位换算，`uniquekey` 写回必带。
- 写回：`POST /open/food/upsert_gzip`，`foods[]` 包含 `date`、`meal_type`、`name`、`amount`、`unit`、`uniquekey`、`ntr`。
- 自定义食物：搜索不到时才创建；创建前展示营养来源和摘要，用户确认。
- **禁止使用聚合 `totals` 做宏量评估**；一律遍历记录，按每 100g `ntr` 和实际克数本地累加。
- 限频：查询/搜索/写回同类接口 15s。

### 3.4 鉴权与密钥

不在仓库、日志、回复中保存或回显 key。Hermes 侧使用：

- `XUNJI_TRAIN_API_KEY`
- `XUNJI_FOOD_API_KEY`
- `XUNJI_FOOD_SEARCH_API_KEY`
- `MI_HEALTH_BASE_URL`（非密）
- `MI_HEALTH_API_KEY`

通过 `~/.hermes/.env` 和 skill 的 `required_environment_variables` 注入。训练与饮食 key 分开；搜索 key 与饮食记录 key 也分开。

## 4. 核心工作流

### 4.1 晨间 readiness

默认时间：07:30（安装时可改）。

输入：

- 昨晚睡眠：时长、实际睡眠、清醒时长、分期、睡眠分。
- 整晚 HRV：avg/median/min/max/std、Xiaomi baseline。
- 静息心率、夜间/日间心率。
- 昨日压力、SpO₂、步数/活动。
- 昨日训记训练负荷与晚间饮食时间。
- 今日日程（可选日历工具；没有则给通用高能窗口）。

输出：

1. 一句判断（绿/黄/红）。
2. 2–3 条带具体数字的证据。
3. 今日训练/营养/认知负荷的具体动作。
4. 一句确认或追问。

Readiness 规则：

- 透明证据权重：睡眠时长 20、睡眠连续性 10、HRV 20、RHR 15、昨日训练负荷 15、压力 7.5、SpO₂ 7.5、活动 5。
- 异常心搏是安全门，不参与加权。
- 数据覆盖 <60% 时标记低置信度，采用保守建议。
- 初始阈值：绿 ≥70、黄 40–69、红 <40；无任何可用信号时输出“数据不足”，不冒充红/绿。
- 8 周后用实际表现/RPE 校准一次，校准写入决策日志，不自动改权重。
- HRV/RHR 用 28 天滚动中位数；Xiaomi baseline 作为辅助。
- 单次异常不下强结论；至少 3 次重复且无替代解释才说“模式”。

认知负荷：

- 基于睡眠时长、睡眠惯性和昼夜节律给“高能窗口”（如起床后 2–4 小时）。
- 有日历就避开固定日程，只在空档建议；没有日历就给通用窗口，由用户自行放置。
- 不修改日历、不改课表、不假设用户能调整固定课程。

### 4.2 训前 auto-regulation

默认时间：常去训练时间前 2 小时（安装时配置）。

输入：

- 今日 readiness、当前步数/活跃卡路里、日间心率。
- 昨日训练完成度、部位和训练量。
- 今日已记录饮食。
- 训记官方计划今天的动作/组次。

输出：

- 今天是否按计划、减量或改恢复。
- 具体到动作、组数、重量/RPE、休息的调整；一次只改 1–2 个变量。
- 训前 1 小时的具体碳水/蛋白质组合，符合宿舍/食堂条件。
- 如果数据不足，给保守版本并说明假设。

调整规则：

- 绿：按计划；可按渐进超负荷加 1 组或小幅加重。
- 黄：减少 1–2 个正式组，或把 RPE 上限降到 7–8；不同时减组和降强度。
- 红：主动恢复/休息；不做高疲劳复合动作。
- 红旗症状：停止训练建议，转安全分流。

### 4.3 晚间复盘

默认时间：21:00。

输入：

- 当日训记训练实际组次、重量、RPE、休息、时长。
- 当日饮食记录（本地累加）。
- 昨日/上周同指标。

输出：

- 训练量 vs 上周、动作表现、完成率。
- 蛋白质/碳水/脂肪/热量与目标差距。
- 1–2 条明天可执行的调整；不做惩罚性节食或有氧补偿。
- 写决策日志：证据、假设、取舍、下一次验证。

### 4.4 周报

默认时间：周日 21:00，也可手动。

内容：

- 训练频率、总组数、训练量、部位覆盖。
- 主要动作表现和渐进超负荷。
- 蛋白质执行率、体重趋势（有数据时）。
- readiness 趋势和异常信号。
- 下周 1–2 个调整建议。
- 更新训练 DNA（数据足够时）。

### 4.5 Photo-to-Macros

触发：用户发送食物图片且无明确文字指令；或明确说“记录这顿饭”。

管线：

1. 视觉识别食物、餐具/手等参照物，估算克数；炒菜额外估算 10–15g 烹饪油。
2. 调用训记食物搜索，优先 `res.foods[]`；匹配名称、单位、`uniquekey`、每 100g `ntr`。
3. 本地按克数累加，计算热量/蛋白/脂肪/碳水。
4. 输出预览：食物、估算克数、营养、假设、置信度。
5. 关键歧义最多问 1 个问题（如“米饭半碗还是一碗”）。
6. 用 `clarify` 给“确认写入 / 修改 / 取消”；Telegram 渲染为 inline buttons。
7. 确认后调用写回；成功用服务端返回覆盖缓存。
8. 搜索不到时创建自定义食物，但必须先展示营养来源并确认；不凭相似名称直接写回。

## 5. 训练计划与训练 DNA

### 5.1 计划

- 训记官方计划是基线，只读。
- coach 可以建议调整动作、组数、重量、RPE、休息，但不自动改官方计划。
- 训练记录写回仅在用户确认后执行；保留 `localid`、`start`、`end`、未完成组和原 note 元数据。

### 5.2 训练 DNA

- 从归一化训练历史提炼 8 个维度：训练频率、部位分布、有效刺激、负荷进展、有氧反应、恢复、依从性、风险边界。
- 每个结论带证据范围、置信度、未知项。
- 首次窗口只标记“观察中”；连续 2–3 个可比窗口才提高置信度。
- DNA 版本和变更写入 SQLite + `DECISIONS.md`，不覆盖历史。

## 6. 自主权与安全

### 6.1 自主权

- 低风险自主：休息日建议、餐食替换、组次微调建议、提醒。
- 中风险确认：写回训记、修改当日训练主结构。
- 高风险禁止：改长期周期、极端饮食、带伤训练、医学诊断。

### 6.2 安全边界

- 红旗：胸痛、晕厥/接近晕厥、异常心悸、轻微活动即明显气短、进行性麻木无力、急性严重外伤、近期手术。
- 红旗出现时停止自动训练处方，建议专业评估。
- 异常心搏事件：结合症状；有症状时按红旗处理，无症状也提示关注，不用来打分。
- 不做疾病诊断、康复处方、PED 或极端减脂。

## 7. 输出规范

- 中文，先结论后证据，再行动。
- 默认中短版，参考 PRD 的 Good Examples：判断 + 2–3 条具体数字/动作 + 一句确认。
- 不播报无意义数据；每条建议必须能落到今天的具体行为。
- 数据不足、过期、单位混合时必须标注，不制造趋势。
- 跨域归因用证据分级：单次“可能相关”，重复 ≥3 次才说“模式/倾向”，禁止把单次事件说成因果。

## 8. 错误与恢复

- 小米 stale：显示 `data_as_of` 和 `last_synced_at`，建议同步；不阻塞建议，但降低置信度。
- 训记限频：按 `retry_after_ms` 等待；同一天缓存优先。
- 写回未知：先核对服务端记录，不自动重试；本地操作日志按 `client_request_id` 防重。
- 搜索/匹配不确定：追问或取消，不猜。
- 数据缺失：标未知，不补齐、不编造。

## 9. 测试与验收

### 9.1 单元测试

- 训记 v2 训练/饮食 JSON 归一化。
- `totals` 拦截：只按每 100g `ntr` 累加。
- 训练量、混合单位、自重、计时/有氧。
- readiness 权重、缺失数据、异常心搏安全门、阈值边界。
- 营养目标与缺口计算。
- 写回预览、`localid` 保留、防重、限频。
- 训练 DNA 置信度和版本。

### 9.2 冒烟测试

用固定 fixture 跑：

- 晨间 readiness Markdown。
- 训前调整 Markdown。
- 晚间复盘 Markdown。
- 拍照记录预览 + 确认写回 dry-run。
- 周报 + DNA 更新。

### 9.3 验收标准

- 在无 Hermes 本地环境时，脚本可用 fixture 端到端跑通。
- 在 Hermes 中安装后，`/ai-fitness-coach` 能加载 skill，MCP/HTTP 配置正确。
- 工作流 cron（晨间/训前/晚间/周报）和每日训记同步能按配置触发并投递到聊天；小米数据由工作流实时读取。
- 任何写回都必须出现预览和确认；无确认不写。
- 密钥不出现在仓库、日志、回复和报告中。

## 10. 安装期待填

- 个人档案：年龄、性别、身高、时区、训练时间、训练分化、器械、伤病、饮食限制、常去食堂/外卖选项。
- 密钥：训记训练 key、饮食 key、食物搜索 key、mi-health key 和 URL。
- cron 时间：晨间、训前提前量、晚间、周报。
- 是否接日历：有则读日程，无则通用高能窗口。

## 11. 已定决策摘要

| 决策 | 结论 |
| --- | --- |
| 运行时 | Hermes Agent，远程，skills-only |
| 定位 | 通用骨架 + 私人档案 |
| 数据面 | mi-health-mcp + 训记 HTTP 直连 |
| 训记缓存 | SQLite 归一化 + raw JSON |
| 脚本 | Python 3.11+ 标准库 |
| 范围 | 全量 PRD：晨间/训前/晚间/周报/Photo-to-Macros/DNA |
| 写回 | 预览 + `clarify` 确认；训练实际记录、饮食记录 |
| 计划 | 训记官方计划只读，coach 只建议 |
| Readiness | 透明加权 + 数据完整度置信度；异常心搏安全门 |
| 归因 | 证据分级，单次不报因果 |
| 输出 | 中文，PRD Good Examples 风格，中短版 |
| 知识库 | 25 来源卡 + 新增睡眠/ExRx/RP 摘要 + 按需 web_search |
| 视觉 | v1 不做分享图/图卡 |
