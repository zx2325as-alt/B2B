import streamlit as st
import streamlit.components.v1 as components
import uuid
import time
import requests
import pandas as pd
from app.core.database import SessionLocal
from app.models.sql_models import ConversationSegment, Character, AnalysisLog
from app.core.config import settings

# Page Config
st.set_page_config(page_title="Realtime Recording", layout="wide")

API_URL = f"http://localhost:{settings.BACKEND_PORT}/api/v1"

# Session State
if "rt_session_id" not in st.session_state:
    st.session_state.rt_session_id = str(uuid.uuid4())

st.title("🎙️ 实时录音与分析 (Realtime Recording & Analysis)")

# Sidebar: Controls & Recorder
with st.sidebar:
    st.header("控制台 (Console)")
    st.caption(f"Session ID: {st.session_state.rt_session_id}")
    
    if st.button("🆕 新会话 (New Session)"):
        st.session_state.rt_session_id = str(uuid.uuid4())
        st.rerun()
    
    st.markdown("---")
    
    # Character Selection
    st.subheader("👥 在场角色 (Active Characters)")
    # Fetch characters
    char_names = ["Unknown"]
    all_chars_data = []
    try:
        chars_res = requests.get(f"{API_URL}/characters/")
        if chars_res.status_code == 200:
            all_chars_data = chars_res.json()
            char_names += [c["name"] for c in all_chars_data]
        else:
            st.error(f"Failed to load characters: {chars_res.status_code}")
    except Exception as e:
        st.error(f"Connection error: {e}")
        
    # Multiselect for active participants
    # "Default recognized person" - we can't easily guess, so we leave empty or user selects.
    active_chars = st.multiselect(
        "选择参与对话的角色 (Select Participants)", 
        [c for c in char_names if c != "Unknown"], 
        default=[]
    )
    
    # Store in session state for potential use
    st.session_state.active_chars = active_chars
        
    st.markdown("---")
    st.markdown("### 🔴 录音控制 (Recorder)")
    
    # Custom JS Component for Audio Recording
    ws_port = settings.BACKEND_PORT
    session_id = st.session_state.rt_session_id
    
    html_code = f"""
    <html>
    <head>
        <style>
            body {{ background-color: #f0f2f6; font-family: sans-serif; padding: 10px; }}
            .btn {{ padding: 10px 20px; color: white; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; width: 100%; margin-bottom: 5px; }}
            .btn-start {{ background: #ff4b4b; }}
            .btn-start:disabled {{ background: gray; cursor: not-allowed; }}
            .btn-stop {{ background: #333; }}
            .btn-stop:disabled {{ background: gray; cursor: not-allowed; }}
            #status {{ font-weight: bold; color: gray; margin-bottom: 10px; text-align: center; }}
        </style>
    </head>
    <body>
        <div id="status">Ready to Record</div>
        <button id="btn-start" class="btn btn-start" onclick="startRecording()">🎤 开始录音 (Start)</button>
        <button id="btn-stop" class="btn btn-stop" onclick="stopRecording()" disabled>⏹️ 停止 (Stop)</button>
        
        <script>
            let socket;
            let audioContext;
            let processor;
            let input;
            let isRecording = false;
            
            const wsUrl = "ws://localhost:{ws_port}/api/v1/ws/audio/{session_id}";
            
            function updateStatus(msg, color='black') {{
                const el = document.getElementById('status');
                el.innerText = msg;
                el.style.color = color;
            }}

            async function startRecording() {{
                try {{
                    updateStatus("Connecting...", "orange");
                    socket = new WebSocket(wsUrl);
                    socket.binaryType = 'arraybuffer';
                    
                    socket.onopen = () => {{
                        updateStatus("🔴 Recording...", "red");
                        initAudio();
                    }};
                    
                    socket.onclose = () => {{
                        if (isRecording) {{
                            updateStatus("Disconnected", "gray");
                            stopRecordingUI();
                        }}
                    }};
                    
                    socket.onerror = (e) => {{
                        console.error(e);
                        updateStatus("Connection Error", "red");
                    }};
                    
                    socket.onmessage = (event) => {{
                        // Received analysis result
                        console.log("Result received", JSON.parse(event.data));
                    }};
                    
                }} catch (e) {{
                    console.error(e);
                    updateStatus("Error: " + e, "red");
                }}
            }}

            async function initAudio() {{
                try {{
                    const stream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
                    
                    // Try to set sampleRate, but check actual rate later
                    audioContext = new (window.AudioContext || window.webkitAudioContext)({{ sampleRate: 16000 }});
                    const sourceRate = audioContext.sampleRate;
                    console.log("Audio Context Sample Rate:", sourceRate);

                    input = audioContext.createMediaStreamSource(stream);
                    
                    // Buffer size 4096
                    processor = audioContext.createScriptProcessor(4096, 1, 1);
                    
                    input.connect(processor);
                    processor.connect(audioContext.destination);
                    
                    processor.onaudioprocess = (e) => {{
                        if (!socket || socket.readyState !== WebSocket.OPEN) return;
                        
                        const inputData = e.inputBuffer.getChannelData(0);
                        let outputData = inputData;
                        
                        // Resample to 16000Hz if needed
                        if (sourceRate !== 16000) {{
                            const ratio = sourceRate / 16000;
                            const newLength = Math.floor(inputData.length / ratio);
                            const downsampled = new Float32Array(newLength);
                            
                            for (let i = 0; i < newLength; i++) {{
                                // Linear interpolation for better quality
                                const idx = i * ratio;
                                const intIdx = Math.floor(idx);
                                const frac = idx - intIdx;
                                
                                const p0 = inputData[intIdx];
                                const p1 = (intIdx + 1 < inputData.length) ? inputData[intIdx + 1] : p0;
                                
                                downsampled[i] = p0 * (1 - frac) + p1 * frac;
                            }}
                            outputData = downsampled;
                        }}

                        // Convert float32 to int16 PCM
                        const buffer = new ArrayBuffer(outputData.length * 2);
                        const view = new DataView(buffer);
                        for (let i = 0; i < outputData.length; i++) {{
                            let s = Math.max(-1, Math.min(1, outputData[i]));
                            view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true); // little-endian
                        }}
                        socket.send(buffer);
                    }};
                    
                    document.getElementById('btn-start').disabled = true;
                    document.getElementById('btn-stop').disabled = false;
                    isRecording = true;
                    
                }} catch (e) {{
                    console.error(e);
                    updateStatus("Audio Error: " + e.message, "red");
                }}
            }}

            function stopRecording() {{
                if (socket) socket.close();
                if (audioContext) audioContext.close();
                if (processor) processor.disconnect();
                if (input) input.disconnect();
                stopRecordingUI();
                updateStatus("Stopped", "gray");
                isRecording = false;
            }}
            
            function stopRecordingUI() {{
                document.getElementById('btn-start').disabled = false;
                document.getElementById('btn-stop').disabled = true;
            }}
        </script>
    </body>
    </html>
    """
    components.html(html_code, height=200)

    st.markdown("---")
    # Archive Button
    if st.button("💾 归档当前会话 (Archive Session)"):
        with st.spinner("Archiving..."):
            try:
                # Fetch segments
                db = SessionLocal()
                segments = db.query(ConversationSegment).filter(ConversationSegment.session_id == session_id).order_by(ConversationSegment.created_at).all()
                
                if segments:
                    # Construct Transcript
                    transcript = ""
                    analysis_summary = ""
                    for s in segments:
                        transcript += f"{s.speaker_name}: {s.text}\n"
                        if s.analysis:
                            # Extract summary or key insight
                            report = s.analysis.get("report", "")
                            if report:
                                analysis_summary += f"[{s.speaker_name}] Analysis: {report[:100]}...\n"
                    
                    # Create AnalysisLog
                    new_log = AnalysisLog(
                        session_id=session_id,
                        user_input=transcript,
                        bot_response=analysis_summary or "Realtime Session Archive",
                        scenario_id="realtime_recording",
                        character_id=None,
                        latency_ms=0
                    )
                    db.add(new_log)
                    db.commit()
                    st.success("Session Archived to Global Monitoring!")
                    time.sleep(1)
                    st.session_state.rt_session_id = str(uuid.uuid4())
                    st.rerun()
                else:
                    st.warning("No segments to archive.")
                db.close()
            except Exception as e:
                st.error(f"Archive failed: {e}")

# Main Area
st.info("💡 提示: 保持此页面开启以进行录音。如需实时查看分析结果而不中断录音，请在【新标签页】中打开 'Admin Dashboard > Core Monitoring'。")

# Simple Log View (Manual Refresh)
st.subheader("📝 当前会话日志 (Current Session Logs)")

# Auto-refresh mechanism
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = False

col_r1, col_r2, col_r3 = st.columns([1, 1, 3])
with col_r1:
    if st.button("🔄 刷新日志 (Refresh Logs)"):
        st.rerun()
with col_r2:
    auto_refresh = st.checkbox("⚡ 自动刷新 (Auto Refresh)", value=st.session_state.auto_refresh, key="chk_auto_refresh")
    # Update session state
    st.session_state.auto_refresh = auto_refresh

if st.session_state.auto_refresh:
    time.sleep(2)
    st.rerun()

# Optimize dropdown options
active = st.session_state.get("active_chars", [])
# char_names is available from the sidebar execution
if "char_names" not in locals():
    char_names = ["Unknown"]

# Construct sorted options: Unknown -> Active -> Others
others = [c for c in char_names if c not in active and c != "Unknown"]
dropdown_options = ["Unknown"] + active + others

db = SessionLocal()
segments = db.query(ConversationSegment).filter(ConversationSegment.session_id == session_id).order_by(ConversationSegment.created_at.desc()).all()
db.close()

if segments:
    for seg in segments:
        # Use speaker_name as label
        label = f"[{seg.speaker_name}] {seg.text[:50]}..."
        with st.expander(label, expanded=True):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(f"**Text:** {seg.text}")
                if seg.analysis:
                    st.markdown("**Analysis:**")
                    # Display report nicely
                    report = seg.analysis.get("report", "")
                    if report:
                        st.markdown(report)
                    else:
                        st.json(seg.analysis.get("structured", {}))
            with c2:
                st.caption(f"Emotion: {seg.emotion}")
                
                # Speaker Modification
                current_speaker = seg.speaker_name or "Unknown"
                # Index for selectbox
                try:
                    idx = dropdown_options.index(current_speaker)
                except ValueError:
                    idx = 0
                    
                new_speaker = st.selectbox(
                    "Assign Speaker", 
                    dropdown_options, 
                    index=idx, 
                    key=f"sel_spk_{seg.id}"
                )
                
                if new_speaker != current_speaker:
                    if st.button("Update & Re-analyze", key=f"btn_upd_{seg.id}"):
                        try:
                            # Call API to update
                            res = requests.put(
                                f"{API_URL}/segments/{seg.id}/speaker",
                                json={"speaker_name": new_speaker}
                            )
                            if res.status_code == 200:
                                st.success("Updated!")
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.error(f"Failed: {res.text}")
                        except Exception as e:
                            st.error(f"Error: {e}")
else:
    st.write("Waiting for speech...")
