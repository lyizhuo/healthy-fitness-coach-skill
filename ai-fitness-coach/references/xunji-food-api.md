# 训记饮食 Open API

## 鉴权

- 饮食记录/自定义食物/模板：`Authorization: Bearer $XUNJI_FOOD_API_KEY`
- 食物搜索：`Authorization: Bearer $XUNJI_FOOD_SEARCH_API_KEY`
- 也兼容 `x-api-key` / `x-agent-key`；不要放 body/query；不要回显。

## Base

- 记录：`https://eatings.xunjiapp.cn`
- 搜索：`https://api.xunjiapp.cn`

## 查询饮食记录

```http
POST https://eatings.xunjiapp.cn/open/food/query_gzip
Authorization: Bearer $XUNJI_FOOD_API_KEY
Content-Type: application/json

{
  "start_date": "2026-08-01",
  "end_date": "2026-11-04",
  "include_detail": true
}
```

- 范围限制：过去一年到未来 3 个月；超出时拆分。
- 成功时 `success === true`，核心在 `res`。
- 读取后按 `日期 + 餐次 + 食物名 + 记录 id` 缓存；写回成功后用服务端返回覆盖缓存。
- 只读用户明确需要的范围，不扫全量。

## 搜索食物

```http
POST https://api.xunjiapp.cn/open_agent/food/search_gzip
Authorization: Bearer $XUNJI_FOOD_SEARCH_API_KEY
Content-Type: application/json

{"keyword": "鸡蛋", "limit": 8}
```

- 优先 `res.foods[]`；`ntr` 是**每 100g** 营养；`units` 是单位换算；`uniquekey` 写回必带。
- `res.d` 是客户端压缩数组 `[id, name, cal, carb, fat, protein, foodpic, uniquekey, units]`。
- 匹配不唯一、单位或份量不确定时先问用户，不要凭相似名称写回。

## 写回饮食记录

```http
POST https://eatings.xunjiapp.cn/open/food/upsert_gzip
Authorization: Bearer $XUNJI_FOOD_API_KEY
Content-Type: application/json

{
  "client_request_id": "unique-id-from-agent",
  "dry_run": false,
  "foods": [
    {
      "date": "2026-11-04",
      "meal_type": "lunch",
      "name": "鸡胸肉",
      "amount": 150,
      "unit": "g",
      "uniquekey": "使用搜索结果或自定义食物返回的 uniquekey",
      "ntr": {"cal": 165, "protein": 31, "fat": 3.6, "carb": 0}
    }
  ]
}
```

- 写回前必须先搜索，带上 `uniquekey`、`units` 和每 100g `ntr`。
- 写回接口不搜索、不猜营养；没有确认过的 `ntr` 不写。
- 有服务端记录 id 时更新原记录；没有则新建；不删除未出现的旧记录。
- 写回前展示日期、餐次、食物、数量、单位，并等待确认。
- 同类接口 15 秒/次；`too frequent` 按 `retry_after_ms` 等待。

## 创建自定义食物

```http
POST https://eatings.xunjiapp.cn/open/food/custom/upsert_gzip
Authorization: Bearer $XUNJI_FOOD_API_KEY
Content-Type: application/json

{
  "client_request_id": "unique-id-from-agent",
  "dry_run": false,
  "food": {
    "name": "用户确认的食物名",
    "ntr": {
      "cal": 165,
      "protein": 31,
      "fat": 3.6,
      "carb": 0,
      "foodpic": "",
      "foodUnit": [{"unit": "份", "count": "1", "gram": 100}]
    },
    "units": [{"unit": "份", "count": "1", "gram": 100}]
  }
}
```

- 只有搜索不到合适官方食物，或用户明确要私有食物时才创建。
- 创建前展示营养来源和每 100g 数值，让用户确认；不确定时追问，不估算。
- `units` 与 `ntr.foodUnit` 必须一致；没有明确单位时传空数组，默认按克。
- 创建成功后用返回的 `res.food` 的 `name`、`uniquekey`、`units`、`ntr` 再写回记录。

## 模板

- 查询：`POST /open/food/templates/list_gzip`
- 套用：`POST /open/food/templates/apply_gzip`
- 套用模板也是写回，必须先给摘要并确认。

## 单位与 totals 陷阱

- 只按每 100g `ntr` 和实际克数累加；**禁止直接使用聚合 `totals`**。
- 单位是 `g/克` 时：`factor = amount / 100`。
- 单位是 `个/份` 等：必须从 `units` 找到 `gram`/`count` 换算；找不到就标未知，不累加。
- 一份记录如果 `ntr` 看起来是“整份”而不是每 100g，先核对来源；不能确认就不写入统计。

## 本地工具映射

- `python3 -m coach search-food --keyword 鸡蛋`：搜索并返回 `res.foods`。
- `python3 -m coach photo --input items.json`：按每 100g `ntr` 计算拍照估算。
- `python3 -m coach writeback preview-food --input foods.json`：本地校验 + 服务端 dry-run。
- `python3 -m coach writeback confirm-food --preview-id`：确认后写回。

## 查询记录的 ntr 语义

饮食查询返回的 `ntr` 可能是“该条记录的实际营养”，也可能仍是每 100g；不同接口/字段版本不一致。本 skill 的处理：

- 先按每 100g × 克数计算 `per100`。
- 如果记录带 `cals`/`calories`，比较 `cals` 更接近 `ntr.cal` 还是 `ntr.cal × factor`：
  - 更接近 `ntr.cal` → `macro_basis=record`，直接用 `ntr` 作为该条总量；
  - 更接近 `per100` → `macro_basis=per_100g`，用乘算结果。
- 没有 `cals` 时默认按每 100g 计算，并保留 `macro_basis` 供审计。
- 单位无法换算到克时 `macro_known=false`，不计入总数。

这条规则是为了同时兼容两种返回形态，不是鼓励使用聚合 `totals`。
