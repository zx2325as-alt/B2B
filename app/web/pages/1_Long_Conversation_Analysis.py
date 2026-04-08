import streamlit as st
import requests
import json
import os
import datetime
import uuid
from app.core.config import settings
from app.utils.data_utils import deep_merge_profile

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


def load_raw_dialogue_logs(character_names=None, character_map=None, limit=-1):
    """
    Load raw dialogue logs (User inputs & Bot responses) from backend API.
    Returns a list of dicts: {"character": str, "text": str, "timestamp": str}
    """
    raw_history = []
    try:
        # We want to fetch logs for the selected characters.
        # The /logs endpoint filters by character_id.
        # If character_names is provided, we need to find their IDs.

        target_ids = []
        if character_names and character_map:
            for name in character_names:
                if name in character_map:
                    target_ids.append(character_map[name]["id"])

        # If no specific characters selected, maybe fetch all?
        # But usually we focus on selected ones.

        all_logs = []

        limit_param = limit if limit is not None else 50
        if not target_ids:
            # Try to fetch some recent global logs?
            # Or just return empty if no char selected.
            # Let's fetch global recent logs if no char selected (unlikely in this UI)
            res = requests.get(f"{API_URL}/logs", params={"limit": limit_param})
            if res.status_code == 200:
                all_logs = res.json()
        else:
            # Fetch for each character (API doesn't support list of IDs yet, so loop)
            # This might be slow if many chars, but usually 1-3.
            for cid in target_ids:
                res = requests.get(
                    f"{API_URL}/logs",
                    params={"character_id": cid, "limit": limit_param},
                )
                if res.status_code == 200:
                    all_logs.extend(res.json())

        # Deduplicate by id (if multiple chars in same session, might get same log?
        # DialogueLog has character_id, so usually one char per log unless group chat?
        # Current model seems 1 char per log)
        seen_ids = set()
        unique_logs = []
        for log in all_logs:
            if log["id"] not in seen_ids:
                unique_logs.append(log)
                seen_ids.add(log["id"])

        # Sort by created_at
        unique_logs.sort(key=lambda x: x["created_at"])

        # Format
        for log in unique_logs:
            ts = log.get("created_at", "")

            # User turn
            if log.get("user_input"):
                raw_history.append(
                    {"character": "User", "text": log["user_input"], "timestamp": ts}
                )

            # Bot turn
            if log.get("bot_response"):
                # Resolve character name
                cid = log.get("character_id")
                cname = "Assistant"
                # Try to find name from map
                if character_map:
                    for name, c_obj in character_map.items():
                        if c_obj["id"] == cid:
                            cname = name
                            break

                raw_history.append(
                    {"character": cname, "text": log["bot_response"], "timestamp": ts}
                )

    except Exception as e:
        # print(f"Error loading raw logs: {e}")
        pass

    return raw_history


def perform_character_archive(
    api_url, target_char_id, target_char_name, profile_update, event_data
):
    """
    Unified function to archive character data (Events + Profile Update).
    Returns: (success, message, updated_dims)
    """
    import requests
    import datetime
    from app.utils.data_utils import deep_merge_profile

    logs = []
    updated_dims = []

    try:
        # 1. Add Timeline Event (Deeds)
        # Priority: explicit deeds list in profile_update > event_data
        events_to_post = []
        if profile_update and isinstance(profile_update, dict):
            deeds = profile_update.get("character_deeds", [])
            if deeds:
                for deed in deeds:
                    events_to_post.append(
                        {
                            "summary": deed.get("event"),
                            "timestamp": deed.get("timestamp"),
                        }
                    )

        if not events_to_post and event_data:
            events_to_post.append(event_data)

        for evt in events_to_post:
            evt_time = evt.get("timestamp") or datetime.datetime.now().strftime(
                "%Y-%m-%d"
            )
            summary = evt.get("summary")
            if not summary:
                continue

            # Use metadata from event_data if available, otherwise defaults
            intent = (
                event_data.get("intent", "Manual Archive") if event_data else "Archive"
            )
            strategy = (
                event_data.get("strategy", "Analysis") if event_data else "Analysis"
            )
            session_id = (
                event_data.get("session_id", "manual_analysis")
                if event_data
                else "manual_analysis"
            )

            payload = {
                "summary": f"[{evt_time}] {summary}",
                "intent": intent,
                "strategy": strategy,
                "session_id": session_id,
                "event_date": evt_time,
            }
            try:
                requests.post(
                    f"{api_url}/characters/{target_char_id}/events", json=payload
                )
                logs.append(f"✅ 时间线事件已添加: {summary[:20]}...")
            except Exception as e:
                logs.append(f"⚠️ 时间线添加失败: {e}")

        # 2. Update Profile (Deep Merge)
        if profile_update:
            # Re-fetch latest profile
            try:
                res = requests.get(f"{api_url}/characters/{target_char_id}")
                if res.status_code == 200:
                    latest_char = res.json()
                else:
                    latest_char = {}
                    logs.append("⚠️ 无法获取最新档案，跳过档案更新")
            except Exception as e:
                logs.append(f"⚠️ 获取最新档案失败: {e}")
                latest_char = {}

            if latest_char:
                current_dyn = latest_char.get("dynamic_profile", {}) or {}
                current_attrs = latest_char.get("attributes", {}) or {}
                current_traits = latest_char.get("traits", {}) or {}

                # Merge
                # D1: Basic Attributes
                if "basic_attributes" in profile_update:
                    raw = profile_update["basic_attributes"]
                    new_val = raw.get("data", raw) if isinstance(raw, dict) else {}
                    current_attrs = deep_merge_profile(current_attrs, new_val)
                    updated_dims.append("基础属性")

                # D5: Personality Traits
                if "personality_traits" in profile_update:
                    raw = profile_update["personality_traits"]
                    new_val = raw.get("data", raw) if isinstance(raw, dict) else {}
                    current_traits = deep_merge_profile(current_traits, new_val)
                    updated_dims.append("人格特质")

                # D2,3,4,6,7 -> Dynamic
                map_keys = {
                    "surface_behavior": "表层行为",
                    "emotional_traits": "情绪特征",
                    "cognitive_decision": "认知决策",
                    "core_essence": "核心本质",
                    "character_arc": "人物弧光",
                }
                for k, label in map_keys.items():
                    if k in profile_update:
                        raw = profile_update[k]
                        new_val = raw.get("data", raw) if isinstance(raw, dict) else {}
                        # Merge under the specific key to maintain structure
                        current_dyn = deep_merge_profile(current_dyn, {k: new_val})
                        updated_dims.append(label)

                # Update
                update_payload = {
                    "attributes": current_attrs,
                    "traits": current_traits,
                    "dynamic_profile": current_dyn,
                    "version_note": event_data.get("version_note", "Analysis Archive"),
                }

                res_put = requests.put(
                    f"{api_url}/characters/{target_char_id}", json=update_payload
                )
                if res_put.status_code == 200:
                    logs.append(
                        f"✅ 档案深度更新成功 (维度: {', '.join(updated_dims)})"
                    )
                else:
                    logs.append(f"❌ 档案更新请求失败: {res_put.text}")
                    return False, " | ".join(logs), updated_dims
            else:
                # If we couldn't fetch latest, we skipped update but maybe event succeeded
                pass

        return True, " | ".join(logs), updated_dims

    except Exception as e:
        return False, f"归档过程发生未知异常: {str(e)}", []


st.set_page_config(page_title="长对话分析", page_icon="📜", layout="wide")

st.title("📜 长对话深度分析与归档")
st.markdown("---")

if "lc_session_id" not in st.session_state:
    st.session_state.lc_session_id = str(uuid.uuid4())
if "input_text_content" not in st.session_state:
    st.session_state.input_text_content = ""

# Sidebar: Character Selection
st.sidebar.header("已知角色 (Known Characters)")

if st.sidebar.button("🔄 刷新角色列表"):
    st.rerun()
if st.sidebar.button("🆕 新对话"):
    st.session_state.lc_session_id = str(uuid.uuid4())
    keys_to_clear = [
        "analysis_result",
        "input_text_content",
        "uploaded_text_content",
        "diarization_result",
        "main_text_area",
        "analyzed_text_content",
        "lc_char_select",
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]
    for k in list(st.session_state.keys()):
        if k.startswith("lc_feedback_"):
            del st.session_state[k]
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
    default=["我"],
    key="lc_char_select",
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
web_file_path = None  # To track downloaded file

with tab1:
    uploaded_file = st.file_uploader(
        "支持 .txt, .md 文本; .wav, .mp3, .m4a 音频; .mp4, .mov, .avi, .mkv 视频",
        type=["txt", "md", "wav", "mp3", "m4a", "mp4", "mov", "avi", "mkv"],
    )

    # Cleanup state if file is removed
    if uploaded_file is None:
        if "uploaded_text_content" in st.session_state:
            del st.session_state.uploaded_text_content
            st.rerun()  # Rerun to update UI label


with tab2:
    st.info(
        "支持主流视频网站链接 (YouTube, Bilibili等)。将自动下载并提取音频进行分析。"
    )
    media_url = st.text_input("🔗 输入视频/音频 URL (Enter URL)")
    if st.button(
        "🚀 下载并开始分析 (Download & Analyze)", type="primary", key="btn_web_dl"
    ):
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
target_file_path = web_file_path  # For web downloaded files, we have a path string

if target_file is not None or target_file_path is not None:
    # Determine file info
    if target_file:
        file_name = target_file.name
        file_ext = file_name.split(".")[-1].lower()
    else:
        file_name = os.path.basename(target_file_path)
        file_ext = file_name.split(".")[-1].lower()

    # Case 1: Text File (Only supports upload for now, web usually gives video/audio)
    if file_ext in ["txt", "md"] and target_file:
        try:
            content = target_file.read().decode("utf-8")
            # User Requirement: If text file uploaded, read directly, input box is supplementary.
            # So we store it separately and don't overwrite the main text area.
            st.session_state.uploaded_text_content = content
            st.success(f"📄 已加载文本文件: {file_name} ({len(content)} 字符)")
            st.info(
                "💡 提示: 文件内容将直接用于分析。下方的输入框已切换为【补充说明/指令】模式。"
            )

            # Clear input_text_content to avoid confusion if it had old data,
            # or keep it if user wants to use it as supplementary?
            # Let's keep it but maybe clear it if it was from previous run?
            # Safer to just let user decide.
        except Exception as e:
            st.error(f"文件读取失败: {e}")

    # Case 2: Audio File (WAV, MP3, M4A)
    elif file_ext in ["wav", "mp3", "m4a"]:
        st.info(f"🎤 已加载音频文件: {file_name}")

        # Auto-start for web download, Button for upload
        start_analysis = False
        if target_file_path:  # Web download
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
                            res = requests.post(
                                f"{API_URL}/audio/diarization", files=files
                            )

                    if res.status_code == 200:
                        st.session_state.diarization_result = res.json()

                        # Auto-populate text with default names
                        raw_segments = st.session_state.diarization_result.get(
                            "raw_segments", []
                        )
                        initial_text = ""
                        for seg in raw_segments:
                            initial_text += (
                                f"【{seg['speaker_name']}】: {seg['text']}\n"
                            )

                        st.session_state.input_text_content = initial_text
                        st.session_state.main_text_area = (
                            initial_text  # Sync widget state
                        )

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
    elif file_ext in ["mp4", "mov", "avi", "mkv"]:
        st.info(f"🎥 已加载视频文件: {file_name}")

        start_analysis = False
        if target_file_path:
            start_analysis = (
                True  # Web download usually gives wav if forced, but if not
            )
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
                        with tempfile.NamedTemporaryFile(
                            delete=False, suffix=f".{file_ext}"
                        ) as tmp_video:
                            tmp_video.write(target_file.getvalue())
                            tmp_video_path = tmp_video.name
                    else:
                        tmp_video_path = target_file_path

                    try:
                        # 2. Extract Audio
                        output_dir = Path(tempfile.gettempdir())
                        success, _, audio_path_extracted = extract_audio_ffmpeg(
                            tmp_video_path, output_dir, audio_format="wav"
                        )

                        if not success:
                            st.error(f"音频提取失败: {audio_path_extracted}")
                        else:
                            st.success(
                                f"音频提取成功: {Path(audio_path_extracted).name}"
                            )

                            # 3. Call Diarization API
                            with open(audio_path_extracted, "rb") as f:
                                files = {"file": (f"{file_name}.wav", f, "audio/wav")}
                                res = requests.post(
                                    f"{API_URL}/audio/diarization", files=files
                                )

                            if res.status_code == 200:
                                st.session_state.diarization_result = res.json()

                                # Auto-populate text with default names
                                raw_segments = st.session_state.diarization_result.get(
                                    "raw_segments", []
                                )
                                initial_text = ""
                                for seg in raw_segments:
                                    initial_text += (
                                        f"【{seg['speaker_name']}】: {seg['text']}\n"
                                    )

                                st.session_state.input_text_content = initial_text
                                st.session_state.main_text_area = (
                                    initial_text  # Sync widget state
                                )

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
                    other_chars = [
                        c for c in char_names if c not in selected_char_names
                    ]

                    # Options: Unknown, New, [Selected Chars], [Other Chars]
                    options = (
                        ["不指定 (Unknown)", "新建角色..."]
                        + selected_char_names
                        + other_chars
                    )

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

                            selected = st.selectbox(
                                "映射为:", options, index=default_idx, key=sel_key
                            )

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
                        st.session_state.main_text_area = final_text  # Force sync
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
    if (
        "uploaded_text_content" in st.session_state
        and st.session_state.uploaded_text_content
    ):
        final_text = st.session_state.uploaded_text_content
        if text_input and text_input.strip():
            final_text += f"\n\n【补充说明】\n{text_input}"
    else:
        final_text = text_input

    if not final_text:
        st.warning("请先输入内容或上传文本文件。")
    else:
        # Store for feedback
        st.session_state.analyzed_text_content = final_text
        with st.spinner("正在分析中 (Analyzing)..."):
            try:
                actual_char_names = [
                    name for name in selected_char_names if name in char_options
                ]
                history_records = load_history_from_api(actual_char_names)

                # Load raw dialogue history (User requested "reference to historical speech")
                raw_dialogue_history = load_raw_dialogue_logs(
                    actual_char_names, char_options, limit=-1
                )

                # Take recent summaries for context
                recent_history = []
                for r in history_records:
                    summary_val = r.get("summary")
                    if not summary_val:
                        summary_val = (r.get("structured_data") or {}).get("summary")
                    if not summary_val and r.get("markdown_report"):
                        summary_val = r.get("markdown_report")[:200]
                    if summary_val:
                        recent_history.append(
                            {"timestamp": r.get("created_at"), "summary": summary_val}
                        )

                payload = {
                    "text": final_text,
                    "character_names": selected_char_names,
                    "history_context": recent_history,
                    "character_profiles": [
                        char_options[name]
                        for name in selected_char_names
                        if name in char_options
                    ],
                    "dialogue_history": raw_dialogue_history,
                }
                res = requests.post(f"{API_URL}/analysis/conversation", json=payload)

                if res.status_code == 200:
                    analysis_result = res.json()
                    st.session_state.analysis_result = analysis_result

                    # Persistence is now handled by the backend (saved to DB)
                    if "log_id" in analysis_result:
                        st.success(
                            f"分析完成并已保存记录 (ID: {analysis_result['log_id']})！"
                        )
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
    # 0. Data Prep & Definition
    structured_data = result.get("structured_data", {})
    # Support both keys just in case
    char_analysis_list = (
        structured_data.get("characters", [])
        or structured_data.get("character_analysis", [])
        or result.get("analysis", [])
    )
    overall_summary = result.get("overall_analysis", {}).get(
        "summary", ""
    ) or result.get("summary", "")

    if char_analysis_list:
        st.subheader("🧩 详细画像提取与归档 (Deep Profile Extraction & Archiving)")
        st.caption("以下数据已从思考报告中结构化提取，可用于更新角色档案。")

        # Get existing characters for dropdown
        existing_chars = []
        try:
            res_chars = requests.get(f"{API_URL}/characters")
            if res_chars.status_code == 200:
                existing_chars = res_chars.json()
        except:
            pass
        char_options = {
            c["name"]: c for c in existing_chars
        }  # Ensure char_options is fresh

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
                st.write(
                    f"📊 检测到 {len(char_analysis_list)} 个角色数据，其中 {matched_count} 个已自动匹配现有档案。"
                )

            with col_batch_btn:
                btn_batch_archive = st.button(
                    "📦 批量归档所有匹配角色", type="primary", use_container_width=True
                )

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
                        profile_update = item.get("profile_update") or item.get(
                            "metrics", {}
                        )
                        if isinstance(profile_update, dict):
                            profile_update = profile_update.copy()
                            if "character_arc" in item:
                                profile_update["character_arc"] = item["character_arc"]

                        deep_intent = item.get("deep_intent", "未检测到")
                        strategies = item.get("strategy") or item.get("strategies", [])
                        if isinstance(strategies, list):
                            strategies = ", ".join(strategies)

                        # 2. Event Data
                        evt_summary = profile_update.get("timeline_summary")
                        if not evt_summary:
                            evt_summary = (
                                f"参与对话分析。意图: {deep_intent}。策略: {strategies}"
                            )

                        event_data = {
                            "summary": evt_summary,
                            "intent": deep_intent,
                            "strategy": strategies,
                            "session_id": result.get("log_id", "manual_analysis"),
                            "version_note": "Batch Analysis Archive",
                        }

                        # 3. Call Unified Function
                        success, msg, updated_dims = perform_character_archive(
                            API_URL,
                            target_char["id"],
                            target_char["name"],
                            profile_update,
                            event_data,
                        )

                        if success:
                            success_count += 1
                            logs.append(f"✅ [{c_name}] {msg}")
                        else:
                            fail_count += 1
                            logs.append(f"❌ [{c_name}] {msg}")

                    except Exception as e:
                        fail_count += 1
                        logs.append(f"❌ [{c_name}] 归档失败: {e}")
                else:
                    fail_count += 1
                    logs.append(f"⚠️ [{c_name}] 未找到匹配档案，跳过")

                progress_bar.progress((idx + 1) / len(char_analysis_list))

            if success_count > 0:
                st.success(
                    f"批量归档完成！成功: {success_count}, 失败/跳过: {fail_count}"
                )
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
            if isinstance(strategies, list):
                strategies = ", ".join(strategies)
            mood = item.get("mood") or item.get("emotions", [])
            if isinstance(mood, list):
                mood = ", ".join(mood)

            profile_update = item.get("profile_update") or item.get("metrics", {})
            if isinstance(profile_update, dict):
                profile_update = profile_update.copy()
                if "character_arc" in item:
                    profile_update["character_arc"] = item["character_arc"]

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
                    st.caption(
                        "以下是从对话中提取的六维深度数据，点击归档将同步至人物档案。"
                    )

                    # 7 Dimensions Tabs
                    tab_names = [
                        "1️⃣ 基础属性",
                        "2️⃣ 表层行为",
                        "3️⃣ 情绪特征",
                        "4️⃣ 认知决策",
                        "5️⃣ 人格特质",
                        "6️⃣ 核心本质",
                        "7️⃣ 人物弧光",
                    ]
                    tabs = st.tabs(tab_names)

                    # Helper to display dimension data
                    def display_dim(tab, key, label):
                        with tab:
                            data_obj = profile_update.get(key, {})
                            if isinstance(data_obj, dict) and "data" in data_obj:
                                content = data_obj.get("data", {})
                                desc = data_obj.get("desc", f"{label}更新")
                            else:
                                content = data_obj
                                desc = f"{label}更新"

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
                    d7_data = display_dim(tabs[6], "character_arc", "人物弧光")

                # Archiving Action UI
                st.markdown("---")
                st.markdown("##### 📥 归档操作")

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
                    other_chars = sorted(
                        [
                            c
                            for c in char_options.keys()
                            if c != (matched_char["name"] if matched_char else "")
                        ]
                    )
                    opts.extend([f"👤 {c}" for c in other_chars])

                    sel_label = st.selectbox(
                        f"归档目标 (Target)",
                        opts,
                        key=f"archive_sel_{i}",
                        label_visibility="collapsed",
                    )

                    if "🆕 新建角色..." in sel_label:
                        archive_mode = "New"
                        new_char_name_input = st.text_input(
                            "输入新角色名称:", value=char_name, key=f"new_name_{i}"
                        )
                    elif "✅" in sel_label:
                        archive_mode = "Existing"
                        target_char_obj = matched_char
                    else:
                        archive_mode = "Existing"
                        selected_name = sel_label.replace("👤 ", "")
                        target_char_obj = char_options.get(selected_name)

                with col_action:
                    btn_clicked = st.button(
                        "🚀 执行归档",
                        key=f"do_archive_{i}",
                        type="primary",
                        use_container_width=True,
                    )

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
                                "system_prompt": f"You are {new_char_name_input}.",  # Basic init
                                "attributes": {},
                                "traits": {},
                            }
                            res_create = requests.post(
                                f"{API_URL}/characters", json=create_payload
                            )
                            if res_create.status_code == 200:
                                target_char_obj = res_create.json()
                                st.toast(
                                    f"✅ 新角色 [{new_char_name_input}] 创建成功！"
                                )
                            else:
                                st.error(f"创建角色失败: {res_create.text}")
                                st.stop()

                        if target_char_obj:
                            target_name = target_char_obj["name"]

                            # Prepare Event Data
                            timeline_summary = profile_update.get("timeline_summary")
                            if not timeline_summary:
                                timeline_summary = (
                                    overall_summary[:50] + "..."
                                    if overall_summary
                                    else "对话分析归档"
                                )

                            event_data = {
                                "summary": timeline_summary,
                                "intent": deep_intent,
                                "strategy": strategies,
                                "session_id": result.get("log_id", "manual_analysis"),
                                "version_note": "来自深度对话分析(六维画像归档)",
                            }

                            # Call Unified Function
                            success, msg, _ = perform_character_archive(
                                API_URL,
                                target_char_obj["id"],
                                target_name,
                                profile_update,
                                event_data,
                            )

                            if success:
                                st.toast(f"✅ 已成功更新 {target_name} 的六维档案！")
                                st.success(f"归档成功！数据已合并至 [{target_name}]。")
                            else:
                                st.error(f"归档失败: {msg}")
                        else:
                            st.error("无法确定目标角色，归档失败。")

                    except Exception as e:
                        st.error(f"归档过程异常: {e}")

    else:
        # 调试信息
        st.write("调试信息：分析结果的结构")
        st.write(result)
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
    st.caption(
        "将本次分析结果（摘要/报告）归档到指定角色的时间线或档案中。支持多角色批量归档。"
    )

    # Universal Archive Container
    with st.container():
        # Prepare Archive Data
        archive_content = overall_summary
        if not archive_content:
            if "markdown_report" in result:
                archive_content = result["markdown_report"][:200] + "..."
            else:
                archive_content = st.session_state.input_text_content[:200] + "..."

        # --- Multi-Character Selection Logic ---
        detected_names = [
            item.get("name") for item in char_analysis_list if item.get("name")
        ]

        # Pre-select detected characters if they exist in DB
        default_selections = []
        for name in detected_names:
            if name in char_options:
                default_selections.append(name)

        # Filter valid options from DB
        all_char_names = sorted(list(char_options.keys()))

        col_univ_target, col_univ_action = st.columns([3, 1])

        with col_univ_target:
            selected_targets = st.multiselect(
                "选择归档目标 (可多选，默认选中分析检测到的角色)",
                options=all_char_names,
                default=default_selections,
                key="univ_archive_multiselect",
            )

            # Show warning for detected but missing characters
            missing_chars = [
                name for name in detected_names if name not in char_options
            ]
            if missing_chars:
                st.warning(f"⚠️ 检测到未注册角色: {', '.join(missing_chars)}")
                # Option to auto-create missing could be added here, but keeping it simple for now
                # Or provide a quick create button?
                cols_missing = st.columns(len(missing_chars))
                for idx, m_name in enumerate(missing_chars):
                    if cols_missing[idx].button(
                        f"➕ 创建 '{m_name}'", key=f"create_missing_{idx}"
                    ):
                        try:
                            create_payload = {
                                "name": m_name,
                                "system_prompt": f"You are {m_name}.",
                                "attributes": {},
                                "traits": {},
                            }
                            res_create = requests.post(
                                f"{API_URL}/characters", json=create_payload
                            )
                            if res_create.status_code == 200:
                                st.toast(
                                    f"✅ 新角色 [{m_name}] 创建成功！请刷新页面或重新选择。"
                                )
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error(f"创建失败: {res_create.text}")
                        except Exception as e:
                            st.error(f"Error: {e}")

        with col_univ_action:
            st.write("")  # Spacer
            st.write("")
            btn_univ_archive = st.button(
                "🚀 批量归档 (Batch Archive)",
                key="btn_univ_archive",
                type="primary",
                use_container_width=True,
            )

        if btn_univ_archive:
            if not selected_targets:
                st.error("请至少选择一个归档目标角色！")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()

                success_count = 0
                fail_count = 0

                for idx, target_name in enumerate(selected_targets):
                    status_text.text(f"正在处理: {target_name}...")
                    try:
                        target_char_obj = char_options.get(target_name)

                        if target_char_obj:
                            # Prepare data
                            profile_update = {}
                            found_struct = next(
                                (
                                    item
                                    for item in char_analysis_list
                                    if item.get("name") == target_name
                                ),
                                None,
                            )

                            # If found specific analysis for this character, use it
                            if found_struct:
                                profile_update = found_struct.get(
                                    "profile_update"
                                ) or found_struct.get("metrics", {})
                                if isinstance(profile_update, dict):
                                    profile_update = profile_update.copy()
                                    if "character_arc" in found_struct:
                                        profile_update["character_arc"] = found_struct[
                                            "character_arc"
                                        ]
                                        # Auto-extract timeline summary from Arc
                                        if (
                                            isinstance(
                                                found_struct["character_arc"], dict
                                            )
                                            and "event" in found_struct["character_arc"]
                                        ):
                                            profile_update["timeline_summary"] = (
                                                found_struct["character_arc"]["event"]
                                            )

                            event_data = {
                                "summary": f"对话分析归档: {archive_content[:100]}...",
                                "intent": "Manual Archive",
                                "strategy": "Analysis",
                                "session_id": result.get("log_id", "manual_analysis"),
                                "version_note": "Universal Analysis Archive",
                            }

                            success, msg, updated_dims = perform_character_archive(
                                API_URL,
                                target_char_obj["id"],
                                target_char_obj["name"],
                                profile_update,
                                event_data,
                            )

                            if success:
                                success_count += 1
                                # st.toast(f"✅ [{target_name}] 归档成功！")
                            else:
                                fail_count += 1
                                st.error(f"[{target_name}] 归档失败: {msg}")
                        else:
                            fail_count += 1
                            st.error(f"[{target_name}] 角色对象未找到。")

                    except Exception as e:
                        fail_count += 1
                        st.error(f"[{target_name}] 处理异常: {e}")

                    progress_bar.progress((idx + 1) / len(selected_targets))

                status_text.text("处理完成！")
                st.success(f"批量归档完成！成功: {success_count}, 失败: {fail_count}")
                if success_count > 0:
                    st.balloons()

    st.markdown("---")
    st.subheader("📊 质量反馈与进化 (Feedback & Evolution)")
    st.caption(
        "您的反馈将帮助系统进化。差评 (<=2星) 将自动触发‘复盘分析’并生成微调数据。"
    )

    feedback_log_id = result.get("log_id", "manual_analysis")
    rating_key = f"lc_feedback_rating_{feedback_log_id}"
    comment_key = f"lc_feedback_comment_{feedback_log_id}"
    if rating_key not in st.session_state:
        st.session_state[rating_key] = 5
    if comment_key not in st.session_state:
        st.session_state[comment_key] = ""

    with st.form(f"feedback_form_{feedback_log_id}", clear_on_submit=False):
        col_f1, col_f2 = st.columns([1, 3])
        with col_f1:
            rating = st.select_slider(
                "评分 (Rating)",
                options=[1, 2, 3, 4, 5],
                value=st.session_state[rating_key],
                key=rating_key,
            )
        with col_f2:
            comment = st.text_area(
                "建议/吐槽 (Optional comment)", key=comment_key, height=120
            )

        submitted = st.form_submit_button("提交反馈 (Submit)")
        if submitted:
            feedback_input = st.session_state.get(
                "analyzed_text_content", st.session_state.get("input_text_content", "")
            )

            feedback_payload = {
                "session_id": st.session_state.get("lc_session_id", "manual_analysis"),
                "user_input": feedback_input[:5000],
                "model_output": json.dumps(result, ensure_ascii=False, default=str),
                "rating": rating,
                "comment": comment,
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
