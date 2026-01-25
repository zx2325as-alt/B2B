import streamlit as st
import threading
import queue
import time
import requests
import pyaudio
import wave
import uuid
import os
import json
import audioop
import numpy as np
from datetime import datetime
from pathlib import Path
from app.core.config import settings
from app.services.voice_profile import VoiceProfileService
from app.utils.history_utils import HistoryService

# ==========================================
# 1. Configuration & Global State
# ==========================================
st.set_page_config(page_title="实时语音分析", page_icon="🎙️", layout="wide")

API_URL = settings.API_URL
CHUNK_DURATION = 5  # Increased to 5s for better recognition accuracy
SAMPLE_RATE = 16000
CHANNELS = 1
HISTORY_FILE = Path(settings.DATA_DIR) / "analysis_history.jsonl"

# CSS Styling
st.markdown("""
<style>
    .stMetric { background-color: #f0f2f6; padding: 10px; border-radius: 5px; }
    .speaker-tag { font-size: 1.2em; font-weight: bold; color: #1f77b4; }
    .emotion-tag { font-size: 1em; color: #ff7f0e; }
    .log-container { max-height: 600px; overflow-y: auto; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. Audio Capture Engine (Producer-Consumer)
# ==========================================
class AudioCaptureManager:
    """
    Manages background audio recording (Producer) and processing (Consumer).
    Uses a Queue to decouple recording from API calls, enabling overlap processing.
    """
    def __init__(self):
        self.is_recording = False
        self.record_thread = None
        self.process_thread = None
        self.stop_event = threading.Event()
        self.device_index = None
        
        # Audio Queue for Overlap Processing
        self.audio_queue = queue.Queue()
        
        # Shared State
        self.logs = HistoryService.load_history(50) 
        self.last_status = ""
        self.current_volume = 0.0 # RMS value (0-100 normalized approx)
        self.known_characters = [] # Cache for known characters to avoid calling st.cache_data in thread
        
        # Stats
        self.session_id = str(uuid.uuid4())[:8]

    def update_known_characters(self, characters: list):
        """Update the list of known characters (Thread-safe update from main thread)"""
        self.known_characters = characters

    def start_recording(self, device_index):
        if self.is_recording:
            return
        
        self.is_recording = True
        self.stop_event.clear()
        self.device_index = device_index
        
        # Start Threads
        self.record_thread = threading.Thread(target=self._record_loop, daemon=True)
        self.process_thread = threading.Thread(target=self._process_loop, daemon=True)
        
        self.record_thread.start()
        self.process_thread.start()
        
        self.last_status = "🚀 录音与处理线程已启动 (Overlap Mode)..."

    def stop_recording(self):
        if not self.is_recording:
            return
            
        self.is_recording = False
        self.stop_event.set()
        
        # Wait for threads
        if self.record_thread:
            self.record_thread.join(timeout=1)
            self.record_thread = None
            
        # Note: We don't join process_thread immediately to allow it to finish queue
        self.last_status = "🛑 录音已停止"

    def _record_loop(self):
        """Producer: Captures audio and puts chunks into queue"""
        p = pyaudio.PyAudio()
        stream = None
        try:
            stream = p.open(format=pyaudio.paInt16,
                            channels=CHANNELS,
                            rate=SAMPLE_RATE,
                            input=True,
                            input_device_index=self.device_index,
                            frames_per_buffer=1024)
            
            self.last_status = f"🎙️ 正在监听设备 ID: {self.device_index}"
            
            while not self.stop_event.is_set():
                frames = []
                chunk_frames = int(SAMPLE_RATE / 1024 * CHUNK_DURATION)
                
                chunk_rms = []
                
                for _ in range(chunk_frames):
                    if self.stop_event.is_set():
                        break
                    try:
                        data = stream.read(1024, exception_on_overflow=False)
                        frames.append(data)
                        # Calculate RMS for this small frame
                        rms = audioop.rms(data, 2)
                        chunk_rms.append(rms)
                    except Exception as read_err:
                        print(f"Read error: {read_err}")
                        break
                
                # Update current volume (Average RMS of this chunk)
                if chunk_rms:
                    avg_rms = sum(chunk_rms) / len(chunk_rms)
                    # Normalize roughly (0-32768 is theoretical max for 16-bit)
                    # Map to 0-100 for UI
                    self.current_volume = min(100.0, (avg_rms / 3000.0) * 100)

                if frames:
                    # Put raw bytes into queue for processing
                    self.audio_queue.put(b''.join(frames))
                    
        except Exception as e:
            self.last_status = f"❌ 录音错误: {str(e)}"
            self.is_recording = False
        finally:
            if stream:
                try: stream.stop_stream(); stream.close()
                except: pass
            p.terminate()

    def _process_loop(self):
        """Consumer: Reads from queue and calls API"""
        while True:
            try:
                # Get audio data with timeout to allow checking stop_event
                audio_data = self.audio_queue.get(timeout=1) 
            except queue.Empty:
                if not self.is_recording and self.audio_queue.empty():
                    break
                continue
            
            if audio_data:
                self.last_status = f"⚡ 正在分析片段 (Queue: {self.audio_queue.qsize()})..."
                self._process_chunk(audio_data)
                self.audio_queue.task_done()

    def _process_chunk(self, audio_data):
        filename = f"rt_{self.session_id}_{uuid.uuid4().hex[:6]}.wav"
        try:
            # 1. Write temp file (Assuming Int16, 16kHz, Mono)
            wf = wave.open(filename, 'wb')
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2) # 2 bytes for Int16
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_data)
            wf.close()
            
            # 2. Send to Backend
            with open(filename, "rb") as f:
                files = {"file": (filename, f, "audio/wav")}
                start_t = time.time()
                try:
                    res = requests.post(f"{API_URL}/audio/transcribe", files=files, timeout=60)
                    latency = time.time() - start_t
                except requests.exceptions.Timeout:
                    self.last_status = "⚠️ 请求超时 (Backend Timeout)"
                    return
                except Exception as req_err:
                    self.last_status = f"⚠️ 请求错误: {req_err}"
                    return
            
            # 3. Handle Result
            if res.status_code == 200:
                data = res.json()
                text = data.get("text", "").strip()
                
                if not text:
                    self.last_status = "... (静音/无语音)"
                else:
                    # 3.1 Immediate Display (Predictive/Partial Translation Feel)
                    # Create log entry immediately with available data
                    log_id = str(uuid.uuid4())
                    log_entry = {
                        "id": log_id,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "text": text,
                        "speaker": data.get("speaker_name", "Unknown"),
                        "emotion": data.get("top_emotion", "neutral"),
                        "latency": f"{latency:.2f}s",
                        "full_data": data,
                        "analysis": {} # Placeholder for deep analysis
                    }
                    
                    # Update UI & File
                    self.logs.append(log_entry)
                    HistoryService.append_log(log_entry)
                    self.last_status = "✅ 识别完成，正在深度分析..."
                    
                    # 3.2 Trigger Deep Analysis (Reuse BtB Core)
                    # We perform this AFTER updating UI so the user sees text immediately.
                    try:
                        # Fetch all characters to simulate "all present characters" context
                        # Use cached known_characters from self instead of calling st.cache_data function
                        all_chars = self.known_characters
                        char_names = [c["name"] for c in all_chars] if all_chars else []

                        speaker = data.get('speaker_name', 'Unknown')
                        # Refine context based on identity
                        if speaker in char_names:
                            context_text = f"【{speaker}】(角色) 说：{text}"
                        else:
                            context_text = f"【{speaker}】(外部用户/未知) 说：{text}"

                        # Construct payload for analysis
                        payload = {
                            "text": context_text,
                            "character_names": char_names, # Pass all characters for multi-role reaction
                            "mode": "deep", # Use deep mode for Inner OS & Emotion
                            "session_id": self.session_id,
                            "audio_features": data.get("features", {}) # Pass audio features (pitch, energy)
                        }
                        
                        ana_res = requests.post(f"{API_URL}/analysis/conversation", json=payload, timeout=60)
                        if ana_res.status_code == 200:
                            analysis_result = ana_res.json()
                            
                            # Update In-Memory Log
                            log_entry["analysis"] = analysis_result
                            
                            # Update File Persistence
                            HistoryService.update_log_entry(log_id, {"analysis": analysis_result})
                            
                            self.last_status = "✅ 深度分析完成"
                    except Exception as ana_err:
                        print(f"Analysis failed: {ana_err}")
                        self.last_status = f"⚠️ 分析失败: {ana_err}"

            else:
                self.last_status = f"⚠️ API 错误: {res.status_code}"

        except Exception as e:
            self.last_status = f"❌ 处理异常: {str(e)}"
        finally:
            if os.path.exists(filename):
                try: os.remove(filename)
                except: pass

    def update_log_text(self, log_id, new_text):
        """Update text for a specific log entry (User Correction)"""
        for log in self.logs:
            if log["id"] == log_id:
                log["text"] = new_text
                return True
        return False

@st.cache_resource
def get_manager():
    return AudioCaptureManager()

manager = get_manager()

# Robustness: Ensure new attributes exist on cached instance (Hot-fix for reload)
if not hasattr(manager, 'current_volume'):
    manager.current_volume = 0.0
if not hasattr(manager, 'known_characters'):
    manager.known_characters = []

# ==========================================
# 4. Helpers
# ==========================================
@st.cache_data(ttl=60)
def fetch_characters():
    """Fetch characters from backend for sync"""
    try:
        res = requests.get(f"{API_URL}/characters/")
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"Fetch chars error: {e}")
    return []

# Update manager's known characters in MAIN THREAD
chars = fetch_characters()
manager.update_known_characters(chars)

# ==========================================
# 5. Sidebar: Controls & Settings
# ==========================================
with st.sidebar:
    st.header("⚙️ 设置 (Settings)")
    
    # Device Selection
    device_options = {}
    try:
        p = pyaudio.PyAudio()
        info = p.get_host_api_info_by_index(0)
        numdevices = info.get('deviceCount')
        for i in range(0, numdevices):
            d_info = p.get_device_info_by_host_api_device_index(0, i)
            if d_info.get('maxInputChannels') > 0:
                device_options[i] = d_info.get('name')
        p.terminate()
    except Exception as e:
        st.error(f"无法加载音频设备: {e}")

    selected_device_idx = st.selectbox(
        "🎙️ 选择输入设备", 
        options=list(device_options.keys()), 
        format_func=lambda x: device_options[x],
        index=0
    )
    st.caption("提示: 录制系统声音请选择 'Stereo Mix' 或 'Loopback'。")
    
    st.divider()
    
    # Controls
    col_b1, col_b2 = st.columns(2)
    if col_b1.button("🔴 开始录制", type="primary", use_container_width=True):
        manager.start_recording(selected_device_idx)
        st.rerun()
        
    if col_b2.button("⬛ 停止录制", use_container_width=True):
        manager.stop_recording()
        st.rerun()
        
    # Status Indicator
    if manager.is_recording:
        st.success("🟢 正在录制中...")
        # Volume Meter
        vol = int(manager.current_volume)
        st.progress(vol, text=f"音量 (Volume): {vol}%")
    else:
        st.info("⚪ 等待开始")
        
    st.divider()
    
    # Speaker Management (Synced)
    st.subheader("👥 声纹库 (Voice Profiles)")
    if st.button("🔄 刷新"):
        st.rerun()
        
    # Load Profiles
    profile_service = VoiceProfileService() # Local instance for reading
    profiles = profile_service.get_all_speakers()
    
    # Load DB Characters
    db_chars = fetch_characters()
    char_names = [c["name"] for c in db_chars] if db_chars else []
    
    if profiles:
        st.write(f"已存 {len(profiles)} 个声纹")
        # Rename Interface
        spk_opts = {p["id"]: p["name"] for p in profiles}
        target_spk_id = st.selectbox("选择声纹 (Select Voice)", list(spk_opts.keys()), format_func=lambda x: spk_opts[x])
        
        current_name = spk_opts[target_spk_id]
        
        st.markdown("👇 **关联角色 (Bind Character)**")
        # If current name is in char_names, set index there
        try:
            default_idx = char_names.index(current_name)
        except ValueError:
            default_idx = 0
            
        selected_char = st.selectbox(
            "选择系统角色", 
            ["-- 不关联 (Custom) --"] + char_names,
            index=default_idx + 1 if current_name in char_names else 0
        )
        
        new_name = ""
        if selected_char != "-- 不关联 (Custom) --":
            new_name = selected_char
        else:
            new_name = st.text_input("自定义名称 (Custom Name)", value=current_name)
            
        if st.button("💾 保存设置 (Save)"):
            if new_name:
                profile_service.update_speaker_name(target_spk_id, new_name)
                st.success(f"已更新为: {new_name}")
                time.sleep(0.5)
                st.rerun()
    else:
        st.warning("暂无声纹数据")

    # System Test
    st.divider()
    with st.expander("🛠️ 系统自检 (Test)", expanded=False):
        if st.button("▶️ 生成测试语音"):
            if manager.is_recording:
                st.warning("请先停止录制")
            else:
                try:
                    res = requests.post(f"{API_URL}/audio/synthesize", data={"text": "测试语音分析功能是否正常。"})
                    if res.status_code == 200:
                        st.audio(res.content, format="audio/mp3")
                        # Simulate log
                        log_entry = {
                            "id": "test",
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "text": "测试语音分析功能是否正常。",
                            "speaker": "System Test",
                            "emotion": "neutral",
                            "latency": "0.1s",
                            "full_data": {}
                        }
                        manager.logs.append(log_entry)
                        HistoryService.append_log(log_entry)
                        st.success("测试通过，已生成日志")
                    else:
                        st.error("生成失败")
                except Exception as e:
                    st.error(f"Error: {e}")

    # ==========================================
    # 7. Voice Profile Management (CRUD)
    # ==========================================
    with st.expander("👤 声纹库管理 (Voice Profiles)", expanded=False):
        # 1. List
        st.subheader("声纹列表")
        
        # Load profiles directly via API or Service (Service is simpler here since we are in same app context usually, but web app should ideally use API. 
        # For simplicity and speed, we use Service class directly as per existing pattern in this file).
        # We need to re-instantiate service or access via manager if we want shared state, but profiles are file-based so new instance is fine.
        vp_service = VoiceProfileService()
        speakers = vp_service.get_all_speakers()
        
        if not speakers:
            st.info("暂无声纹数据")
        else:
            # Table
            grid_data = []
            for sp in speakers:
                grid_data.append({
                    "ID": sp["id"],
                    "Name": sp["name"],
                    "Created": datetime.fromtimestamp(sp.get("created_at", 0)).strftime("%Y-%m-%d %H:%M"),
                    "Vector Dim": len(sp.get("fingerprint", []))
                })
            st.dataframe(grid_data, use_container_width=True)
            
            # Edit / Delete
            c_edit, c_del = st.columns(2)
            
            with c_edit:
                st.markdown("#### 修改名称")
                edit_id = st.selectbox("选择声纹ID", [s["id"] for s in speakers], key="edit_sel")
                new_name_input = st.text_input("新名称", key="edit_name")
                if st.button("更新名称"):
                    if vp_service.update_speaker_name(edit_id, new_name_input):
                        st.success(f"已更新 {edit_id} -> {new_name_input}")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("更新失败")
            
            with c_del:
                st.markdown("#### 删除声纹")
                del_id = st.selectbox("选择声纹ID (删除)", [s["id"] for s in speakers], key="del_sel")
                if st.button("🗑️ 确认删除", type="primary"):
                    if vp_service.delete_speaker(del_id):
                        st.warning(f"已删除 {del_id}")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("删除失败")

# ==========================================
# 6. Main Area: Live Dashboard
# ==========================================
st.title("🎙️ 实时语音全链路分析")

# State for Logs
# Direct use of manager.logs (Shared Source of Truth)
logs = manager.logs

# Display latest status
if manager.last_status:
    st.toast(manager.last_status)

# --- Layout ---
# 1. Latest Analysis Card
if logs:
    latest = logs[-1]
    
    st.subheader("📊 实时监控 (Live Monitor)")
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🗣️ 说话人", latest["speaker"])
    c2.metric("😊 情绪", latest["emotion"])
    c3.metric("⏱️ 延迟", latest["latency"])
    c4.metric("📝 字数", len(latest["text"]))
    
    st.info(f"**识别内容**: {latest['text']}")
    
    # Acoustic Features Display
    with st.expander("📊 声学特征 (Acoustic Features)", expanded=True):
        feats = latest.get("full_data", {}).get("features", {})
        if feats:
            ac1, ac2, ac3 = st.columns(3)
            ac1.metric("🎵 音高 (Pitch)", f"{feats.get('pitch_mean', 0):.1f} Hz")
            ac2.metric("⚡ 能量 (Energy)", f"{feats.get('energy_mean', 0):.1f}")
            ac3.metric("📈 语速 (Speed)", f"{feats.get('speech_rate', 0):.1f} char/s")
            # st.json(feats) # Debug
        else:
            st.caption("暂无声学特征数据")

    # Correction & Rating UI moved to Admin Dashboard
    st.caption("评分与纠错请前往后台看板 (Admin Dashboard)")

else:
    st.info("👋 点击左侧 '开始录制' 启动分析...")

# 2. History Timeline
st.divider()
st.subheader("📝 历史记录 (Timeline)")

# Clear Button
if st.button("🗑️ 清空记录"):
    manager.logs.clear() # Clear memory
    HistoryService.clear_history() # Clear file
    st.rerun()

# Render Logs (Newest first)
for log in reversed(logs):
    with st.chat_message("user" if log["speaker"] == "User" else "assistant"):
        st.markdown(f"**{log['speaker']}** `[{log['timestamp']}]`")
        
        # Display Text & Emotion
        emotion_tag = f" *({log['emotion']})*" if log['emotion'] else ""
        rating_tag = f" | ⭐ {log['rating']}" if log.get('rating') else ""
        st.write(f"{log['text']}{emotion_tag}{rating_tag}")
        
        # Display Analysis Result (If available)
        if "analysis" in log and log["analysis"]:
            ana = log["analysis"]
            if "summary" in ana:
                st.info(f"💡 **分析摘要**: {ana['summary']}")
            if "observations" in ana and ana["observations"]:
                with st.expander("🔍 深度观察 (Observations)"):
                    for obs in ana["observations"]:
                        st.markdown(f"- {obs}")
        
        with st.expander("查看详细数据"):
            st.json(log.get("full_data", {}))
            
            # Acoustic Features Display
            features = log.get("full_data", {}).get("features", {})
            if features:
                st.markdown("#### 🔊 声学特征 (Acoustic Features)")
                col_af1, col_af2 = st.columns(2)
                with col_af1:
                    pitch = features.get("pitch", "N/A")
                    st.metric("🎵 音高 (Pitch)", f"{pitch:.2f} Hz" if isinstance(pitch, (int, float)) else pitch)
                with col_af2:
                    energy = features.get("energy", "N/A")
                    st.metric("⚡ 能量 (Energy)", f"{energy:.2f} dB" if isinstance(energy, (int, float)) else energy)

# ==========================================
# 5. Auto-Refresh Logic
# ==========================================
if manager.is_recording:
    time.sleep(1) # Refresh rate
    st.rerun()
