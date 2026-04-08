# BtB — Deep Dialogue Intelligence System

> AI Harness 驱动的沉浸式对话深度分析平台

---

## 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│                         前端 (Vue 3)                          │
│  ┌──────────────────┐        ┌─────────────────────────────┐  │
│  │  Page 1: Chat UI │        │ Page 3: Admin Dashboard      │  │
│  │  • 多角色发言     │        │ • 角色CRUD + AI档案生成      │  │
│  │  • 流式AI回复     │        │ • 关系图谱 (Canvas force)    │  │
│  │  • 深层分析展开   │        │ • 时间线事件                 │  │
│  │  • 对话分支       │        │ • AI建议审核工作流           │  │
│  │  • 情绪面板       │        │ • 关系AI分析                 │  │
│  └──────────────────┘        └─────────────────────────────┘  │
└──────────────────────┬───────────────────────────────────────┘
                       │ HTTP / SSE
┌──────────────────────▼───────────────────────────────────────┐
│                    AI Harness Layer                           │
│  ┌─────────────┐ ┌──────────────┐ ┌───────────┐ ┌─────────┐ │
│  │PromptRegistry│ │ContextManager│ │ModelRouter│ │Guardrails│ │
│  │• 6个模板     │ │• Token计数   │ │• 按任务路由│ │• JSON校验│ │
│  │• 参数化渲染  │ │• 历史裁剪    │ │• 复杂度评估│ │• 安全过滤│ │
│  └─────────────┘ └──────────────┘ └───────────┘ └─────────┘ │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │              Orchestrator (统一调度)                     │  │
│  │  • stream_chat()  • generate_character_profile()        │  │
│  │  • analyze_relationship()  • suggest_character_update() │  │
│  └─────────────────────────────────────────────────────────┘  │
└──────────────────────┬───────────────────────────────────────┘
                       │ Anthropic SDK
              ┌────────▼────────┐
              │  Claude API      │
              │  claude-sonnet   │
              │  claude-haiku    │
              └─────────────────┘
┌─────────────────────────────────────────────────────────────┐
│                 FastAPI + SQLAlchemy + SQLite                 │
│  characters / character_events / relationships /             │
│  character_observations / conversations / messages           │
└─────────────────────────────────────────────────────────────┘
```

---

## 快速启动

### 环境要求
- Python 3.11+
- Node.js 18+
- Anthropic API Key

### 1. 配置 API Key

```bash
export ANTHROPIC_API_KEY=sk-ant-xxx
```

### 2. 启动后端

```bash
chmod +x start_backend.sh
./start_backend.sh
```

后端运行在 `http://localhost:8000`
API文档: `http://localhost:8000/docs`

### 3. 启动前端

```bash
chmod +x start_frontend.sh
./start_frontend.sh
```

前端运行在 `http://localhost:5173`

### 或使用 Docker Compose

```bash
ANTHROPIC_API_KEY=sk-ant-xxx docker-compose up
```

---

## AI Harness 组件说明

### PromptRegistry (`harness/prompt_templates.py`)
集中管理所有AI提示词模板，支持参数化渲染。内置6种模板：

| 模板名 | 用途 |
|--------|------|
| `chat_analysis` | 聊天消息深层分析 |
| `character_profile_gen` | 角色心理档案生成 |
| `relationship_analysis` | 双角色关系分析 |
| `ai_suggest_update` | AI建议档案更新 |
| `emotion_curve` | 情绪曲线分析 |

### ContextManager (`harness/context_manager.py`)
- Token预算管理（默认8000 token）
- 自动历史裁剪（保留最新对话）
- 角色记忆注入

### ModelRouter (`harness/model_router.py`)
- **SIMPLE任务** → claude-haiku（快速/低成本）
- **MEDIUM任务** → claude-sonnet（平衡）
- **COMPLEX任务** → claude-sonnet（深度分析）
- 根据内容长度动态升级复杂度

### Guardrails (`harness/model_router.py` > `OutputGuardrails`)
- JSON格式自动提取（容忍markdown包装）
- 必填字段校验
- Prompt注入防护
- 自动重试（最多2次）

### Orchestrator (`harness/orchestrator.py`)
统一调度入口，提供：
- `stream_chat()` — SSE流式对话分析
- `generate_character_profile()` — 角色档案AI生成
- `analyze_relationship()` — 关系AI分析
- `suggest_character_update()` — AI建议更新

---

## 功能覆盖

### Page 1: Chat UI ✅
- [x] 多角色切换发言 (1.1)
- [x] 消息气泡带分析层 — 内心独白/情绪/潜台词 (1.2)
- [x] AI流式回复 — SSE (1.3)
- [x] 场景预设 (1.4)
- [x] 实时心理侧写标签 (1.5)
- [x] 对话历史导出（通过API）(1.7)
- [x] 对话分支与回退 (1.9)
- [x] 角色情绪面板 (1.13)

### Page 3: Admin Dashboard ✅
- [x] 角色档案CRUD (3.1)
- [x] 动态特征演化 — 大五人格可视化 (3.2)
- [x] 人物事迹时间线 (3.3)
- [x] AI建议更新审核流 (3.4)
- [x] 关系图谱可视化 — Canvas Force布局 (3.5)
- [x] 手动编辑关系 (3.6)
- [x] 角色搜索与过滤 (3.7)
- [x] 关系强度历史追踪 (3.10)
- [x] 批量事件管理 (3.11)

---

## 项目结构

```
btb/
├── backend/
│   ├── app/
│   │   ├── harness/           # AI Harness 核心
│   │   │   ├── prompt_templates.py  # Prompt注册中心
│   │   │   ├── context_manager.py   # 上下文管理
│   │   │   ├── model_router.py      # 模型路由 + 护栏
│   │   │   └── orchestrator.py      # 统一调度器
│   │   ├── api/
│   │   │   ├── characters.py        # 角色/关系/事件API
│   │   │   ├── chat.py              # 聊天/SSE流API
│   │   │   └── deps.py              # 数据库依赖
│   │   ├── models/
│   │   │   └── sql_models.py        # SQLAlchemy模型
│   │   ├── schemas/
│   │   │   └── __init__.py          # Pydantic schemas
│   │   └── main.py                  # FastAPI入口
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── views/
│   │   │   ├── ChatUI.vue           # 页面1: 聊天UI
│   │   │   └── AdminDashboard.vue   # 页面3: 角色管理
│   │   ├── stores/
│   │   │   ├── chat.js              # Pinia聊天状态
│   │   │   └── characters.js        # Pinia角色状态
│   │   ├── api/index.js             # API客户端
│   │   ├── router/index.js          # Vue Router
│   │   ├── assets/global.css        # 全局设计系统
│   │   ├── App.vue                  # 根布局 + 侧边栏
│   │   └── main.js                  # 入口
│   ├── package.json
│   ├── vite.config.js
│   └── Dockerfile
├── docker-compose.yml
├── start_backend.sh
└── start_frontend.sh
```
