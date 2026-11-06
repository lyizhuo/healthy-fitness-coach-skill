# 训记训练 Open API v2

## 鉴权

```http
Authorization: Bearer $XUNJI_TRAIN_API_KEY
Content-Type: application/json
```

也兼容 `x-api-key`。不要放 body/query；不要在日志或回复中回显。

## Base

- 训练：`https://trains.xunjiapp.cn`
- 官方计划：`https://api.xunjiapp.cn`
- 动作中文名表：`https://github.com/Foveluy/Xunji-movements`

## 读取训练

```http
POST https://trains.xunjiapp.cn/api_trains_for_llm_v2
Authorization: Bearer $XUNJI_TRAIN_API_KEY
Content-Type: application/json

{
  "schema_version": "train_open_api_v2",
  "datestr": "2026-11-03",
  "include_full_data": false
}
```

- 默认轻量读取；需要 RPE、未完成组、备注、左右侧重量、实练秒数、休息秒数、动作级心率时用 `include_full_data: true`。
- 训练在 `res.trains`；写回旧训练保留 `localid`、`start`、`end`。
- 动作休息：`restTime` 正式组，`warn_restTime` 热身组；`sets[].restSeconds` 是实际休息，不是目标。
- 有氧/计时/Tabata/苹果健康在 `sets[].metrics` 返回 `distance/kcal/calories/workoutTime/avgHeartRate/maxHeartRate/minHeartRate`。
- 整次心率在 `trains[].heartRate`；动作级心率在 `sets[].heartRate`，`values` 最多 50 个分桶平均点，第 N 点约 `N * step` 秒。
- 超级组在 `sets[].items[]`；递减组在 `include_full_data: true` 时 `sets[].dropSets[]`。

## 读取官方计划

```http
POST https://api.xunjiapp.cn/open/plan/query_gzip
Authorization: Bearer $XUNJI_TRAIN_API_KEY
Accept-Encoding: gzip

{"schema_version":"plan_open_api_v1","action":"list"}
```

```json
{
  "schema_version": "plan_open_api_v1",
  "action": "get",
  "plan_ref": "platform:155",
  "start_date": "2026-10-12",
  "end_date": "2026-11-12",
  "include_movements": true
}
```

- `list` 返回 `res.plans`；`get` 返回 `res.plan`、`res.date_range`、`res.days`。
- `get` 不传日期默认今天前 7 天到后 30 天；自定义范围最多 92 天。
- 只读；动作返回中文名和目标组，不返回内部 key。

## 写回训练

```http
POST https://trains.xunjiapp.cn/api_upsert_trains_for_llm_v2
Authorization: Bearer $XUNJI_TRAIN_API_KEY
Content-Type: application/json

{
  "schema_version": "train_open_api_v2",
  "client_request_id": "unique-id-from-agent",
  "dry_run": false,
  "include_full_data": false,
  "res": [
    {
      "datestr": "2026-11-03",
      "localid": 123456,
      "title": "胸部训练",
      "start": 1762180000000,
      "end": 1762183600000,
      "movements": [
        {
          "name": "杠铃卧推",
          "restTime": 90,
          "warnRestTime": 45,
          "sets": [
            {"done": true, "weight": "60", "unit": "kg", "reps": "10", "setType": "热"},
            {"done": true, "weight": "80", "unit": "kg", "reps": "8", "rpe": "8"}
          ]
        }
      ]
    }
  ]
}
```

### 写回规则

- 允许写今天前后各 6 个月内的日期。
- `res` 可以是数组或 `{ "trains": [...] }`；单次最多 4 条训练，必须同一天。
- 每条训练最多 15 个动作；每个动作最多 20 组/轮；不支持嵌套超级组。
- 有 `localid` 更新原训练；没有则新建。不要因为列表里缺少旧训练就删除旧训练。
- 更新旧训练保留 `localid`、`start`、`end`，除非用户明确要改时间。
- 动作只传中文 `name`，不要传内部 key。
- 组至少包含 `weight`/`weight_kg`、`reps`、`time`/`duration_s`、`selfWeight` 之一。
- 未完成组用 `done: false`；不要擅自删掉完整模式读到的未完成组。
- RPE 写在具体组：合法字符串 `"6"`、`"6.5"` … `"10"`；清空用 `""`，不要写 `0`。
- 动作难度写在 movement：`easy`、`normal`、`hard`。
- 超级组用 `sets[].items[]`，每个 set 表示一轮，item 包含中文 `name` 和单个 `set`。
- 原生有氧日用 `cardio: true` 且不传 `sets`，指标写在 movement 顶层 `metrics`；不要用“跑步_有氧训练 + sets”。
- 历史颜色在 `note.trainColor`，改前先读原训练，保留 `note` 其他字段。

## 限频与错误

- 轻量读 15 秒/次；完整读 30 秒/次；写回 45 秒/次。
- `too frequent`：按 `retry_after_ms` 等待。
- `apikey missing` / `apikey invalid`：让用户在训记 App 重新申请并更新 `~/.hermes/.env`。
- `仅VIP可用`：账号需要会员权限。

## 本地工具映射

- `python3 -m coach sync-day --date`：读取并归一化训练 + 饮食。
- `python3 -m coach sync-plan`：同步官方计划。
- `python3 -m coach plan --date`：查看本地计划快照。
- `python3 -m coach writeback preview-train --input`：本地校验 + 服务端 dry-run。
- `python3 -m coach writeback confirm-train --preview-id`：确认后写回。
