# 教练工作流

## 0. 首次安装

```bash
cd <skill>/scripts
python3 -m coach init
# 配置 ~/.hermes/.env 后
python3 -m coach sync-plan
python3 -m coach sync --days 90
python3 -m coach status
```

首次回填只同步训记，默认轻量读取约 20–25 分钟；加 `--full` 约 45 分钟（训记按天读，15/30 秒一次）。回填期间可以继续聊天，但趋势/基线结论要标注数据未齐。小米数据实时读取，不用回填。

## 1. 晨间 readiness

触发：默认 07:30，或用户说“早上好/今天怎么练/我今天状态怎么样”。

步骤：

1. 运行 `python3 -m coach facts morning --date <today> --format json`。
2. 读 `readiness`、`sleep`、`hrv`、`rhr`、`yesterday.training_load`、`energy_window`。
3. 按 `references/output-style.md` 组织：判断 → 2–3 条证据 → 今日动作 → 一句确认。
4. 如果 `data_quality.stale=true` 或 `error` 非空，说明小米数据可能不新或接口异常，结论置信度低。
5. 如果 `readiness.safety_flag=true`，先给安全提示，再给训练建议。

不要：

- 只报“睡眠分 82”。
- 没有数据还硬给绿/黄/红。
- 把单次夜宵说成 HRV 下降的原因。

## 2. 训前 auto-regulation

触发：默认训练前 2 小时，或用户说“等会儿练/今天练什么/帮我调一下”。

步骤：

1. 运行 `python3 -m coach facts preworkout --date <today> --format json`。
2. 读 `plan`（训记官方计划）、`readiness`、`today_food`、`yesterday_training`、`activity`。
3. 给出具体调整：动作、组数、重量/RPE、休息；一次只改 1–2 个变量。
4. 给训前 1 小时的碳水/蛋白组合，符合你的实际就餐条件（食堂/外卖/宿舍）。
5. 如果计划未同步，先 `sync-plan`；仍没有就按常规安排给建议并说明。

调整规则：

- 绿：按计划；可加 1 组或小幅加重。
- 黄：减 1–2 个正式组，或 RPE 上限 7–8；不同时改两个。
- 红：主动恢复/休息；不做高疲劳复合动作。
- 红旗：停止训练建议，转安全分流。

## 3. 晚间复盘

触发：默认 21:00，或用户说“今天练完了/复盘一下”。

步骤：

1. 运行 `python3 -m coach facts evening --date <today> --format json`。
2. 读 `trains`、`food`、`gap`、`weekly_volume`、`protein_options`。
3. 输出：训练量 vs 上周、动作表现、蛋白/热量缺口、1–2 条明天调整。
4. 把本次判断写入决策日志：
   ```bash
   python3 -m coach decision --date <today> --kind evening_review \
     --summary "..." --evidence '{"volume":...}' --action "..." --verification "..."
   ```

不要：

- 因为一顿高热量安排补偿性节食或有氧。
- 用 `totals` 或估算值冒充精确摄入。
- 一天改多个变量。

## 4. 周报与训练 DNA

触发：默认周日 21:00，或用户说“周报/总结这周/更新训练 DNA”。

步骤：

1. 运行 `python3 -m coach facts weekly --date <today> --format json`。
2. 运行 `python3 -m coach dna --weeks 8`（会保存新版本）。
3. 输出：训练频率/组数/训练量、部位覆盖、主要动作表现、蛋白执行率、readiness 趋势、下周 1–2 个调整。
4. DNA 置信度：`insufficient`/`low` 时只当观察，不包装成结论；连续 2–3 个窗口后才提高。

## 5. 拍照饮食

触发：用户发食物图片且无明确文字指令，或说“记录这顿饭”。

步骤：

1. 用 `vision_analyze` 识别食物、餐具/手等参照物、份量；炒菜额外估算 10–15g 油。
2. 对每种食物 `search-food --keyword`，优先 `res.foods[]` 的 `uniquekey`、`units`、每 100g `ntr`。
3. 把估算克数和搜索结果写成 `/tmp/items.json`：
   ```json
   {
     "date": "2026-11-04",
     "meal_type": "lunch",
     "items": [
       {"name": "鸡胸肉", "amount": 120, "unit": "g", "uniquekey": "...", "ntr": {"cal": 165, "protein": 31, "fat": 3.6, "carb": 0}}
     ]
   }
   ```
4. 运行 `python3 -m coach photo --input /tmp/items.json`，得到本地宏量。
5. 关键歧义最多问 1 个问题（米饭半碗/一碗、几个蛋）。
6. 展示预览；`clarify` 给「确认写入 / 修改 / 取消」。
7. 确认后 `writeback preview-food` → `confirm-food`。

搜索不到时：

- 查公开营养信息或包装成分表。
- 创建自定义食物前展示来源和每 100g 数值，等确认。
- 自定义食物走 `writeback preview-custom-food` → `confirm-custom-food`。
- 不凭相似名称直接写回。

## 6. 训练写回

训练写回只写**训练记录**，不改官方计划。

1. 从用户描述/已完成训练构造 `trains` JSON；更新旧记录保留 `localid`、`start`、`end`。
2. 运行 `writeback preview-train --input`。
3. 展示变更摘要；`clarify` 确认。
4. `writeback confirm-train --preview-id`。
5. 结果未知先核对服务端记录，不自动重试。

## 7. 数据同步

- 每日：`python3 -m coach sync-day --date <yesterday/today>`；或让 Hermes no-agent cron 在 00:10 跑 `sync-day`。
- 小米：`facts`/`readiness` 每次实时读取 mi-health，没有本地同步任务；服务端 worker 只影响 `meta.stale`。
- 计划：每周/训练周期开始时 `sync-plan`。
- 回填：`sync --days 90`；中断后重跑会按日期覆盖，不产生重复。

## 8. 失败与恢复

- 训记 `too frequent`：等待 `retry_after_ms`，不要连环重试。
- 写回 `unknown`：先读服务端记录核对；不要自动重发。
- 小米 `data_quality.stale` 或 `error`：说明 `data_as_of`/接口错误，结论降置信度；不阻塞。
- 食物匹配不确定：追问或取消；不猜。
- 密钥失效：让用户在训记 App 重新申请，更新 `~/.hermes/.env`；不在聊天里贴 key。
