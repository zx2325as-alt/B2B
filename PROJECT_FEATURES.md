# Project Features & Documentation

## 1. 核心功能模块 (Core Modules)

### A. 长对话深度分析 (Long Conversation Analysis)
- **入口**: `pages/1_Long_Conversation_Analysis.py`
- **功能**:
  - **多角色多维度分析**: 支持对对话中的多个角色进行并行分析，提取 6 维人物属性（基础属性、表层行为、情绪特征、认知决策、人格特质、核心本质）。
  - **动态归档 (Dynamic Archiving)**: 
    - 使用 `deep_merge_profile` 算法，支持对角色档案的非破坏性增量更新。
    - 自动版本控制，保留历史变更记录。
    - 支持 "Pending" 状态的观察记录，需管理员审核后合入主档案。
  - **全量历史回溯**: 支持加载完整的对话历史 (`limit=-1`) 进行深度挖掘。
  - **可视化展示**: 提供多维度的雷达图、趋势图展示角色成长与变化。

### B. 实时语音交互 (Real-time Audio Interaction)
- **入口**: `pages/3_Audio_Collector.py` (Frontend) + `pages/4_Analysis_Monitor.py` (Backend Monitor)
- **架构**: 
  - **前后端分离**: 采集端 (Collector) 负责音频流捕获、VAD 切分、初步特征提取 (MFCC, SER)；分析端 (Monitor) 负责深度 LLM 分析与融合。
  - **WebSocket流式传输**: 实现低延迟的音频数据传输。
  - **并发处理**: 采用生产者-消费者模型，音频录制与 API 调用并行，支持 Overlap 处理。
- **特性**:
  - **实时转写 (STT)**: 集成 Faster-Whisper，支持 CUDA 加速与 CPU 自动回退 (Fallback)。
  - **说话人分离 (Diarization)**: 基于聚类 (Agglomerative Clustering) 的轻量级声纹识别，结合 Voice Profile 数据库。
  - **情感识别 (SER)**: 实时输出情感标签与置信度。

### C. 会议分析系统 (Meeting Analysis System)
- **入口**: `pages/5_Meeting_Analysis_System.py`
- **功能**:
  - **实时仪表盘**: 整合音频采集、波形显示、实时转写、情感分析于一体。
  - **角色弧光 (Character Arc)**: 实时追踪参会者的情绪变化与观点演进。
  - **深度分析**: 会后自动生成会议纪要、决议提取、待办事项整理。

### D. 系统管理后台 (Admin Dashboard)
- **入口**: `pages/Admin_Dashboard.py`
- **功能概览**:
  - **数据管理中心**: 提供对系统核心数据（对话日志、角色档案、场景配置）的增删改查 (CRUD) 界面。
  - **反馈与评估系统**: 查看并管理用户提交的对话评分 (Rating) 与反馈建议 (Feedback)，用于模型微调与系统优化。
- **子模块详情**:
  1.  **场景管理 (Scene Management)**:
      -   **功能**: 管理对话场景的预设配置，包括场景背景、预设引导语、相关角色绑定等。
      -   **实现**: 基于 `SceneService`，支持 JSON 配置的导入导出。
  2.  **角色管理 (Character Management)**:
      -   **功能**: 查看和编辑系统中的角色档案 (Profiles)。支持查看角色的多维度属性（基础、行为、情绪等）以及历史版本记录。
      -   **实现**: 复用 `CharacterService`，提供结构化 JSON 编辑器。
  3.  **关系管理 (Relation Management)**:
      -   **功能**: 定义和管理角色之间的人物关系图谱 (Relationship Graph)。
      -   **可视化**: 使用图表展示角色间的互动频率与情感倾向。
  4.  **核心监控 (Core Monitoring)**:
      -   **功能**: 全局监控系统运行状态，包括聊天日志、实时语音日志和长对话分析记录。
      -   **指标**: 实时计算平均响应延迟 (Latency)、用户评分 (Rating) 和对话吞吐量。
  5.  **待处理建议 (Suggestions)**:
      -   **功能**: 审核由 AI 自动提取的角色观察建议 (Observations)。
      -   **操作**: 管理员可对建议进行 "批准 (Approve)" 或 "拒绝 (Reject)"，批准后自动合入档案。
  6.  **人物指标 (Character Metrics)**:
      -   **功能**: 可视化展示角色的成长轨迹和关键指标变化（如好感度、情绪波动等）。

## 2. 关键技术特性 (Key Technical Features)

### 数据一致性与版本控制
- **Deep Merge Strategy**: 自研 `deep_merge_profile` 工具函数 (`app/utils/data_utils.py`)，确保 JSON 数据在合并时保留原有结构，支持列表追加与字典递归更新。
- **Session State Management**: 利用 Streamlit Session State 在多页面间保持上下文与用户状态。

### 高性能音频处理
- **Hybrid Retrieval**: 结合 BM25 关键词检索与语义向量检索 (`KnowledgeService`)，提高 RAG 准确率。
- **CUDA/CPU Hybrid**: 智能检测硬件环境，自动切换推理设备，确保系统稳定性。

### API 与 接口规范
- **RESTful API**: 基于 FastAPI 构建后端服务 (`app/api/`)。
- **规范化校验**: 使用 Pydantic 模型与 `Body(..., embed=True)` 确保请求参数的严格校验，统一前端调用规范 (JSON Body)。

## 3. 部署与环境 (Deployment)
- **依赖管理**: `requirements.txt`
- **模型下载**: `scripts/download_models.py` (支持 HF Mirror)
- **启动脚本**: `start_btb.bat` (集成环境配置与服务启动)
