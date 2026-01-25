import streamlit as st
import requests
import uuid
import json
import chardet
from app.core.config import settings

# ==========================================
# 页面配置 (Page Configuration)
# ==========================================
st.set_page_config(page_title="BtB 通用助手", page_icon="🤖", layout="wide")

API_URL = settings.API_URL

# ==========================================
# 会话状态初始化 (Session State Initialization)
# ==========================================
if "gen_session_id" not in st.session_state:
    st.session_state.gen_session_id = str(uuid.uuid4())
if "gen_messages" not in st.session_state:
    st.session_state.gen_messages = []

# ==========================================
# 侧边栏：文件上传与设置 (Sidebar)
# ==========================================
with st.sidebar:
    st.header("🛠️ 通用助手设置")
    st.info("此页面为无角色设定的通用对话模式，支持文件分析与指令处理。")
    
    st.divider()
    
    st.subheader("📂 文件上传")
    uploaded_file = st.file_uploader("上传 txt/md 文件", type=["txt", "md"])
    file_content = ""
    file_info = ""
    
    if uploaded_file:
        try:
            bytes_data = uploaded_file.getvalue()
            # 自动检测编码
            detected = chardet.detect(bytes_data)
            encoding = detected['encoding'] or 'utf-8'
            
            try:
                file_content = bytes_data.decode(encoding)
            except:
                # 降级尝试
                try:
                    file_content = bytes_data.decode('utf-8')
                    encoding = 'utf-8'
                except:
                    file_content = bytes_data.decode('gbk', errors='ignore')
                    encoding = 'gbk (fallback)'
            
            st.success(f"已加载: {uploaded_file.name}")
            st.caption(f"编码: {encoding} | 大小: {len(bytes_data)} bytes")
            
            with st.expander("查看文件内容预览"):
                st.text(file_content[:1000] + ("..." if len(file_content) > 1000 else ""))
                
            file_info = f"【已加载文件】: {uploaded_file.name}\n"
        except Exception as e:
            st.error(f"文件读取失败: {e}")
            
    if st.button("🗑️ 清空对话"):
        st.session_state.gen_messages = []
        st.rerun()

    st.divider()
    st.subheader("🎙️ 语音交互 (Audio)")
    
    # TTS Toggle
    enable_tts = st.toggle("🔊 启用语音播报 (Enable TTS)", value=False)
    
    # Microphone Recorder
    try:
        from audiorecorder import audiorecorder
        st.caption("点击下方麦克风开始录音，再次点击停止。")
        audio = audiorecorder("🎤 点击开始录音", "⏹️ 点击停止录音")
        
        if len(audio) > 0:
            # Check if this audio is new (avoid reprocessing on rerun)
            # Use hash or length as simple check. For simplicity, we just check if it's non-empty and user hasn't sent it yet.
            # Ideally, we should add a 'Send' button or auto-send.
            # Let's provide a "Send Voice Message" button to confirm.
            
            st.audio(audio.export().read(), format="audio/wav")
            
            if st.button("📤 发送语音消息"):
                with st.spinner("正在处理语音消息..."):
                    try:
                        # Save to temp
                        temp_filename = f"mic_{uuid.uuid4()}.wav"
                        # audiorecorder returns pydub segment. export() returns a file-like object.
                        audio.export(temp_filename, format="wav")
                        
                        # Send to backend
                        with open(temp_filename, "rb") as f:
                            files = {"file": (temp_filename, f, "audio/wav")}
                            res = requests.post(f"{API_URL}/audio/transcribe", files=files)
                        
                        # Cleanup
                        import os
                        if os.path.exists(temp_filename):
                            os.remove(temp_filename)
                            
                        if res.status_code == 200:
                            data = res.json()
                            text = data.get("text", "")
                            emotion = data.get("top_emotion", "neutral")
                            
                            # Set session state to trigger LLM flow below
                            st.session_state.audio_input_text = text
                            st.session_state.audio_input_emotion = emotion
                            st.session_state.trigger_audio_send = True
                            st.rerun()
                        else:
                            st.error(f"识别失败: {res.text}")
                    except Exception as e:
                        st.error(f"处理异常: {e}")
                        
    except ImportError:
        st.warning("请安装 streamlit-audiorecorder 以使用麦克风功能。")
        st.code("pip install streamlit-audiorecorder")

    # Fallback / File Upload (Keep as option)
    with st.expander("📂 上传音频文件 (备用)"):
        audio_file = st.file_uploader("上传语音指令", type=["wav", "mp3", "m4a", "webm"])
        if audio_file and st.button("🔄 识别文件"):
             # ... (Same logic as before, omitted for brevity but could reuse)
             pass

# ==========================================
# 主界面 (Main Interface)
# ==========================================
st.title("🤖 BtB 通用智能助手")

# 1. 显示历史消息
for msg in st.session_state.gen_messages:
    role = msg["role"]
    content = msg["content"]
    avatar = "🧑‍💻" if role == "user" else "🤖"
    with st.chat_message(role, avatar=avatar):
        st.markdown(content)

# 2. 处理用户输入
# Check for audio input override
audio_input = st.session_state.get("audio_input_text", "")
if audio_input:
    # Clear it so it doesn't stick
    del st.session_state.audio_input_text

# Get chat input (returns None if not submitted)
chat_prompt = st.chat_input("请输入您的指令或问题...")

# Determine final prompt
prompt = None
if audio_input:
    prompt = audio_input
elif chat_prompt:
    prompt = chat_prompt

if prompt:
    # 显示用户消息
    display_content = prompt
    # If we have emotion from audio, append it for display context (optional)
    audio_emotion = st.session_state.get("audio_input_emotion")
    if audio_emotion:
         display_content += f" (🎙️ 情感: {audio_emotion})"
         # Clear emotion
         del st.session_state.audio_input_emotion
         
    st.session_state.gen_messages.append({"role": "user", "content": display_content})
    with st.chat_message("user", avatar="🧑‍💻"):
        st.markdown(display_content)

    # 构造请求上下文
    # 如果有文件内容，将其作为上下文注入
    final_input = prompt
    if file_content:
        final_input = f"【背景知识/文件内容】\n{file_content}\n\n【用户指令】\n{prompt}"
    
    # 调用 API
    with st.chat_message("assistant", avatar="🤖"):
        message_placeholder = st.empty()
        full_response = ""
        
        # 构造 Payload
        # 使用通用会话 ID，不绑定角色和场景
        payload = {
            "text": final_input,
            "user_id": "general_user",
            "session_id": st.session_state.gen_session_id,
            "character_id": None,
            "scenario_id": None
        }
        
        try:
            with requests.post(f"{API_URL}/chat", json=payload, stream=True) as r:
                if r.status_code == 200:
                    # 处理流式响应 (NDJSON)
                    for line in r.iter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                # 忽略 NLU 阶段的中间结果，只关注 response 或 reasoning
                                if "response" in data:
                                    content = data["response"]
                                    full_response = content
                                    message_placeholder.markdown(full_response + "▌")
                            except:
                                pass
                    
                    # 最终显示
                    message_placeholder.markdown(full_response)
                    st.session_state.gen_messages.append({"role": "assistant", "content": full_response})
                    
                    # TTS Playback
                    if enable_tts and full_response:
                        try:
                            with st.spinner("正在生成语音..."):
                                tts_res = requests.post(
                                    f"{API_URL}/audio/synthesize", 
                                    data={"text": full_response}
                                )
                                if tts_res.status_code == 200:
                                    st.audio(tts_res.content, format="audio/mp3")
                                else:
                                    st.warning("语音生成失败")
                        except Exception as e:
                            st.error(f"TTS Error: {e}")
                    
                else:
                    err_msg = f"服务请求失败: {r.text}"
                    message_placeholder.error(err_msg)
                    st.session_state.gen_messages.append({"role": "assistant", "content": err_msg})
                    
        except Exception as e:
            err_msg = f"连接异常: {e}"
            message_placeholder.error(err_msg)
            st.session_state.gen_messages.append({"role": "assistant", "content": err_msg})
