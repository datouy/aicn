<div align="center">

# ⚡ aicn

**让国产大模型一键接入 AI 编程工具**
*Wire Chinese LLMs into AI coding tools — in one command.*

[![Stars](https://img.shields.io/github/stars/datouy/aicn?style=social)](https://github.com/datouy/aicn)
[![License](https://img.shields.io/badge/license-MIT-orange)](https://github.com/datouy/aicn/blob/main/LICENSE)
![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)
![Version](https://img.shields.io/badge/version-0.1.0-brightgreen)
![Dependencies](https://img.shields.io/badge/dependencies-0-success)
[![Sister](https://img.shields.io/badge/sister_project-llmbench--cn-blueviolet)](https://github.com/datouy/llmbench-cn)

</div>

---

## 🔗 姊妹项目 · Sister Project

> **先选型,再接入。** Pick first, then plug in.

不确定该买哪个模型?先用 **[llmbench-cn](https://github.com/datouy/llmbench-cn)** 用自己的密钥实测各家模型的速度、成本与客观任务通过率;选定之后,再用 **aicn** 一键接入你的编程工具。

Not sure which model to buy? Benchmark speed, cost and task pass-rate with your own keys in **[llmbench-cn](https://github.com/datouy/llmbench-cn)**; once you pick a winner, wire it into your tools with **aicn**.

---

## 📌 这是什么 · What is aicn

**aicn** 是一个零依赖的单文件 Python CLI,帮助国内开发者把 **DeepSeek / Kimi / GLM / Qwen / 豆包** 等国产大模型接入 **Codex / Claude Code / Cursor / Cline**。不转发任何流量、不需要服务器、不依赖第三方库,只做三件事:**查价格、测连通、写配置**。

**aicn** is a zero-dependency, single-file Python CLI that connects Chinese LLMs (DeepSeek / Kimi / GLM / Qwen / Doubao…) to AI coding tools (Codex / Claude Code / Cursor / Cline). No traffic forwarding, no server, no third-party packages — just three jobs: **check prices, test connectivity, write configs**.

## 🎯 为什么需要 · Why aicn

国内开发者接入 AI 编程工具有三个常见痛点 / Three pains Chinese developers hit every day:

- 💬 **配置分散**:每个工具的配置格式、文件路径、协议要求都不一样;Every tool has a different config format, path and protocol;
- ⚠️ **协议陷阱**:当前 Codex 只支持 Responses 协议,Claude Code 只认 Anthropic 协议,配错了就是 404/401;Codex now speaks only `responses`, Claude Code only speaks Anthropic — one wrong setting and it's 404s all the way;
- 🧩 **信息零散**:模型名、价格、端点分散在各家官网,没有统一的"查一眼"入口;Model names, prices and endpoints are scattered across vendor sites.

`aicn` 一条命令解决:先 `doctor` 看环境,再 `test` 验证协议,最后 `gen --write` 写入配置。One command at a time: `doctor` the environment, `test` the protocol, `gen --write` the config.

## 🚀 快速开始 · Quick Start

```bash
# 环境要求 / Requires: Python >= 3.9（零第三方依赖 / zero deps）
git clone https://github.com/datouy/aicn.git
cd aicn

python aicn.py doctor                                    # 环境体检 / environment check
python aicn.py list                                      # 查模型·价格·协议 / prices & protocols
python aicn.py test -p deepseek -m deepseek-chat -k sk-xxx
python aicn.py gen -t codex -p qwen -m qwen-plus --write # 一键写入配置 / write config
python aicn.py env qwen                                  # 密钥环境变量命令 / env vars
```

## 🧰 命令一览 · Commands

| 命令 / Command | 作用 / What it does | 示例 / Example |
|---|---|---|
| `aicn list [-p 供应商] [--json]` | 查看模型、价格、协议支持 / models, prices, protocols | `aicn list -p deepseek` |
| `aicn test -p <p> -m <m> [-k key] [--protocol chat\|responses\|anthropic]` | 实测连通性 / connectivity test | `aicn test -p qwen -m qwen-plus --protocol responses` |
| `aicn gen -t <tool> -p <p> -m <m> [--write]` | 生成/写入工具配置 / generate config | `aicn gen -t codex -p qwen --write` |
| `aicn env -p <p>` | 密钥环境变量命令 / env var commands | `aicn env deepseek` |
| `aicn doctor` | 环境体检 / full checkup | `aicn doctor` |

## 🔀 工具支持矩阵 · Tool Matrix

| 工具 / Tool | 一键写入 / One-shot write | 要求 / Requires | 说明 / Notes |
|---|---|---|---|
| **Codex** | ✅ `~/.codex/config.toml` | Responses 协议 | 自动备份原文件(`.aicn.bak`) / auto-backup |
| **Claude Code** | ✅ `~/.claude/settings.json` | Anthropic 协议 | 仅适用于收录了 anthropic 端点的供应商(Kimi / GLM 编码套餐 / SiliconFlow) |
| **Cursor** | ⬜ 界面指引 / UI guide | OpenAI 兼容 | 输出逐步操作指引 |
| **Cline** | ⬜ 界面指引 / UI guide | OpenAI 兼容 | 输出逐步操作指引 |

> ⚠️ Codex 官方文档规定 `wire_api` 当前**只支持 `responses`**。`gen --tool codex` 默认生成 `responses` 配置;供应商未确认支持时(数据中标记 `responses?`),请先 `aicn test --protocol responses` 验证,或改用已确认的供应商(如 qwen),或在本地架设网关(one-api / claude-code-router / 9router)。

## 🏷️ 已收录供应商 · Providers

| 供应商 / Provider | 接入方式 / Protocol | 备注 / Notes |
|---|---|---|
| DeepSeek | chat | 国内直连,未确认 Responses |
| Moonshot Kimi | chat + anthropic | K3 系列,可原生接 Claude Code |
| 智谱 GLM | chat + anthropic | 编码套餐宣称支持 Claude Code / Codex |
| 阿里云百炼 Qwen | chat + **responses** | 已确认支持 Responses,首选接 Codex |
| 火山方舟 豆包 | chat | 需控制台创建推理接入点 |
| SiliconFlow | chat + anthropic | 聚合开源模型,新用户有免费额度 |
| OpenRouter / OpenAI / Anthropic | 海外 | 美元计费,国内访问受限 |

完整价格与模型列表见 `aicn list`;数据在 `data/providers.json`,欢迎 PR 更新。Full data lives in `data/providers.json` — PRs welcome.

## 🆚 与现有项目的区别 · vs. Existing Tools

| 项目 | 类型 | 需要部署 | 转发流量 | aicn |
|---|---|---|---|---|
| one-api / new-api | 网关中转服务 | 需要服务器 | 是 | 不转发流量 |
| LiteLLM | 网关 | 较重 | 是 | 零依赖单文件 |
| cc-switch | 桌面应用 | 需安装 | 否 | 纯 CLI,无需安装 |
| claude-code-router / 9router | 本地路由服务 | 需要 Node 进程 | 是 | 只写配置、不常驻 |
| **aicn** | **配置 + 诊断 CLI** | **否** | **否** | - |

## 🔒 安全与隐私 · Security

- 密钥默认**不落盘**:Codex 配置只引用环境变量名;仅 Claude Code 的 `--key` 会写入本地 `settings.json`(官方机制);Keys stay in env vars by default — nothing is stored on disk;
- 写入配置前自动备份为 `*.aicn.bak`;Config files are backed up before any write;
- 只有你主动运行 `test` 时才发起网络请求,其余命令全部本地执行。Network requests only happen when you run `test`.

## ❓ FAQ

**Q:为什么 Claude Code 不能直接接 DeepSeek?** Claude Code 只讲 Anthropic 协议。方案:a) 用 Kimi / GLM 编码套餐 / SiliconFlow 的 anthropic 端点;b) 本地架设 claude-code-router 做协议转换。

**Q:为什么 Codex 提示模型不存在或 404?** 当前 Codex 只支持 Responses 协议。先 `aicn test --protocol responses` 确认;不支持就用 qwen 或本地网关。

**Q:`--write` 会弄坏我现有的配置文件吗?** 不会。写入前自动备份;Codex 配置只替换 `[model_providers.<你的供应商>]` 小节;Claude Code 只合并 `env` 字段。

**Q:价格/模型名更新慢怎么办?** `data/providers.json` 是纯 JSON,任何人都能 PR 更新。

## 🗺️ 路线图 · Roadmap

- [ ] `aicn gateway`:可选的一键本地协议转换小服务(chat ↔ responses ↔ anthropic)
- [ ] 用量统计:本地 SQLite 记录 token 与费用
- [ ] 自动拉取官方价格页更新数据文件
- [ ] 更多工具:Windsurf / Trae / OpenCode / Kilo Code
- [ ] 交互式 TUI 选择器

## 📁 项目结构 · Structure

```
aicn/
├── aicn.py              # 单文件 CLI（零依赖）
├── data/providers.json  # 供应商/模型/价格数据
├── tests/test_aicn.py   # 单元测试
├── examples/            # 配置示例
└── docs/调研报告.md      # GitHub 生态调研与立项依据
```

## 📄 License

[MIT](LICENSE)
