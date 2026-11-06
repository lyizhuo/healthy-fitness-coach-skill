# mi-health-mcp 使用说明

## 连接方式

Hermes 可用两种方式：

1. **MCP（推荐给对话）**：Streamable HTTP，URL 形如 `https://your-mi-health.example.com/mcp/`（本机则 `http://127.0.0.1:8330/mcp/`），Header `Authorization: Bearer $MI_HEALTH_API_KEY`。
2. **REST（推荐给脚本）**：`$MI_HEALTH_BASE_URL/api/*`，同一 Bearer key。`scripts/coach/mi_health.py` 使用这条路径。

小米数据实时读取，不落本地 SQLite；脚本一次读取当天 + 28 天基线（`sleep/heart-rate/summary` 范围查询）。

## MCP 工具

| 工具 | 用途 |
| --- | --- |
| `get_connection_status` | 配置与各类型同步状态 |
| `get_daily_summary` | 每日步数/距离/卡路里 |
| `query_metric_series` | steps/distance_m/active_kcal 日/周/月 |
| `query_heart_rate` | 逐分钟/静息/被动心率 |
| `query_sleep` | 睡眠、分期、整晚 HRV |
| `query_workouts` | 小米运动记录 |
| `query_body_measurements` | 体重/体脂（有秤时） |
| `query_spo2` | 血氧 |
| `query_stress` | 压力 |
| `query_abnormal_heart_beat` | 异常心搏事件 |
| `get_data_coverage` | 数据覆盖与缺口 |
| `sync_data` | 强制同步（需要 sync scope） |
| `get_sync_status` | 同步任务状态 |

## 响应结构

```json
{
  "status": "ok",
  "data": [],
  "meta": {
    "count": 0,
    "data_as_of": "...",
    "last_synced_at": "...",
    "next_sync_at": "...",
    "stale": false,
    "sync_status": "healthy",
    "sync_error": null,
    "source": "mi_fitness_cloud"
  }
}
```

## 使用规则

- 先看 `meta.stale`；`true` 时说明数据可能不新，不把旧数据包装成实时结论。`facts` 会把它汇总到 `data_quality`，并带 `data_as_of`/`last_synced_at`/`error`。
- `query_sleep` 默认 `include_naps=true`；教练分析用 `include_naps=false`，避免午睡干扰夜间睡眠。
- 睡眠分期可能是 `deep/light/rem/awake`；缺失时标未知，不按 PRD 的旧假设写死。
- 静息心率优先 `sample_type=resting`；没有时用被动样本的最低值，并标方法。
- 异常心搏事件只做安全提示，不参与 readiness 加权。
- 身体成分没有数据时不追问、不编造；有秤数据时可用于体重趋势。
- 小米数据是只读；写回只发生在训记。
