import streamlit as st
import requests
import uuid
import json
import graphviz
from app.core.config import settings

# 前端用户界面 (Frontend UI)
#
# 基于 Streamlit 框架构建的 Web 界面，提供以下核心功能：
# 1. **沉浸式工作台 (Sidebar)**:
#     - 用户身份设置
#     - 场景 (Scenario) 与角色 (Character) 选择
#     - 实时关系图谱 (Relationship Graph) 展示
#     - 角色档案一键同步 (Profile Sync)
# 2. **主对话区域 (Main Chat Area)**:
#     - 类似微信/Slack 的对话流展示
#     - 支持多角色发言 (通过 "Who is speaking?" 切换)
#     - 实时流式响应 (Streaming Response)
# 3. **分析与反馈 (Analysis & Feedback)**:
#     - 展示 AI 的思考过程、意图分析、潜台词解读
#     - 全景反应推演 (Audience Analysis)
#     - 用户打分与反馈 (1-5分机制)

# ==========================================
# 页面配置 (Page Configuration)
# ==========================================
st.set_page_config(page_title="BtB 智能对话", page_icon="💬", layout="wide")

# API 地址
API_URL = settings.API_URL

# ==========================================
# 会话状态初始化 (Session State Initialization)
# ==========================================
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "history" not in st.session_state:
    st.session_state.history = []
if "current_scenario_id" not in st.session_state:
    st.session_state.current_scenario_id = None
if "current_character_id" not in st.session_state:
    st.session_state.current_character_id = None
if "feedback_map" not in st.session_state:
    # 存储用户对每条日志的反馈状态
    # Structure: { log_id: { count: 0, score: 3, comment: "" } }
    st.session_state.feedback_map = {}

# ==========================================
# 辅助函数 (Helper Functions)
# ==========================================
def create_or_update_session():
    """
    同步前端会话状态到后端。
    
    功能:
    1. 如果已有 session_id，调用 PUT 更新当前绑定的角色和场景。
    2. 如果没有 session_id，调用 POST 创建新会话。
    3. 处理会话过期(404)情况，自动重建会话。
    """
    try:
        payload = {
            "user_id": st.session_state.get("user_id", "guest"),
            "character_id": st.session_state.current_character_id,
            "scenario_id": st.session_state.current_scenario_id
        }
        
        # If we already have a session_id, we UPDATE it (PUT)
        if st.session_state.session_id:
            res = requests.put(f"{API_URL}/sessions/{st.session_state.session_id}", params=payload)
            if res.status_code == 200:
                pass # st.toast(f"会话上下文已更新") - Hidden as requested
            else:
                if res.status_code == 404:
                     # st.warning("会话过期，创建新会话...") - Hidden as requested
                     st.session_state.session_id = None # Reset to force create
                     create_or_update_session() # Recursive call
                else:
                    st.error(f"会话更新失败: {res.text}")
        
        # If no session_id, we CREATE one (POST)
        else:
            res = requests.post(f"{API_URL}/sessions", params=payload)
            if res.status_code == 200:
                data = res.json()
                st.session_state.session_id = data["session_id"]
                # st.toast(f"新会话已创建") - Hidden as requested
            else:
                st.error(f"会话创建失败: {res.text}")
                
    except Exception as e:
        st.error(f"会话同步异常: {e}")

st.title("💬 BtB 深度对话理解与个性化翻译系统")
st.markdown("---")

# ==========================================
# 侧边栏：沉浸式工作台 (Sidebar: Workbench)
# ==========================================
with st.sidebar:
    st.header("🛠️ 沉浸式工作台")
    
    # 1. User & Settings
    with st.expander("👤 用户设置", expanded=False):
        user_id = st.text_input("用户ID", value="guest", key="user_id")
    
    # 2. Context Management
    st.subheader("📍 上下文管理")
    
    # Fetch Scenarios
    try:
        scenarios_res = requests.get(f"{API_URL}/scenarios/")
        scenarios = scenarios_res.json() if scenarios_res.status_code == 200 else []
        scenario_map = {s["name"]: s["id"] for s in scenarios}
        
        selected_scenario_name = st.selectbox(
            "选择场景 (Scenario)", 
            options=list(scenario_map.keys()),
            index=0 if list(scenario_map.keys()) else None,
            key="scenario_selector"
        )
        
        if selected_scenario_name:
            new_scen_id = scenario_map[selected_scenario_name]
            if new_scen_id != st.session_state.current_scenario_id:
                st.session_state.current_scenario_id = new_scen_id
                create_or_update_session()
                
    except Exception as e:
        st.error(f"场景加载失败: {e}")

    # Fetch Characters
    try:
        chars_res = requests.get(f"{API_URL}/characters/")
        chars = chars_res.json() if chars_res.status_code == 200 else []
        char_map = {c["name"]: c["id"] for c in chars}
        
        # Add "Me / User" option
        char_options = ["我 (User)"] + list(char_map.keys())
        
        selected_option = st.selectbox(
            "选择发言人 (Who is speaking?)",
            options=char_options,
            index=1 if list(char_map.keys()) else 0, # Default to first character if available
            key="char_selector"
        )
        
        if selected_option:
            if selected_option == "我 (User)":
                st.session_state.current_character_id = None
                current_speaker_name = "我"
            else:
                new_char_id = char_map[selected_option]
                st.session_state.current_character_id = new_char_id
                current_speaker_name = selected_option
                
            # Update session context (if needed, though session usually binds to a target character context, 
            # here we might want to keep the session alive but change the 'active speaker' context)
            create_or_update_session()
            
            # Hide the toast notification as requested
            # st.toast(f"已切换到 {current_speaker_name}")
                
    except Exception as e:
        st.error(f"角色加载失败: {e}")
        char_map = {} # Ensure char_map exists even on error

    st.divider()

    # 3. Current Context Display (Fixed)
    st.subheader("📊 当前上下文")
    st.caption(f"Session ID: {st.session_state.session_id}")
    
    # Relationship Graph
    if st.session_state.current_character_id:
        try:
            # Fetch relationships for current character
            rel_res = requests.get(f"{API_URL}/characters/{st.session_state.current_character_id}/relationships")
            if rel_res.status_code == 200:
                rels = rel_res.json()
                if rels:
                    st.markdown("**🔗 关系图谱**")
                    graph = graphviz.Digraph()
                    graph.attr(rankdir='LR', size='8,5')
                    graph.attr('node', shape='box', style='filled', color='lightblue')
                    
                    # Root node
                    root_name = current_speaker_name if st.session_state.current_character_id else "我"
                    graph.node(root_name, shape='ellipse', color='gold')
                    
                    for r in rels:
                        # Determine target name (simplified, ideally need to fetch name if only ID)
                        # The API usually returns basic relationship info. 
                        # Assuming we have target_id, let's try to map it if possible or just show type
                        target_id = r['target_id'] if r['source_id'] == st.session_state.current_character_id else r['source_id']
                        # Find name in local map
                        target_name = next((name for name, cid in char_map.items() if cid == target_id), f"ID:{target_id}")
                        
                        details_text = str(r.get('details') or "")
                        label = f"{r['relation_type']}\n({details_text[:10]}...)"
                        graph.edge(root_name, target_name, label=label)
                    
                    st.graphviz_chart(graph)
                else:
                    st.info("暂无关系数据")
        except Exception as e:
            st.caption(f"无法加载关系图: {e}")

    st.divider()

    # 4. Profile Sync (New Feature)
    st.subheader("📝 角色档案同步")
    with st.expander("一键总结与更新", expanded=False):
        sync_char_options = list(char_map.keys())
        sync_selected_name = st.selectbox("选择目标角色", sync_char_options, key="sync_char_selector")
        
        if st.button("🔄 立即总结并同步"):
            if sync_selected_name:
                sync_char_id = char_map[sync_selected_name]
                try:
                    with st.spinner(f"正在分析 {sync_selected_name} 的对话记录..."):
                        res = requests.post(f"{API_URL}/characters/{sync_char_id}/summarize", params={"session_id": st.session_state.session_id})
                        if res.status_code == 200:
                            data = res.json()
                            if data.get("status") == "skipped":
                                st.warning("没有足够的对话记录可供总结")
                            else:
                                st.success(f"同步成功! 版本: v{data.get('version')}")
                                st.json(data.get("summary"))
                        else:
                            st.error(f"同步失败: {res.text}")
                except Exception as e:
                    st.error(f"请求错误: {e}")

    # 5. History Backtracking (Hidden as requested)
    # with st.expander("🕰️ 历史回溯", expanded=False):
    #     if st.session_state.history:
    #         for i, msg in enumerate(st.session_state.history):
    #             role_icon = "👤" if msg['role'] == 'user' else "🤖"
    #             st.markdown(f"**{role_icon} {msg['role'].title()}**: {msg['content'][:50]}...")
    #             st.divider()
    #     else:
    #         st.caption("暂无历史记录")
            
    if st.button("🗑️ 清除会话"):
        st.session_state.messages = []
        st.session_state.history = []
        create_or_update_session()
        st.rerun()

# ==========================================
# 主对话区域 (Main Chat Area)
# ==========================================
# 显示聊天记录
for message in st.session_state.messages:
    if message["role"] == "user":
        speaker = message.get("speaker", "User")
        avatar = "🧑‍💻" if speaker in ["我", "我 (User)", "User"] else "🗣️"
        with st.chat_message("user", avatar=avatar):
             st.write(f"**{speaker}** 说：")
             st.markdown(message["content"])
    else:
        with st.chat_message("assistant", avatar="🕵️‍♂️"):
            st.markdown(message["content"])
            
            # Display Structured Analysis (History)
            if "details" in message and message["details"].get("reasoning"):
                reasoning = message["details"]["reasoning"]
                if isinstance(reasoning, dict):
                    # 1. Primary Analysis
                    pa = reasoning.get("primary_analysis")
                    if pa:
                        st.markdown("---")
                        # st.caption(f"🎯 深度解码 ({pa.get('speaker', '未知')})")
                        st.info(f"**🕵️ 意图**：{pa.get('intent_analysis')}\n\n**🔍 潜台词**：{pa.get('subtext')}\n\n**🧠 心理**：{pa.get('psychological_profile')}")
                    
                    # 2. Audience Analysis
                    aa = reasoning.get("audience_analysis", [])
                    if aa:
                        st.markdown("#### 👥 全景反应推演")
                        cols = st.columns(len(aa)) if len(aa) <= 3 else st.columns(3)
                        for idx, char_react in enumerate(aa):
                            col = cols[idx % 3]
                            with col:
                                with st.container(border=True):
                                    st.markdown(f"**👤 {char_react.get('role')}**")
                                    st.caption(f"💭 {char_react.get('likely_thought')}")
                                    st.caption(f"⚡ {char_react.get('likely_reaction')}")
            
            # 3. Feedback System
            log_id = message.get("details", {}).get("log_id")
            if log_id:
                # Initialize feedback state for this log if new
                if log_id not in st.session_state.feedback_map:
                    st.session_state.feedback_map[log_id] = {"count": 0, "score": 3, "comment": ""}
                
                fb_state = st.session_state.feedback_map[log_id]
                
                # Only show if modification count < 3
                if fb_state["count"] < 3:
                    with st.expander("📝 评价与反馈 (Help us improve)", expanded=False):
                        # Rating
                        cols = st.columns([1, 4])
                        with cols[0]:
                            new_score = st.number_input("打分 (1-5)", min_value=1, max_value=5, value=fb_state["score"], key=f"score_{log_id}")
                        with cols[1]:
                            st.caption("1分: 减少类似内容 | 5分: 增加类似内容")
                        
                        # Comment
                        new_comment = st.text_input("建议 (可选)", value=fb_state["comment"], key=f"comment_{log_id}", placeholder="例如：分析太啰嗦，或者非常精准...")
                        
                        if st.button("提交反馈", key=f"btn_{log_id}"):
                            # Call API
                            try:
                                res = requests.post(f"{API_URL}/chat/{log_id}/rate", params={"rating": new_score, "feedback": new_comment})
                                if res.status_code == 200:
                                    # Update local state
                                    st.session_state.feedback_map[log_id]["count"] += 1
                                    st.session_state.feedback_map[log_id]["score"] = new_score
                                    st.session_state.feedback_map[log_id]["comment"] = new_comment
                                    st.success(f"反馈已提交! (剩余修改次数: {3 - st.session_state.feedback_map[log_id]['count']})")
                                    st.rerun()
                                else:
                                    st.error("提交失败")
                            except Exception as e:
                                st.error(f"Error: {e}")
                else:
                    st.caption(f"✅ 已完成反馈 (评分: {fb_state['score']} 分)")


# ==========================================
# 用户输入处理 (User Input Handling)
# ==========================================
if prompt := st.chat_input("请输入发言内容..."):
    # Determine speaker name
    # Ensure current_speaker_name is available or derive it safely
    if 'current_speaker_name' not in locals():
        if st.session_state.current_character_id:
             # Try to find name in char_map if possible, otherwise generic
             current_speaker_name = next((name for name, cid in char_map.items() if cid == st.session_state.current_character_id), "角色")
        else:
             current_speaker_name = "我"
             
    speaker_name = current_speaker_name
    
    # 1. 显示用户消息
    st.session_state.messages.append({"role": "user", "content": prompt, "speaker": speaker_name})
    with st.chat_message("user", avatar="🧑‍💻" if speaker_name == "我" else "🗣️"):
        st.write(f"**{speaker_name}** 说：")
        st.markdown(prompt)

    # 2. 调用 API
    try:
        # Construct text with speaker info for backend analysis
        # Format: "【Speaker Name】说：Content"
        # This allows the backend to identify WHO is speaking without relying solely on metadata
        input_text_with_speaker = f"【{speaker_name}】说：{prompt}"
        
        payload = {
            "text": input_text_with_speaker,
            "user_id": user_id,
            "session_id": st.session_state.session_id, 
            "history": st.session_state.history,
            "scenario_id": st.session_state.current_scenario_id,
            "character_id": st.session_state.current_character_id
        }
        
        with st.chat_message("assistant", avatar="🕵️‍♂️"):
            message_placeholder = st.empty()
            # Initial state of expander
            # Hidden/Removed as requested "others don't want"
            # if st.session_state.current_character_id:
            #     status_text = f"🕵️‍♂️ 顾问正在分析 {speaker_name} 的内心..."
            # else:
            #     status_text = "🕵️‍♂️ 顾问正在观察众人的反应..."
            # details_expander = st.expander(status_text, expanded=True)
            pass
            
            # Streamlit logic for handling streaming response
            full_response = ""
            analysis_data = {}
            reasoning_content = ""
            current_log_id = None
            
            # ==========================================
            # 流式响应处理 (Streaming Response Handling)
            # ==========================================
            # We use stream=True for requests
            with requests.post(f"{API_URL}/chat", json=payload, stream=True) as response:
                if response.status_code == 200:
                    for line in response.iter_lines():
                        if line:
                            try:
                                chunk = json.loads(line.decode('utf-8'))
                                
                                # Chunk Type: Meta (Log ID)
                                if chunk.get("type") == "meta":
                                    current_log_id = chunk.get("log_id")
                                
                                # Chunk 1: Analysis (Silent)
                                elif chunk.get("type") == "streaming":
                                    analysis_data = chunk
                                    # Do NOT show NLU/Scenario details as requested
                                        
                                # Chunk 2: Final Response
                                elif chunk.get("response"):
                                    full_response = chunk.get("response")
                                    reasoning = chunk.get("reasoning")
                                    
                                    # Update Main Message with Thinking Process
                                    if full_response:
                                         message_placeholder.markdown(full_response)
                                    
                                    # Append Structured Analysis BELOW the main text
                                    if reasoning and isinstance(reasoning, dict):
                                        # 1. Primary Analysis
                                        pa = reasoning.get("primary_analysis")
                                        if pa:
                                            st.markdown("---")
                                            st.info(f"**🕵️ 意图**：{pa.get('intent_analysis')}\n\n**🔍 潜台词**：{pa.get('subtext')}\n\n**🧠 心理**：{pa.get('psychological_profile')}")

                                        # 2. Audience Analysis
                                        aa = reasoning.get("audience_analysis", [])
                                        if aa:
                                            st.markdown("#### 👥 全景反应推演")
                                            cols = st.columns(len(aa)) if len(aa) <= 3 else st.columns(3)
                                            for idx, char_react in enumerate(aa):
                                                col = cols[idx % 3]
                                                with col:
                                                    with st.container(border=True):
                                                        st.markdown(f"**👤 {char_react.get('role')}**")
                                                        st.caption(f"💭 {char_react.get('likely_thought')}")
                                                        st.caption(f"⚡ {char_react.get('likely_reaction')}")
                                    
                                    # Save reasoning for history but do not display other parts
                                    reasoning_content = reasoning

                            except Exception as e:
                                if line.strip():
                                    pass # st.warning(f"解析响应数据时出错: {e}")
                else:
                    st.error(f"API请求失败: {response.text}")

            # Update Session State History
            if full_response:
                latency_label = "已思考 (完成)" 
                
                details = {
                    "reasoning": reasoning_content,
                    "nlu": analysis_data.get("nlu_analysis"),
                    "scenario": analysis_data.get("scenario"),
                    "context": analysis_data.get("context_used"),
                    "log_id": current_log_id
                }
                
                st.session_state.messages.append({
                    "role": "assistant", 
                    "content": full_response,
                    "details": details
                })
                
                # Add to context history (limit 20)
                st.session_state.history.append({"role": "user", "content": input_text_with_speaker})
                st.session_state.history.append({"role": "assistant", "content": full_response})
                if len(st.session_state.history) > 20:
                    st.session_state.history = st.session_state.history[-20:]
                    
    except Exception as e:
        st.error(f"系统错误: {e}")
