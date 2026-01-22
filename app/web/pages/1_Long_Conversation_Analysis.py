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
            
            # Use index in expander key to avoid duplicate ID errors
            with st.expander(f"🎭 {char_name} 归档面板", expanded=False):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**🎯 意图**: {deep_intent}")
                    st.markdown(f"**♟️ 策略**: {strategies}")
                with col2:
                    st.markdown(f"**😊 情绪**: {mood}")
                
                # Archiving Action
                # Find the character ID if it exists in our DB
                char_obj = char_options.get(char_name)
                if char_obj:
                    btn_key = f"archive_btn_{char_obj['id']}_{i}"
                    if st.button(f"📥 归档到 {char_name}", key=btn_key):
                        # Logic to update character profile
                        new_profile = char_obj.get("dynamic_profile", {}) or {}
                        
                        # Append to background
                        current_bg = new_profile.get("background", "")
                        
                        # Richer archive content
                        archive_content = f"""
                        \n--- [深度分析归档 {text_input[:10]}...] ---
                        【意图】{deep_intent}
                        【策略】{strategies}
                        【情绪】{mood}
                        【小结】{overall_summary}
                        """
                        new_profile["background"] = (current_bg or "") + archive_content
                        
                        # Merge personality tags (simple append for now)
                        # current_tags = new_profile.get("personality_tags", []) ...
                            
                        # Update Request
                        update_payload = {
                            "dynamic_profile": new_profile,
                            "version_note": "来自深度对话分析(Thinking-Driven)的归档"
                        }
                        
                        try:
                            up_res = requests.put(f"{API_URL}/characters/{char_obj['id']}", json=update_payload)
                            if up_res.status_code == 200:
                                st.toast(f"✅ 已成功更新 {char_name} 的档案！")
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
