# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 快速启动

### Windows（推荐）

```bat
start.bat
```

该脚本会自动清理 5174 / 8001 / 7474 / 7687 端口的旧进程，然后分别启动 Neo4j、后端和前端。

- **后端**：`http://localhost:8001`，API 文档：`http://localhost:8001/docs`
- **前端**：`http://localhost:5174`
- **Neo4j Browser**：`http://localhost:7474`（可选；如本机无 Java 17+ 会自动跳过）

### 手动启动

```bash
# 后端（在 backend/ 目录下）
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# 前端（在 frontend/ 目录下）
npm run dev

# Neo4j（可选，需 Java 17+）
cd backend/app/models/neo4j-community-5.18.1 && bin/neo4j.bat console
```

### 前端代理配置

`frontend/vite.config.js` 中已将 `/api` 代理到 `http://127.0.0.1:8001`。若后端端口变动，需同步修改此文件（用 IP 而非 `localhost`，避免 Node 18+ 的 IPv6 解析冲突）。

### 安装依赖

```bash
# 后端
cd backend && pip install -r requirements.txt

# 前端
cd frontend && npm install
```

---

## 测试

后端使用 **pytest + pytest-asyncio**，所有测试位于 `backend/tests/`。

```bash
# 在 backend/ 目录下运行
pytest                              # 跑全部
pytest tests/test_send_e2e.py -v    # 跑单个文件
pytest -k diagnosis                 # 按关键字过滤
pytest --tb=short                   # 失败时只显示短 traceback
```

关键路径覆盖：`test_send_e2e`（端到端）、`test_single_pass_final`（单次推理出 final）、
`test_archive_fix`（归档崩溃修复）、`test_diagnosis_no_crash`、`test_cold_start`、
`test_quick_ingest`、`test_counterpart_memory`、`test_provider_fallback`、`test_context_maxed`、
`test_chat_advice_rollback`、`test_analysis_migration`、`test_archive_fix`。

前端无单测；`package.json` 只有 `dev` / `build` / `preview` 三个脚本。

---

## AI 模型配置

所有模型供应商配置统一在 `backend/app/conf/config.yaml`，**不使用环境变量覆盖**（环境变量会干扰 config.yaml 中的密钥优先级）。

当前默认供应商：`deepseek`。切换供应商只需修改 `default_provider`，或在 `task_providers` 中为具体任务单独指定。

支持的供应商：`deepseek`、`openai`、`ollama`、`vllm`（均为 OpenAI 兼容接口）。`ping_llm.py` 是供应商连通性冒烟脚本。

本地覆盖：`backend/app/conf/config.local.yaml`（git ignore 当前未追踪，保留个人 provider/key 时用）。

---

## 架构概览

### 整体分层

```
前端 (Vue 3)  ──HTTP/SSE──>  FastAPI  ──>  AI Harness  ──>  LLM API
                                |
                  SQLite + 可选 Neo4j（图存储）
```

### 业务核心：双向闭环

系统本质是"**会话驱动建模，建模反哺会话**"的闭环，而非普通聊天+管理组合：

- **会话页** (`/chat`)：运行态。产生对话、AI 分析结果、关系变化信号
- **人物信息页** (`/admin`)：建模态。沉淀角色档案、审核 AI 建议、管理关系/事件
- **AI 更新记录** (`/ai-update-log`)：按模块展示来源、依据、置信度、变更类型、应用状态

从会话页归档一次对话，会自动生成事件、更新关系强度、抽取行为模式观察；人物信息页维护的角色档案会在下一轮会话的上下文组装阶段被读取，形成闭环。

### AI Harness 层（`backend/app/harness/`）

Harness 层是系统与 LLM 之间的完整抽象，**不能绕过直接调用模型**：

| 模块 | 文件 | 职责 |
|------|------|------|
| Orchestrator | `orchestrator.py` | 统一 AI 调度入口，提供 `stream_chat()`、`generate_character_profile()`、`analyze_relationship()`、`suggest_character_update()`、`parse_import_content()` |
| ModelRouter | `model_router.py` | 按任务动态路由 provider/model，支持任务级 max_tokens/temperature 覆盖；`OutputGuardrails` 负责 JSON 提取、截断修复、重试 |
| ContextManager | `context_manager.py` | Token 预算（默认 8000）、历史裁剪、角色记忆注入 |
| StateEngine | `state_engine.py` | 每个会话×角色的持续心理状态（情绪向量、目标、防御机制、稳定人格） |
| ConsistencyEngine | `consistency_engine.py` | 生成人格/关系/上下文一致性约束，防止角色漂移 |
| ImportEngine | `import_engine.py` | 解析导入文件（TXT/MD/PDF/DOCX/JSON/CSV），基础规则解析 + AI 增强，多轮降载重试 |
| PromptRegistry | `prompt_templates.py` | 集中管理所有提示词模板（chat_analysis、character_profile_gen、relationship_analysis、import_dialogue_parse 等） |

### Services 层（`backend/app/services/`）

从 `chat.py` 抽出的辅助业务模块：

- `diagnosis_service.py`：结构化深度诊断（按需触发，不在核心读链路）
- `analysis_store.py`：长期记忆 / 证据片段写入（`create_memory_item` / `create_evidence_span`，被诊断与归档共用）
- `profiles.py` / `identity.py` / `hypotheses.py` / `relationships.py`：角色画像/身份/假设/关系等模块化服务

### 消息发送：单次推理直接出 final

`backend/app/api/chat.py` 核心读是「**单次推理直接出 final**」：多视角分析在一次调用里完成自检 + 权衡反面 + 整合，`_save_perspectives` 直接写 `analysis_json.final`，**前端立即显示**（无后台 critic/debate/synthesize 覆盖、无时序错位）。

发送一条消息时，后端先进行**上下文组装**（读取双方档案、关系、近期对话、状态机、一致性约束），再执行两阶段 AI 调用：

1. `chat_surface_reply`：流式生成自然语气回复
2. `chat_analysis`：生成结构化深层分析（内心独白×3层、情绪×4段、潜台词、心理标签）

### 导入流程（异步两阶段）

1. **预览阶段**：规则解析立即返回基础预览（固定输出 8 大角色档案模块） → 后台异步 AI 增强 → 前端轮询 `/imports/{id}/status`
2. **提交阶段**：立即返回排队状态 → 后台 AI 审核代理 → 并发重建分析层 → 批量写库

### 持久层

- **SQLite**：主存储，文件 `backend/btb.db`（含 `-shm` / `-wal` 配套）。无迁移工具，通过 `main.py` 的 `_ensure_sqlite_columns()` 在启动时自动补充缺失列（不删表，向前兼容）
- **Neo4j**（可选）：图存储，用于多跳关系查询；嵌入式发行版 `backend/app/models/neo4j-community-5.18.1/`，需 Java 17+

---

## 关键文件索引

### 后端

- `backend/app/main.py`：FastAPI 入口，注册路由、CORS、启动时补列
- `backend/app/api/chat.py`：会话相关 API（发消息/SSE、归档、情绪张力、补全分析）。核心读为「单次推理直接出 final」
- `backend/app/api/characters.py`：角色/关系/事件/导入/导出 API
- `backend/app/api/deps.py`：数据库依赖注入
- `backend/app/services/diagnosis_service.py`：结构化深度诊断（按需触发，不在核心读链路）
- `backend/app/services/analysis_store.py`：长期记忆 / 证据片段写入（诊断与归档共用）
- `backend/app/harness/`：AI Harness 层（不可绕过）
- `backend/app/models/sql_models.py`：SQLAlchemy 模型（Character、Relationship、CharacterEvent、CharacterObservation、Conversation、Message、ImportFile、InteractionUnit）
- `backend/app/schemas/__init__.py`：Pydantic 请求响应 schema
- `backend/app/conf/config.yaml`：AI 供应商、模型、任务级参数配置
- `docs/adr/0001-chat-py-split.md`：**chat.py 拆分的 ADR** —— 若未来继续拆，**第一刀必须先抽 shared support 模块**，不可直接抽 conversation/archive/perspective（详见文档的依赖发现与风险清单）

### 前端

- `frontend/src/views/ChatUI.vue`：会话页（多角色发言、SSE 流式、情绪面板、分支回退、归档）
- `frontend/src/views/AdminDashboard.vue`：人物信息页（角色 CRUD、关系图谱、事件时间线、导入/导出、AI 更新审核）
- `frontend/src/views/AIUpdateLog.vue`：AI 更新记录独立页
- `frontend/src/stores/chat.js`：Pinia 会话状态（含 AbortController 流式中断）
- `frontend/src/stores/characters.js`：Pinia 角色/关系状态
- `frontend/src/api/index.js`：Axios + Fetch SSE 封装

---

## 重要注意事项

- **不要用环境变量传 API Key**：`start.bat` 已移除 `ANTHROPIC_API_KEY` 注入，所有 key 在 `config.yaml`（或 `config.local.yaml`）中管理
- **Vite proxy 目标是 8001**：`vite.config.js` 代理到 `127.0.0.1:8001`（用 IP 而非 localhost，避免 Node 18+ IPv6 解析冲突）
- **AI 建议不直接写入角色档案**：必须经过 `CharacterObservation` 中间层，用户批准后才落主档案
- **导入会话标记为只读**：`is_readonly=true` 的会话在会话页不可继续发言
- **不要绕过 Harness 直接调 LLM**：所有模型调用必须经 `harness/orchestrator.py`
- **chat.py 拆分的纪律**：详见 `docs/adr/0001-chat-py-split.md`——继续拆之前先抽 shared support 模块，避免 service → chat → service 循环 import
- **日志位置**：`backend/app/logs/backend.log` 和 `import.log`（RotatingFileHandler，单文件 5MB）