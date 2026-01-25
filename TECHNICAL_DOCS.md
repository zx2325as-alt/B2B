# 全景对话心理分析系统 - 技术文档

## 1. 项目概述 (Project Overview)
本项目是一个基于大语言模型 (LLM) 的**全景对话心理分析系统**。不同于传统的角色扮演聊天机器人，本系统的核心定位是用户的“深度沟通顾问”与“军师”。它能够实时监听对话，分析发言者的真实意图、潜台词及心理状态，并推演在场其他关键角色的内心反应。

## 2. 核心功能 (Core Features)

### 2.1 全景心理分析 (Panoramic Analysis)
- **多角色心理推演**：不仅分析当前发言者，还并行推演所有在场关键角色（如老领导、飞飞飞等）的内心OS和情绪反应。
- **意图与潜台词解码**：深度挖掘对话背后的真实动机，识别“话里有话”。
- **思考过程可视化**：完整展示AI的推理逻辑，像讲故事一样描述局势变化。

### 2.2 动态对话舞台 (Dynamic Dialogue Stage)
- **实时角色追踪**：系统自动维护一个“对话舞台”，记录最近活跃的角色、上一轮对话内容及当前发言者。
- **自适应上下文**：根据舞台状态，动态组装Prompt，确保AI始终基于最新的局势进行分析。

### 2.3 角色与关系管理 (Character & Relationship Management)
- **角色CRUD**：支持创建、查看、更新、删除角色档案。
- **动态档案 (Dynamic Profile)**：支持存储非结构化的JSON数据（如性格标签、过往经历），并具备版本控制（每次更新版本号+1）。
- **关系图谱**：管理角色之间的人际关系（如“上下级”、“竞争对手”），并在分析时作为重要参考。

### 2.4 智能反馈与微调 (Feedback & Tuning)
- **打分机制**：用户可对AI分析结果进行打分 (1-5分) 和评论。
- **自适应输出**：系统根据用户打分自动调整分析的详细程度（1分简化，5分详尽）。
- **档案同步**：一键总结对话信息，自动更新至角色档案库。

### 2.5 实时语音全链路分析 (Real-time Voice Analysis) **(New)**
- **低延迟重叠处理 (Overlap Processing)**: 采用生产者-消费者 (Producer-Consumer) 架构，实现录音与分析的并行处理。将切片时长优化至 3秒，配合异步队列，实现 <3秒 的端到端响应延迟，保证对话识别的连续性，不漏字、不卡顿。
- **多模态融合 (Multi-modal Fusion)**: 
    - **声纹识别**: 自动提取 MFCC 声纹指纹，通过余弦相似度进行说话人识别 (Speaker ID)。
    - **角色同步**: 支持将声纹与系统角色 (Character) 绑定，实现“闻其声知其人”。
    - **声学特征**: 实时提取音高 (Pitch)、能量 (Energy)、语速 (Duration) 等副语言特征，辅助情绪判断。
- **实时纠错 (Real-time Correction)**: 提供 UI 交互界面，允许用户在对话过程中实时修正识别错误的文本，修正结果即时同步至历史记录与上下文。
- **断点续传与持久化**: 采用 JSONL 文件存储分析历史，支持页面刷新后数据自动恢复，确保长会话数据不丢失。

## 3. 技术架构 (Architecture)

### 3.1 总体架构
采用 **Client-Server** 架构，前端基于 Streamlit，后端基于 FastAPI。

```mermaid
graph TD
    Client[前端 (Streamlit)] <--> API[后端 API (FastAPI)]
    API <--> Service[业务逻辑层 (Services)]
    Service <--> Context[上下文管理器 (ContextManager)]
    Service <--> LLM[大模型接口 (LLM Interface)]
    Service <--> DB[(SQLite Database)]
    Client -- Audio Stream --> AudioService[音频服务]
    AudioService -- STT/SER --> Whisper/Wav2Vec2
```

### 3.2 关键模块

#### A. 前端 (app/web/chat_ui.py)
- **职责**：负责用户交互、展示分析报告、管理会话状态。
- **技术点**：
    - 使用 `st.session_state` 管理会话上下文。
    - 实时渲染多角色“心理卡片”。
    - 通过 RESTful API 与后端通信。

#### B. 后端服务 (app/services/)
- **ContextManager (context_manager.py)**：
    - 核心大脑。负责构建“对话舞台” (`stage_context`)，解析输入文本中的发言者，聚合角色档案与历史记忆。
- **DialogueService (dialogue.py)**：
    - 负责调用 LLM。根据 ContextManager 提供的信息，选择合适的 Prompt 模板，生成 JSON 格式的分析结果。
- **CharacterService (character_service.py)**：
    - 处理角色的增删改查及动态档案的更新。
- **AudioService (audio_service.py)** **(Updated)**:
    - 集成 `faster-whisper` (STT), `edge-tts` (TTS), `transformers` (SER), `librosa` (Feature Extraction)。
    - 提供本地化的多模态处理能力。

#### C. 数据存储 (app/models/sql_models.py)
- 使用 SQLAlchemy ORM。
- 核心表：
    - `Character`: 角色基本信息 + `dynamic_profile` (JSON)。
    - `Relationship`: 角色间关系。
    - `ConversationSession`: 会话记录。
    - `Feedback`: 用户评分与反馈（新增）。

## 4. 接口说明 (API Documentation)

本节提供核心接口的调用说明与示例。

### 4.1 会话管理
- `PUT /sessions/{session_id}`: 更新会话状态（当前角色、场景）。
- `POST /sessions`: 创建新会话。

### 4.2 角色管理
- `GET /characters`: 获取角色列表。
- `POST /characters/{id}/summarize`: **(新增)** 根据对话历史生成角色总结并同步至档案。

### 4.3 对话生成
- `POST /chat`: 发送对话内容，获取全景分析结果。
    - 输入：`text` (包含 "Role说：..."), `session_id`.
    - 输出：`thinking_process` (思考过程), `primary_analysis` (主分析), `audience_analysis` (观众反应).

### 4.4 语音服务 (Audio Services)
- `POST /audio/transcribe`: 上传音频文件，返回文本、情绪、声纹ID及声学特征。
- `POST /audio/synthesize`: 文本转语音 (TTS)。

### 4.5 反馈系统
- `POST /feedback`: **(新增)** 提交对某次回复的打分与评论。

### 4.6 调用示例 (Usage Examples)

#### A. 发起对话 (Start Chat)
```bash
curl -X POST "http://localhost:8000/api/v1/chat" \
     -H "Content-Type: application/json" \
     -d '{
           "text": "【李雷】说：这个项目必须今天上线！",
           "user_id": "user_123",
           "session_id": "uuid-session-001",
           "character_id": 1,
           "scenario_id": 1
         }'
```
> **注意**: 响应为 `application/x-ndjson` 流式格式，需按行解析 JSON。
