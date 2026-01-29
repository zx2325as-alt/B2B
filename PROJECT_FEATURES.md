# BtB 系统深度功能技术白皮书

本文档深入解析 BtB (Behind the Bot) 系统各个模块的技术实现细节、数据流逻辑及核心算法策略。

---

## 1. 🏠 前端交互与会话管理 (Frontend UI)
**核心文件**: `app/web/chat_ui.py`

基于 Streamlit 构建的沉浸式角色扮演工作台，采用了 **Session State 驱动** 的状态管理模式。

### **1.1 会话状态同步机制 (Session Synchronization)**
前端与后端通过 `create_or_update_session` 函数保持严格同步，确保上下文的一致性：
- **状态初始化**: 系统启动时自动生成 UUID 作为 `session_id`。
- **动态更新 (PUT)**: 当用户切换 **场景 (Scenario)** 或 **当前扮演角色 (Character)** 时，触发 `PUT /sessions/{session_id}` 请求，更新后端上下文指针。
- **自动恢复 (Auto-Recovery)**: 若后端返回 `404 Not Found` (会话过期)，前端会自动重置 `session_id` 并发起 `POST` 请求创建新会话，实现无感知的断线重连。

### **1.2 可视化组件技术细节**
- **实时关系图谱 (Graphviz)**:
    - 调用 `GET /characters/{id}/relationships` 获取邻接表数据。
    - 使用 `graphviz.Digraph` 动态渲染有向图，当前角色节点高亮 (Gold)，关系边显示交互细节 (`details`)。
- **人机回环反馈 UI (HITL Feedback)**:
    - **状态机管理**: 每个消息块独立维护反馈状态 (`pending` -> `providing_reason` -> `done_yes/no`)。
    - **多级反馈**:
        - ✅ **准确**: 直接提交正向反馈。
        - ❌ **不准确**: 触发二级表单，收集 `reason_category` (如：情绪判断错误、意图偏差) 和 `comment`，用于后续的模型微调 (SFT) 数据集构建。

### **1.3 多模态消息渲染**
- **结构化推理展示**: 解析后端返回的 JSON `details` 字段，通过 `st.expander` 或直接嵌入消息体展示：
    - **意图分析 (Intent)**: 显式展示 AI 对用户话语的意图判断。
    - **潜台词 (Subtext)**: 揭示角色听到的“弦外之音”。
    - **全景推演 (Audience Analysis)**: 使用 `st.columns` 网格化展示在场其他 NPC 的心理活动与预期反应。

---

## 2. 📜 长对话深度分析引擎 (Deep Analysis Engine)
**核心文件**: `app/services/extraction_service.py`, `app/web/pages/1_Long_Conversation_Analysis.py`

系统的核心大脑，负责将非结构化的对话流转化为结构化的角色档案数据。

### **2.1 上下文注入策略 (Context Injection Strategy)**
为了让 LLM (Large Language Model) 做出精准判断，系统采用了 **动态提示词工程 (Dynamic Prompt Engineering)**，注入多源上下文：
1.  **多模态感知 (Multimodal Context)**:
    - 注入音频特征：`Pitch` (音高/Hz), `Energy` (能量/dB), `Duration` (时长)。
    - 注入 SER (语音情感识别) 结果：例如 `Top Emotion: Anger (0.85)`。
    - *目的*: 修正 LLM 仅凭文本对语气和情绪的误判。
2.  **历史摘要 (History Summaries)**:
    - 检索 ChromaDB 或 SQL 中的过往会话摘要，构建长期记忆链。
3.  **原始对话回溯 (Raw Dialogue History)**:
    - **新增特性**: 不仅依赖摘要，直接注入角色过往的 **原始对话记录 (Raw Logs)**。
    - *实现*: `load_raw_dialogue_logs` 函数按时间戳拉取 `User` 和 `Bot` 的逐字对白，保留原汁原味的说话风格。
4.  **已知档案锚点 (Known Metrics)**:
    - 注入角色当前的 6 维属性，要求 LLM 仅提取 **“变化”** 或 **“新信息”**，避免重复提取。

### **2.2 七维数据提取架构 (7-Dimensional Extraction)**
LLM 被指示严格按照 JSON Schema 提取以下七个维度的信息：
1.  **基础属性 (Basic Attributes)**: 身份、年龄、客观事实。
2.  **表层行为 (Surface Behavior)**: 口癖、肢体语言习惯。
3.  **情绪特征 (Emotional Traits)**: 情绪阈值、压力反应模式。
4.  **认知决策 (Cognitive Decision)**: 逻辑闭环、价值观优先级。
5.  **人格特质 (Personality Traits)**: Big Five, MBTI, 核心性格底色。
6.  **核心本质 (Core Essence)**: 终极欲望、恐惧、灵魂暗面。
7.  **人物弧光 (Character Arc) [NEW]**:
    - **事件驱动**: 记录 `event` (事件描述) 和 `timestamp`。
    - **类型标记**: 识别变化类型 (`Growth` 成长, `Regression` 退行, `Turning Point` 转折点)。

### **2.3 鲁棒性设计 (Robustness)**
- **JSON 自修复机制**: 若 LLM 输出的 JSON 格式错误 (如多余的逗号、Markdown 标记)，系统会自动捕获 `JSONDecodeError` 并发起二次 LLM 调用 (`repair_prompt`) 进行格式修复，确保数据管道不中断。

---

## 3. 💾 数据归档与演化算法 (Data Management)
**核心文件**: `app/utils/data_utils.py`, `app/web/pages/1_Long_Conversation_Analysis.py`

### **3.1 非破坏性深度合并算法 (Non-Destructive Deep Merge)**
**函数**: `deep_merge_profile(old_data, new_data)`
为了解决“新分析覆盖旧记忆”的问题，实现了递归合并逻辑：
- **字典 (Dict)**: 递归遍历键值对进行合并。
- **列表 (List)**: **追加并去重 (Append & Deduplicate)**。
    - 使用 `Set` 对可哈希元素去重。
    - 对不可哈希元素 (如复杂 Dict) 直接追加，保留完整历史痕迹。
- **基本类型 (Primitive)**: 仅当新值非空 (Truthy) 时才覆盖旧值，防止有效信息被空值擦除。

### **3.2 统一归档工作流 (Unified Workflow)**
`perform_character_archive` 函数标准化了所有归档操作：
1.  **时间线记录**: 将分析出的 `character_deeds` 或手动事件写入 `Event` 表。
2.  **最新状态同步**: 在合并前强制 `GET` 最新档案，防止并发写入导致的数据回滚 (Stale Data)。
3.  **增量更新**: 应用 `deep_merge_profile` 生成最终档案快照。
4.  **版本控制**: 每次归档自动生成 `version_note`，支持回滚。

---

## 4. 🎙️ 实时音频流处理 (Real-time Processing)
**核心文件**: `app/web/pages/6_Realtime_Recording.py`

### **4.1 低延迟架构**
- **WebSocket 全双工通信**: 浏览器端 JS 组件通过 WebSocket 直接推送 16kHz PCM 音频流。
- **VAD (Voice Activity Detection)**: 后端集成 `webrtcvad` 进行静音检测，仅处理有效语音帧，降低计算负载。
- **流式识别**: 采用 `Faster-Whisper` 或云端 API 进行流式 STT (Speech-to-Text)。

### **4.2 动态声纹聚类**
- 系统实时维护一个 **声纹特征池 (Embedding Pool)**。
- 每段新语音计算 Embedding 后，与池中质心计算余弦相似度，实时判断是 "Speaker A" 还是 "New Speaker"，实现会议场景下的自动角色区分。

---

## 5. 🛠️ 通用助手与文件解析
**核心文件**: `app/web/pages/2_General_Assistant.py`

- **智能编码检测**: 使用 `chardet` 库自动识别上传文件 (`.txt`, `.md`) 的编码格式 (UTF-8, GBK, Latin-1)，彻底解决中文乱码问题。
- **思维链展示 (CoT)**: 对于复杂指令，系统会请求 LLM 输出 `<thinking>` 标签包裹的推理过程，并在 UI 上通过 `st.expander("Reasoning")` 折叠展示，增强可解释性。
