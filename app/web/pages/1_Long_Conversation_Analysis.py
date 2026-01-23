import streamlit as st
import requests
import json
from app.core.config import settings

API_URL = settings.API_URL

st.set_page_config(page_title="长对话分析", page_icon="📜", layout="wide")

st.title("📜 长对话深度分析与归档")
st.markdown("---")

# Sidebar: Character Selection
st.sidebar.header("已知角色 (Known Characters)")
characters = []
try:
    res = requests.get(f"{API_URL}/characters")
    if res.status_code == 200:
        characters = res.json()
except Exception as e:
    st.error(f"Failed to fetch characters: {e}")

# Multi-select for characters involved in the text
char_options = {c["name"]: c for c in characters}
selected_char_names = st.sidebar.multiselect(
    "选择文本中包含的角色 (Select Characters)",
    options=list(char_options.keys())
)

# Main Area: Text Input
st.subheader("📝 输入长对话内容 (Input Conversation)")
st.caption("支持粘贴大段对话记录、小说片段或工作日志。系统将自动区分角色并分析重点。")
text_input = st.text_area("在此粘贴内容...", height=300)

if st.button("开始分析 (Start Analysis)", type="primary"):
    if not text_input:
        st.warning("请先输入内容。")
    else:
        with st.spinner("正在分析中 (Analyzing)..."):
            try:
                payload = {
                    "text": text_input,
                    "character_names": selected_char_names
                }
                res = requests.post(f"{API_URL}/analysis/conversation", json=payload)
                
                if res.status_code == 200:
                    analysis_result = res.json()
                    st.session_state.analysis_result = analysis_result
                    st.success("分析完成！")
                else:
                    st.error(f"分析失败: {res.text}")
            except Exception as e:
                st.error(f"请求异常: {e}")

# Display Results
if "analysis_result" in st.session_state:
    result = st.session_state.analysis_result
    
    # ==========================================
    # 1. New Format: Deep Thinking Report (Markdown)
    # ==========================================
    if "markdown_report" in result:
        st.markdown("### 🧠 深度思考报告 (Deep Thinking Report)")
        st.markdown(result["markdown_report"])
        st.markdown("---")
        
        # Prepare structured data for archiving section
        structured_data = result.get("structured_data", {})
        char_analysis_list = structured_data.get("character_analysis", [])
        overall_summary = structured_data.get("summary", "")
        
    else:
        # Fallback: Old Format Support
        st.warning("⚠️ 收到旧格式数据或解析失败，尝试以兼容模式显示。")
        structured_data = result
        char_analysis_list = result.get("analysis", [])
        overall_summary = result.get("overall_analysis", {}).get("summary", "")

    # ==========================================
    # 2. Character Archiving (Structured Data)
    # ==========================================
    if char_analysis_list:
        st.subheader("👤 角色深度画像归档 (Character Archiving)")
        st.caption("以下数据已从思考报告中结构化提取，可用于更新角色档案。")

        for i, item in enumerate(char_analysis_list):
            # Compatible field mapping
            char_name = item.get("name", item.get("character_name", "Unknown"))
            deep_intent = item.get("deep_intent", "未检测到")
            strategies = item.get("strategy") or item.get("strategies", [])
            if isinstance(strategies, list): strategies = ", ".join(strategies)
            mood = item.get("mood") or item.get("emotions", [])
            if isinstance(mood, list): mood = ", ".join(mood)
            
            profile_update = item.get("profile_update", {})

            # Use index in expander key to avoid duplicate ID errors
            with st.expander(f"🎭 {char_name} 归档面板", expanded=False):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**🎯 意图**: {deep_intent}")
                    st.markdown(f"**♟️ 策略**: {strategies}")
                with col2:
                    st.markdown(f"**😊 情绪**: {mood}")
                
                # Six Dimensions Display
                if profile_update:
                    st.divider()
                    st.markdown("#### 🧬 深度画像归档 (Deep Profile Archiving)")
                    st.caption("以下是从对话中提取的六维深度数据，点击归档将同步至人物档案。")
                    
                    # 6 Dimensions Tabs
                    tab_names = [
                        "1️⃣ 基础属性", "2️⃣ 表层行为", "3️⃣ 情绪特征", 
                        "4️⃣ 认知决策", "5️⃣ 人格特质", "6️⃣ 核心本质"
                    ]
                    tabs = st.tabs(tab_names)
                    
                    # Helper to display dimension data
                    def display_dim(tab, key, label):
                        with tab:
                            data_obj = profile_update.get(key, {})
                            desc = data_obj.get("desc", f"{label}更新")
                            content = data_obj.get("data", {})
                            
                            st.markdown(f"**{desc}**")
                            if content:
                                st.json(content)
                            else:
                                st.info("本轮对话未提取到相关新信息。")
                            return content

                    d1_data = display_dim(tabs[0], "basic_attributes", "基础属性")
                    d2_data = display_dim(tabs[1], "surface_behavior", "表层行为")
                    d3_data = display_dim(tabs[2], "emotional_traits", "情绪特征")
                    d4_data = display_dim(tabs[3], "cognitive_decision", "认知决策")
                    d5_data = display_dim(tabs[4], "personality_traits", "人格特质")
                    d6_data = display_dim(tabs[5], "core_essence", "核心本质")

                # Archiving Action
                # Find the character ID if it exists in our DB
                char_obj = char_options.get(char_name)
                
                st.markdown("---")
                if char_obj:
                    btn_key = f"archive_btn_{char_obj['id']}_{i}"
                    if st.button(f"📥 归档到 {char_name}", key=btn_key):
                        # Logic to update character profile
                        # 1. Prepare Base Data
                        current_dyn = char_obj.get("dynamic_profile", {}) or {}
                        current_attrs = char_obj.get("attributes", {}) or {}
                        current_traits = char_obj.get("traits", {}) or {}
                        
                        # 2. Merge Updates (Strategy: Update if exists in extraction)
                        # D1: Basic -> Attributes
                        if profile_update and d1_data:
                            current_attrs.update(d1_data)
                            
                        # D2: Surface -> Dynamic
                        if profile_update and d2_data:
                            if d2_data.get("communication_style"): current_dyn["communication_style"] = d2_data["communication_style"]
                            if d2_data.get("behavior_habits"): current_dyn["behavior_habits"] = d2_data["behavior_habits"]
                            # Merge others
                            for k, v in d2_data.items():
                                if k not in ["communication_style", "behavior_habits"]:
                                    current_dyn[k] = v

                        # D3: Emotional -> Dynamic
                        if profile_update and d3_data:
                            if d3_data.get("emotional_baseline"): current_dyn["emotional_baseline"] = d3_data["emotional_baseline"]
                            
                        # D4: Cognitive -> Dynamic
                        if profile_update and d4_data:
                            if d4_data.get("decision_style"): current_dyn["decision_style"] = d4_data["decision_style"]
                            if d4_data.get("thinking_mode"): current_dyn["thinking_mode"] = d4_data["thinking_mode"]

                        # D5: Personality -> Traits
                        if profile_update and d5_data:
                            current_traits.update(d5_data)
                            
                        # D6: Core -> Dynamic
                        if profile_update and d6_data:
                            if d6_data.get("core_drivers"): 
                                # Merge lists strictly to avoid duplicates
                                exist_drivers = set(current_dyn.get("core_drivers", []))
                                new_drivers = d6_data["core_drivers"]
                                if isinstance(new_drivers, list):
                                    exist_drivers.update(new_drivers)
                                    current_dyn["core_drivers"] = list(exist_drivers)
                            
                            if d6_data.get("inferred_core_needs"):
                                exist_needs = set(current_dyn.get("inferred_core_needs", []))
                                new_needs = d6_data["inferred_core_needs"]
                                if isinstance(new_needs, list):
                                    exist_needs.update(new_needs)
                                    current_dyn["inferred_core_needs"] = list(exist_needs)

                        # 3. Add Timeline Events (Character Arc - Deeds)
                        character_deeds = profile_update.get("character_deeds", [])
                        
                        # If no structured deeds, try legacy summary
                        if not character_deeds:
                            timeline_summary = profile_update.get("timeline_summary")
                            if not timeline_summary:
                                timeline_summary = overall_summary[:50] + "..." if overall_summary else "对话分析归档"
                            character_deeds = [{"event": timeline_summary, "timestamp": datetime.now().strftime("%Y-%m-%d")}]

                        # Sort deeds by timestamp desc (as requested)
                        # Note: Server appends, so we add them in reverse order of occurrence? 
                        # Actually user wants "Time Reverse Order" display, but storage is chronological usually.
                        # We will store them as they come. The display logic handles sorting.
                        
                        count_events = 0
                        for deed in character_deeds:
                            evt_content = deed.get("event")
                            evt_time = deed.get("timestamp") or datetime.now().strftime("%Y-%m-%d")
                            
                            event_payload = {
                                "summary": f"[{evt_time}] {evt_content}",
                                "intent": deep_intent,
                                "strategy": strategies,
                                "session_id": "manual_analysis"
                            }
                            try:
                                requests.post(f"{API_URL}/characters/{char_obj['id']}/events", json=event_payload)
                                count_events += 1
                            except Exception as e:
                                st.warning(f"时间线添加失败: {e}")
                        
                        if count_events > 0:
                            st.toast(f"✅ 已添加 {count_events} 条人物事迹到弧光！")

                        # 4. Construct Payload
                        update_payload = {
                            "attributes": current_attrs,
                            "traits": current_traits,
                            "dynamic_profile": current_dyn,
                            "version_note": "来自深度对话分析(六维画像归档)"
                        }
                        
                        try:
                            up_res = requests.put(f"{API_URL}/characters/{char_obj['id']}", json=update_payload)
                            if up_res.status_code == 200:
                                st.toast(f"✅ 已成功更新 {char_name} 的六维档案！")
                                st.success("归档成功！请前往后台看板查看最新画像。")
                            else:
                                st.error(f"更新失败: {up_res.text}")
                        except Exception as e:
                            st.error(f"请求异常: {e}")
                else:
                    st.caption("⚠️ 未在系统中找到该角色，无法归档。")

    # ==========================================
    # 3. Feedback & Evolution
    # ==========================================
    st.markdown("---")
    st.subheader("📊 质量反馈与进化 (Feedback & Evolution)")
    st.caption("您的反馈将帮助系统进化。差评 (<=2星) 将自动触发‘复盘分析’并生成微调数据。")
    
    with st.form("feedback_form"):
        col_f1, col_f2 = st.columns([1, 3])
        with col_f1:
            rating = st.slider("评分 (Rating)", 1, 5, 5, help="1=差评(触发进化), 5=好评")
        with col_f2:
            comment = st.text_input("建议/吐槽 (Optional comment)")
            
        submitted = st.form_submit_button("提交反馈 (Submit)")
        if submitted:
            feedback_payload = {
                "session_id": "manual_analysis",
                "user_input": text_input,
                "model_output": json.dumps(result, ensure_ascii=False),
                "rating": rating,
                "comment": comment
            }
            try:
                f_res = requests.post(f"{API_URL}/feedback", json=feedback_payload)
                if f_res.status_code == 200:
                    st.success("✅ 反馈已提交！系统正在后台学习...")
                    if rating <= 2:
                        st.info("🧬 已触发【复盘分析】机制，系统正在生成改进版报告...")
                else:
                    st.error(f"反馈提交失败: {f_res.text}")
            except Exception as e:
                st.error(f"请求异常: {e}")
