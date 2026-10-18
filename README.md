# BareMetal Harness

> 轻量级终端 AI Agent Harness 运行系统 —— 零 Agent 框架依赖，运行时只有 `httpx` 一个第三方库。

<p align="center">
  <a href="https://github.com/v11061373-hue/baremetal-harness/actions/workflows/ci.yml"><img src="https://github.com/v11061373-hue/baremetal-harness/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/v11061373-hue/baremetal-harness/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="License"></a>
  <a href="https://github.com/v11061373-hue/baremetal-harness"><img src="https://img.shields.io/badge/Python-3.12+-blue" alt="Python"></a>
  <a href="https://github.com/v11061373-hue/baremetal-harness"><img src="https://img.shields.io/badge/tests-516-brightgreen" alt="tests"></a>
  <a href="https://github.com/v11061373-hue/baremetal-harness"><img src="https://img.shields.io/badge/deps-httpx%20only-lightgrey" alt="deps"></a>
</p>

BareMetal Harness 是一个从零实现的通用任务 Agent 运行系统，形态类似 Claude Code。
Agent Loop、Tool Runtime、Context 预算、长期记忆、Planning、Permission、Sandbox、
Skills、Subagent、Scheduler、MCP 客户端、Tracing、Evals —— 全部由仓库代码实现，
不依赖任何 Agent 框架或厂商 SDK。要求 Python 3.12+；测试、Evals 与示例完全离线，
不需要 API Key 即可跑通全链路。

## 核心能力

**① 完整运行链路，零框架依赖**

基于 `httpx` 直连大模型 HTTP 流式接口，手写 Agent Loop 显式状态机、工具调用组装与
执行预算控制，将模型交互、工具执行、权限审批、持久化与审计串成一条完整链路。
核心运行时仅依赖 `httpx` 一个第三方库，覆盖 516 项自动化测试。

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

## 架构

```text
┌────────────────────────────────────────────────────────────┐
│ 交互层   AppRepl · CommandRouter                            │
│         终端输入 / 斜杠命令（本地处理，不发给模型）           │
├────────────────────────────────────────────────────────────┤
│ 编排层   AgentLoop（显式状态机，非法状态转移直接报错）        │
│          ├─ ContextBuilder    确定性预算裁剪 + Skill/记忆注入│
│          ├─ ModelProvider     手写 SSE 流式解码             │
│          └─ PermissionPolicy  能力声明 → ALLOW / ASK / DENY │
├────────────────────────────────────────────────────────────┤
│ 执行层   ToolExecutor                                       │
│          ├─ 文件 / Shell / Git / 网页 / MCP                 │
│          ├─ Memory / Plan / Scheduler                       │
│          └─ Subagent（独立 Child AgentLoop，工具白名单取交集）│
├────────────────────────────────────────────────────────────┤
│ 隔离层   SandboxRouter（Process / Docker）· 工作区副本       │
├────────────────────────────────────────────────────────────┤
│ 持久层   Session · Checkpoint · Event Store · Trace          │
└────────────────────────────────────────────────────────────┘
```

自上而下五层：交互层收指令，编排层跑 Agent Loop 并做上下文与权限治理，执行层调度
内置工具 / 记忆 / 计划 / 子 Agent，隔离层保证改动只落在沙箱副本，持久层支撑恢复与审计。

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
uv run pytest -q                                             # 516 tests
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

## License

[MIT](LICENSE)
