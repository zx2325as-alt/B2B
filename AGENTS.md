# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

---

## 快速启动

### Windows（推荐）

```bat
start.bat
```

该脚本会自动清理 5173 / 8001 端口的旧进程，然后分别启动后端和前端。

- **后端**：`http://localhost:8001`，API 文档：`http://localhost:8001/docs`
- **前端**：`http://localhost:5173`

### 手动启动

```bash
# 后端（在 backend/ 目录下）
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# 前端（在 frontend/ 目录下）
npm run dev
```

### 前端代理配置

`frontend/vite.config.js` 中已将 `/api` 代理到 `http://127.0.0.1:8001`。若后端端口变动，需同步修改此文件。

---

## AI 模型配置

所有模型供应商配置统一在 `backend/app/conf/config.yaml`，**不使用环境变量覆盖**（环境变量会干扰 config.yaml 中的密钥优先级）。

当前默认供应商：`deepseek`。切换供应商只需修改 `default_provider`，或在 `task_providers` 中为具体任务单独指定。

支持的供应商：`deepseek`、`openai`、`ollama`、`vllm`（均为 OpenAI 兼容接口）。

---

## 架构概览

### 整体分层

```
前端 (Vue 3)  ──HTTP/SSE──>  FastAPI  ──>  AI Harness  ──>  LLM API
                                |
                             SQLite
```

### 业务核心：双向闭环

系统本质是"**会话驱动建模，建模反哺会话**"的闭环，而非普通聊天+管理组合：

- **会话页** (`/chat`)：运行态。产生对话、AI 分析结果、关系变化信号
- **人物信息页** (`/admin`)：建模态。沉淀角色档案、审核 AI 建议、管理关系/事件

从会话页归档一次对话，会自动生成事件、更新关系强度、抽取行为模式观察；人物信息页维护的角色档案会在下一轮会话的上下文组装阶段被读取，形成闭环。

### AI Harness 层（`backend/app/harness/`）

Harness 层是系统与 LLM 之间的完整抽象，不能绕过直接调用模型：

| 模块 | 文件 | 职责 |
|------|------|------|
| Orchestrator | `orchestrator.py` | 统一 AI 调度入口，提供 `stream_chat()`、`generate_character_profile()`、`analyze_relationship()`、`suggest_character_update()`、`parse_import_content()` |
| ModelRouter | `model_router.py` | 按任务动态路由 provider/model，支持任务级 max_tokens/temperature 覆盖；`OutputGuardrails` 负责 JSON 提取、截断修复、重试 |
| ContextManager | `context_manager.py` | Token 预算（默认 8000）、历史裁剪、角色记忆注入 |
| StateEngine | `state_engine.py` | 每个会话×角色的持续心理状态（情绪向量、目标、防御机制、稳定人格） |
| ConsistencyEngine | `consistency_engine.py` | 生成人格/关系/上下文一致性约束，防止角色漂移 |
| ImportEngine | `import_engine.py` | 解析导入文件（TXT/MD/PDF/DOCX/JSON/CSV），基础规则解析 + AI 增强，多轮降载重试 |
| PromptRegistry | `prompt_templates.py` | 集中管理所有提示词模板（chat_analysis、character_profile_gen、relationship_analysis、import_dialogue_parse 等） |

### 消息发送两阶段策略

发送一条消息时，后端先进行**上下文组装**（读取双方档案、关系、近期对话、状态机、一致性约束），再执行两阶段 AI 调用：

1. `chat_surface_reply`：流式生成自然语气回复
2. `chat_analysis`：生成结构化深层分析（内心独白×3层、情绪×4段、潜台词、心理标签）

### 导入流程（异步两阶段）

1. **预览阶段**：规则解析立即返回基础预览 → 后台异步 AI 增强 → 前端轮询 `/imports/{id}/status`
2. **提交阶段**：立即返回排队状态 → 后台 AI 审核代理 → 并发重建分析层 → 批量写库

### 数据库

SQLite，文件位于 `backend/btb.db`。无迁移工具，通过 `main.py` 的 `_ensure_sqlite_columns()` 在启动时自动补充缺失列（不删表，向前兼容）。

---

## 关键文件索引

### 后端

- `backend/app/main.py`：FastAPI 入口，注册路由、CORS、启动时补列
- `backend/app/api/chat.py`：会话相关 API（发消息/SSE、归档、情绪张力、补全分析）
- `backend/app/api/characters.py`：角色/关系/事件/导入/导出 API
- `backend/app/models/sql_models.py`：SQLAlchemy 模型（Character、Relationship、CharacterEvent、CharacterObservation、Conversation、Message、ImportFile、InteractionUnit）
- `backend/app/schemas/__init__.py`：Pydantic 请求响应 schema
- `backend/app/conf/config.yaml`：AI 供应商、模型、任务级参数配置

### 前端

- `frontend/src/views/ChatUI.vue`：会话页（多角色发言、SSE 流式、情绪面板、分支回退、归档）
- `frontend/src/views/AdminDashboard.vue`：人物信息页（角色 CRUD、关系图谱、事件时间线、导入/导出、AI 更新审核）
- `frontend/src/views/AIUpdateLog.vue`：AI 更新记录独立页
- `frontend/src/stores/chat.js`：Pinia 会话状态（含 AbortController 流式中断）
- `frontend/src/stores/characters.js`：Pinia 角色/关系状态
- `frontend/src/api/index.js`：Axios + Fetch SSE 封装

---

## 重要注意事项

- **不要用环境变量传 API Key**：`start.bat` 已移除 `ANTHROPIC_API_KEY` 注入，所有 key 在 `config.yaml` 中管理
- **Vite proxy 目标是 8001**：`vite.config.js` 代理到 `127.0.0.1:8001`（用 IP 而非 localhost，避免 Node 18+ IPv6 解析冲突）
- **AI 建议不直接写入角色档案**：必须经过 `CharacterObservation` 中间层，用户批准后才落主档案
- **导入会话标记为只读**：`is_readonly=true` 的会话在会话页不可继续发言
- **日志位置**：`backend/app/logs/backend.log` 和 `import.log`（RotatingFileHandler，单文件 5MB）
