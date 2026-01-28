import streamlit as st
import requests
import json
import os
import datetime
from app.core.config import settings

API_URL = settings.API_URL

def load_history_from_api(character_names=None):
    """
    Load analysis history from backend API.
    """
    try:
        # User requested "Comprehensive analysis with reference to historical records"
        # and "Containing character's all history, not just recent three".
        # So we request ALL records (-1).
        params = {"limit": -1} 
        if character_names:
            params["character_names"] = character_names
            
        res = requests.get(f"{API_URL}/analysis/history", params=params)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        # st.error(f"Failed to load history: {e}")
        pass
    return []

st.set_page_config(page_title="长对话分析", page_icon="📜", layout="wide")

st.title("📜 长对话深度分析与归档")
st.markdown("---")

# Initialize session state
if "input_text_content" not in st.session_state:
    st.session_state.input_text_content = ""

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
all_options = ["我"] + list(char_options.keys())
selected_char_names = st.sidebar.multiselect(
    "选择文本中包含的角色 (Select Characters)",
    options=all_options,
    default=["我"]
)

# Main Area: Text Input
st.subheader("📝 输入长对话内容 (Input Conversation)")
st.caption("支持粘贴大段对话记录、小说片段或工作日志。系统将自动区分角色并分析重点。")

# Initialize text area state if not exists
if "input_text_content" not in st.session_state:
    st.session_state.input_text_content = ""

# File Uploader
uploaded_file = st.file_uploader("上传文件 (支持 .txt, .md 文本; .wav, .mp3, .m4a 音频; .mp4, .mov, .avi, .mkv 视频)", type=["txt", "md", "wav", "mp3", "m4a", "mp4", "mov", "avi", "mkv"])

if uploaded_file is not None:
    file_ext = uploaded_file.name.split('.')[-1].lower()
    
    # Case 1: Text File
    if file_ext in ['txt', 'md']:
        try:
            # Read and update state immediately
            content = uploaded_file.read().decode("utf-8")
            if content != st.session_state.input_text_content:
                st.session_state.input_text_content = content
                st.rerun()
        except Exception as e:
            st.error(f"文件读取失败: {e}")
            
    # Case 2: Audio File
    elif file_ext in ['wav', 'mp3', 'm4a']:
        st.info(f"🎤 已上传音频文件: {uploaded_file.name}")
        
        # Transcribe Button
        if st.button("🎙️ 开始语音识别与角色区分 (Start Analysis)", type="primary"):
            with st.spinner("正在进行语音转文字及声纹分析... (可能需要几分钟)"):
                try:
                    # Reset file pointer
                    uploaded_file.seek(0)
                    files = {"file": (uploaded_file.name, uploaded_file, uploaded_file.type)}
                    res = requests.post(f"{API_URL}/audio/diarization", files=files)
                    
                    if res.status_code == 200:
                        st.session_state.diarization_result = res.json()
                        st.success("识别完成！请在下方确认角色身份。")
                    else:
                        st.error(f"识别失败: {res.text}")
                except Exception as e:
                    st.error(f"Request Error: {e}")

    # Case 3: Video File
    elif file_ext in ['mp4', 'mov', 'avi', 'mkv']:
        st.info(f"🎥 已上传视频文件: {uploaded_file.name}")
        
        if st.button("🎬 提取音频并开始识别 (Extract & Analyze)", type="primary"):
            with st.spinner("正在提取音频并进行分析..."):
                try:
                    import tempfile
                    from app.utils.readvoice import extract_audio_ffmpeg
                    from pathlib import Path
                    
                    # 1. Save uploaded video to temp file
                    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_ext}") as tmp_video:
                        tmp_video.write(uploaded_file.getvalue())
                        tmp_video_path = tmp_video.name
                    
                    try:
                        # 2. Extract Audio
                        output_dir = Path(tempfile.gettempdir())
                        success, _, audio_path = extract_audio_ffmpeg(tmp_video_path, output_dir, audio_format="wav")
                        
                        if not success:
                            st.error(f"音频提取失败: {audio_path}")
                        else:
                            st.success(f"音频提取成功: {Path(audio_path).name}")
                            
                            # 3. Call Diarization API
                            with open(audio_path, "rb") as f:
                                files = {"file": (f"{uploaded_file.name}.wav", f, "audio/wav")}
                                res = requests.post(f"{API_URL}/audio/diarization", files=files)
                            
                            if res.status_code == 200:
                                st.session_state.diarization_result = res.json()
                                st.success("识别完成！请在下方确认角色身份。")
                            else:
                                st.error(f"识别失败: {res.text}")
                            
                            # Cleanup audio
                            try:
                                os.remove(audio_path)
                            except:
                                pass
                                
                    finally:
                        # Cleanup video
                        try:
                            os.remove(tmp_video_path)
                        except:
                            pass
                            
                except Exception as e:
                    st.error(f"处理异常: {e}")

        # Display Diarization Result & Mapping UI
        if "diarization_result" in st.session_state:
            d_res = st.session_state.diarization_result
            speakers = d_res.get("detected_speakers", [])
            
            with st.expander("🗣️ 角色身份确认 (Speaker Identification)", expanded=True):
                st.markdown("##### 请为检测到的说话人指定角色")
                
                with st.form("speaker_mapping_form"):
                    mappings = {}
                    cols = st.columns(2)
                    
                    # Prepare options
                    # Filter out "我" from characters list to avoid duplication if it's there
                    char_names = [c["name"] for c in characters]
                    options = ["不指定 (Unknown)", "新建角色..."] + char_names
                    
                    for idx, spk in enumerate(speakers):
                        spk_id = spk["id"]
                        spk_name = spk["name"]
                        
                        with cols[idx % 2]:
                            st.markdown(f"**🔊 {spk_name}**")
                            
                            # Smart Default: Try to match if name exists
                            default_idx = 0
                            if spk_name in char_names:
                                default_idx = options.index(spk_name)
                            
                            sel_key = f"sel_{spk_id}"
                            txt_key = f"txt_{spk_id}"
                            
                            selected = st.selectbox("映射为:", options, index=default_idx, key=sel_key)
                            
                            custom_name = ""
                            if selected == "新建角色...":
                                custom_name = st.text_input("输入新名称:", key=txt_key)
                            
                            mappings[spk_id] = (selected, custom_name)
                    
                    st.markdown("---")
                    if st.form_submit_button("✅ 应用映射并生成文本"):
                        # Apply mapping to segments
                        raw_segments = d_res.get("raw_segments", [])
                        final_text = ""
                        
                        for seg in raw_segments:
                            sid = seg["speaker_id"]
                            sname = seg["speaker_name"]
                            
                            if sid in mappings:
                                sel, cust = mappings[sid]
                                if sel == "新建角色..." and cust:
                                    sname = cust
                                elif sel != "不指定 (Unknown)":
                                    sname = sel
                            
                            final_text += f"【{sname}】: {seg['text']}\n"
                        
                        # Update main text area
                        st.session_state.input_text_content = final_text
                        # Clear diarization result to hide the mapping UI (optional, but cleaner)
                        # del st.session_state.diarization_result 
                        st.rerun()

text_input = st.text_area("在此粘贴内容...", value=st.session_state.input_text_content, height=300, key="main_text_area")

# Sync manual edits back to state (Streamlit widgets with key update state automatically, 
# but we need to ensure our custom state variable tracks it if we used a separate one. 
# Here we used `input_text_content` as the initial value, but `key="main_text_area"` stores the current value in `st.session_state.main_text_area`.
# To keep them in sync for the next rerun if we manipulate `input_text_content` again:
st.session_state.input_text_content = st.session_state.main_text_area

if st.button("开始分析 (Start Analysis)", type="primary"):
    if not text_input:
        st.warning("请先输入内容。")
    else:
        with st.spinner("正在分析中 (Analyzing)..."):
            try:
                # Load recent history for context
                history_records = load_history_from_api(selected_char_names)
                
                # Take recent summaries for context
                recent_history = [
                    {"timestamp": r.get("created_at"), "summary": r.get("summary")} 
                    for r in history_records
                ]

                payload = {
                    "text": text_input,
                    "character_names": selected_char_names,
                    "history_context": recent_history
                }
                res = requests.post(f"{API_URL}/analysis/conversation", json=payload)
                
                if res.status_code == 200:
                    analysis_result = res.json()
                    st.session_state.analysis_result = analysis_result
                    
                    # Persistence is now handled by the backend (saved to DB)
                    if "log_id" in analysis_result:
                         st.success(f"分析完成并已保存记录 (ID: {analysis_result['log_id']})！")
                    else:
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
                
                # If not found, allow manual selection
                if not char_obj:
                    st.warning(f"⚠️ 系统未找到名为 '{char_name}' 的角色档案。")
                    col_sel, col_new = st.columns([2, 1])
                    with col_sel:
                        manual_name = st.selectbox(
                            f"将其归档到现有角色 (For '{char_name}'):", 
                            ["-- 请选择 --"] + list(char_options.keys()),
                            key=f"manual_sel_{i}"
                        )
                        if manual_name != "-- 请选择 --":
                            char_obj = char_options.get(manual_name)
                    
                st.markdown("---")
                if char_obj:
                    # Update name for display if manually selected
                    target_name = char_obj['name']
                    
                    btn_key = f"archive_btn_{char_obj['id']}_{i}"
                    if st.button(f"📥 归档到 [{target_name}]", key=btn_key):
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
