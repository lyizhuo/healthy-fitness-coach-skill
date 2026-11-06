# AI Fitness Coach for Hermes

私人增肌与健康教练 skill：训记计划/记录 + 小米 readiness + 饮食拍照记录 + 周报 + 训练 DNA。

## 安装（GitHub，推荐；可更新）

仓库：`lyizhuo/healthy-fitness-coach-skill`，skill 路径：`ai-fitness-coach`。

```bash
hermes skills inspect lyizhuo/healthy-fitness-coach-skill/ai-fitness-coach
hermes skills install lyizhuo/healthy-fitness-coach-skill/ai-fitness-coach
```

也可以在 Hermes 会话里：

```text
/skills install lyizhuo/healthy-fitness-coach-skill/ai-fitness-coach
```

用 GitHub 安装而不是手工复制，Hermes 才会记录来源和内容 hash，之后可以：

```bash
hermes skills check                    # 检查上游是否有更新
hermes skills update ai-fitness-coach  # 只更新这个 skill
```

注意：

- 前提是仓库已推送到 GitHub，且包含 `ai-fitness-coach/SKILL.md`。
- `hermes skills update` 会跳过你本地改过的 skill；确认没有本地改动，或明确用 `--force` 覆盖。
- `profile.json`、`coach.sqlite`、`DECISIONS.md` 在 `~/.hermes/data/ai-coach/`，不在 skill 目录内，更新不会覆盖。
- 不要直接改 `~/.hermes/skills/` 里的安装副本；要改就改仓库，再 commit/push。

本地开发时仍可手工复制：

```bash
mkdir -p "${HERMES_HOME:-$HOME/.hermes}/skills/health"
cp -R ai-fitness-coach "${HERMES_HOME:-$HOME/.hermes}/skills/health/ai-fitness-coach"
```

然后按 [`references/setup.md`](references/setup.md) 配置：

1. `~/.hermes/.env` 写入训记三个 key、mi-health URL/key（云端如 `https://your-mi-health.example.com`）。
2. `~/.hermes/config.yaml` 配置 `mi-health` MCP 和 `terminal.env_passthrough`。
3. `python3 -m coach init && python3 -m coach sync --days 90   # 仅训记；需要历史 RPE 用 --full`。
4. 填写 `${HERMES_HOME:-~/.hermes}/data/ai-coach/profile.json`（12 项必需字段）。
5. 创建 cron（晨间/训前/晚间/周报 + 每晚训记同步）。小米数据实时读取，不需要本地同步。

## 常用命令

```bash
cd "${HERMES_HOME:-$HOME/.hermes}/skills/health/ai-fitness-coach/scripts"
python3 -m coach preflight
python3 -m coach status
python3 -m coach facts morning --date 2026-11-04 --format markdown
python3 -m coach facts preworkout --date 2026-11-04 --format json
python3 -m coach facts evening --date 2026-11-04 --format markdown
python3 -m coach dna --weeks 8
python3 -m coach search-food --keyword 鸡蛋
python3 -m coach photo --input /tmp/items.json
python3 -m coach writeback preview-food --input /tmp/foods.json
```

## 测试

```bash
cd "${HERMES_HOME:-$HOME/.hermes}/skills/health/ai-fitness-coach/scripts"
python3 -m unittest discover -s tests -v
```

## 数据与隐私

- 本地数据：`${HERMES_HOME:-~/.hermes}/data/ai-coach/`；小米数据不落本地。
- 密钥：`~/.hermes/.env`
- 不写回未确认的数据；不使用饮食聚合 `totals`；不改训记官方计划。
- 本项目不是医疗建议；红旗症状请寻求专业评估。

## 来源与上游同步

训练/营养/证据参考改编自 [Surge-Dan/healthy-fitness-coach-skill](https://github.com/Surge-Dan/healthy-fitness-coach-skill)（MIT），并针对训记 Open API、mi-health 和 Hermes 做了改写。

上游变更如何合入、哪些文件可直接复制、哪些需要手工 port，见 [`UPSTREAM.md`](UPSTREAM.md)。
