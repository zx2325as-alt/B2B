import streamlit as st
import requests
import json
import yaml
import pandas as pd
import random
import plotly.express as px
import plotly.graph_objects as go
import streamlit.components.v1 as components
from app.core.config import settings
from app.utils.history_utils import HistoryService
from app.services.voice_profile import VoiceProfileService
import datetime
import time

# ==========================================
# 配置与初始化 (Configuration & Initialization)
# ==========================================

# 获取后端 API 地址
API_URL = settings.API_URL

# 设置 Streamlit 页面配置
st.set_page_config(page_title="BtB 后台管理系统", layout="wide", page_icon="🛠️")

# --- CSS 注入：优化布局与样式 ---
# 1. 减少顶部空白
# 2. 优化 Tab 样式 (类似于浏览器标签页)
# 3. 优化 Expander 和按钮样式
st.markdown("""
    <style>
    /* 1. Reduce top padding and margin */
    .block-container {
        padding-top: 1rem !important;
        margin-top: 5px !important;
    }
    
    /* 2. Optimize Tab Styles */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        height: 45px;
        white-space: pre-wrap;
        background-color: #f8f9fa;
        border-radius: 8px 8px 0 0;
        border: 1px solid #e0e0e0;
        border-bottom: none;
        padding: 0 16px;
        font-weight: 500;
        transition: all 0.2s ease;
    }
    .stTabs [aria-selected="true"] {
        background-color: #ffffff !important;
        border-top: 3px solid #ff4b4b !important;
        color: #ff4b4b !important;
        font-weight: bold;
    }
    .stTabs [data-baseweb="tab"]:hover {
        background-color: #ffffff;
        color: #ff4b4b;
    }

    /* 3. Builder/Popup Components Optimization */
    div[data-testid="stExpander"] {
        border-radius: 8px;
        border: 1px solid #eee;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    
    /* General Input/Button Polish */
    .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {
        border-radius: 6px;
    }
    .stButton button {
        border-radius: 6px;
        font-weight: 500;
        transition: all 0.2s;
    }
    .stButton button:hover {
        transform: translateY(-1px);
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    }
    </style>
""", unsafe_allow_html=True)

st.title("🛠️ BtB 系统后台管理看板")

# 创建主要的功能标签页
tab1, tab2, tab3, tab4, tab5,  tab7 = st.tabs(["🎭 场景管理", "👤 角色管理", "🔗 关系管理", "📊 核心监控 (Monitoring)", "🧠 待处理建议 (Suggestions)", "📈 人物指标 (Metrics)"])

# ==========================================
# Tab 5: 待处理建议 (Suggestions)
# ==========================================
with tab5:
    # 1. 获取待处理的观察建议 (Fetch Suggestions)
    try:
        res = requests.get(f"{API_URL}/observations/pending")
        if res.status_code == 200:
            observations = res.json()
        else:
            observations = []
            st.error(f"无法获取建议: {res.text}")
    except Exception as e:
        observations = []
        st.error(f"连接错误: {e}")

    if not observations:
        st.info("暂无待处理的观察建议。系统会在对话分析中自动生成。")
    else:
        # 2. 按角色分组展示 (Group by Character)
        obs_by_char = {}
        for obs in observations:
            c_id = obs.get("character_id")
            if c_id not in obs_by_char:
                obs_by_char[c_id] = []
            obs_by_char[c_id].append(obs)

        # 获取角色名称映射 (用于显示)
        char_map = {}
        try:
            c_res = requests.get(f"{API_URL}/characters/")
            if c_res.status_code == 200:
                for c in c_res.json():
                    char_map[c["id"]] = c["name"]
        except:
            pass

        # 3. 渲染每个角色的建议列表 (Display)
        for c_id, obs_list in obs_by_char.items():
            c_name = char_map.get(c_id, f"Unknown Character ({c_id})")
            with st.expander(f"👤 {c_name} ({len(obs_list)} 条建议)", expanded=True):
                for obs in obs_list:
                    col_content, col_action = st.columns([4, 1])
                    with col_content:
                        content = obs.get("content", {})
                        category = content.get("category", "General")
                        text = content.get("observation", "")
                        confidence = obs.get("confidence", 0.0)
                        
                        st.markdown(f"**[{category}]** {text}")
                        st.caption(f"Session: {obs.get('session_id')} | Confidence: {confidence} | Date: {obs.get('created_at')[:10]}")
                    
                    with col_action:
                        # 批准建议 (Approve)
                        if st.button("✅ 批准", key=f"approve_{obs['id']}"):
                            try:
                                r = requests.post(f"{API_URL}/observations/{obs['id']}/approve")
                                if r.status_code == 200:
                                    st.success("已批准！")
                                    st.rerun()
                                else:
                                    st.error("失败")
                            except:
                                st.error("错误")
                        
                        # 拒绝建议 (Reject)
                        if st.button("❌ 拒绝", key=f"reject_{obs['id']}"):
                            try:
                                r = requests.post(f"{API_URL}/observations/{obs['id']}/reject")
                                if r.status_code == 200:
                                    st.success("已拒绝！")
                                    st.rerun()
                                else:
                                    st.error("失败")
                            except:
                                st.error("错误")
                    st.divider()

# ==========================================
# Tab 4: 核心监控 (Monitoring)
# ==========================================
with tab4:
    st.markdown("### 📊 全局核心监控 (Global Monitoring)")
    
    # Source Selection
    monitor_source = st.radio(
        "选择监控数据源", 
        ["💬 聊天对话日志 (Chat Logs)", "🎙️ 实时语音日志 (Realtime Voice Logs)", "📜 长对话分析记录 (Long Conversation Logs)"],
        horizontal=True
    )
    
    col_header, col_btn = st.columns([8, 2])
    with col_btn:
        if st.button("🔄 刷新数据 (Sync)", key="refresh_monitor"):
            st.rerun()

    # -------------------------------------------------------
    # A. 聊天对话日志 (Chat Logs)
    # -------------------------------------------------------
    if "Chat Logs" in monitor_source:
        st.markdown("在此监控系统核心指标，并对历史对话进行人工评分。")
        
        # 1. 筛选器 (Filters)
        col_f1, col_f2 = st.columns(2)
        
        # 获取场景列表用于筛选
        filter_scenario_id = None
        try:
            scenarios_res = requests.get(f"{API_URL}/scenarios/")
            if scenarios_res.status_code == 200:
                scenarios = scenarios_res.json()
                scenario_options = {"全部": None}
                for s in scenarios:
                    scenario_options[s["name"]] = s["id"]
                
                with col_f1:
                    selected_s = st.selectbox("按场景筛选", options=list(scenario_options.keys()))
                    filter_scenario_id = scenario_options[selected_s]
        except:
            pass
            
        # 获取角色列表用于筛选
        filter_character_id = None
        try:
            chars_res = requests.get(f"{API_URL}/characters/")
            if chars_res.status_code == 200:
                chars = chars_res.json()
                char_options = {"全部": None}
                for c in chars:
                    char_options[c["name"]] = c["id"]
                    
                with col_f2:
                    selected_c = st.selectbox("按人物筛选", options=list(char_options.keys()))
                    filter_character_id = char_options[selected_c]
        except:
            pass

        # 2. 获取并显示日志 (Fetch Logs)
        try:
            params = {"limit": 50} # Increased limit for better metrics
            if filter_scenario_id:
                params["scenario_id"] = filter_scenario_id
            if filter_character_id:
                params["character_id"] = filter_character_id
                
            logs_res = requests.get(f"{API_URL}/logs", params=params)
            if logs_res.status_code == 200:
                logs = logs_res.json()
                
                # --- Metrics Dashboard ---
                if logs:
                    df = pd.DataFrame(logs)
                    # Ensure columns exist
                    if 'rating' not in df.columns: df['rating'] = 0
                    if 'latency_ms' not in df.columns: df['latency_ms'] = 0
                    
                    # Calculate metrics
                    avg_rating = df[df['rating'] > 0]['rating'].mean()
                    if pd.isna(avg_rating): avg_rating = 0.0
                    
                    avg_latency = df['latency_ms'].mean()
                    
                    st.markdown("### 📈 核心指标 (Core Metrics)")
                    m1, m2, m3 = st.columns(3)
                    m1.metric("平均评分 (Quality)", f"{avg_rating:.1f}/5.0", help="仅统计已评分的对话")
                    m2.metric("平均延迟 (Performance)", f"{avg_latency:.0f} ms")
                    m3.metric("近期对话量 (Volume)", len(logs))
                    st.divider()

                if not logs:
                    st.info("暂无对话日志。")
                else:
                    st.subheader("📝 对话日志详情")
                    for log in logs:
                        # 显示每条日志的详情
                        with st.expander(f"[{log['created_at']}] User: {log['user_input'][:20]}..."):
                            col1, col2 = st.columns([2, 1])
                            with col1:
                                st.markdown("**User Input:**")
                                st.info(log['user_input'])
                                st.markdown("**Bot Response:**")
                                st.success(log['bot_response'])
                                if log.get('reasoning_content'):
                                    st.markdown("**🤔 Reasoning (CoT):**")
                                    st.warning(log['reasoning_content'])
                                
                                st.json({
                                    "Latency": f"{log['latency_ms']:.2f}ms",
                                    "Scenario ID": log['scenario_id'],
                                    "Rating": log['rating']
                                })
                                
                            with col2:
                                st.markdown("### 人工评分")
                                # 评分表单
                                with st.form(f"rate_{log['id']}"):
                                    new_rating = st.slider("评分 (1-5)", 1, 5, value=log['rating'] or 3)
                                    feedback = st.text_area("反馈意见", value=log['feedback_text'] or "")
                                    if st.form_submit_button("提交评分"):
                                        try:
                                            rate_res = requests.post(
                                                f"{API_URL}/chat/{log['id']}/rate", 
                                                params={"rating": new_rating, "feedback": feedback}
                                            )
                                            if rate_res.status_code == 200:
                                                st.success("已更新！")
                                                st.rerun()
                                        except Exception as e:
                                            st.error(f"Error: {e}")
            else:
                st.error("无法获取日志。")
        except Exception as e:
            st.error(f"连接错误: {e}")
            
    # -------------------------------------------------------
    # C. 长对话分析记录 (Long Conversation Logs)
    # -------------------------------------------------------
    elif "Long Conversation Logs" in monitor_source:
        st.markdown("在此查看和评价长对话分析的归档记录。")
        
        # 1. Fetch
        try:
            res = requests.get(f"{API_URL}/analysis/history", params={"limit": 50})
            if res.status_code == 200:
                logs = res.json()
                
                if not logs:
                    st.info("暂无分析记录")
                else:
                    # Metrics
                    rated_logs = [l for l in logs if l.get('structured_data', {}).get('rating', 0) > 0]
                    avg_rating = sum([l['structured_data']['rating'] for l in rated_logs]) / len(rated_logs) if rated_logs else 0.0
                    
                    st.markdown("### 📈 核心指标 (Core Metrics)")
                    m1, m2 = st.columns(2)
                    m1.metric("记录总数 (Total)", len(logs))
                    m2.metric("平均评分 (Avg Rating)", f"{avg_rating:.1f} ⭐")
                    st.divider()
                    
                    # Display
                    for log in logs:
                        s_data = log.get('structured_data', {}) or {}
                        rating = s_data.get('rating', 0)
                        
                        with st.expander(f"📝 [{log['created_at'][:16]}] {log.get('summary', '')[:50]}...", expanded=False):
                            col1, col2 = st.columns([3, 1])
                            with col1:
                                st.markdown(f"**Log ID**: {log['id']} | **Time**: {log['created_at']}")
                                st.markdown(f"**摘要**: {log.get('summary', 'N/A')}")
                                st.markdown(f"**参与角色**: {log.get('character_names', [])}")
                                
                                # Structured Data Preview
                                if s_data.get("character_analysis"):
                                    st.markdown("**角色分析概览**:")
                                    for char_a in s_data["character_analysis"]:
                                        c_name = char_a.get("name", "Unknown")
                                        c_intent = char_a.get("deep_intent", "N/A")
                                        st.caption(f"- {c_name}: {c_intent}")

                                st.markdown("**完整分析报告**:")
                                with st.container(height=300):
                                    st.markdown(log.get('markdown_report', ''))

                                if st.checkbox("显示完整数据 (Raw & JSON)", key=f"show_raw_{log['id']}"):
                                     st.text_area("原始内容", log.get('text_content', ''), height=200)
                                     st.json(s_data)
                                
                            with col2:
                                st.markdown("### 评分")
                                new_rating = st.slider("Rating", 1, 5, value=rating if rating > 0 else 3, key=f"lc_rate_{log['id']}")
                                if st.button("提交评分", key=f"btn_lc_{log['id']}"):
                                    try:
                                        r = requests.post(f"{API_URL}/analysis/logs/{log['id']}/rate", json={"rating": new_rating})
                                        if r.status_code == 200:
                                            st.success("评分已更新")
                                            time.sleep(0.5)
                                            st.rerun()
                                        else:
                                            st.error("更新失败")
                                    except Exception as e:
                                        st.error(f"Error: {e}")
                                        
            else:
                st.error("获取数据失败")
        except Exception as e:
            st.error(f"Connection Error: {e}")

    # -------------------------------------------------------
    # B. 实时语音日志 (Realtime Voice Logs)
    # -------------------------------------------------------
    else:
        st.info("正在监控实时语音分析流 (Live Stream)...")
        
        # 1. Fetch Segments
        try:
            res = requests.get(f"{API_URL}/segments", params={"limit": 50})
            if res.status_code == 200:
                segments = res.json()
            else:
                segments = []
                st.error("Failed to fetch segments")
        except Exception as e:
            segments = []
            st.error(f"Connection Error: {e}")
        
        if not segments:
            st.warning("暂无语音日志 (No Segments)。")
        else:
            # Metrics
            total_logs = len(segments)
            rated_logs = [s for s in segments if s.get("rating", 0) > 0]
            avg_rating = sum([s["rating"] for s in rated_logs]) / len(rated_logs) if rated_logs else 0.0
            
            m1, m2 = st.columns(2)
            m1.metric("Total Segments", total_logs)
            m2.metric("Avg Quality", f"{avg_rating:.1f} ⭐")
            
            st.divider()
            
            # Display Segments
            if segments:
                for seg in segments:
                    # Color code emotion
                    emotion = seg.get("emotion", {}) or {}
                    
                    with st.expander(f"🔊 [{seg.get('speaker_name')}] {seg.get('text', '')[:50]}...", expanded=False):
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.markdown(f"**Text:** {seg.get('text')}")
                            st.caption(f"Time: {seg.get('created_at')} | Speaker ID: {seg.get('speaker_id')}")
                            
                            # Analysis Preview
                            analysis = seg.get("analysis", {}) or {}
                            if analysis.get("structured"):
                                 st.json(analysis["structured"])
                            if analysis.get("report"):
                                 st.markdown("**Analysis Report:**")
                                 st.markdown(analysis["report"])
                                 
                            st.json(emotion)

                        with col2:
                            st.markdown("### 评分 (Rating)")
                            curr_rating = seg.get("rating", 0)
                            curr_feedback = seg.get("feedback", "")
                            
                            with st.form(f"rate_seg_{seg['id']}"):
                                new_rating = st.slider("Rating", 1, 5, value=curr_rating if curr_rating > 0 else 3)
                                new_feedback = st.text_area("Feedback", value=curr_feedback or "")
                                
                                if st.form_submit_button("Submit"):
                                    try:
                                        r = requests.post(
                                            f"{API_URL}/segments/{seg['id']}/rate", 
                                            params={"rating": new_rating, "feedback": new_feedback}
                                        )
                                        if r.status_code == 200:
                                            st.success("Saved!")
                                            time.sleep(0.5)
                                            st.rerun()
                                        else:
                                            st.error(f"Failed: {r.text}")
                                    except Exception as e:
                                        st.error(f"Error: {e}")
            else:
                    st.info("No realtime segments found.")
                        # Sync Backend
                    try:
                            payload = {
                                "session_id": "monitor_rating",
                                "user_input": log.get("text"),
                                "model_output": json.dumps(log.get("analysis", {})),
                                "rating": rating,
                                "comment": "Monitor Rating"
                            }
                            requests.post(f"{API_URL}/feedback/feedback", json=payload, timeout=5)
                            st.toast(f"评分已同步: {rating}")
                    except: pass
                        
                    # 3. Deep Analysis Inspection (Reuse Logic)
                    analysis = log.get("analysis", {})
                    if analysis:
                        st.divider()
                        st.markdown("#### 🧠 深度对话理解 (Deep Understanding)")
                        
                        # Markdown Report
                        if "markdown_report" in analysis:
                            with st.expander("查看思考过程 (Thinking Process)"):
                                st.markdown(analysis["markdown_report"])
                        
                        # Structured Data
                        structured = analysis.get("structured_data", {})
                        char_analysis_list = structured.get("character_analysis", [])
                        
                        if char_analysis_list:
                             # Reuse display logic
                             st.caption("检测到的角色分析数据：")
                             
                             for j, item in enumerate(char_analysis_list):
                                char_name = item.get("name", "Unknown")
                                deep_intent = item.get("deep_intent", "N/A")
                                strategies = item.get("strategy", [])
                                if isinstance(strategies, list): strategies = ", ".join(strategies)
                                mood = item.get("mood", [])
                                if isinstance(mood, list): mood = ", ".join(mood)
                                
                                st.markdown(f"**🎭 {char_name}**")
                                c1, c2 = st.columns(2)
                                c1.info(f"意图: {deep_intent}")
                                c2.info(f"情绪: {mood}")
                                st.markdown(f"策略: {strategies}")
                                
                                # Profile Update (6 Dimensions)
                                profile_update = item.get("profile_update", {})
                                if profile_update:
                                    tab_names = [
                                        "1️⃣ 基础属性", "2️⃣ 表层行为", "3️⃣ 情绪特征", 
                                        "4️⃣ 认知决策", "5️⃣ 人格特质", "6️⃣ 核心本质"
                                    ]
                                    tabs = st.tabs(tab_names)
                                    
                                    # Helper
                                    def display_dim_mon(tab, key, label):
                                        with tab:
                                            data_obj = profile_update.get(key, {})
                                            desc = data_obj.get("desc", label)
                                            content = data_obj.get("data", {})
                                            if content:
                                                st.json(content)
                                            else:
                                                st.caption("无更新")
                                    
                                    display_dim_mon(tabs[0], "basic_attributes", "基础属性")
                                    display_dim_mon(tabs[1], "surface_behavior", "表层行为")
                                    display_dim_mon(tabs[2], "emotional_traits", "情绪特征")
                                    display_dim_mon(tabs[3], "cognitive_decision", "认知决策")
                                    display_dim_mon(tabs[4], "personality_traits", "人格特质")
                                    display_dim_mon(tabs[5], "core_essence", "核心本质")

# ==========================================
# Tab 1: 场景管理 (Scenario Management)
# ==========================================
with tab1:
    # 1. 场景列表显示 (List Scenarios)
    try:
        response = requests.get(f"{API_URL}/scenarios/")
        if response.status_code == 200:
            scenarios = response.json()
            if scenarios:
                df = pd.DataFrame(scenarios)
                # 重命名列以显示中文
                df_display = df[["id", "name", "domain", "description"]].rename(columns={
                    "id": "ID", "name": "名称", "domain": "领域", "description": "描述"
                })
                st.dataframe(df_display, use_container_width=True)
            else:
                st.info("暂无场景数据。")
        else:
            st.error("无法获取场景数据。")
    except Exception as e:
        st.error(f"连接错误: {e}")

    # 2. 创建新场景 (Create Scenario)
    with st.expander("➕ 创建新场景"):
        with st.form("new_scenario"):
            name = st.text_input("场景名称")
            domain = st.text_input("所属领域 (如: 医疗, 客服)")
            desc = st.text_area("场景描述")
            rules = st.text_area("规则配置 (JSON格式)", value="{}")
            submitted = st.form_submit_button("创建场景")
            
            if submitted:
                try:
                    payload = {
                        "name": name,
                        "domain": domain,
                        "description": desc,
                        "rules": json.loads(rules)
                    }
                    res = requests.post(f"{API_URL}/scenarios/", json=payload)
                    if res.status_code == 200:
                        st.success("场景创建成功！")
                        st.rerun()
                    else:
                        st.error(f"创建失败: {res.text}")
                except Exception as e:
                    st.error(f"JSON格式错误或其他异常: {e}")

# ==========================================
# Tab 2: 角色管理 (Character Management)
# ==========================================
with tab2:
    
    # --- 会话状态管理 (Session State for Dialog) ---
    # char_dialog_mode: None (List View), "add" (Create), "edit" (Update)
    if "char_dialog_mode" not in st.session_state:
        st.session_state.char_dialog_mode = None 
    if "selected_char_id" not in st.session_state:
        st.session_state.selected_char_id = None
        
    # 辅助函数：关闭弹窗并重置状态
    def close_char_dialog():
        st.session_state.char_dialog_mode = None
        st.session_state.selected_char_id = None
        st.session_state.edit_char_data = None
        st.rerun()

    # --- 弹窗模式：新增/编辑表单 (DIALOG / FORM SECTION) ---
    if st.session_state.char_dialog_mode:
        mode = st.session_state.char_dialog_mode
        is_edit = (mode == "edit")
        title = "新增角色" if not is_edit else "修改角色"
        
        # 准备编辑数据
        char_data = {}
        if is_edit:
            if st.session_state.get("edit_char_data"):
                char_data = st.session_state.edit_char_data
            elif st.session_state.selected_char_id:
                # 如果缺少数据，重新从后端获取
                try:
                    res = requests.get(f"{API_URL}/characters/{st.session_state.selected_char_id}")
                    if res.status_code == 200:
                        char_data = res.json()
                except:
                    st.error("Fetch failed")
        
        # 显示表单容器
        with st.container(border=True):
            c_head, c_close = st.columns([8, 1])
            c_head.subheader(title)
            if c_close.button("❌", key="close_dialog_x"):
                close_char_dialog()

            # --- 角色编辑表单 ---
            with st.form("char_form_popup"):
                name = st.text_input("角色姓名", value=char_data.get("name", ""))
                
                # 结构化动态档案字段 (Structured Core Fields)
                st.markdown("#### 🔹 结构化动态档案 (Structured Dynamic Profile)")
                dyn_profile_data = char_data.get("dynamic_profile") or {}
                if not isinstance(dyn_profile_data, dict): dyn_profile_data = {}
                
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    drivers_val = "\n".join(dyn_profile_data.get("core_drivers", []))
                    drivers = st.text_area("核心诉求 (每行一个)", value=drivers_val, height=100)
                    
                    needs_val = "\n".join(dyn_profile_data.get("inferred_core_needs", []))
                    needs = st.text_area("深层需求 (每行一个)", value=needs_val, height=100)
                    
                    behavior = st.text_input("行为模式", value=dyn_profile_data.get("behavior_habits", ""))
                    emotion = st.text_input("情绪基线", value=dyn_profile_data.get("emotional_baseline", ""))
                    comm_style = st.text_input("沟通风格", value=dyn_profile_data.get("communication_style", ""))

                with col_d2:
                    events_val = "\n".join(dyn_profile_data.get("recent_key_events", []))
                    events = st.text_area("近期关键事件 (每行一个)", value=events_val, height=150)
                    
                    rel_val = json.dumps(dyn_profile_data.get("relationship_summary", {}), ensure_ascii=False, indent=2)
                    rels = st.text_area("关系摘要 (JSON)", value=rel_val, height=150)

                st.divider()
                # 高级 JSON 编辑 (用于 Attributes 和 Traits)
                with st.expander("高级 JSON 编辑 (Advanced JSON)"):
                    c1, c2 = st.columns(2)
                    with c1:
                        attrs_val = json.dumps(char_data.get("attributes", {"age": 25, "role": "user", "occupation": "工程师"}), ensure_ascii=False, indent=2)
                        attrs = st.text_area("基础属性 (Attributes)", value=attrs_val, height=200)
                    with c2:
                        traits_val = json.dumps(char_data.get("traits", {"personality": "friendly", "tone": "formal"}), ensure_ascii=False, indent=2)
                        traits = st.text_area("性格特征 (Traits)", value=traits_val, height=200)
                    
                    st.markdown("#### 🔹 动态档案 JSON (Dynamic Profile)")
                    dyn_prof_val = json.dumps(dyn_profile_data, ensure_ascii=False, indent=2)
                    dyn_profile_json_input = st.text_area("完整动态档案 (Dynamic Profile JSON)", value=dyn_prof_val, height=300, help="在此处修改将覆盖上方表单中的对应字段")
                
                # --- 声纹绑定 (Voice Binding) ---
                st.divider()
                st.markdown("#### 🔊 声纹绑定 (Voice Binding)")
                
                # Helper to get voice profiles
                vp_service = VoiceProfileService()
                all_profiles = vp_service.get_all_speakers()
                
                # Find current bound profile
                current_voice_id = None
                current_voice_info = "无 (None)"
                char_name_curr = char_data.get("name", "")
                
                for p in all_profiles:
                    if p["name"] == char_name_curr and char_name_curr:
                        current_voice_id = p["id"]
                        current_voice_info = f"{p['name']} (ID: {p['id']})"
                        break
                
                st.info(f"当前关联声纹: {current_voice_info}")
                
                # Options
                voice_options = ["-- 不关联 (Unbind) --"]
                voice_map = {"-- 不关联 (Unbind) --": "-- 不关联 (Unbind) --"}
                
                if current_voice_id:
                     voice_options.append(current_voice_id)
                     voice_map[current_voice_id] = f"当前: {current_voice_info}"
                     
                for p in all_profiles:
                    # Show Unknowns or potential candidates
                    if "Unknown" in p["name"] or "speaker" in p["id"]:
                        if p["id"] != current_voice_id:
                             voice_options.append(p["id"])
                             voice_map[p["id"]] = f"{p['name']} ({p['id']})"
                
                # Remove duplicates if any
                voice_options = list(dict.fromkeys(voice_options))
                
                selected_voice = st.selectbox(
                    "选择声纹进行关联 (Select Voice to Bind)", 
                    options=voice_options,
                    format_func=lambda x: voice_map.get(x, x),
                    index=voice_options.index(current_voice_id) if current_voice_id in voice_options else 0
                )

                cols_btn = st.columns([1, 1])
                submitted = cols_btn[0].form_submit_button("💾 保存提交")
                
                if submitted:
                    try:
                        attrs_json = json.loads(attrs)
                        traits_json = json.loads(traits)
                        rels_json = json.loads(rels)
                        
                        # 1. Determine priority: JSON vs Form
                        # Check if JSON input was modified by user
                        json_modified = False
                        base_dyn_profile = {}
                        
                        try:
                            current_json_obj = json.loads(dyn_profile_json_input)
                            # Get original for comparison
                            orig_dyn_profile = char_data.get("dynamic_profile") or {}
                            
                            # Simple comparison (serialize both to ensure format matches)
                            if json.dumps(current_json_obj, sort_keys=True) != json.dumps(orig_dyn_profile, sort_keys=True):
                                json_modified = True
                                base_dyn_profile = current_json_obj
                            else:
                                base_dyn_profile = orig_dyn_profile.copy()
                        except:
                            # JSON parse error, fall back to empty or original
                            base_dyn_profile = char_data.get("dynamic_profile", {}).copy()
                        
                        # 2. Apply Form Overrides ONLY if JSON was NOT modified
                        # If user modified JSON, we assume they want full control and ignore partial form inputs
                        # (unless we want to enforce form inputs on top? Better to trust JSON edit)
                        if not json_modified:
                            if drivers.strip():
                                base_dyn_profile["core_drivers"] = [x.strip() for x in drivers.split('\n') if x.strip()]
                            if needs.strip():
                                base_dyn_profile["inferred_core_needs"] = [x.strip() for x in needs.split('\n') if x.strip()]
                            if behavior.strip():
                                base_dyn_profile["behavior_pattern"] = behavior
                            if emotion.strip():
                                base_dyn_profile["emotional_baseline"] = emotion
                            if comm_style.strip():
                                base_dyn_profile["communication_style"] = comm_style
                            if events.strip():
                                base_dyn_profile["recent_key_events"] = [x.strip() for x in events.split('\n') if x.strip()]
                            
                            # Relationship summary is special - merge from separate JSON input
                            if rels_json:
                                base_dyn_profile["relationship_summary"] = rels_json
                        
                        # IMPORTANT: If JSON was modified, we trust base_dyn_profile completely.
                        # However, rels_json comes from a separate text area.
                        # If user edited the MAIN JSON, they likely edited relationship_summary there too.
                        # If they edited the separate "Relationship Summary" box, we should respect that IF the main JSON wasn't touched for that part.
                        # For simplicity:
                        # - If main JSON modified -> Use main JSON entirely (ignore separate boxes)
                        # - If main JSON NOT modified -> Use separate boxes to update base_dyn_profile
                        
                        # (The logic above `if not json_modified` already handles the separate boxes)
                        # The only missing part was `relationship_summary` inside that block.
                        # Added `if rels_json:` block above.
                        
                        # 合并原始数据中未在 UI 显示的字段 (已经在 JSON 加载时包含)
                        # for k, v in dyn_profile_data.items(): ... (不再需要，因为 base_dyn_profile 已经包含了)

                        payload = {
                            "name": name,
                            "attributes": attrs_json,
                            "traits": traits_json,
                            "dynamic_profile": base_dyn_profile
                        }

                        
                        if is_edit:
                            res = requests.put(f"{API_URL}/characters/{char_data['id']}", json=payload)
                        else:
                            res = requests.post(f"{API_URL}/characters/", json=payload)
                            
                        if res.status_code == 200:
                            # --- Handle Voice Binding ---
                            try:
                                # 1. Unbind old if changed (Rename back to Unknown)
                                if current_voice_id and selected_voice != current_voice_id:
                                    vp_service.update_speaker_name(current_voice_id, f"Unknown (was {char_name_curr})")
                                
                                # 2. Bind new if selected (Rename to Char Name)
                                if selected_voice != "-- 不关联 (Unbind) --" and selected_voice != current_voice_id:
                                    vp_service.update_speaker_name(selected_voice, name)
                                    st.success(f"声纹已关联: {name}")
                            except Exception as ve:
                                st.warning(f"声纹更新异常: {ve}")

                            st.success("操作成功！")
                            close_char_dialog()
                        else:
                            st.error(f"失败: {res.text}")
                    except Exception as e:
                        st.error(f"错误: {e}")

            if st.button("🔙 取消并返回列表"):
                close_char_dialog()

    # --- 列表模式 (LIST / TABLE SECTION) ---
    else:
        # 1. 搜索栏 (Search Bar)
        with st.container(border=True):
            c_s1, c_s2, c_s_btn = st.columns([3, 3, 1])
            search_name = c_s1.text_input("姓名 (Character Name)", placeholder="输入姓名查询")
            search_id = c_s2.text_input(" (ID)", placeholder="输入ID查询")
            do_search = c_s_btn.button("🔍 查询", use_container_width=True)

        # 2. 操作栏 (Action Bar)
        c_act1, c_act2, c_act3, c_act4, c_space = st.columns([1, 1, 1, 1, 4])
        add_clicked = c_act1.button("➕ 新增", type="primary", use_container_width=True)
        edit_clicked = c_act2.button("✏️ 修改", use_container_width=True)
        del_clicked = c_act3.button("🗑️ 删除", type="primary", use_container_width=True)
        
        # 模板下载 (Download Template)
        template_json = {
            "characters": [
                {
                    "name": "Alice (示例角色)",
                    "description": "Character Description",
                    "attributes": {
                        "age": 25, 
                        "role": "user", 
                        "occupation": "engineer"
                    },
                    "traits": {
                        "personality": "friendly"
                    },
                    "dynamic_profile": {
                        "core_drivers": ["driver1"]
                    }
                },
                {
                    "name": "Bob (示例角色)",
                    "attributes": {"age": 30}
                }
            ],
            "relationships": [
                {
                    "source": "Alice (示例角色)",
                    "target": "Bob (示例角色)",
                    "relation": "Friend",
                    "strength": 7,
                    "sentiment": 2,
                    "details": {"context": "同事"}
                }
            ]
        }
        c_act4.download_button(
            label="📥 模版",
            data=json.dumps(template_json, indent=4, ensure_ascii=False),
            file_name="import_template.json",
            mime="application/json",
            use_container_width=True
        )

        # ==========================================
        # 2.4 导入功能 (Import Functionality)
        # ==========================================
        with st.expander("📤 导入角色 (Import JSON)"):
            st.info("支持导入单个角色对象、角色列表，或包含 characters/relationships 的完整包。")
            uploaded_file = st.file_uploader("选择 JSON 文件", type=["json"])
            if uploaded_file is not None:
                try:
                    data = json.load(uploaded_file)
                    
                    # Preview
                    if isinstance(data, dict) and "characters" in data:
                        st.write(f"预览: {len(data.get('characters', []))} 个角色, {len(data.get('relationships', []))} 条关系")
                    elif isinstance(data, list):
                        st.write(f"预览: {len(data)} 个角色")
                    
                    if st.button("🚀 确认导入"):
                        try:
                            res = requests.post(f"{API_URL}/characters/import", json=data)
                            if res.status_code == 200:
                                result = res.json()
                                st.success(f"导入完成! 角色: {result.get('characters')}, 关系: {result.get('relationships')}")
                                if result.get("errors"):
                                    with st.expander("查看错误详情"):
                                        st.json(result["errors"])
                                # st.rerun() # 让用户看到结果后再刷新
                            else:
                                st.error(f"导入失败: {res.text}")
                        except Exception as e:
                            st.error(f"请求异常: {e}")
                            
                except Exception as e:
                    st.error(f"JSON 解析错误: {e}")

        
        # ==========================================
        # 2.5 数据列表与操作 (Data List & Actions)
        # ==========================================

        # --- 获取数据 (Fetch Data) ---
        chars = []
        try:
            res = requests.get(f"{API_URL}/characters/")
            if res.status_code == 200:
                chars = res.json()
        except:
            st.error("数据加载失败")

        # --- 过滤逻辑 (Filter Logic) ---
        filtered_chars = chars
        if search_name:
            filtered_chars = [c for c in filtered_chars if search_name in c["name"]]
        if search_id:
            filtered_chars = [c for c in filtered_chars if str(c["id"]) == search_id]

        # --- 数据表格展示 (Data Table) ---
        selected_rows = []
        if filtered_chars:
            df = pd.DataFrame(filtered_chars)
            # 添加选择列 (Add Selection Column)
            df.insert(0, "选择", False)
            
            # 提取显示字段 (Extract Display Fields)
            df["类型"] = df["attributes"].apply(lambda x: x.get("role", "-") if isinstance(x, dict) else "-")
            
            df_display = df[["选择", "id", "name", "类型", "version", "updated_at"]]
            
            # 配置列显示格式 (Column Configuration)
            column_config = {
                "选择": st.column_config.CheckboxColumn("选择", width="small"),
                "id": st.column_config.TextColumn("Id", width="small"),
                "name": st.column_config.TextColumn("姓名", width="medium"),
                "类型": st.column_config.TextColumn("关系", width="medium"),
                "version": st.column_config.NumberColumn("版本", width="small"),
                "updated_at": st.column_config.DatetimeColumn("更新日期", format="YYYY-MM-DD HH:mm")
            }
            
            # 可编辑表格 (Editable Dataframe for Selection)
            edited_df = st.data_editor(
                df_display,
                column_config=column_config,
                hide_index=True,
                use_container_width=True,
                key="char_table_editor",
                disabled=["id", "name", "类型", "version", "updated_at"]
            )
            
            # 获取选中行 (Get Selected Rows)
            selected_df = edited_df[edited_df["选择"]]
            
            # 映射回原始数据 (Map back to original data)
            if not selected_df.empty:
                selected_ids = selected_df["id"].tolist()
                selected_rows = [c for c in filtered_chars if c["id"] in selected_ids]

        else:
            st.info("暂无数据")

        # --- 按钮操作逻辑 (Button Action Logic) ---
        # 1. 新增 (Add)
        if add_clicked:
            st.session_state.char_dialog_mode = "add"
            st.session_state.edit_char_data = None
            st.session_state.selected_char_id = None
            st.rerun()
            
        # 2. 编辑 (Edit)
        if edit_clicked:
            if len(selected_rows) == 1:
                st.session_state.char_dialog_mode = "edit"
                st.session_state.edit_char_data = selected_rows[0]
                st.session_state.selected_char_id = selected_rows[0]["id"]
                st.rerun()
            elif len(selected_rows) == 0:
                st.toast("⚠️ 请先勾选一个进行修改！", icon="⚠️")
            else:
                st.toast("⚠️ 一次只能修改一个！", icon="⚠️")
        
        # 3. 删除 (Delete)
        if del_clicked:
            if len(selected_rows) > 0:
                count = 0
                for row in selected_rows:
                    try:
                        requests.delete(f"{API_URL}/characters/{row['id']}")
                        count += 1
                    except:
                        pass
                st.toast(f"✅ 成功删除 {count} 条记录", icon="✅")
                st.rerun()
            else:
                st.toast("⚠️ 请先勾选要删除的！", icon="⚠️")

    # --- Historical Versions & Timeline (Below Table) ---
    # if not st.session_state.char_dialog_mode and len(selected_rows) == 1:
    #     # Show details for the single selected row at the bottom
    #     sel_char = selected_rows[0]
    #     st.divider()
    #     st.markdown(f"### 📜 {sel_char['name']} 的详细档案")
        
    #     c_detail1, c_detail2 = st.columns(2)
    #     with c_detail1:
    #         st.markdown("#### 📅 人物弧光 (Character Arc)")
    #         try:
    #             timeline_res = requests.get(f"{API_URL}/characters/{sel_char['id']}/timeline")
    #             if timeline_res.status_code == 200:
    #                 events = timeline_res.json()
    #                 if events:
    #                     # Sort by date descending
    #                     events.sort(key=lambda x: x.get("event_date", ""), reverse=True)
                        
    #                     for event in events:
    #                         date_str = event.get("event_date", "")[:10]
    #                         summary = event.get("summary", "无标题事件")
                            
    #                         with st.container(border=True):
    #                             st.markdown(f"**{date_str}** | {summary}")
    #                             desc = event.get("description", "")
    #                             if desc:
    #                                 st.caption(desc)
    #                 else:
    #                     st.info("无时间线记录")
    #         except:
    #             st.error("加载失败")
                
    #     with c_detail2:
    #         st.markdown("#### 📜 历史版本对比 (Version Contrast)")
    #         try:
    #             # Fetch full current details for comparison
    #             cur_res = requests.get(f"{API_URL}/characters/{sel_char['id']}")
    #             current_data = cur_res.json() if cur_res.status_code == 200 else sel_char
    #             current_dyn = current_data.get("dynamic_profile", {})

    #             v_res = requests.get(f"{API_URL}/characters/{sel_char['id']}/versions")
    #             if v_res.status_code == 200:
    #                 versions = v_res.json()
    #                 if versions:
    #                     # Sort versions descending
    #                     versions = sorted(versions, key=lambda x: x['version'], reverse=True)
                        
    #                     # Selectbox for version
    #                     v_options = [f"v{v['version']} - {str(v['created_at'])[:16]}" for v in versions]
    #                     selected_v_str = st.selectbox("选择历史版本进行对比", options=v_options, key="history_version_select")
                        
    #                     # Find selected version data
    #                     selected_v_idx = v_options.index(selected_v_str)
    #                     selected_v_data = versions[selected_v_idx]
    #                     hist_snap = selected_v_data.get('dynamic_profile_snapshot', {})
    #                     hist_attrs = selected_v_data.get('attributes_snapshot', {}) # Assuming snapshot stores these?
    #                     # Note: Server might not be snapshotting attributes/traits yet. 
    #                     # If not, we can only compare dynamic_profile. 
    #                     # Let's check domain_schemas.py or similar to see what's in snapshot.
    #                     # Actually, looking at CharacterResponse, it doesn't explicitly show snapshot structure.
    #                     # But typically snapshots might be just dynamic_profile.
    #                     # If the server only snapshots dynamic_profile, we can only compare that.
    #                     # However, let's assume we want to be robust.
                        
    #                     # --- Contrast View ---
    #                     st.caption(f"🆚 正在对比: {selected_v_str} (左) vs 当前最新版 (右)")
                        
    #                     def render_diff_row(label, val_old, val_new):
    #                         if val_old or val_new:
    #                             with st.expander(label, expanded=False):
    #                                 c1, c2 = st.columns(2)
    #                                 with c1:
    #                                     st.markdown("**🏛️ 历史版本**")
    #                                     if val_old: st.write(val_old)
    #                                     else: st.caption("空")
    #                                 with c2:
    #                                     st.markdown("**🆕 当前版本**")
    #                                     if val_new: st.write(val_new)
    #                                     else: st.caption("空")
                        
    #                     # 1. Attributes (Dimension 1)
    #                     # Historical attributes might not be available if not snapshotted.
    #                     # If hist_snap contains everything, great. If not, we skip.
    #                     # For now, let's stick to dynamic_profile as it's the main focus of "Long Conversation Analysis" updates.
    #                     # But wait, we updated attributes and traits too. 
    #                     # If the backend doesn't version attributes/traits, we can't show history for them.
    #                     # Let's check standard behavior. Usually `dynamic_profile` is the unstructured JSON that gets versioned.
    #                     # `attributes` and `traits` are separate fields.
                        
    #                     # Let's just improve the dynamic profile comparison for now to cover all dynamic fields we know of.
                        
    #                     st.markdown("##### 🧬 核心维度对比")
    #                     render_diff_row("🗣️ 沟通模式 (Communication)", hist_snap.get("communication_style"), current_dyn.get("communication_style"))
    #                     render_diff_row("🎭 行为习惯 (Habits)", hist_snap.get("behavior_habits"), current_dyn.get("behavior_habits"))
    #                     render_diff_row("🌊 情绪基线 (Emotional Baseline)", hist_snap.get("emotional_baseline"), current_dyn.get("emotional_baseline"))
    #                     render_diff_row("⚖️ 决策风格 (Decision Style)", hist_snap.get("decision_style"), current_dyn.get("decision_style"))
    #                     render_diff_row("🧠 思维模式 (Thinking Mode)", hist_snap.get("thinking_mode"), current_dyn.get("thinking_mode"))
    #                     render_diff_row("🚀 核心驱动力 (Drivers)", hist_snap.get("core_drivers"), current_dyn.get("core_drivers"))
    #                     render_diff_row("❤️ 深层需求 (Needs)", hist_snap.get("inferred_core_needs"), current_dyn.get("inferred_core_needs"))
                        
    #                     # Add new fields from 6 dimensions
    #                     render_diff_row("🤝 社交风格 (Social Style)", hist_snap.get("social_style"), current_dyn.get("social_style"))
    #                     render_diff_row("💥 情绪触发点 (Triggers)", hist_snap.get("emotional_triggers"), current_dyn.get("emotional_triggers"))
    #                     render_diff_row("📤 情绪表达 (Expression)", hist_snap.get("emotional_expression"), current_dyn.get("emotional_expression"))
    #                     render_diff_row("🧘 情绪调节 (Regulation)", hist_snap.get("emotional_regulation"), current_dyn.get("emotional_regulation"))
    #                     render_diff_row("📏 判断标准 (Judgment)", hist_snap.get("judgment_criteria"), current_dyn.get("judgment_criteria"))
    #                     render_diff_row("📥 信息处理 (Info Processing)", hist_snap.get("info_processing"), current_dyn.get("info_processing"))
    #                     render_diff_row("🔋 动机来源 (Motivation)", hist_snap.get("motivation_source"), current_dyn.get("motivation_source"))
    #                     render_diff_row("🛡️ 行为底线 (Bottom Line)", hist_snap.get("behavior_bottom_line"), current_dyn.get("behavior_bottom_line"))

    #                     st.divider()
    #                     with st.expander("🔍 查看完整历史快照 JSON"):
    #                         st.json(hist_snap)
    #                 else:
    #                     st.info("无历史版本")
    #         except Exception as e:
    #             st.error(f"加载历史版本出错: {e}")

    #     # --- 3. Structured Dynamic Profile (Full View) ---
    #     st.divider()
    #     st.markdown("### 🧬 当前版本完整结构化画像 (Current Full Profile)")
        
    #     # Reuse current_data and current_dyn from above if available, else use sel_char
    #     if 'current_data' not in locals():
    #         current_data = sel_char
    #         current_dyn = current_data.get("dynamic_profile", {})
        
    #     # Helper to safely get nested values
    #     def get_val_t2(data, key, default="待补充"):
    #         val = data.get(key)
    #         if val:
    #             if isinstance(val, (dict, list)): return val
    #             return val
    #         return default

    #     # Use Tabs for better structure
    #     tabs = st.tabs([
    #         "1️⃣ 基础属性", "2️⃣ 表层行为", "3️⃣ 情绪特征", 
    #         "4️⃣ 认知决策", "5️⃣ 人格特质", "6️⃣ 核心本质"
    #     ])

    #     # Layer 1: Basic Attributes
    #     with tabs[0]:
    #         st.caption("维度1：基础属性层 (Basic Attributes)")
    #         attrs = current_data.get("attributes", {})
    #         c1, c2, c3 = st.columns(3)
    #         with c1:
    #             st.markdown("**🏷️ 身份标签**")
    #             st.write(get_val_t2(attrs, "identity_tags"))
    #         with c2:
    #             st.markdown("**🌱 成长经历**")
    #             st.write(get_val_t2(attrs, "growth_experiences"))
    #         with c3:
    #             st.markdown("**🚧 客观边界**")
    #             st.write(get_val_t2(attrs, "objective_boundaries"))

    #     # Layer 2: Surface Behavior
    #     with tabs[1]:
    #         st.caption("维度2：表层行为层 (Surface Behavior)")
    #         c1, c2, c3 = st.columns(3)
    #         with c1:
    #             st.markdown("**🗣️ 沟通模式**")
    #             st.write(get_val_t2(current_dyn, "communication_style"))
    #         with c2:
    #             st.markdown("**🎭 行为习惯**")
    #             st.write(get_val_t2(current_dyn, "behavior_habits"))
    #         with c3:
    #             st.markdown("**🤝 社交风格**")
    #             st.write(get_val_t2(current_dyn, "social_style"))

    #     # Layer 3: Emotional Traits
    #     with tabs[2]:
    #         st.caption("维度3：情绪特征层 (Emotional Traits)")
    #         c1, c2 = st.columns(2)
    #         with c1:
    #             st.markdown("**🌊 情绪基线**")
    #             st.info(get_val_t2(current_dyn, "emotional_baseline"))
    #             st.markdown("**💥 情绪触发点**")
    #             st.write(get_val_t2(current_dyn, "emotional_triggers"))
    #         with c2:
    #             st.markdown("**📤 情绪表达**")
    #             st.write(get_val_t2(current_dyn, "emotional_expression"))
    #             st.markdown("**🧘 情绪调节**")
    #             st.write(get_val_t2(current_dyn, "emotional_regulation"))

    #     # Layer 4: Cognitive Decision
    #     with tabs[3]:
    #         st.caption("维度4：认知决策层 (Cognitive Decision)")
    #         traits_dict = current_data.get("traits", {})
    #         # Try dynamic first, then traits (legacy fallback)
    #         dec_style = current_dyn.get("decision_style") or traits_dict.get("decision_style")
    #         thk_mode = current_dyn.get("thinking_mode") or traits_dict.get("thinking_mode")
            
    #         c1, c2 = st.columns(2)
    #         with c1:
    #             st.markdown("**⚖️ 决策风格**")
    #             st.write(dec_style or "待补充")
    #             st.markdown("**🧠 思维模式**")
    #             st.write(thk_mode or "待补充")
    #         with c2:
    #             st.markdown("**📏 判断标准**")
    #             st.write(get_val_t2(current_dyn, "judgment_criteria"))
    #             st.markdown("**📥 信息处理**")
    #             st.write(get_val_t2(current_dyn, "info_processing"))

    #     # Layer 5: Personality Traits
    #     with tabs[4]:
    #         st.caption("维度5：人格特质层 (Personality Traits)")
    #         traits = current_data.get("traits", {})
    #         c1, c2 = st.columns(2)
    #         with c1:
    #             st.markdown("**🧩 核心性格**")
    #             st.write(get_val_t2(traits, "core_personality"))
    #             st.markdown("**🧭 特质倾向**")
    #             st.write(get_val_t2(traits, "trait_tendency"))
    #         with c2:
    #             st.markdown("**🌏 三观底色**")
    #             st.write(get_val_t2(traits, "three_views"))
    #             st.markdown("**🔄 行为一致性**")
    #             st.write(get_val_t2(traits, "consistency"))

    #     # Layer 6: Core Essence
    #     with tabs[5]:
    #         st.caption("维度6：核心本质层 (Core Essence)")
    #         c1, c2 = st.columns(2)
    #         with c1:
    #             st.markdown("**🚀 核心驱动力**")
    #             drivers = current_dyn.get("core_drivers", [])
    #             if drivers:
    #                 for d in drivers: st.markdown(f"- {d}")
    #             else: st.caption("待挖掘")
                
    #             st.markdown("**🔋 动机来源**")
    #             st.write(get_val_t2(current_dyn, "motivation_source"))
                
    #         with c2:
    #             st.markdown("**❤️ 深层需求**")
    #             needs = current_dyn.get("inferred_core_needs", [])
    #             if needs:
    #                 for n in needs: st.markdown(f"- {n}")
    #             else: st.caption("待挖掘")
                
    #             st.markdown("**🛡️ 行为底线**")
    #             st.write(get_val_t2(current_dyn, "behavior_bottom_line"))

# ==========================================
# Tab 3: 关系管理 (Relationship Management)
# ==========================================
with tab3:
    # --- 1. 初始化与数据获取 (Init & Fetch) ---
    if "edit_rel_data" not in st.session_state:
        st.session_state.edit_rel_data = None

    chars = []
    relationships = []
    try:
        # 获取角色列表 (Fetch Characters)
        c_res = requests.get(f"{API_URL}/characters/")
        if c_res.status_code == 200:
            chars = c_res.json()
            
        # 获取关系列表 (Fetch Relationships)
        r_res = requests.get(f"{API_URL}/characters/relationships/all")
        if r_res.status_code == 200:
            relationships = r_res.json()
    except:
        pass
        
    char_map = {c["id"]: c["name"] for c in chars}
    char_options = {c["name"]: c["id"] for c in chars}
    
    # Load from config
    from app.core.config import settings
    COMMON_RELATIONS = settings.PROMPTS.get("ui", {}).get("common_relations", [])
    if not COMMON_RELATIONS:
        COMMON_RELATIONS = [
            "朋友", "敌人", "同事", "家人", "恋人", 
            "陌生人", "主仆", "对手", "师徒", "盟友",
            "邻居", "亲戚", "同学", "伴侣", "仇人",
            "上下级", "债权人-债务人", "偶像-粉丝", "守护者-被守护者", "暧昧"
        ]

    # --- 2. 页面布局 (Layout) ---
    # 左: 影响力地图 (Map) | 中: 编辑表单 (Edit) | 右: 关系列表 (List)
    c_map, c_edit, c_list = st.columns([5, 4, 3])
    
    # ==========================================
    # 3.1 影响力地图可视化 (Influence Map)
    # ==========================================
    with c_map:
        st.subheader("🕸️ 影响力地图")
        if chars and relationships:
            # 准备 Vis.js 数据 (Prepare Vis.js Data)
            vis_nodes = []
            vis_edges = []
            
            # 计算节点度数以调整大小 (Calculate Degree for Size)
            degree_map = {}
            for r in relationships:
                s = r["source_id"]
                t = r["target_id"]
                degree_map[s] = degree_map.get(s, 0) + 1
                degree_map[t] = degree_map.get(t, 0) + 1

            for c in chars:
                c_id = c["id"]
                # 基础大小 20, 每个连接 +5 (Base size 20, +5 per link)
                size = 20 + (degree_map.get(c_id, 0) * 5)
                
                attrs = c.get("attributes") or {}
                role = attrs.get("role", "Default")
                
                vis_nodes.append({
                    "id": c_id,
                    "label": c["name"],
                    "title": f"Role: {role}",
                    "value": size,
                    "group": role
                })

            for r in relationships:
                # 情感倾向映射颜色 (Sentiment -> Color)
                sentiment = r.get("sentiment", 0)
                if sentiment > 0:
                    color = "#4caf50" # Green (Positive)
                elif sentiment < 0:
                    color = "#f44336" # Red (Negative)
                else:
                    color = "#9e9e9e" # Grey (Neutral)

                # 强度映射宽度 (Strength -> Width)
                strength = r.get("strength", 5)
                width = max(1, strength / 2)

                vis_edges.append({
                    "from": r["source_id"],
                    "to": r["target_id"],
                    "label": r["relation_type"],
                    "title": f"Strength: {strength}, Sentiment: {sentiment}",
                    "width": width,
                    "color": {"color": color},
                    "arrows": "to"
                })

            # HTML/JS 代码集成 (HTML/JS Integration)
            # 包含全屏功能 (Includes Fullscreen Support)
            html_code = f"""
            <!DOCTYPE html>
            <html>
            <head>
              <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
              <style type="text/css">
                body {{ margin: 0; padding: 0; }}
                #container_wrapper {{
                    position: relative;
                    width: 100%;
                    height: 400px;
                    border: 1px solid #eee;
                    background-color: #fafafa;
                    border-radius: 8px;
                }}
                #mynetwork {{
                    width: 100%;
                    height: 100%;
                }}
                .fs-btn {{
                    position: absolute;
                    top: 10px;
                    right: 10px;
                    z-index: 1000;
                    padding: 5px 10px;
                    background: rgba(255, 255, 255, 0.8);
                    border: 1px solid #ccc;
                    border-radius: 4px;
                    cursor: pointer;
                    font-family: sans-serif;
                    font-size: 12px;
                }}
                .fs-btn:hover {{ background: #fff; }}
              </style>
            </head>
            <body>
              <div id="container_wrapper">
                  <div id="mynetwork"></div>
                  <button id="btn_fs" class="fs-btn" onclick="toggleFullScreen()">⛶ 全屏查看</button>
                  <button id="btn_exit" class="fs-btn" onclick="exitFullScreen()" style="display: none;">❌ 退出全屏</button>
              </div>
              
              <script type="text/javascript">
                var nodes = new vis.DataSet({json.dumps(vis_nodes)});
                var edges = new vis.DataSet({json.dumps(vis_edges)});
                var container = document.getElementById('mynetwork');
                var data = {{ nodes: nodes, edges: edges }};
                var options = {{
                  nodes: {{
                    shape: 'dot',
                    font: {{ size: 16 }}
                  }},
                  edges: {{
                    smooth: {{ type: 'dynamic' }}
                  }},
                  physics: {{
                    stabilization: false,
                    barnesHut: {{
                      gravitationalConstant: -3000,
                      springLength: 200
                    }}
                  }}
                }};
                var network = new vis.Network(container, data, options);
                
                function toggleFullScreen() {{
                    var elem = document.getElementById('container_wrapper');
                    if (elem.requestFullscreen) {{
                        elem.requestFullscreen();
                    }} else if (elem.webkitRequestFullscreen) {{ /* Safari */
                        elem.webkitRequestFullscreen();
                    }} else if (elem.msRequestFullscreen) {{ /* IE11 */
                        elem.msRequestFullscreen();
                    }}
                }}
                
                function exitFullScreen() {{
                    if (document.exitFullscreen) {{
                        document.exitFullscreen();
                    }} else if (document.webkitExitFullscreen) {{
                        document.webkitExitFullscreen();
                    }} else if (document.msExitFullscreen) {{
                        document.msExitFullscreen();
                    }}
                }}
                
                document.addEventListener('fullscreenchange', (event) => {{
                    var elem = document.getElementById('container_wrapper');
                    var btnFs = document.getElementById('btn_fs');
                    var btnExit = document.getElementById('btn_exit');
                    
                    if (document.fullscreenElement) {{
                        btnFs.style.display = 'none';
                        btnExit.style.display = 'block';
                        elem.style.height = '100vh';
                        elem.style.borderRadius = '0';
                        elem.style.border = 'none';
                    }} else {{
                        btnFs.style.display = 'block';
                        btnExit.style.display = 'none';
                        elem.style.height = '400px';
                        elem.style.borderRadius = '8px';
                        elem.style.border = '1px solid #eee';
                    }}
                }});
              </script>
            </body>
            </html>
            """
            
            components.html(html_code, height=420)
        else:
            st.info("暂无数据以展示地图。")

    # ==========================================
    # 3.2 编辑表单 (Add/Edit Form)
    # ==========================================
    with c_edit:
        rel_data = st.session_state.get("edit_rel_data")
        is_edit = rel_data is not None
        
        form_title = "🛠️ 编辑关系" if is_edit else "🛠️ 新增关系"
        st.subheader(form_title)
        
        if is_edit:
            s_name_default = char_map.get(rel_data["source_id"])
            t_name_default = char_map.get(rel_data["target_id"])
            st.info(f"正在编辑 ID: {rel_data['id']}")
        else:
            s_name_default = None
            t_name_default = None

        with st.form("rel_form"):
            st.caption("关系定义")
            
            s_col, t_col = st.columns(2)
            with s_col:
                s_index = list(char_options.keys()).index(s_name_default) if s_name_default in char_options else 0
                source_name = st.selectbox("源角色 (Source)", options=list(char_options.keys()), index=s_index, key="rel_source")
            with t_col:
                t_index = list(char_options.keys()).index(t_name_default) if t_name_default in char_options else 0
                target_name = st.selectbox("目标角色 (Target)", options=list(char_options.keys()), index=t_index, key="rel_target")
                
            # 关系类型 (Relationship Type)
            default_rel = COMMON_RELATIONS[0] if COMMON_RELATIONS else "Friend"
            current_type = rel_data.get("relation_type", default_rel) if is_edit else default_rel
            type_index = COMMON_RELATIONS.index(current_type) if current_type in COMMON_RELATIONS else 0
            
            rel_type = st.selectbox("关系类型", options=COMMON_RELATIONS + ["Other"], index=type_index)
            if rel_type == "Other":
                custom_val = current_type if is_edit and current_type not in COMMON_RELATIONS else ""
                rel_type = st.text_input("输入自定义关系类型", value=custom_val)
            
            # 强度与情感 (Strength & Sentiment)
            c_str, c_sent = st.columns(2)
            with c_str:
                curr_strength = rel_data.get("strength", 5) if is_edit else 5
                strength = st.slider("关系强度", 1, 10, value=curr_strength, help="1=弱关系, 10=强绑定")
            with c_sent:
                curr_sentiment = rel_data.get("sentiment", 0) if is_edit else 0
                sentiment = st.slider("情感倾向", -5, 5, value=curr_sentiment, help="-5=敌对, 0=中立, +5=亲密")

            details_val = json.dumps(rel_data.get("details", {}), ensure_ascii=False) if is_edit else "{}"
            details = st.text_area("备注 (JSON)", value=details_val, height=68)
            
            submitted = st.form_submit_button("💾 保存" if not is_edit else "💾 更新", use_container_width=True)
            
            if submitted:
                s_id = char_options.get(source_name)
                t_id = char_options.get(target_name)
                
                if s_id and t_id and s_id == t_id:
                    st.error("源角色和目标角色不能相同！")
                elif s_id and t_id:
                    try:
                        payload = {
                            "source_id": s_id,
                            "target_id": t_id,
                            "relation_type": rel_type,
                            "details": json.loads(details),
                            "strength": strength,
                            "sentiment": sentiment
                        }
                        
                        if is_edit:
                            res = requests.put(f"{API_URL}/characters/relationships/{rel_data['id']}", json=payload)
                        else:
                            res = requests.post(f"{API_URL}/characters/relationships", json=payload)
                            
                        if res.status_code == 200:
                            st.success("成功！")
                            st.session_state.edit_rel_data = None
                            st.rerun()
                        else:
                            st.error(f"失败: {res.text}")
                    except Exception as e:
                        st.error(f"错误: {e}")

        if is_edit:
            if st.button("❌ 取消编辑", key="cancel_rel_edit", use_container_width=True):
                st.session_state.edit_rel_data = None
                st.rerun()

    # ==========================================
    # 3.3 关系列表 (Relationship List)
    # ==========================================
    with c_list:
        st.subheader("📋 关系列表")
        if relationships:
            for rel in relationships:
                with st.container(border=True):
                    c1, c2 = st.columns([4, 1])
                    s_name = char_map.get(rel["source_id"], f"ID:{rel['source_id']}")
                    t_name = char_map.get(rel["target_id"], f"ID:{rel['target_id']}")
                    
                    c1.markdown(f"**{s_name}** ↔️ **{t_name}**")
                    c1.caption(f"{rel['relation_type']} | 强度: {rel.get('strength', 5)} | 情感: {rel.get('sentiment', 0)}")
                    
                    if c2.button("✏️", key=f"edit_rel_{rel['id']}"):
                        st.session_state.edit_rel_data = rel
                        st.rerun()
                    if c2.button("🗑️", key=f"del_rel_{rel['id']}"):
                         requests.delete(f"{API_URL}/characters/relationships/{rel['id']}")
                         st.rerun()
        else:
            st.info("暂无关系数据。")

# ==========================================
# Tab 6: 长对话深度分析与归档 (Long Conversation Analysis)
# [功能开发中 / Disabled for Future Release]
# ==========================================
# with tab6:
    # st.header("📜 长对话深度分析与归档")
    # st.markdown("---")
    
    # # Character Selection
    # st.subheader("角色选择 (Select Characters)")
    # # Reuse chars from tab3 if available, or fetch
    # char_options_lc = {c["name"]: c for c in chars} if 'chars' in locals() and chars else {}
    # if not char_options_lc:
    #     try:
    #         res = requests.get(f"{API_URL}/characters/")
    #         if res.status_code == 200:
    #             char_options_lc = {c["name"]: c for c in res.json()}
    #     except:
    #         pass
            
    # # Auto-select from session state if available
    # default_lc_chars = []
    # current_char_id = st.session_state.get("current_character_id")
    # if current_char_id:
    #     for name, c_obj in char_options_lc.items():
    #         if c_obj["id"] == current_char_id:
    #             default_lc_chars.append(name)
    #             break
    
    # selected_char_names = st.multiselect(
    #     "选择文本中包含的角色 (默认选中当前会话角色)",
    #     options=list(char_options_lc.keys()),
    #     default=default_lc_chars,
    #     key="lc_char_select"
    # )

    # # Text Input
    # st.subheader("📝 输入长对话内容")
    # st.caption("支持粘贴大段对话记录、小说片段或工作日志。系统将自动区分角色并分析重点。")
    # lc_text_input = st.text_area("在此粘贴内容...", height=300, key="lc_text_input")

    # if st.button("开始分析 (Start Analysis)", type="primary", key="lc_start_btn"):
    #     if not lc_text_input:
    #         st.warning("请先输入内容。")
    #     else:
    #         with st.spinner("正在分析中 (Analyzing)..."):
    #             try:
    #                 payload = {
    #                     "text": lc_text_input,
    #                     "character_names": selected_char_names
    #                 }
    #                 res = requests.post(f"{API_URL}/analysis/conversation", json=payload)
                    
    #                 if res.status_code == 200:
    #                     st.session_state.lc_analysis_result = res.json()
    #                     st.success("分析完成！")
    #                 else:
    #                     st.error(f"分析失败: {res.text}")
    #             except Exception as e:
    #                 st.error(f"请求异常: {e}")

    # # Display Results
    # if "lc_analysis_result" in st.session_state:
    #     result = st.session_state.lc_analysis_result
        
    #     # Markdown Report
    #     if "markdown_report" in result:
    #         st.markdown("### 🧠 深度思考报告")
    #         st.markdown(result["markdown_report"])
    #         st.markdown("---")
    #         structured_data = result.get("structured_data", {})
    #         char_analysis_list = structured_data.get("character_analysis", [])
    #         overall_summary = structured_data.get("summary", "")
    #     else:
    #         # Fallback
    #         structured_data = result
    #         char_analysis_list = result.get("analysis", [])
    #         overall_summary = result.get("overall_analysis", {}).get("summary", "")

    #     # Archiving
    #     if char_analysis_list:
    #         st.subheader("👤 角色深度画像归档")
    #         for i, item in enumerate(char_analysis_list):
    #             char_name = item.get("name", item.get("character_name", "Unknown"))
    #             deep_intent = item.get("deep_intent", "未检测到")
    #             strategies = item.get("strategy", [])
    #             if isinstance(strategies, list): strategies = ", ".join(strategies)
    #             mood = item.get("mood", [])
    #             if isinstance(mood, list): mood = ", ".join(mood)
                
    #             profile_update = item.get("profile_update", {})

    #             with st.expander(f"🎭 {char_name} 归档面板", expanded=False):
    #                 c1, c2 = st.columns(2)
    #                 c1.markdown(f"**🎯 意图**: {deep_intent}")
    #                 c1.markdown(f"**♟️ 策略**: {strategies}")
    #                 c2.markdown(f"**😊 情绪**: {mood}")
                    
    #                 # Six Dimensions Display
    #                 if profile_update:
    #                     st.divider()
    #                     st.markdown("#### 🧬 深度画像归档 (Deep Profile Archiving)")
    #                     st.caption("以下是从对话中提取的六维深度数据，点击归档将同步至人物档案。")
                        
    #                     # 6 Dimensions Tabs
    #                     tab_names = [
    #                         "1️⃣ 基础属性", "2️⃣ 表层行为", "3️⃣ 情绪特征", 
    #                         "4️⃣ 认知决策", "5️⃣ 人格特质", "6️⃣ 核心本质"
    #                     ]
    #                     tabs = st.tabs(tab_names)
                        
    #                     # Helper to display dimension data
    #                     def display_dim(tab, key, label):
    #                         with tab:
    #                             data_obj = profile_update.get(key, {})
    #                             desc = data_obj.get("desc", f"{label}更新")
    #                             content = data_obj.get("data", {})
                                
    #                             st.markdown(f"**{desc}**")
    #                             if content:
    #                                 st.json(content)
    #                             else:
    #                                 st.info("本轮对话未提取到相关新信息。")
    #                             return content

    #                     d1_data = display_dim(tabs[0], "basic_attributes", "基础属性")
    #                     d2_data = display_dim(tabs[1], "surface_behavior", "表层行为")
    #                     d3_data = display_dim(tabs[2], "emotional_traits", "情绪特征")
    #                     d4_data = display_dim(tabs[3], "cognitive_decision", "认知决策")
    #                     d5_data = display_dim(tabs[4], "personality_traits", "人格特质")
    #                     d6_data = display_dim(tabs[5], "core_essence", "核心本质")

    #                 # Archiving Button
    #                 char_obj = char_options_lc.get(char_name)
    #                 st.markdown("---")
    #                 if char_obj:
    #                     if st.button(f"📥 归档到 {char_name}", key=f"lc_archive_{i}"):
    #                         # 1. Prepare Base Data
    #                         current_dyn = char_obj.get("dynamic_profile", {}) or {}
    #                         current_attrs = char_obj.get("attributes", {}) or {}
    #                         current_traits = char_obj.get("traits", {}) or {}
                            
    #                         # 2. Merge Updates
    #                         if profile_update and d1_data: current_attrs.update(d1_data)
    #                         if profile_update and d2_data:
    #                             if d2_data.get("communication_style"): current_dyn["communication_style"] = d2_data["communication_style"]
    #                             if d2_data.get("behavior_habits"): current_dyn["behavior_habits"] = d2_data["behavior_habits"]
    #                             for k, v in d2_data.items():
    #                                 if k not in ["communication_style", "behavior_habits"]: current_dyn[k] = v
    #                         if profile_update and d3_data:
    #                             if d3_data.get("emotional_baseline"): current_dyn["emotional_baseline"] = d3_data["emotional_baseline"]
    #                         if profile_update and d4_data:
    #                             if d4_data.get("decision_style"): current_dyn["decision_style"] = d4_data["decision_style"]
    #                             if d4_data.get("thinking_mode"): current_dyn["thinking_mode"] = d4_data["thinking_mode"]
    #                         if profile_update and d5_data: current_traits.update(d5_data)
    #                         if profile_update and d6_data:
    #                             if d6_data.get("core_drivers"): 
    #                                 exist_drivers = set(current_dyn.get("core_drivers", []))
    #                                 new_drivers = d6_data["core_drivers"]
    #                                 if isinstance(new_drivers, list):
    #                                     exist_drivers.update(new_drivers)
    #                                     current_dyn["core_drivers"] = list(exist_drivers)
    #                             if d6_data.get("inferred_core_needs"):
    #                                 exist_needs = set(current_dyn.get("inferred_core_needs", []))
    #                                 new_needs = d6_data["inferred_core_needs"]
    #                                 if isinstance(new_needs, list):
    #                                     exist_needs.update(new_needs)
    #                                     current_dyn["inferred_core_needs"] = list(exist_needs)

    #                         # 3. Add Timeline Events (Character Arc - Deeds)
    #                         character_deeds = profile_update.get("character_deeds", [])
                            
    #                         # If no structured deeds, try legacy summary
    #                         if not character_deeds:
    #                             timeline_summary = profile_update.get("timeline_summary")
    #                             if not timeline_summary:
    #                                 timeline_summary = overall_summary[:50] + "..." if overall_summary else "对话分析归档"
    #                             character_deeds = [{"event": timeline_summary, "timestamp": datetime.now().strftime("%Y-%m-%d")}]

    #                         count_events = 0
    #                         for deed in character_deeds:
    #                             evt_content = deed.get("event")
    #                             evt_time = deed.get("timestamp") or datetime.now().strftime("%Y-%m-%d")
                                
    #                             event_payload = {
    #                                 "summary": f"[{evt_time}] {evt_content}",
    #                                 "intent": deep_intent,
    #                                 "strategy": strategies,
    #                                 "session_id": "manual_analysis"
    #                             }
    #                             try:
    #                                 requests.post(f"{API_URL}/characters/{char_obj['id']}/events", json=event_payload)
    #                                 count_events += 1
    #                             except Exception as e:
    #                                 st.warning(f"时间线添加失败: {e}")
                            
    #                         if count_events > 0:
    #                             st.toast(f"✅ 已添加 {count_events} 条人物事迹到弧光！")
                            
    #                         try:
    #                             update_payload = {
    #                                 "attributes": current_attrs,
    #                                 "traits": current_traits,
    #                                 "dynamic_profile": current_dyn,
    #                                 "version_note": "Long Conversation Analysis (Six Dimensions)"
    #                             }
    #                             up_res = requests.put(f"{API_URL}/characters/{char_obj['id']}", json=update_payload)
    #                             if up_res.status_code == 200:
    #                                 st.success(f"已更新 {char_name}")
    #                                 st.rerun() # Refresh immediately
    #                             else:
    #                                 st.error("更新失败")
    #                         except:
    #                             st.error("请求失败")

# --- Tab 7: Character Metrics ---
with tab7:
    st.header("📈 人物指标与数据可视化 (Character Metrics)")
    
    # 1. Prepare Char Map (Name -> ID)
    char_map_metrics = {}
    if 'char_options' in locals() and char_options:
        char_map_metrics = char_options
    else:
        try:
            res = requests.get(f"{API_URL}/characters/")
            if res.status_code == 200:
                for c in res.json():
                    char_map_metrics[c["name"]] = c["id"]
        except:
            pass

    # 2. Selector
    selected_char_name = st.selectbox("选择查看的角色", options=list(char_map_metrics.keys()), key="metric_char_select")
    
    if selected_char_name:
        selected_char_id = char_map_metrics[selected_char_name]
        
        # 3. Fetch Real Data
        char_detail = {}
        timeline_events = []
        
        # A. Fetch Detail
        try:
            res_d = requests.get(f"{API_URL}/characters/{selected_char_id}")
            if res_d.status_code == 200:
                char_detail = res_d.json()
        except Exception as e:
            st.error(f"无法获取角色详情: {e}")
            
        # B. Fetch Timeline
        try:
            res_t = requests.get(f"{API_URL}/characters/{selected_char_id}/timeline")
            if res_t.status_code == 200:
                timeline_events = res_t.json()
        except:
            pass
            
        # 4. Display "Suitable Indicators" (Real Data)
        st.subheader(f"📊 {selected_char_name} 的实时数据看板")
        
        # Calculate some metrics
        dyn = char_detail.get("dynamic_profile", {})
        
        # Metric 1: Timeline Events
        count_events = len(timeline_events)
        
        # Metric 2: Core Drivers Count
        drivers = dyn.get("core_drivers", [])
        count_drivers = len(drivers) if isinstance(drivers, list) else 0
        
        # Metric 3: Profile Completeness (Simple heuristic)
        fields = ["core_drivers", "inferred_core_needs", "behavior_habits", "emotional_baseline", "communication_style"]
        filled_fields = sum(1 for f in fields if dyn.get(f))
        completeness = int((filled_fields / len(fields)) * 100)

        # Fetch historical versions for contrast
        versions = []
        try:
            v_res = requests.get(f"{API_URL}/characters/{selected_char_id}/versions")
            if v_res.status_code == 200:
                versions = v_res.json()
        except:
            pass
        
        # Sort versions descending
        if versions:
            versions = sorted(versions, key=lambda x: x['version'], reverse=True)
        
        # Selectbox for version
        # Add "Current" as the first option
        v_options = ["当前版本 (Current)"] + [f"v{v['version']} - {str(v['created_at'])[:16]}" for v in versions]
        selected_v_str = st.selectbox("选择版本进行对比 (Select Version)", options=v_options, key="metric_hist_version_select")
        
        # Logic: Only show contrast if a historical version is selected
        if selected_v_str != "当前版本 (Current)":
            # Parse selected version
            # Format: "v{version} - {date}"
            # We can find it by index or parsing
            sel_idx = v_options.index(selected_v_str) - 1 # -1 because of "Current"
            selected_v_data = versions[sel_idx]
            
            hist_snap = selected_v_data.get('dynamic_profile_snapshot', {}) or {}
            
            st.caption(f"🆚 正在对比: {selected_v_str} (左) vs 当前最新版 (右)")
            
            def render_diff_row(label, val_old, val_new):
                if val_old or val_new:
                    # Use columns directly for compact view
                    c1, c2, c3 = st.columns([2, 4, 4])
                    c1.markdown(f"**{label}**")
                    with c2:
                        if val_old: st.caption(f"Old: {val_old}")
                        else: st.caption("Old: -")
                    with c3:
                        if val_new != val_old:
                            st.markdown(f"New: :green[{val_new}]")
                        else:
                            st.caption(f"New: {val_new}")
                    st.divider()

            # Render Contrast
            with st.container(border=True):
                st.markdown("#### 📜 历史版本差异 (Version Contrast)")
                
                # 1. Basic & Surface
                render_diff_row("沟通模式", hist_snap.get("communication_style"), dyn.get("communication_style"))
                render_diff_row("行为习惯", hist_snap.get("behavior_habits"), dyn.get("behavior_habits"))
                render_diff_row("社交风格", hist_snap.get("social_style"), dyn.get("social_style"))
                
                # 2. Emotional
                render_diff_row("情绪基线", hist_snap.get("emotional_baseline"), dyn.get("emotional_baseline"))
                render_diff_row("情绪触发点", hist_snap.get("emotional_triggers"), dyn.get("emotional_triggers"))
                
                # 3. Cognitive
                render_diff_row("决策风格", hist_snap.get("decision_style"), dyn.get("decision_style"))
                render_diff_row("思维模式", hist_snap.get("thinking_mode"), dyn.get("thinking_mode"))
                render_diff_row("判断标准", hist_snap.get("judgment_criteria"), dyn.get("judgment_criteria"))
                
                # 4. Core
                render_diff_row("核心驱动力", hist_snap.get("core_drivers"), dyn.get("core_drivers"))
                render_diff_row("深层需求", hist_snap.get("inferred_core_needs"), dyn.get("inferred_core_needs"))
                render_diff_row("行为底线", hist_snap.get("behavior_bottom_line"), dyn.get("behavior_bottom_line"))
                
        else:
            st.caption("👈 选择一个历史版本以查看差异对比")
                            
        # 5. Detailed Profile & Timeline Layout
        # Optimized Layout: Use Tabs for 6 Dimensions to save space
        st.divider()
        st.subheader("🧬 结构化动态档案 (Structured Dynamic Profile)")
        
        # Helper to safely get nested values
        def get_val(data, key, default="待补充"):
            val = data.get(key)
            if val:
                if isinstance(val, (dict, list)): return val
                return val
            return default

        # Use Tabs instead of vertical expanders
        p_tab1, p_tab2, p_tab3, p_tab4, p_tab5, p_tab6 = st.tabs([
            "1️⃣ 基础属性", "2️⃣ 表层行为", "3️⃣ 情绪特征", 
            "4️⃣ 认知决策", "5️⃣ 人格特质", "6️⃣ 核心本质"
        ])
        
        attrs = char_detail.get("attributes", {})
        traits = char_detail.get("traits", {})
        
        with p_tab1:
            c1, c2, c3 = st.columns(3)
            c1.markdown("**🏷️ 身份标签**"); c1.write(get_val(attrs, "identity_tags"))
            c2.markdown("**🌱 成长经历**"); c2.write(get_val(attrs, "growth_experiences"))
            c3.markdown("**🚧 客观边界**"); c3.write(get_val(attrs, "objective_boundaries"))
            
        with p_tab2:
            c1, c2, c3 = st.columns(3)
            c1.markdown("**🗣️ 沟通模式**"); c1.write(get_val(dyn, "communication_style"))
            c2.markdown("**🎭 行为习惯**"); c2.write(get_val(dyn, "behavior_habits"))
            c3.markdown("**🤝 社交风格**"); c3.write(get_val(dyn, "social_style"))
            
        with p_tab3:
            c1, c2, c3 = st.columns(3)
            c1.markdown("**🌊 情绪基线**"); c1.info(get_val(dyn, "emotional_baseline"))
            c2.markdown("**💥 情绪触发点**"); c2.write(get_val(dyn, "emotional_triggers"))
            c3.markdown("**📤 情绪表达**"); c3.write(get_val(dyn, "emotional_expression"))
            # Regulation in c1 or new line? Let's put regulation in c1 bottom
            # st.markdown("**🧘 情绪调节**"); st.write(get_val(dyn, "emotional_regulation"))
            
        with p_tab4:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**⚖️ 决策风格**"); st.write(get_val(dyn, "decision_style"))
                st.markdown("**🧠 思维模式**"); st.write(get_val(dyn, "thinking_mode"))
            with c2:
                st.markdown("**📏 判断标准**"); st.write(get_val(dyn, "judgment_criteria"))
                st.markdown("**📥 信息处理**"); st.write(get_val(dyn, "info_processing"))
                
        with p_tab5:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**🧩 核心性格**"); st.write(get_val(traits, "core_personality"))
                st.markdown("**🧭 特质倾向**"); st.write(get_val(traits, "trait_tendency"))
            with c2:
                st.markdown("**🌏 三观底色**"); st.write(get_val(traits, "three_views"))
                st.markdown("**🔄 行为一致性**"); st.write(get_val(traits, "consistency"))
                
        with p_tab6:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**🚀 核心驱动力**")
                drivers = dyn.get("core_drivers", [])
                if drivers:
                    for d in drivers: st.markdown(f"- {d}")
                else: st.caption("待挖掘")
                st.markdown("**🔋 动机来源**"); st.write(get_val(dyn, "motivation_source"))
                
            with c2:
                st.markdown("**❤️ 深层需求**")
                needs = dyn.get("inferred_core_needs", [])
                if needs:
                    for n in needs: st.markdown(f"- {n}")
                else: st.caption("待挖掘")
                st.markdown("**🛡️ 行为底线**"); st.write(get_val(dyn, "behavior_bottom_line"))
            
            # Pending Updates
            st.caption("📝 待更新信息：基于后续对话分析自动补充...")

        st.divider()
        st.markdown("### 📅 人物弧光 (Character Arc)")
        if timeline_events:
            # Sort by date descending
            timeline_events.sort(key=lambda x: x.get("event_date", ""), reverse=True)
            
            for event in timeline_events:
                date_str = event.get("event_date", "")[:10]
                summary = event.get("summary", "无标题事件")
                
                with st.container(border=True):
                    st.markdown(f"**{date_str}** | {summary}")
                    desc = event.get("description", "")
                    if desc:
                        st.caption(desc)
        else:
            st.info("暂无时间线记录。请在对话分析中生成或手动添加。")

    else:
        st.info("请先在左侧或上方选择一个角色以查看详细指标。")
