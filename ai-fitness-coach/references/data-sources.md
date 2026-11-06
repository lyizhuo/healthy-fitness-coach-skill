# 数据源与本地存储

## 1. 小米运动健康：mi-health-mcp

Hermes 可走 Streamable HTTP MCP；脚本走同源 REST。两者共用查询层，返回结构一致。

### 环境变量

- `MI_HEALTH_BASE_URL`：例如 `https://your-mi-health.example.com`，或本机 `http://127.0.0.1:8330`
- `MI_HEALTH_API_KEY`：`mhk_...`，只读 scope 即可

### 常用 REST 端点

| 数据 | 端点 |
| --- | --- |
| 状态 | `GET /api/status` |
| 覆盖 | `GET /api/coverage` |
| 每日活动 | `GET /api/summary?start_date=&end_date=` |
| 心率 | `GET /api/heart-rate?start_date=&end_date=&sample_type=` |
| 睡眠 | `GET /api/sleep?start_date=&end_date=&include_naps=false` |
| 运动 | `GET /api/workouts?start_date=&end_date=` |
| 身体成分 | `GET /api/body-measurements?start_date=&end_date=` |
| 血氧 | `GET /api/spo2?start_date=&end_date=` |
| 压力 | `GET /api/stress?start_date=&end_date=` |
| 异常心搏 | `GET /api/abnormal-heart-beat?start_date=&end_date=` |
| 触发同步 | `POST /api/sync`（需要 sync scope） |

### MCP 工具

`get_connection_status`、`get_profile`、`get_daily_summary`、`query_metric_series`、`query_heart_rate`、`query_sleep`、`query_workouts`、`query_body_measurements`、`query_spo2`、`query_stress`、`query_abnormal_heart_beat`、`get_data_coverage`、`sync_data`、`get_sync_status`。

### 字段与新鲜度

- `SleepSession`：`duration_minutes`、`time_asleep_minutes`、`time_awake_minutes`、`sleep_score`、`stages[{stage, minutes}]`（`deep/light/rem/awake`）、整晚 HRV 聚合（`avg_hrv_ms`、`min_hrv_ms`、`max_hrv_ms`、`hrv_median_ms`、`hrv_std_ms`、分位、`hrv_base_min_ms`、`hrv_base_max_ms`、`hrv_analysis_at`）。
- `DailyActivity`：`steps`、`distance_m`、`active_kcal`、`total_kcal`、`floors`、`active_minutes`。
- `HeartRateSample`：`bpm`、`sample_type`（`resting/active/passive/workout`）、`timestamp`。
- `Workout`：`activity_type`、`duration_minutes`、`distance_m`、`calories_kcal`、`avg_heart_rate_bpm`、`max_heart_rate_bpm`、`avg_pace_sec_per_km`、`total_steps`。
- 每条响应带 `meta.data_as_of`、`meta.last_synced_at`、`meta.stale`；`stale=true` 时必须说明。

## 2. 训记：训练 Open API

- Base：`https://trains.xunjiapp.cn`
- 鉴权：`Authorization: Bearer $XUNJI_TRAIN_API_KEY`
- 读取：`POST /api_trains_for_llm_v2`
- 写回：`POST /api_upsert_trains_for_llm_v2`
- 计划：`POST https://api.xunjiapp.cn/open/plan/query_gzip`（同一训练 key）

完整契约见 `references/xunji-train-api.md`。

## 3. 训记：饮食 Open API

- 记录 Base：`https://eatings.xunjiapp.cn`
- 搜索 Base：`https://api.xunjiapp.cn`
- 鉴权：`Authorization: Bearer $XUNJI_FOOD_API_KEY`（记录） / `$XUNJI_FOOD_SEARCH_API_KEY`（搜索）
- 查询：`POST /open/food/query_gzip`
- 写回：`POST /open/food/upsert_gzip`
- 搜索：`POST /open_agent/food/search_gzip`

完整契约见 `references/xunji-food-api.md`。

## 4. 本地 SQLite

路径：`${HERMES_HOME:-~/.hermes}/data/ai-coach/coach.sqlite`

核心表：

- `trains`、`movements`、`sets`：训记训练归一化；保留 `raw_json`。
- `food_days`、`food_records`：饮食原始与归一化；`macro_known` 表示是否能按每 100g `ntr` 计算。
- `plans`：训记官方计划每日快照。
- `readiness`：每日 readiness 结果与分项；`inputs.freshness` 保留小米元数据。
- `weights`：体重记录。
- `decisions`：决策日志。
- `dna_versions`：训练 DNA 版本。
- `operations`：写回预览与确认状态，`client_request_id` 防重。

原始 JSON 保存在 `raw/`，用于审计和字段变化排查。小米数据不落本地库；`facts`/`readiness` 直接读取 mi-health REST，返回里带 `data_quality`（`stale`、`data_as_of`、`last_synced_at`、`error`）。

## 5. 数据原则

- 小米数据只读 mi-health，不复制、不落本地；REST 与 MCP 共用同一后端。
- 训记按日读取、按日缓存；同一天不重复请求。
- 饮食宏量禁止使用聚合 `totals`；必须按每 100g `ntr` 和实际克数本地累加。
- 单位不明、份量不明、食物匹配不唯一时标未知或追问，不猜。
