# BtB (Deep Dialogue Understanding and Personalized Translation System) 项目详细功能与架构文档

## 1. 项目概述

BtB 是一个旨在深入理解对话“潜台词”的智能系统。它不仅处理文字层面的翻译或对话，更通过分析角色的**内心独白 (Inner OS)**、**真实情绪 (Emotion)** 和**隐含动机 (Subtext)**，实现对复杂社交场景的深度剖析。系统采用前后端分离的现代化架构，支持实时音频输入、多角色关系建模以及基于反馈的模型自我进化机制。

---

## 2. 核心功能点及具体实现方式

### 2.1 沉浸式智能对话与多角色互动 (Chat UI)
- **功能描述**: 提供类似微信/Slack 的聊天界面，支持多角色（如：用户、顾问、其他参与者）切换发言。AI 会实时分析每句话的深层意图，并给出带分析过程的流式回复。
- **实现方式**: 
  - **前端**: 基于 [chat_ui.py](file:///e:/python/conda/B2B/app/web/chat_ui.py) 使用 Streamlit 的 `st.chat_message` 和 `st.session_state` 管理会话历史和当前发言人。
  - **后端**: FastAPI 提供流式接口 `/api/v1/stream`，支持 Server-Sent Events (SSE) 或 NDJSON 的流式输出。
  - **AI 引擎**: `DialogueService` 动态组装 System Prompt，结合当前场景 (`Scenario`)、选定角色 (`Character`) 和 RAG 检索出的历史上下文进行内容生成。

### 2.2 长对话深度分析与归档 (Long Conversation Analysis)
- **功能描述**: 允许用户粘贴大段文本、上传文件或输入音视频链接。系统将自动分离角色、提取核心话题、分析心理侧写，生成结构化报告和关系图谱，并支持一键批量归档到角色的长期记忆中。
- **实现方式**:
  - **多模态输入**: 在 [1_Long_Conversation_Analysis.py](file:///e:/python/conda/B2B/app/web/pages/1_Long_Conversation_Analysis.py) 中处理直接文本、文件上传，或通过 `media_downloader.py` 下载音视频，调用 `/api/v1/audio/diarization` 接口（集成 Pyannote 和 Faster-Whisper）进行声纹分离与语音转写。
  - **深度推演**: 调用 `ExtractionService.deep_analyze`，根据 `prompts.yaml` 的模板，让 LLM 提取 7 个维度的数据：基础属性、表层行为、情绪特征、认知决策、人格特质、核心本质和人物弧光。
  - **归档迭代**: `perform_character_archive` 函数使用 `deep_merge_profile` 进行深层字典/列表合并，将新提取的分析结果迭代（非覆盖）更新至数据库中的 `Character` 和 `CharacterEvent` 表。

### 2.3 动态角色管理与关系图谱 (Admin Dashboard)
- **功能描述**: 管理角色的静态属性、动态特征（如性格、弱点）、人物事迹（Timeline），并可视化呈现角色之间的社交关系网络。
- **实现方式**:
  - **数据持久化**: 基于 [sql_models.py](file:///e:/python/conda/B2B/app/models/sql_models.py) 中的 `Character`, `CharacterEvent`, `Relationship` 等 SQLAlchemy ORM 模型。
  - **关系可视化**: 前端使用 `graphviz` 渲染节点（角色）和边（关系强度 Strength、情感极性 Sentiment）。
  - **版本控制与审核**: 每次档案更新生成版本快照；AI 生成的角色更新建议（Observations）需经人工审核 (Approve/Reject) 才能并入核心档案，确保人设不崩塌。

### 2.4 实时录音与多模态感知 (Realtime Recording)
- **功能描述**: 实时捕获麦克风音频，进行语音活动检测 (VAD)、情感分析 (SER) 和转写，动态捕捉对话者的真实情绪与语气。
- **实现方式**:
  - **音频流接入**: [6_Realtime_Recording.py](file:///e:/python/conda/B2B/app/web/pages/6_Realtime_Recording.py) 中通过 WebSocket 发送音频块。
  - **后端处理管道**: `RealtimeAudioService` 接收音频流，使用 WebRTCVAD 进行端点检测，Wav2vec2 提取音高、能量等声学特征辅助判断情绪，并调用 Faster-Whisper 进行高精度转写。

### 2.5 NLU 意图路由与场景化引擎 (NLU & Scenario Engine)
- **功能描述**: 智能判断用户输入的意图（闲聊、分析、系统指令），并根据预设场景（如 HR、医疗、通用）应用不同的系统设定和思维链。
- **实现方式**:
  - **意图识别**: `NLUEngine` 解析输入，输出 JSON（包含 intent, emotion, reasoning, subtext）。
  - **配置驱动**: 场景配置存储在 YAML 文件中，通过 `ScenarioService` 同步到数据库，运行时由 `ContextManager` 根据当前环境动态加载并渲染 System Prompt。

### 2.6 质量反馈与自我进化机制 (Feedback & Evolution)
- **功能描述**: 收集用户对系统分析结果的打分和评论。如果评分较低（<=2 星），自动触发复盘机制，生成改进建议，沉淀为模型微调数据。
- **实现方式**:
  - **反馈收集**: 前端通过动态生成的表单收集评分（1-5）和吐槽，提交至 `/api/v1/feedback` 接口。
  - **触发进化**: `FeedbackService.trigger_evolution_if_needed` 判定为低分时，调用 LLM 的 `review_analysis` 模板，诊断问题原因并重新生成优秀的报告，最终作为 `EvolutionCase` 落库，实现 Data Flywheel。

---

## 3. 功能的完整性评估

### **高完整性方面**
1. **业务逻辑闭环**: 系统实现了从“多模态输入 -> NLU 意图解析 -> 深度分析/流式交互 -> 结构化结果呈现 -> 用户反馈打分 -> 归档与模型进化”的完整数据飞轮。
2. **多模态处理能力**: 不仅处理纯文本，还整合了复杂的音频处理管线（VAD, STT, SER, Diarization），具备落地到真实世界复杂会议、访谈场景的潜力。
3. **架构分层清晰**: 采用 FastAPI (Backend) + SQLAlchemy (DB) + Streamlit (Frontend) 架构。核心引擎 (`Engine`, `Services`) 和 API 路由分离，易于后续扩展或更换组件。

### **待完善与脆弱点**
1. **状态管理依赖度高**: Streamlit 前端对于复杂状态（如长对话分析的页面留存、对话切换）的管理较为脆弱。由于 Streamlit 的重绘机制，目前高度依赖 `st.session_state` 手动干预，容易出现状态残留或异常清空。
2. **并发与计算瓶颈**: 音频转写（Whisper）、声纹分离和深度的 LLM 分析均属于计算/IO 密集型任务。当前架构下的大文件或并发请求可能导致接口超时或阻塞。
3. **记忆的深度融合**: 虽然具备历史记录 (`CharacterEvent`)，但在大规模长对话中，RAG 的检索质量决定了 AI 是否会“遗忘”早期设定的重要细节。

---

## 4. 多维度优化方案

### 4.1 性能与并发维度 (Performance & Concurrency)
- **引入异步任务队列**: 将音频处理、长文本深度心理分析、关系图谱更新等耗时操作剥离出 HTTP 请求生命周期，放入 **Celery** 或 **RabbitMQ** 异步执行。前端通过长轮询或 WebSocket 实时获取任务进度栏。
- **LLM 结构化流式输出**: 对于长对话分析，当前是等待所有 JSON 解析完毕后一次性展示。可采用类似 `LangChain` 或 `Instructor` 的 Streaming JSON 解析方案，在分析过程中逐步向前端渲染各个维度的结果，大幅降低用户的体感等待时间。
- **本地模型加速**: 若本地部署语音模型和 LLM，可引入 **vLLM** 或 **TensorRT-LLM** 框架加速推理吞吐量。

### 4.2 架构与代码质量维度 (Architecture & Code Quality)
- **前端技术栈升级**: Streamlit 适合快速验证和内部 Dashboard。对于面向最终用户的沉浸式对话、复杂的长对话表单交互，建议使用 **React/Next.js** 或 **Vue 3** 进行重构。FastAPI 仅提供纯净的 RESTful/GraphQL API。
- **持久化状态同步**: 将前端的 Session State 深度绑定到 **Redis**。即使用户刷新页面或更换设备，也能通过 `user_id` 和 `session_id` 从 Redis 完整恢复工作台状态，实现真正的跨端一致性。

### 4.3 AI 与算法维度 (AI & Algorithm)
- **图检索增强 (GraphRAG)**: 目前的 RAG 可能是基础的向量匹配。建议引入 GraphRAG 技术，深度结合现有的 `Relationship` 表。让模型在回答时不仅检索“他说过什么”，还能推理“他们之间的社会网络关系如何影响这句话的潜台词”。
- **动态上下文压缩 (Context Compression)**: 针对超长对话和记忆积累，引入类似 MemGPT 的机制。当历史事件超过 Token 阈值时，触发后台的“记忆折叠”动作，将早期的低权重事件抽象为高维度的性格特征，防止注意力机制稀释。
- **基于反馈的 RLHF 自动化**: 将 `EvolutionCase` 中收集到的“原始输入-差评输出-改进版输出”数据，定期通过自动化脚本整理为 DPO (Direct Preference Optimization) 格式，定期微调本地基础大模型，让系统越用越懂特定领域的“黑话”和潜台词。

### 4.4 用户体验与产品维度 (UX & Product)
- **多维数据可视化**: 当前“深度思考报告”主要为 Markdown 和 JSON。可以引入 **ECharts** 或 **Plotly**，使用雷达图展示角色各项属性的动态得分，使用折线图展示角色在时间线上的情绪起伏。
- **交互式人机协同打标**: 在长对话分析结果页，允许用户用鼠标高亮某段对话，直接在侧边栏手动修正其“意图/潜台词”。系统根据用户的局部修正，实时局部重算人物的心理侧写，提供更专业、可控的分析工具体验。
