# BareMetal Harness

> 自改进终端 AI Agent Harness —— 长期记忆（BM25 + 半衰期 + 去重）、确定性命令护栏、子 agent 编排、外层进化循环；零 Agent 框架依赖，唯一第三方依赖是 `httpx`。

<p align="center">
  <a href="https://github.com/v11061373-hue/baremetal-harness/actions/workflows/ci.yml"><img src="https://github.com/v11061373-hue/baremetal-harness/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/v11061373-hue/baremetal-harness/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="License"></a>
  <a href="https://github.com/v11061373-hue/baremetal-harness"><img src="https://img.shields.io/badge/Python-3.12+-blue" alt="Python"></a>
  <a href="https://github.com/v11061373-hue/baremetal-harness"><img src="https://img.shields.io/badge/tests-583-brightgreen" alt="tests"></a>
  <a href="https://github.com/v11061373-hue/baremetal-harness"><img src="https://img.shields.io/badge/deps-httpx%20only-lightgrey" alt="deps"></a>
</p>

BareMetal Harness 是一个可嵌入的评测迭代 Agent harness——类 Claude Code 形态，但作为库而非产品：Agent Loop、工具、记忆、权限、评测、自迭代全由仓库代码实现，零框架依赖。
Agent Loop、Tool Runtime、Context 预算、长期记忆、Planning、Permission、Sandbox、
Skills、Subagent、Scheduler、MCP 客户端、Tracing、Evals —— 全部由仓库代码实现，
不依赖任何 Agent 框架或厂商 SDK。要求 Python 3.12+；测试、Evals 与示例完全离线，
不需要 API Key 即可跑通全链路。

## 核心能力

可嵌入（进程内库）、可插拔（`ModelProvider`/`Verifier`/`PermissionPolicy` 等均为 Protocol，可替换）、
项目级（规则/技能/评测随 `.baremetal_harness/` 进 git）。

**① 完整运行链路，零框架依赖**

基于 `httpx` 直连大模型 HTTP 流式接口，手写 Agent Loop 显式状态机、工具调用组装与
执行预算控制，将模型交互、工具执行、权限审批、持久化与审计串成一条完整链路。
核心运行期仅依赖 `httpx` 一个第三方库，覆盖 583 项自动化测试。

**② 能力声明与三级审批**

每个工具声明自己的 `filesystem / network / subprocess / secrets / risk_level` 能力，
统一权限策略据此给出 `ALLOW / ASK / DENY` 三种处置：只读自动放行，写入与网络必须审批。
所有改动落在工作区副本，经临时文件原子替换写回，`/changes` 查差异、`/apply` 显式批准，
构成执行、检查、应用三步可控的文件修改交付。子 Agent 委派以工具白名单取交集 + 委派深度
限制约束，与后台无人值守任务一起纳入权限传播控制。

**③ 中断恢复与副作用规避**

进程可能在工具产生副作用之后、结果落盘之前中断，留下状态不一致的会话。为此 Checkpoint
以校验摘要做完整性检查，通过工具调用与结果的配对检测识别未完成调用，再结合工具幂等性
声明判断恢复策略：未完成的非幂等操作强制人工审批后才允许恢复会话，有效规避中断恢复
场景下重复产生副作用的风险。

**④ 流式稳定性与审计性能**

在首个流式事件发出前，对限流、超时等可重试异常采用带上限的指数退避与随机抖动重试，
并遵循服务端重试等待指示；开始输出后不再自动重启流，避免重复内容。审计日志追加不再
重复解析全量历史，改为事件 ID 与运行序号的增量索引缓存，同时保留重复事件与序号连续性
校验，处理量不再随日志增长而线性恶化。

**⑤ 离线评测与故障注入**

基于 FakeModel 与脚本化模型搭建离线评测与故障注入体系，无需真实 API Key 即可稳定复现
限流恢复、认证失败、网络异常等场景。基础离线 Evals 共 10 项全部通过，覆盖文本流拼接、
完成状态、事件顺序与中文输出验证，并接入 CI 实现系统行为的持续可重复验证。

## 自改进与确定性（九模块优化）

在基础能力之上，九个模块补全了确定性外壳、评测体系与自改进路径：

- **验证回环（模块 1）**：`Verifier` 协议让任务输出先过验证再判完成，未达标自动重试，
  验证失败留下 `VerificationFailed` 审计事件，raiser 验证器触发 FAILED 而非崩溃。
- **BM25 记忆检索（模块 2）**：检索从词重叠换成 BM25 × 分类半衰期 × 负样本加权，
  写路径经 consolidator 去重（dedup / supersede），trace 检索（deja-vu）无 LLM。
- **上下文压缩（模块 3）**：会话启动按相关性注入记忆（`memory:session` 必填 +
  `memory` 可选），空结果弃权不注入，超限按字符截断。
- **确定性外壳与预算门（模块 4）**：`DestructiveCommandGuard` 精确匹配 `rm -rf /`
  等破坏性命令，在工具执行前拦截（fail-open），配合 turns / tool_calls / timeout
  三层预算门，超限 emit `BudgetExceeded`，拦截 emit `PermissionEvaluated`。
- **外层进化循环（模块 5）**：`harness-evolve` 跑 run-mine-gate-inject 四阶段——
  跑任务 → 挖失败规则 → preserve-and-extend gate → 注入 Skill + 沉淀记忆，零碰运行期。
- **子 agent 与资产治理（模块 6）**：`SubagentSpec.success_criteria` 注入 done-when
  判据；Skill 加 `version`/`enabled` 字段并在发现时过滤禁用项；`.baremetal_harness/AGENTS.md`
  作为项目规则 required 源注入。
- **评测迭代闭环（模块 7）**：失败 run 提升为回归评测用例（`mine_eval_cases`），
  `eval_gate` 让候选不得让历史失败用例回退，`eval_suite_manifest` 把套件版本化进 git——
  评测套件随运行单调增长，自改进不自改。
- **评测体系（模块 8）**：`score_run` 给单次 run 打分，`weighted_gate` 判候选 promote，
  `heuristic_weights` 启发式赋权，`cap_points` 反 Goodhart（硬上限 + 权重降序截断）。
  评分层纯机械——只跑 `evaluate_assertion`，不引入 LLM-judge，规避评分幻觉与不可复现。
- **沙箱分支搜索（模块 9，Σ-RSI）**：`branch_search` 把单路径 ratchet 升级为分支搜索——
  枚举候选脚手架状态 → 离线评测 → `weighted_gate` 选最优非回退者 → 原子写回 SKILL.md；
  规则经 `context_providers` 回注当前轮，`mine_rule_llm` 挖 LLM 规则接采样，
  所有候选必经机械 gate，LLM 提案不自由注入。Σ 派（scaffold 级）RSI 闭环：
  改的是脚手架（规则 + 评测套件），不是模型权重。

用你自己的 agent / 工作流做评测自迭代，三步：① 把目标工作流拆成 `EvolutionTask(prompt, Verifier)`，
Verifier 就是「做到什么算对」的机械判据；② run-mine-gate-inject 跑失败、挖规则、注入该项目 `skills/`；
③ 失败沉淀回归用例进 git，`eval_gate` 让未来候选不得回退。

## 嵌入与评测迭代

两条公开面，均离线可跑，无需 API Key。

**嵌入**（`create_app → run_prompt → aclose`）：

```python
from baremetal_harness import BareMetalHarnessConfig, create_app

app = await create_app(config)          # 传 provider 可接任意 OpenAI 兼容端点
result = await app.run_prompt("你的任务")
await app.aclose()
```

**评测迭代**（`meta` 的 run-mine-gate-eval）：

```python
from baremetal_harness.meta import EvolutionTask, run_task, failure_traces, mine_rule

tasks = (EvolutionTask("math", "6*7", CheckContains("42")),)
runs = {t.task_id: await run_task(t, provider=..., model="fake", tools=None, workspace=None, limits=RunLimits(2, 2)) for t in tasks}
rule = mine_rule(None, failure_traces(tuple(r for r in runs.values() if not r.passed)))
```

完整可跑示例：[`examples/embed.py`](examples/embed.py)、[`examples/eval_iterate.py`](examples/eval_iterate.py)、[`examples/branch_search_live.py`](examples/branch_search_live.py)（Σ-RSI，接真模型）。

## 架构

```text
┌────────────────────────────────────────────────────────────┐
│ 交互层   AppRepl · CommandRouter                            │
│         终端输入 / 斜杠命令（本地处理，不发给模型）           │
├────────────────────────────────────────────────────────────┤
│ 进化层   meta/ —— run-mine-gate-inject 外层循环 + 评测回归门│
│        挖失败规则/用例 → gate → 注入+沉淀 → 评测套件防回退 │
├────────────────────────────────────────────────────────────┤
│ 编排层   AgentLoop（显式状态机，非法状态转移直接报错）        │
│          ├─ Verifier           任务验证 + 回环重试          │
│          ├─ ContextBuilder    确定性预算裁剪 + 压缩/记忆注入 │
│          ├─ ModelProvider     手写 SSE 流式解码             │
│          ├─ PermissionPolicy  能力声明 → ALLOW / ASK / DENY │
│          └─ DestructiveGuard  确定性命令护栏（rm -rf / 等） │
├────────────────────────────────────────────────────────────┤
│ 执行层   ToolExecutor                                       │
│          ├─ 文件 / Shell / Git / 网页 / MCP                 │
│          ├─ Memory（BM25+半衰期+去重）/ Plan / Scheduler     │
│          └─ Subagent（done-when 判据 + 工具白名单取交集）    │
├────────────────────────────────────────────────────────────┤
│ 隔离层   SandboxRouter（Process / Docker）· 工作区副本       │
├────────────────────────────────────────────────────────────┤
│ 持久层   Session · Checkpoint · Event Store · Trace          │
└────────────────────────────────────────────────────────────┘
```

自上而下六层：交互层收指令，进化层跑外层自改进循环与评测回归门，编排层跑 Agent Loop 并做验证、
上下文与权限治理，执行层调度内置工具 / 记忆 / 计划 / 子 Agent，隔离层保证改动只落在
沙箱副本，持久层支撑恢复与审计。

## 快速开始

```bash
git clone https://github.com/v11061373-hue/baremetal-harness.git
cd baremetal-harness
uv python install 3.12
uv sync --extra dev --python 3.12
```

## 接真实模型

```bash
uv run baremetal-harness config set base_url https://api.openai.com/v1
uv run baremetal-harness config set model gpt-4o-mini
uv run baremetal-harness config set api_key        # 交互式输入，不进 shell 历史
```

任何 OpenAI 兼容端点都可以（DeepSeek、Kimi、本地 vLLM / Ollama 等）。也支持环境变量
`OPENAI_BASE_URL` / `OPENAI_MODEL` / `OPENAI_API_KEY`（优先级更高）。

然后在你的项目目录下运行：

```bash
cd /path/to/your/project
baremetal-harness
```

## 命令

```
/changes            查看 Agent 在沙箱里改了什么
/apply <path>|--all 显式应用改动到真实项目
/resume <id>        从 Checkpoint 恢复会话（/sessions 查 id）
/clear              清空对话并开启新会话
/memory <query>     搜索长期记忆
/tasks  /jobs       计划任务 / 定时任务
/skills /agents     已加载的 Skill / 子 Agent 状态
/mcp    /sandbox    MCP 服务器 / 沙箱后端状态
/metrics /trace     token 消耗 / 审计日志
/help
```

## 工具

| 类别 | 工具 |
| --- | --- |
| 文件 | `read_file` `write_file` |
| 执行 | `run_command`（沙箱内，需审批） |
| 版本控制 | `git_status` `git_log` `git_diff` `git_show`（只读，自动放行） |
| 网络 | `fetch_url`（含 SSRF 防护） `web_search`（需配置端点） |
| 记忆 | `remember` `search_memory` |
| 计划 | `create_plan` `list_tasks` `start_task` `complete_task` `fail_task` |
| 并发 | `delegate_task` |
| 调度 | `schedule_task` `list_scheduled_tasks` `cancel_scheduled_task` |
| 扩展 | 任意 MCP 服务器提供的工具 |

## 可选配置

配置文件放在 `<workspace>/.baremetal_harness/`（项目级）或 `~/.baremetal_harness/`（用户级），项目级优先。

**MCP 服务器** —— `mcp.json`（`servers` 与 `mcpServers` 两种键名都认）：

```json
{
  "servers": {
    "files": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]
    }
  }
}
```

MCP 工具统一命名为 `mcp_<服务器>_<工具>`，不会覆盖内置工具；服务器启动失败只影响该
服务器，不影响 Agent 启动。用 `/mcp` 查看状态。

**网页搜索** —— `search.json`，厂商无关，字段映射写在配置里：

```json
{
  "url": "https://api.example.com/search",
  "query_parameter": "q",
  "results_path": "web.results",
  "title_field": "title",
  "url_field": "url",
  "snippet_field": "description",
  "api_key_header": "X-Api-Key"
}
```

密钥只从环境变量 `BAREMETAL_HARNESS_SEARCH_API_KEY` 读取，写进配置文件会被拒绝。未配置端点时
不注册 `web_search` —— 不给模型一个注定失败的能力。

**后台任务预授权** —— 定时任务默认无法执行需要审批的动作，要放行必须显式声明：

```python
app = await create_app(config, unattended_approved_tools=("fetch_url",))
```

## Skills

在 `<workspace>/.baremetal_harness/skills/<name>/SKILL.md` 放一个带 frontmatter 的 Markdown：

```markdown
---
name: release-notes-writer
description: Write concise release notes
triggers:
  - release
scope: project
---
Inspect the git log before writing release notes.
```

命中触发词时，Skill 正文会作为 system message 注入，并留下 `ContextInjected` 审计事件。

## 开发

```bash
uv run ruff check .                                          # lint
uv run pytest -q                                             # 583 tests
bash scripts/smoke_offline.sh                                # 完整离线验收
```

CI 在 Linux 和 macOS 上跑 lint、测试、离线验收，并从构建出的 wheel 做一次干净安装
验证——全程不需要 API Key，不产生模型费用。

## 已知限制

- Token 计数是启发式的（按字符分脚本估算），不是模型自己的 tokenizer；预算偏保守
- 上下文超预算时按优先级丢弃，没有做摘要压缩
- `SandboxRouter` 只在启动时选一次后端
- Trace 始终开启，`/trace on|off` 只返回说明
- `/apply` 的审批绑定路径列表，未绑定内容摘要
- Child Agent 与父共享同一 Provider 与 Sandbox，是权限隔离而非进程隔离
- MCP 只实现 stdio 传输，没有 HTTP/SSE，也没有 resources/prompts
- Scheduler 的跨进程认领依赖单个 SQLite 文件，不适用于多机部署
- 没有浏览器自动化：`fetch_url` 抓取静态 HTML 并提取正文，不执行 JavaScript
- `mine_rule` 单路径仍是机械 fallback（拼接失败 reason 前 3 条）；LLM 挖掘走 `mine_rule_llm` 分支，接进分支搜索采样
- `harness-evolve` CLI 靠套件 `script` 字段离线回放 `branch_search`；接真模型（OpenAI 兼容端点）仍需编程调 `evolve()`/`branch_search()`

## License

[MIT](LICENSE)
