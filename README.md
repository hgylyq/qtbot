# qtbot

`qtbot` 是一个基于 NapCatQQ / OneBot WebSocket 的 QQ 角色扮演机器人。项目把 QQ 消息接入、角色卡管理、OpenAI 兼容模型调用、Tavily MCP 联网搜索、MemPalace 长期记忆和可控的短期上下文压缩串成了一套可运行的 bot 系统。

这个项目的重点不是简单调用大模型，而是围绕真实聊天场景处理几个工程问题：

- 群聊与私聊的不同触发策略。
- 多角色、多聊天对象的状态隔离。
- 长期记忆与短期上下文的边界。
- 联网搜索结果如何被整理后服务于角色回复。
- 模型、MCP、记忆库异常时的降级路径。
- 本地运行、重启、日志和测试可验证性。

## 项目亮点

- **QQ 实时接入**：通过 NapCatQQ 的 OneBot WebSocket 接收私聊和群聊消息，支持 `@bot`、命令前缀和裸命令触发。
- **角色卡系统**：角色以 YAML 存储，支持在 QQ 内生成、查看、编辑、切换、删除；群聊按群维度保存当前角色，私聊按用户维度保存当前角色。
- **Agent 分层**：主 Agent 负责角色回复和上下文组织；Search SubAgent 负责调用 Tavily MCP 并把搜索结果整理成结构化事实。
- **长期记忆**：使用 MemPalace 保存可检索记忆，并提供 transcript fallback；记忆按 `role_id + room` 隔离，避免跨角色、跨用户污染。
- **短期上下文压缩**：持续对话先累积到 dialogue context，超过 token 上限后自动 compact，控制模型输入长度。
- **OpenAI 兼容接口**：直接请求 `/v1/chat/completions`，可接入 OpenAI 或其他兼容网关。
- **显式多模态配置**：通过 `.env` 暴露多模态开关和类型列表，当前默认纯文本，便于后续接入图片理解时保持配置兼容。
- **可运维脚本**：提供 Windows 下的启动、停止、重启脚本，维护 pid、stdout、stderr 日志。
- **测试覆盖核心路径**：测试覆盖消息解析、命令调度、角色存储、搜索摘要、记忆隔离、上下文压缩、tokenizer 和配置优先级。

## 架构概览

```text
NapCatQQ / OneBot WebSocket
        |
        v
src/qqbot/napcat.py
  - 解析 OneBot message event
  - 过滤群聊触发条件
  - 提取文本、@、非文本消息类型
        |
        v
src/qqbot/controller.py
  - 命令调度
  - 权限判断
  - 角色状态读取
  - 调用主 Agent
        |
        v
src/qqbot/agent.py
  - 组装 system prompt
  - 注入 dialogue context
  - 检索长期记忆
  - 按需调用搜索 Agent
  - 触发上下文 compact
        |
        +--------------------+
        |                    |
        v                    v
src/qqbot/memory.py      src/qqbot/search.py
  - MemPalace            - Tavily MCP client
  - transcript           - Search SubAgent
  - dialogue context     - 结构化搜索摘要
```

核心目录：

```text
src/qqbot/
  agent.py        主 Agent：角色回复、记忆注入、搜索注入、对话 compact
  config.py       .env 配置读取，项目 .env 优先于系统环境变量
  controller.py   QQ 消息和命令调度
  llm.py          OpenAI 兼容 /v1/chat/completions 调用
  memory.py       MemPalace、transcript、dialogue context 管理
  models.py       Pydantic / dataclass 数据模型
  napcat.py       NapCat OneBot WebSocket 客户端
  roles.py        角色卡存储和生成
  search.py       Tavily MCP client 和 Search SubAgent
  tokenizer.py    tiktoken token 计数和截断
tests/            单元测试
data/             运行时数据，默认不提交
napcat/           本地 NapCat 文件
```

## 关键设计

### 1. 角色和聊天对象隔离

项目用两个维度隔离状态：

- `role_id`：当前角色卡。
- `room`：当前聊天对象。

私聊 room：

```text
private_<user_id>
```

群聊 room：

```text
group_<group_id>_user_<user_id>
```

这样可以保证同一个用户在不同群、不同角色下的上下文和长期记忆不会混在一起。

### 2. 长期记忆与短期上下文分离

项目没有把所有历史消息直接塞进 prompt，而是分为三层：

- **原始 transcript**：每轮回复写入 markdown，保留完整记录。
- **MemPalace 长期记忆**：按 `role_id + room` 检索相关记忆，作为 prompt 背景。
- **Dialogue Context**：保存最近连续对话，超出 token 上限后 compact 成摘要。

Dialogue context 文件结构：

```json
{
  "role_id": "default",
  "room": "private_123456",
  "compacted": "已经压缩过的旧对话摘要",
  "turns": [
    {
      "user_text": "compact 之后的新用户消息",
      "bot_text": "compact 之后的新 bot 回复"
    }
  ]
}
```

这个设计让 bot 能持续保持上下文，同时避免 prompt 无限增长。

### 3. 联网搜索分层

联网搜索不是把搜索结果直接丢给主模型。流程是：

1. MainAgent 判断是否需要搜索，或由 `/搜 <query>` 强制触发。
2. SearchSubAgent 调用 Tavily MCP。
3. SearchSubAgent 把原始结果整理为 `SearchBrief`：query、summary、facts、source_urls、confidence、freshness_notes。
4. MainAgent 把 `SearchBrief` 当作知识背景，再按当前角色语气回复。

这样可以减少“搜索报告式回复”，也能把外部事实和角色表达解耦。

### 4. 可控降级

真实聊天机器人不能因为一个外部依赖失败就整体不可用。本项目对关键路径做了降级：

- MemPalace 不可用时，使用本地 transcript fallback 搜索。
- 搜索服务异常时，主 Agent 记录日志并继续无搜索回复。
- `tiktoken` 不可用时，退回近似 token 计数。
- 图片、语音、视频、文件等非文本消息不会传给模型，bot 会提示用户改用文字描述。
- 多模态配置可以显式打开支持类型显示，但当前版本还没有实现 OneBot 媒体文件下载和多模态模型消息组装。

## 功能

私聊：

- 默认回复所有文本消息。
- 非文本消息会提示用户使用文字描述。

群聊：

- `@bot 你好`
- `/帮助`
- `/搜 今天的新闻`
- 只 `@bot` 不带文字时，bot 会按当前角色自然回应。

角色管理：

```text
/角色列表
/角色查看 <id>
/角色切换 <id>
/角色生成 <id> <设定描述>
/角色编辑 <id> <field> <content>
/角色删除 <id>
```

记忆和上下文：

```text
/清除context
/清除memory
/清除全部
```

普通用户可使用帮助、查看、搜索和清理当前聊天对象的记忆；角色生成、编辑、删除、切换需要 `BOT_OWNER_IDS` 权限。

## 快速开始

需要 Python 3.11 或更高版本。

```powershell
python -m pip install -e ".[test]"
Copy-Item .env.example .env
```

编辑 `.env`：

```env
NAPCAT_WS_URL=ws://127.0.0.1:3001
BOT_SELF_ID=123456789
BOT_OWNER_IDS=123456789
BOT_PREFIX=/

OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-...
MAIN_MODEL=gpt-4.1-mini
SEARCH_MODEL=gpt-4.1-mini
ROLE_MODEL=gpt-4.1-mini
TOKENIZER_ENCODING=cl100k_base
MULTIMODAL_ENABLED=false
MULTIMODAL_TYPES=image

TAVILY_MCP_URL=https://tavily.ivanli.cc/mcp
TAVILY_MCP_AUTHORIZATION=Bearer replace-with-token
TAVILY_MCP_TOOL=
TAVILY_MAX_RESULTS=5

DEFAULT_ROLE_ID=default
ROLES_DIR=data/roles
STATE_PATH=data/state.yaml
MEMPALACE_PATH=data/mempalace
TRANSCRIPTS_DIR=data/transcripts
MEMPALACE_RESULTS=5
MEMPALACE_AUTO_MINE=true
DIALOGUE_CONTEXT_LIMIT=8000
DIALOGUE_COMPACT_TARGET=3000
```

启动：

```powershell
python -m qqbot
```

Windows 脚本：

```powershell
.\restart_bot.bat
.\stop_bot.bat
```

日志位置：

```text
data/runtime/qqbot.out.log
data/runtime/qqbot.err.log
```

## NapCat 配置

NapCat 需要开启 OneBot WebSocket Server。建议配置：

- host: `127.0.0.1`
- port: `3001`
- messagePostFormat: `array`
- token: 空，或与 `.env` 中的配置保持一致

群聊 `@bot` 检测依赖 `BOT_SELF_ID`，必须填写 bot 自己的 QQ 号。

## 环境变量说明

| 变量 | 作用 |
| --- | --- |
| `NAPCAT_WS_URL` | NapCat OneBot WebSocket 地址 |
| `BOT_SELF_ID` | bot 自己的 QQ 号，用于群聊 @ 检测 |
| `BOT_OWNER_IDS` | 管理员 QQ 号，多个用逗号或分号分隔 |
| `BOT_PREFIX` | 命令前缀，默认 `/` |
| `OPENAI_BASE_URL` | OpenAI 兼容接口地址，支持 `/v1` 或完整 `/v1/chat/completions` |
| `OPENAI_API_KEY` | 模型接口密钥 |
| `MAIN_MODEL` | 主回复模型 |
| `SEARCH_MODEL` | 搜索摘要模型 |
| `ROLE_MODEL` | 角色卡生成模型 |
| `TOKENIZER_ENCODING` | tiktoken 编码名 |
| `MULTIMODAL_ENABLED` | 是否显示启用多模态入口，默认 `false` |
| `MULTIMODAL_TYPES` | 显示启用的多模态类型，多个用逗号分隔，例如 `image,audio` |
| `TAVILY_MCP_URL` | Tavily MCP server 地址 |
| `TAVILY_MCP_AUTHORIZATION` | Tavily MCP 鉴权头 |
| `TAVILY_MCP_TOOL` | 指定 MCP 工具名，留空时自动选择 |
| `TAVILY_MAX_RESULTS` | Tavily 搜索最多返回结果数 |
| `MEMPALACE_RESULTS` | 每次注入 prompt 的长期记忆条数 |
| `MEMPALACE_AUTO_MINE` | 是否每轮回复后写入 MemPalace |
| `DIALOGUE_CONTEXT_LIMIT` | 短期上下文 token 上限 |
| `DIALOGUE_COMPACT_TARGET` | compact 后目标 token 数 |

`.env` 优先于系统环境变量，修改后重启 bot 生效。不要提交真实 key、Tavily token、NapCat token。

当前多模态配置用于显式展示能力开关和未来接入范围。即使 `MULTIMODAL_ENABLED=true`，当前版本仍不会下载 OneBot 媒体文件，也不会把图片、语音、视频或文件字节传给模型。

## 测试

```powershell
python -m pytest -q
```

测试覆盖：

- NapCat 消息解析和群聊触发条件。
- QQ 命令调度和权限判断。
- 角色卡存储、状态隔离和非法 id 防护。
- OpenAI 兼容响应解析和 token usage 日志。
- Tavily MCP 工具参数适配。
- Search SubAgent 结构化摘要。
- MemPalace / transcript fallback 记忆检索。
- Dialogue context compact。
- tokenizer 计数和截断。
- `.env` 优先级。

## 数据目录

```text
data/roles/                 角色卡
data/state.yaml             当前角色状态
data/mempalace/             MemPalace 数据
data/transcripts/pending/   待归档 transcript
data/transcripts/archive/   已归档 transcript
data/transcripts/dialogue/  原始对话 JSONL
data/transcripts/context/   compact 后的对话上下文状态
data/runtime/               pid 和运行日志
```

`data/` 默认不提交 git。

## 工程取舍

- **直接调用 HTTP 接口**：`llm.py` 直接请求 OpenAI 兼容 `/v1/chat/completions`，减少 SDK 差异对兼容网关的影响。
- **YAML 角色卡**：角色配置可读、可手动编辑，也方便在 QQ 内通过命令更新。
- **本地 transcript fallback**：当 MemPalace 不可用时，bot 仍能基于本地记录检索历史。
- **token 级上下文控制**：使用 `tiktoken` 而不是简单按轮数裁剪，更接近模型真实输入限制。
- **Search SubAgent**：把搜索摘要和最终表达拆开，降低主回复 prompt 的复杂度。
- **多模态先配置化**：先把能力边界变成显式参数，避免后续接入图片理解时破坏配置格式或用户提示语义。

## 常见问题

### bot 没反应

检查：

- NapCat 是否已登录。
- `NAPCAT_WS_URL` 是否可连接。
- `.env` 的 `BOT_SELF_ID` 是否是 bot QQ 号。
- 群聊中是否 `@bot` 或使用 `/` 前缀。

### 模型接口 403

检查：

- `OPENAI_BASE_URL` 是否正确。
- `OPENAI_API_KEY` 是否有效。
- 当前网关是否支持 `/v1/chat/completions`。
- 模型名是否有权限调用。

### 角色命令提示没有权限

检查：

```env
BOT_OWNER_IDS=你的QQ号
```

多个管理员：

```env
BOT_OWNER_IDS=123456,456789
```

### 修改 `.env` 后没生效

重启 bot：

```powershell
.\restart_bot.bat
```

### compact 太频繁

调大：

```env
DIALOGUE_CONTEXT_LIMIT=12000
DIALOGUE_COMPACT_TARGET=4000
```

### compact 后丢细节

调大 `DIALOGUE_COMPACT_TARGET`。长期事实仍会由 MemPalace 检索补充，但短期细节主要依赖 dialogue context。

## 后续可以扩展

- 支持图片理解，把 OneBot 图片文件接入多模态模型。
- 增加 Web 管理页，用于管理角色卡、查看日志和测试 prompt。
- 为搜索来源增加引用格式和可信度策略。
- 增加 Docker 部署和系统服务配置。
- 增加端到端集成测试，覆盖真实 WebSocket 连接。
