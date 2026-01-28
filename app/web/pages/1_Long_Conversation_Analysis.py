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

# Dynamic Refresh Button
if st.sidebar.button("🔄 刷新角色列表"):
    st.rerun()

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

# Input Source Selection
st.markdown("### 📥 导入内容 (Import Content)")
tab1, tab2 = st.tabs(["📂 文件上传 (Upload File)", "🌐 网页链接 (Web URL)"])

uploaded_file = None
media_url = None
web_file_path = None # To track downloaded file

with tab1:
    uploaded_file = st.file_uploader("支持 .txt, .md 文本; .wav, .mp3, .m4a 音频; .mp4, .mov, .avi, .mkv 视频", type=["txt", "md", "wav", "mp3", "m4a", "mp4", "mov", "avi", "mkv"])
    
    # Cleanup state if file is removed
    if uploaded_file is None:
        if "uploaded_text_content" in st.session_state:
            del st.session_state.uploaded_text_content
            st.rerun() # Rerun to update UI label


with tab2:
    st.info("支持主流视频网站链接 (YouTube, Bilibili等)。将自动下载并提取音频进行分析。")
    media_url = st.text_input("🔗 输入视频/音频 URL (Enter URL)")
    if st.button("🚀 下载并开始分析 (Download & Analyze)", type="primary", key="btn_web_dl"):
        if not media_url:
            st.warning("请输入有效的 URL。")
        else:
            with st.spinner("正在下载媒体资源... (Depending on network speed)"):
                try:
                    import tempfile
                    from app.utils.media_downloader import download_media
                    
                    # Use temp dir for download
                    dl_dir = tempfile.gettempdir()
                    downloaded_path = download_media(media_url, dl_dir)
                    
                    if downloaded_path:
                        st.success(f"下载成功: {os.path.basename(downloaded_path)}")
                        web_file_path = downloaded_path
                        # Trigger analysis logic below
                    else:
                        st.error("下载失败，请检查 URL 或网络连接。")
                except Exception as e:
                    st.error(f"下载异常: {e}")

# Process Input (File or Web Download)
target_file = uploaded_file
target_file_path = web_file_path # For web downloaded files, we have a path string

if target_file is not None or target_file_path is not None:
    # Determine file info
    if target_file:
        file_name = target_file.name
        file_ext = file_name.split('.')[-1].lower()
    else:
        file_name = os.path.basename(target_file_path)
        file_ext = file_name.split('.')[-1].lower()
    
    # Case 1: Text File (Only supports upload for now, web usually gives video/audio)
    if file_ext in ['txt', 'md'] and target_file:
        try:
            content = target_file.read().decode("utf-8")
            # User Requirement: If text file uploaded, read directly, input box is supplementary.
            # So we store it separately and don't overwrite the main text area.
            st.session_state.uploaded_text_content = content
            st.success(f"📄 已加载文本文件: {file_name} ({len(content)} 字符)")
            st.info("💡 提示: 文件内容将直接用于分析。下方的输入框已切换为【补充说明/指令】模式。")
            
            # Clear input_text_content to avoid confusion if it had old data, 
            # or keep it if user wants to use it as supplementary? 
            # Let's keep it but maybe clear it if it was from previous run? 
            # Safer to just let user decide.
        except Exception as e:
            st.error(f"文件读取失败: {e}")
            
    # Case 2: Audio File (WAV, MP3, M4A)
    elif file_ext in ['wav', 'mp3', 'm4a']:
        st.info(f"🎤 已加载音频文件: {file_name}")
        
        # Auto-start for web download, Button for upload
        start_analysis = False
        if target_file_path: # Web download
             start_analysis = True
        elif st.button("🎙️ 开始语音识别与角色区分 (Start Analysis)", type="primary"):
             start_analysis = True
             
        if start_analysis:
            with st.spinner("正在进行语音转文字及声纹分析... (可能需要几分钟)"):
                try:
                    if target_file:
                        # Reset file pointer
                        target_file.seek(0)
                        files = {"file": (file_name, target_file, target_file.type)}
                        res = requests.post(f"{API_URL}/audio/diarization", files=files)
                    else:
                        # Web file path
                        with open(target_file_path, "rb") as f:
                             files = {"file": (file_name, f, "audio/wav")}
                             res = requests.post(f"{API_URL}/audio/diarization", files=files)
                    
                    if res.status_code == 200:
                        st.session_state.diarization_result = res.json()
                        
                        # Auto-populate text with default names
                        raw_segments = st.session_state.diarization_result.get("raw_segments", [])
                        initial_text = ""
                        for seg in raw_segments:
                            initial_text += f"【{seg['speaker_name']}】: {seg['text']}\n"
                        
                        st.session_state.input_text_content = initial_text
                        st.session_state.main_text_area = initial_text  # Sync widget state
                        
                        st.success("识别完成！请在下方确认角色身份。")
                    else:
                        st.error(f"识别失败: {res.text}")
                        
                except Exception as e:
                    st.error(f"Request Error: {e}")
                finally:
                    # Cleanup web file
                    if target_file_path:
                        try:
                            os.remove(target_file_path)
                        except:
                            pass

    # Case 3: Video File (MP4, MOV, AVI, MKV)
    # Note: download_media converts to wav mostly, but if yt-dlp keeps video or upload video
    elif file_ext in ['mp4', 'mov', 'avi', 'mkv']:
        st.info(f"🎥 已加载视频文件: {file_name}")
        
        start_analysis = False
        if target_file_path:
             start_analysis = True # Web download usually gives wav if forced, but if not
        elif st.button("🎬 提取音频并开始识别 (Extract & Analyze)", type="primary"):
             start_analysis = True
             
        if start_analysis:
            with st.spinner("正在提取音频并进行分析..."):
                tmp_video_path = None
                audio_path_extracted = None
                try:
                    import tempfile
                    from app.utils.readvoice import extract_audio_ffmpeg
                    from pathlib import Path
                    
                    if target_file:
                        # 1. Save uploaded video to temp file
                        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_ext}") as tmp_video:
                            tmp_video.write(target_file.getvalue())
                            tmp_video_path = tmp_video.name
                    else:
                        tmp_video_path = target_file_path
                    
                    try:
                        # 2. Extract Audio
                        output_dir = Path(tempfile.gettempdir())
                        success, _, audio_path_extracted = extract_audio_ffmpeg(tmp_video_path, output_dir, audio_format="wav")
                        
                        if not success:
                            st.error(f"音频提取失败: {audio_path_extracted}")
                        else:
                            st.success(f"音频提取成功: {Path(audio_path_extracted).name}")
                            
                            # 3. Call Diarization API
                            with open(audio_path_extracted, "rb") as f:
                                files = {"file": (f"{file_name}.wav", f, "audio/wav")}
                                res = requests.post(f"{API_URL}/audio/diarization", files=files)
                            
                            if res.status_code == 200:
                                st.session_state.diarization_result = res.json()
                                
                                # Auto-populate text with default names
                                raw_segments = st.session_state.diarization_result.get("raw_segments", [])
                                initial_text = ""
                                for seg in raw_segments:
                                    initial_text += f"【{seg['speaker_name']}】: {seg['text']}\n"
                                
                                st.session_state.input_text_content = initial_text
                                st.session_state.main_text_area = initial_text  # Sync widget state
                                
                                st.success("识别完成！请在下方确认角色身份。")
                            else:
                                st.error(f"识别失败: {res.text}")
                                
                    finally:
                        # Cleanup temp video if it was uploaded/downloaded
                        if tmp_video_path:
                            try:
                                os.remove(tmp_video_path)
                            except:
                                pass
                        # Cleanup extracted audio
                        if audio_path_extracted:
                            try:
                                os.remove(audio_path_extracted)
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
                    
                    # User Requirement: Dropdown should prioritize bound characters (selected_char_names)
                    # Filter selected_char_names to ensure they exist in known chars (or just allow them)
                    # We'll put selected_char_names first.
                    other_chars = [c for c in char_names if c not in selected_char_names]
                    
                    # Options: Unknown, New, [Selected Chars], [Other Chars]
                    options = ["不指定 (Unknown)", "新建角色..."] + selected_char_names + other_chars
                    
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
                        
                        # Generate Mapping Summary Table
                        mapping_summary = "【角色映射表】\n"
                        has_mapping = False
                        
                        # Apply mapping logic
                        final_text_body = ""
                        for seg in raw_segments:
                            sid = seg["speaker_id"]
                            sname = seg["speaker_name"]
                            
                            if sid in mappings:
                                sel, cust = mappings[sid]
                                if sel == "新建角色..." and cust:
                                    sname = cust
                                elif sel != "不指定 (Unknown)":
                                    sname = sel
                            
                            final_text_body += f"【{sname}】: {seg['text']}\n"

                        # Build summary string from mappings dict
                        for sid, (sel, cust) in mappings.items():
                             target = cust if sel == "新建角色..." else sel
                             if target != "不指定 (Unknown)":
                                 mapping_summary += f"🔊 {sid} 映射为: {target}\n"
                                 has_mapping = True
                        
                        if has_mapping:
                            final_text = mapping_summary + "\n" + final_text_body
                        else:
                            final_text = final_text_body
                        
                        # Update main text area
                        st.session_state.input_text_content = final_text
                        st.session_state.main_text_area = final_text # Force sync
                        # Clear diarization result to hide the mapping UI (optional, but cleaner)
                        # del st.session_state.diarization_result 
                        st.rerun()

# Dynamic Text Area Label
text_area_label = "在此粘贴内容..."
if "uploaded_text_content" in st.session_state:
    text_area_label = "📝 补充说明/指令 (Supplementary Instructions) - 文件已加载"

# Ensure session state for text area is initialized correctly to avoid "value set via Session State API" warning
if "main_text_area" not in st.session_state:
    st.session_state.main_text_area = st.session_state.input_text_content

# We do NOT pass `value` here because we rely on `key="main_text_area"` and the session state we just synced.
text_input = st.text_area(text_area_label, height=300, key="main_text_area")

# Sync manual edits back to shadow state variable
st.session_state.input_text_content = st.session_state.main_text_area

if st.button("开始分析 (Start Analysis)", type="primary"):
    # Determine actual input
    final_text = ""
    
    # Priority: Uploaded Text File > Text Input (as main)
    if "uploaded_text_content" in st.session_state and st.session_state.uploaded_text_content:
        final_text = st.session_state.uploaded_text_content
        if text_input and text_input.strip():
             final_text += f"\n\n【补充说明】\n{text_input}"
    else:
        final_text = text_input

    if not final_text:
        st.warning("请先输入内容或上传文本文件。")
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
                    "text": final_text,
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

    # ==========================================
    # 2. Multi-Character Archiving Section
    # ==========================================
    structured_data = result.get("structured_data", {})
    # Support both keys just in case
    char_analysis_list = structured_data.get("characters", []) or structured_data.get("character_analysis", [])

    if char_analysis_list:
        st.markdown("### 🗄️ 多角色归档 (Multi-Character Archiving)")
        st.caption("以下是分析中提取的角色信息，您可以将其归档到角色库中。")
        
        # Get existing characters for dropdown
        existing_chars = []
        try:
            res_chars = requests.get(f"{API_URL}/characters")
            if res_chars.status_code == 200:
                existing_chars = res_chars.json()
        except:
            pass
            
        existing_char_names = [c["name"] for c in existing_chars]
        existing_char_map = {c["name"]: c["id"] for c in existing_chars}

        for idx, char_data in enumerate(char_analysis_list):
            char_name = char_data.get("name", f"Unknown_{idx}")
            summary = char_data.get("summary", "")
            tags = char_data.get("tags", [])
            
            with st.expander(f"👤 {char_name}", expanded=False):
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.markdown(f"**分析摘要**: {summary}")
                    st.markdown(f"**标签**: {', '.join(tags)}")
                
                with col2:
                    # Archiving Form
                    form_key = f"archive_form_{idx}"
                    with st.form(form_key):
                        st.markdown("##### 归档设置")
                        
                        # Match existing or new
                        match_idx = 0
                        if char_name in existing_char_names:
                            match_idx = existing_char_names.index(char_name) + 1 # +1 for New
                            default_action = "Update Existing"
                        else:
                            default_action = "Create New"
                            
                        # Options: [Create New, Existing Char 1, Existing Char 2...]
                        target_options = ["🆕 新建角色 (Create New)"] + existing_char_names
                        
                        # Set default index
                        default_opt_idx = 0
                        if char_name in existing_char_names:
                            default_opt_idx = target_options.index(char_name)
                        
                        selected_target = st.selectbox("目标角色 (Target Character)", target_options, index=default_opt_idx)
                        
                        # Edit Name if New
                        final_name = char_name
                        if selected_target == "🆕 新建角色 (Create New)":
                            final_name = st.text_input("角色名称 (Name)", value=char_name)
                        
                        # Edit Profile/Summary to be saved
                        final_profile = st.text_area("更新内容 (Profile Content)", value=summary, height=100)
                        
                        if st.form_submit_button("💾 保存归档 (Save to Profile)"):
                            try:
                                # Prepare Payload
                                payload = {
                                    "name": final_name if selected_target == "🆕 新建角色 (Create New)" else selected_target,
                                    "description": final_profile, # Using description for simple profile update
                                    # If updating specific fields like 'personality' or 'background', 
                                    # we might need a more complex extraction or mapping.
                                    # For now, we append the summary to the description or specific field if available.
                                    "tags": tags
                                }
                                
                                # Check if Create or Update
                                if selected_target == "🆕 新建角色 (Create New)":
                                    # Create
                                    create_res = requests.post(f"{API_URL}/characters/", json=payload)
                                    if create_res.status_code == 200:
                                        st.success(f"✅ 新角色 '{final_name}' 创建成功！")
                                        st.rerun()
                                    else:
                                        st.error(f"创建失败: {create_res.text}")
                                else:
                                    # Update
                                    # We need ID
                                    target_id = existing_char_map.get(selected_target)
                                    if target_id:
                                        # First get existing to merge? Or just PUT?
                                        # API Update usually expects full object or PATCH.
                                        # Let's try to get first
                                        curr_char = requests.get(f"{API_URL}/characters/{target_id}").json()
                                        
                                        # Merge Description (Append)
                                        new_desc = curr_char.get("description", "") + f"\n\n【{datetime.datetime.now().strftime('%Y-%m-%d')} 归档】\n{final_profile}"
                                        
                                        update_payload = {
                                            "name": selected_target,
                                            "description": new_desc,
                                            "tags": list(set(curr_char.get("tags", []) + tags))
                                        }
                                        
                                        update_res = requests.put(f"{API_URL}/characters/{target_id}", json=update_payload)
                                        if update_res.status_code == 200:
                                            st.success(f"✅ 角色 '{selected_target}' 更新成功！")
                                        else:
                                            st.error(f"更新失败: {update_res.text}")
                                    else:
                                        st.error("无法找到目标角色 ID")
                            except Exception as e:
                                st.error(f"操作异常: {e}")

    else:
        st.info("本次分析未提取到结构化角色信息。")

        # Fallback: Old Format Support
        st.warning("⚠️ 收到旧格式数据或解析失败，尝试以兼容模式显示。")
        structured_data = result
        char_analysis_list = result.get("analysis", [])
        overall_summary = result.get("overall_analysis", {}).get("summary", "")

    # ==========================================
    # 2. Universal Archive (One-Click)
    # ==========================================
    st.subheader("📥 通用一键归档 (One-Click Archive)")
    st.caption("将本次分析结果（摘要/报告）归档到指定角色的时间线或档案中。")
    
    # Universal Archive Container
    with st.container():
        # Prepare Archive Data
        archive_content = overall_summary
        if not archive_content:
             if "markdown_report" in result:
                 archive_content = result["markdown_report"][:200] + "..."
             else:
                 archive_content = st.session_state.input_text_content[:200] + "..."
        
        col_univ_target, col_univ_action = st.columns([3, 1])
        
        with col_univ_target:
            univ_opts = ["🆕 新建角色..."] + sorted([f"👤 {c}" for c in char_options.keys()])
            default_univ_idx = 0
            if selected_char_names:
                first_sel = selected_char_names[0]
                if first_sel in char_options:
                     try:
                        default_univ_idx = univ_opts.index(f"👤 {first_sel}")
                     except:
                        pass
            
            univ_sel = st.selectbox("选择归档目标 (Select Character)", univ_opts, index=default_univ_idx, key="univ_archive_sel")
            
            univ_new_name = ""
            if "🆕" in univ_sel:
                univ_new_name = st.text_input("输入新角色名称:", key="univ_new_name")
        
        with col_univ_action:
            st.write("") # Spacer
            st.write("")
            btn_univ_archive = st.button("🚀 归档本次分析", key="btn_univ_archive", type="primary", use_container_width=True)
            
        if btn_univ_archive:
            try:
                target_char_obj = None
                
                # 1. Handle New Character
                if "🆕" in univ_sel:
                    if not univ_new_name.strip():
                        st.error("请输入新角色名称！")
                        st.stop()
                    
                    create_payload = {
                        "name": univ_new_name.strip(),
                        "system_prompt": f"You are {univ_new_name}.",
                        "attributes": {},
                        "traits": {}
                    }
                    res_create = requests.post(f"{API_URL}/characters", json=create_payload)
                    if res_create.status_code == 200:
                        target_char_obj = res_create.json()
                        st.toast(f"✅ 新角色 [{univ_new_name}] 创建成功！")
                    else:
                        st.error(f"创建角色失败: {res_create.text}")
                        st.stop()
                else:
                    # Existing Character
                    selected_name = univ_sel.replace("👤 ", "")
                    target_char_obj = char_options.get(selected_name)
                
                if target_char_obj:
                    evt_time = datetime.datetime.now().strftime("%Y-%m-%d")
                    event_payload = {
                        "summary": f"[{evt_time}] 对话分析归档: {archive_content[:100]}...",
                        "intent": "Manual Archive",
                        "strategy": "Analysis",
                        "session_id": result.get("log_id", "manual_analysis")
                    }
                    
                    requests.post(f"{API_URL}/characters/{target_char_obj['id']}/events", json=event_payload)
                    st.success(f"✅ 已成功将分析摘要归档至 [{target_char_obj['name']}] 的时间线！")
                    
                    found_struct = next((item for item in char_analysis_list if item.get("name") == target_char_obj['name']), None)
                    if found_struct:
                        st.info(f"💡 检测到 [{target_char_obj['name']}] 的深度画像数据，请在下方【详细画像提取】面板中确认更新。")
                        
                else:
                    st.error("目标角色无效。")
                    
            except Exception as e:
                st.error(f"归档失败: {e}")

    # ==========================================
    # 3. Detailed Character Extraction (Optional)
    # ==========================================
    if char_analysis_list:
        st.subheader("🧩 详细画像提取 (Deep Profile Extraction)")
        st.caption("以下数据已从思考报告中结构化提取，可用于更新角色档案。")
        
        # Batch Archive Section
        with st.container():
            st.info("💡 提示: 系统会自动根据角色名匹配现有档案。")
            col_batch_info, col_batch_btn = st.columns([3, 1])
            with col_batch_info:
                matched_count = 0
                for item in char_analysis_list:
                    c_name = item.get("name", item.get("character_name", "Unknown"))
                    if char_options.get(c_name):
                        matched_count += 1
                st.write(f"📊 检测到 {len(char_analysis_list)} 个角色数据，其中 {matched_count} 个已自动匹配现有档案。")
            
            with col_batch_btn:
                btn_batch_archive = st.button("📦 批量归档所有匹配角色", type="primary", use_container_width=True)
        
        if btn_batch_archive:
            success_count = 0
            fail_count = 0
            logs = []
            
            progress_bar = st.progress(0)
            
            for idx, item in enumerate(char_analysis_list):
                c_name = item.get("name", item.get("character_name", "Unknown"))
                target_char = char_options.get(c_name)
                
                if target_char:
                    try:
                        # 1. Prepare Data
                        profile_update = item.get("profile_update", {})
                        deep_intent = item.get("deep_intent", "未检测到")
                        strategies = item.get("strategy") or item.get("strategies", [])
                        if isinstance(strategies, list): strategies = ", ".join(strategies)
                        
                        # 2. Update Profile (Merge)
                        current_dyn = target_char.get("dynamic_profile", {}) or {}
                        current_attrs = target_char.get("attributes", {}) or {}
                        current_traits = target_char.get("traits", {}) or {}
                        
                        # Merge Logic (Simplified for Batch)
                        if profile_update:
                             # D1
                             if "basic_attributes" in profile_update: current_attrs.update(profile_update["basic_attributes"].get("data", {}))
                             # D2-D6 (Dynamic)
                             for key in ["surface_behavior", "emotional_traits", "cognitive_decision", "core_essence"]:
                                 if key in profile_update:
                                     current_dyn.update(profile_update[key].get("data", {}))
                             # D5 (Traits)
                             if "personality_traits" in profile_update: current_traits.update(profile_update["personality_traits"].get("data", {}))

                        # 3. Add Timeline Event
                        # Use character specific summary or timeline_summary
                        evt_summary = profile_update.get("timeline_summary")
                        if not evt_summary:
                            # Fallback: Create summary from intent/strategy
                            evt_summary = f"参与对话分析。意图: {deep_intent}。策略: {strategies}"
                            
                        evt_time = datetime.datetime.now().strftime("%Y-%m-%d")
                        event_payload = {
                            "summary": f"[{evt_time}] {evt_summary}",
                            "intent": deep_intent,
                            "strategy": strategies,
                            "session_id": result.get("log_id", "manual_analysis")
                        }
                        
                        # API Calls
                        requests.post(f"{API_URL}/characters/{target_char['id']}/events", json=event_payload)
                        
                        update_payload = {
                            "attributes": current_attrs,
                            "traits": current_traits,
                            "dynamic_profile": current_dyn,
                            "version_note": "Batch Analysis Archive"
                        }
                        requests.put(f"{API_URL}/characters/{target_char['id']}", json=update_payload)
                        
                        success_count += 1
                        logs.append(f"✅ [{c_name}] 归档成功")
                        
                    except Exception as e:
                        fail_count += 1
                        logs.append(f"❌ [{c_name}] 归档失败: {e}")
                else:
                    fail_count += 1
                    logs.append(f"⚠️ [{c_name}] 未找到匹配档案，跳过")
                
                progress_bar.progress((idx + 1) / len(char_analysis_list))
                
            if success_count > 0:
                st.success(f"批量归档完成！成功: {success_count}, 失败/跳过: {fail_count}")
                with st.expander("查看归档日志", expanded=True):
                    for log in logs:
                        st.write(log)
            else:
                st.warning("未成功归档任何角色。请检查角色名是否匹配。")

        st.divider()

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

                # Archiving Action UI
                st.markdown("---")
                st.markdown("##### 📥 一键归档操作 (One-click Archive)")
                
                # Try to find a match
                matched_char = char_options.get(char_name)
                
                # UI for Selection
                col_target, col_action = st.columns([3, 1])
                
                target_char_obj = None
                archive_mode = "Existing"
                new_char_name_input = ""

                with col_target:
                    # Construct options list
                    opts = []
                    if matched_char:
                        opts.append(f"✅ 现有角色: {matched_char['name']}")
                    opts.append("🆕 新建角色...")
                    # Add other characters (sorted)
                    other_chars = sorted([c for c in char_options.keys() if c != (matched_char['name'] if matched_char else "")])
                    opts.extend([f"👤 {c}" for c in other_chars])
                    
                    sel_label = st.selectbox(f"归档目标 (Target)", opts, key=f"archive_sel_{i}", label_visibility="collapsed")
                    
                    if "🆕 新建角色..." in sel_label:
                        archive_mode = "New"
                        new_char_name_input = st.text_input("输入新角色名称:", value=char_name, key=f"new_name_{i}")
                    elif "✅" in sel_label:
                        archive_mode = "Existing"
                        target_char_obj = matched_char
                    else:
                        archive_mode = "Existing"
                        selected_name = sel_label.replace("👤 ", "")
                        target_char_obj = char_options.get(selected_name)

                with col_action:
                    btn_clicked = st.button("🚀 执行归档", key=f"do_archive_{i}", type="primary", use_container_width=True)

                if btn_clicked:
                    try:
                        # 0. Handle New Character Creation
                        if archive_mode == "New":
                            if not new_char_name_input.strip():
                                st.error("请输入新角色名称！")
                                st.stop()
                            
                            # Create Character
                            create_payload = {
                                "name": new_char_name_input.strip(),
                                "system_prompt": f"You are {new_char_name_input}.", # Basic init
                                "attributes": {},
                                "traits": {}
                            }
                            res_create = requests.post(f"{API_URL}/characters", json=create_payload)
                            if res_create.status_code == 200:
                                target_char_obj = res_create.json()
                                st.toast(f"✅ 新角色 [{new_char_name_input}] 创建成功！")
                            else:
                                st.error(f"创建角色失败: {res_create.text}")
                                st.stop()

                        if target_char_obj:
                            target_name = target_char_obj['name']
                            
                            # Logic to update character profile
                            # 1. Prepare Base Data
                            current_dyn = target_char_obj.get("dynamic_profile", {}) or {}
                            current_attrs = target_char_obj.get("attributes", {}) or {}
                            current_traits = target_char_obj.get("traits", {}) or {}
                            
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
                                    requests.post(f"{API_URL}/characters/{target_char_obj['id']}/events", json=event_payload)
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
                            
                            up_res = requests.put(f"{API_URL}/characters/{target_char_obj['id']}", json=update_payload)
                            if up_res.status_code == 200:
                                st.toast(f"✅ 已成功更新 {target_name} 的六维档案！")
                                st.success(f"归档成功！数据已合并至 [{target_name}]。")
                            else:
                                st.error(f"更新失败: {up_res.text}")
                        else:
                            st.error("无法确定目标角色，归档失败。")
                            
                    except Exception as e:
                        st.error(f"归档过程异常: {e}")

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
