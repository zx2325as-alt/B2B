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
if prompt := st.chat_input("请输入您的指令或问题..."):
    # 显示用户消息
    st.session_state.gen_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="🧑‍💻"):
        st.markdown(prompt)

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
                                    # 如果是流式增量，可能需要拼接；但目前后端设计似乎是 chunk 返回完整文本或阶段性文本
                                    # 根据 endpoints.py 的逻辑，response 字段通常包含最终回复或 Thinking Process
                                    # 简单起见，我们直接更新显示
                                    full_response = content
                                    message_placeholder.markdown(full_response + "▌")
                            except:
                                pass
                    
                    # 最终显示
                    message_placeholder.markdown(full_response)
                    st.session_state.gen_messages.append({"role": "assistant", "content": full_response})
                    
                else:
                    err_msg = f"服务请求失败: {r.text}"
                    message_placeholder.error(err_msg)
                    st.session_state.gen_messages.append({"role": "assistant", "content": err_msg})
                    
        except Exception as e:
            err_msg = f"连接异常: {e}"
            message_placeholder.error(err_msg)
            st.session_state.gen_messages.append({"role": "assistant", "content": err_msg})
