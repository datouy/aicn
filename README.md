# aicn

> 一个零依赖的 CLI：让国内开发者把 **DeepSeek / Kimi / GLM / Qwen / 豆包** 等国产大模型，一键接入 **Codex / Claude Code / Cursor / Cline** 等 AI 编程工具。

不转发任何流量、不需要服务器、不依赖第三方库 —— 单文件 Python CLI，只做三件事：**查价格、测连通、写配置**。

## 为什么需要 aicn

国内开发者接入 AI 编程工具有三个常见痛点：

- **配置分散**：每个工具（Codex / Claude Code / Cursor / Cline）的配置格式、文件路径、协议要求都不一样，每次都要翻文档；
- **协议陷阱**：当前 Codex 只支持 Responses 协议，Claude Code 只认 Anthropic 协议，而各家国产模型只支持其中一部分，配错了就是 404 / 401 一脸懵；
- **信息零散**：模型名、价格、端点分散在各家官网，没有统一的"查一眼"入口。

`aicn` 用一条命令解决：先 `doctor` 看环境，再 `test` 验证协议，最后 `gen --write` 写入配置。

## 快速开始

```bash
# 0. 环境要求：Python >= 3.9（无任何第三方依赖）
git clone <你的仓库地址>
cd aicn

# 1. 环境体检（网络、配置文件、密钥）
python aicn.py doctor

# 2. 看模型与价格
python aicn.py list

# 3. 实测连通性（先确认能通，再写配置）
python aicn.py test --provider deepseek --model deepseek-chat --key sk-xxx

# 4. 一键生成配置（先 dry-run 预览，确认后加 --write）
python aicn.py gen --tool codex --provider qwen --model qwen-plus --write

# 5. 设置密钥环境变量
python aicn.py env qwen
```

## 命令一览

| 命令 | 作用 | 示例 |
|---|---|---|
| `aicn list [-p 供应商] [--json]` | 查看模型、价格、协议支持 | `aicn list -p deepseek` |
| `aicn test -p <供应商> -m <模型> [-k 密钥] [--protocol chat\|responses\|anthropic]` | 实测连通性与用量 | `aicn test -p qwen -m qwen-plus --protocol responses` |
| `aicn gen -t <工具> -p <供应商> -m <模型> [--write]` | 生成/写入工具配置 | `aicn gen -t codex -p qwen --write` |
| `aicn env -p <供应商>` | 查看密钥环境变量设置命令 | `aicn env deepseek` |
| `aicn doctor` | 环境体检（网络/配置/密钥） | `aicn doctor` |

## 工具支持矩阵

| 工具 | 一键写入 | 要求 | 说明 |
|---|---|---|---|
| **Codex** | ✅ `~/.codex/config.toml` | Responses 协议 | 自动备份原文件（`.aicn.bak`），写入 `[model_providers.<id>]` |
| **Claude Code** | ✅ `~/.claude/settings.json` | Anthropic 协议 | 仅适用于收录了 anthropic 端点的供应商（Kimi / GLM 编码套餐 / SiliconFlow） |
| **Cursor** | ⬜ 界面指引 | OpenAI 兼容 | 输出逐步操作指引（Settings → Models） |
| **Cline** | ⬜ 界面指引 | OpenAI 兼容 | 输出逐步操作指引（OpenAI Compatible） |

> 注意：Codex 官方文档明确规定 `wire_api` 当前**只支持 `responses`**（旧版的 `chat` 已移除）。因此 `gen --tool codex` 默认生成 `responses` 配置；若供应商未官方确认支持 Responses 协议（数据中标记为 `responses?`），请先 `aicn test --protocol responses` 验证，不通过时改用已确认支持的供应商（如 qwen），或在本地架设网关（one-api / claude-code-router / 9router 等）后指向网关地址。

## 已收录供应商

| 供应商 | 接入方式 | 备注 |
|---|---|---|
| DeepSeek | chat | 国内直连，未确认 Responses |
| Moonshot Kimi | chat + anthropic | K3 系列，可原生接 Claude Code |
| 智谱 GLM | chat + anthropic | 编码套餐宣称支持 Claude Code / Codex |
| 阿里云百炼 Qwen | chat + **responses** | 已确认支持 Responses，首选接 Codex |
| 火山方舟 豆包 | chat | 需控制台创建推理接入点 |
| SiliconFlow | chat + anthropic | 聚合开源模型，新用户有免费额度 |
| OpenRouter / OpenAI / Anthropic | 海外 | 美元计费，国内访问受限 |

完整价格与模型列表见 `aicn list`；数据在 `data/providers.json`，欢迎 PR 更新。

## 与现有项目的区别

| 项目 | 类型 | 需要部署 | 转发流量 | aicn |
|---|---|---|---|---|
| one-api / new-api | 网关中转服务 | 需要服务器 | 是 | 不转发流量 |
| LiteLLM | 网关 | 较重 | 是 | 零依赖单文件 |
| claude-code-router / 9router | 本地路由服务 | 需要 Node 进程 | 是 | 只写配置、不常驻 |
| **aicn** | **配置 + 诊断 CLI** | **否** | **否** | - |

需要多 key 池、团队共享、用量审计时，上述网关是更好的选择；个人单 key 接入，`aicn` 一步到位。

## 安全与隐私

- 密钥默认**不落盘**：`gen` 生成的 Codex 配置只引用环境变量名（`env_key`）；只有 Claude Code 的 `--key` 会写入本地 `settings.json`（Claude Code 官方机制）。
- 写入配置文件前自动备份为 `*.aicn.bak`。
- `aicn` 只在你主动运行 `test` 时向供应商端点发送请求，其余命令全部本地执行。

## 数据说明

- 价格为 2026-10 整理时点信息（¥/百万 tokens），变动频繁，**以官方定价页为准**。
- 模型名可能滞后于厂商发布节奏，可用 `--model` 指定任意模型名，并用 `test` 验证。
- 协议支持标记（`responses?`）表示"未官方确认"，建议实测。

## FAQ

**Q：为什么 Claude Code 不能直接接 DeepSeek？**
Claude Code 只讲 Anthropic 协议，DeepSeek 官方只有 chat 接口。选择方案：a) 用 Kimi / GLM 编码套餐 / SiliconFlow 的 anthropic 端点；b) 本地架设 claude-code-router 做协议转换。

**Q：为什么 Codex 提示模型不存在或 404？**
当前 Codex 只支持 Responses 协议。先 `aicn test -p <供应商> -m <模型> --protocol responses` 确认端点支持；不支持就用 qwen（已确认）或本地网关。

**Q：`--write` 会弄坏我现有的配置文件吗？**
不会。写入前自动备份为 `<原文件名>.aicn.bak`；Codex 配置只新增/替换 `[model_providers.<你的供应商>]` 小节，其余内容原样保留；Claude Code 只合并 `env` 字段。

**Q：价格/模型名更新慢怎么办？**
`data/providers.json` 是纯 JSON，任何人都能 PR 更新；也可以用 `aicn list --json` 自建视图。

## 路线图

- [ ] `aicn gateway`：可选的一键本地协议转换小服务（chat ↔ responses ↔ anthropic），解决 Codex 接 DeepSeek 类痛点
- [ ] 用量统计：本地 SQLite 记录每次 `test`/转发请求的 token 与费用
- [ ] 自动拉取官方价格页更新数据文件
- [ ] 更多工具：Windsurf / Trae / OpenCode / Kilo Code
- [ ] 交互式 TUI 选择器

## 项目结构

```
aicn/
├── aicn.py              # 单文件 CLI（零依赖）
├── data/providers.json  # 供应商/模型/价格数据
├── tests/test_aicn.py   # 单元测试（python -m unittest discover -s tests -v）
├── examples/            # 配置示例
└── docs/调研报告.md      # GitHub 生态调研与立项依据
```

## License

[MIT](LICENSE)
