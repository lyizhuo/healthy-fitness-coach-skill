# 上游同步说明

- 上游：<https://github.com/Surge-Dan/healthy-fitness-coach-skill>
- 本仓库：`lyizhuo/healthy-fitness-coach-skill`（fork）
- 衍生 skill：`ai-fitness-coach/`
- 基线提交：`d4471a8`（2026-10-21）

`ai-fitness-coach/` 是上游 `healthy-fitness-coach/` 的改写版，不是 git submodule。上游更新不会自动进入本 skill；`git merge upstream/main` 只会更新仓库根目录的上游 skill。

## 文件对应

### 与上游一致（可直接复制）

`creator-cards.md`、`creator-query-protocol.md`、`evidence-rules.md`、`programming.md`、`recovery-pain.md`、`research-ledger.md`、`safety-screening.md`、`training-domains.md`

### 已改写（需要手工 port）

`assessment.md`、`exercise-coaching.md`、`nutrition.md`、`review-adjustment.md`、`training-dna.md`、`web-research.md`

### Hermes 专用（上游没有）

`autoregulation.md`、`coach-workflows.md`、`data-sources.md`、`mi-health.md`、`output-style.md`、`photo-macros.md`、`readiness.md`、`setup.md`、`sleep-energy.md`、`xunji-food-api.md`、`xunji-train-api.md`

## 同步步骤

```bash
git fetch upstream
git merge upstream/main          # 或 rebase，按你的分支策略
```

先看上游改了什么：

```bash
git diff d4471a8..upstream/main -- healthy-fitness-coach/
```

对“与上游一致”的文件，确认本地没有额外修改后复制：

```bash
cp healthy-fitness-coach/references/creator-cards.md ai-fitness-coach/references/creator-cards.md
```

对“已改写”的文件，先 diff 再手工合并：

```bash
diff -u healthy-fitness-coach/references/nutrition.md ai-fitness-coach/references/nutrition.md
```

改完跑：

```bash
cd ai-fitness-coach/scripts
python3 -m unittest discover -s tests -v
```

最后更新本文件的“基线提交”，commit 并 push。`hermes skills update` 只从 GitHub 拉取，本地改了但没 push 的内容不会被安装端看到。

## 注意

- Hermes GitHub 安装只下载 `ai-fitness-coach/` 目录；根目录的 `healthy-fitness-coach/` 不会被打包。
- 不要直接改 `~/.hermes/skills/` 里的安装副本；改仓库，push，再 `hermes skills update ai-fitness-coach`。
- `profile.json`、`coach.sqlite`、`DECISIONS.md` 在 `~/.hermes/data/ai-coach/`，与 skill 目录分离。
