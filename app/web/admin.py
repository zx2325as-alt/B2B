import streamlit as st
import requests
import json
import pandas as pd
from app.core.config import settings

API_URL = settings.API_URL

st.set_page_config(page_title="BtB 后台管理系统", layout="wide", page_icon="🛠️")
st.title("🛠️ BtB 系统后台管理看板")

tab1, tab2, tab3, tab4 = st.tabs(["🎭 场景管理", "👤 角色管理", "🔗 关系管理", "📊 核心监控 (Monitoring)"])

with tab4:
    col_header, col_btn = st.columns([8, 2])
    with col_header:
        st.header("系统核心监控与评估 (Monitoring & Eval)")
    with col_btn:
        if st.button("🔄 刷新数据 (Sync)", key="refresh_eval_logs"):
            st.rerun()

    st.markdown("在此监控系统核心指标，并对历史对话进行人工评分。")
    
    # 筛选器
    col_f1, col_f2 = st.columns(2)
    
    # 获取场景列表
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
        
    # 获取角色列表
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

    # 获取日志
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
                            # Rate form
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

with tab1:
    st.header("场景管理 (Scenario Management)")
    
    # 列表显示
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

    # 添加场景
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

with tab2:
    st.header("角色管理 (Character Management)")
    
    # Initialize session state for dialogs if not present
    if "edit_char_id" not in st.session_state:
        st.session_state.edit_char_id = None
    if "show_char_dialog" not in st.session_state:
        st.session_state.show_char_dialog = False

    # Fetch Characters
    chars = []
    try:
        response = requests.get(f"{API_URL}/characters/")
        if response.status_code == 200:
            chars = response.json()
    except Exception as e:
        st.error(f"无法获取角色列表: {e}")

    # --- Character Dialog/Form Logic ---
    if st.session_state.get("show_char_dialog", False):
        char_data = st.session_state.get("edit_char_data")
        is_edit = char_data is not None
        title = "编辑角色" if is_edit else "新增角色"
        
        with st.container(border=True):
            st.subheader(title)
            with st.form("char_form"):
                name = st.text_input("角色姓名", value=char_data["name"] if is_edit else "")
                
                # JSON Fields
                c1, c2 = st.columns(2)
                with c1:
                    attrs_val = json.dumps(char_data["attributes"], ensure_ascii=False, indent=2) if is_edit else '{\n  "age": 25,\n  "role": "user",\n  "occupation": "工程师"\n}'
                    attrs = st.text_area("基础属性 (JSON)", value=attrs_val, height=200)
                with c2:
                    traits_val = json.dumps(char_data["traits"], ensure_ascii=False, indent=2) if is_edit else '{\n  "personality": "friendly",\n  "tone": "formal"\n}'
                    traits = st.text_area("性格特征 (JSON)", value=traits_val, height=200)
                
                # Dynamic Profile (New Field)
                dyn_val = json.dumps(char_data.get("dynamic_profile", {}), ensure_ascii=False, indent=2) if is_edit else '{}'
                dyn_profile = st.text_area("动态画像 (Dynamic Profile - System Memory)", value=dyn_val, height=150, help="系统的核心'记忆'，由分析引擎不断更新")
                
                cols_btn = st.columns([1, 1])
                submitted = cols_btn[0].form_submit_button("保存提交")
                
                if submitted:
                    try:
                        payload = {
                            "name": name,
                            "attributes": json.loads(attrs),
                            "traits": json.loads(traits),
                            "dynamic_profile": json.loads(dyn_profile)
                        }
                        
                        if is_edit:
                            # Update
                            res = requests.put(f"{API_URL}/characters/{char_data['id']}", json=payload)
                        else:
                            # Create
                            res = requests.post(f"{API_URL}/characters/", json=payload)
                            
                        if res.status_code == 200:
                            st.success("操作成功！")
                            st.session_state.show_char_dialog = False
                            st.session_state.edit_char_data = None
                            st.rerun()
                        else:
                            st.error(f"失败: {res.text}")
                    except json.JSONDecodeError as e:
                        st.error(f"JSON 格式错误: {e}")
                    except Exception as e:
                        st.error(f"系统错误: {e}")
            
            if st.button("取消", key="cancel_char_edit"):
                st.session_state.show_char_dialog = False
                st.session_state.edit_char_data = None
                st.rerun()

    # --- Toolbar ---
    if not st.session_state.get("show_char_dialog", False):
        if st.button("➕ 新增角色", type="primary"):
            st.session_state.show_char_dialog = True
            st.session_state.edit_char_data = None
            st.rerun()

    # --- Character List ---
    if chars:
        # Display as a table with actions
        # Using columns to create a custom table layout
        header_cols = st.columns([1, 2, 2, 2, 2, 1.5])
        header_cols[0].markdown("**ID**")
        header_cols[1].markdown("**姓名**")
        header_cols[2].markdown("**版本**")
        header_cols[3].markdown("**更新时间**")
        header_cols[4].markdown("**操作**")
        
        st.divider()
        
        for char in chars:
            cols = st.columns([1, 2, 2, 2, 1, 1])
            cols[0].write(char["id"])
            cols[1].write(char["name"])
            cols[2].write(f"v{char.get('version', 1)}")
            cols[3].write(str(char.get("updated_at") or "")[:19])
            
            # Edit Button
            if cols[4].button("✏️", key=f"edit_{char['id']}"):
                st.session_state.show_char_dialog = True
                st.session_state.edit_char_data = char
                st.rerun()
                
            # Delete Button
            if cols[5].button("🗑️", key=f"del_{char['id']}"):
                try:
                    res = requests.delete(f"{API_URL}/characters/{char['id']}")
                    if res.status_code == 200:
                        st.success(f"已删除 {char['name']}")
                        st.rerun()
                    else:
                        st.error(f"删除失败: {res.text}")
                except Exception as e:
                    st.error(f"错误: {e}")
            
            # Expandable details
            with st.expander(f"查看 {char['name']} 详情"):
                st.json({
                    "Attributes": char["attributes"],
                    "Traits": char["traits"],
                    "Dynamic Profile": char.get("dynamic_profile", {})
                })
                
                # --- Timeline Visualization ---
                st.markdown("#### 📅 人物弧光 (Character Timeline)")
                try:
                    timeline_res = requests.get(f"{API_URL}/characters/{char['id']}/timeline")
                    if timeline_res.status_code == 200:
                        events = timeline_res.json()
                        if events:
                            for event in events:
                                date_str = event.get("event_date", "")[:10]
                                with st.container(border=True):
                                    t_col1, t_col2 = st.columns([1, 4])
                                    t_col1.caption(date_str)
                                    t_col1.markdown(f"**ID: {event['id']}**")
                                    
                                    t_col2.markdown(f"**{event.get('summary', 'No summary')}**")
                                    if event.get('intent'):
                                        t_col2.markdown(f"🎯 *Intent*: {event.get('intent')}")
                                    if event.get('strategy'):
                                        t_col2.markdown(f"♟️ *Strategy*: {event.get('strategy')}")
                        else:
                            st.info("该角色暂无时间线事件。")
                    else:
                        st.error("无法加载时间线数据")
                except Exception as e:
                    st.error(f"加载时间线出错: {e}")

    else:
        st.info("暂无角色数据，请点击上方按钮添加。")

with tab3:
    st.header("关系管理 (Relationship Management)")
    
    # Initialize session state for relationship editing
    if "edit_rel_data" not in st.session_state:
        st.session_state.edit_rel_data = None

    # Fetch Data
    chars = []
    relationships = []
    try:
        c_res = requests.get(f"{API_URL}/characters/")
        if c_res.status_code == 200:
            chars = c_res.json()
            
        r_res = requests.get(f"{API_URL}/characters/relationships/all")
        if r_res.status_code == 200:
            relationships = r_res.json()
    except:
        pass
        
    char_map = {c["id"]: c["name"] for c in chars}
    char_options = {c["name"]: c["id"] for c in chars}
    COMMON_RELATIONS = ["Friend", "Enemy", "Colleague", "Family", "Lover", "Stranger", "Master-Servant", "Rival"]
    
    # Layout: Left (List) | Right (Edit/Add)
    col_list, col_edit = st.columns([3, 2])
    
    # --- Right Column: Add/Edit Form ---
    with col_edit:
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
            st.markdown("##### 关系定义")
            
            s_col, t_col = st.columns(2)
            with s_col:
                # Find index for default value
                s_index = list(char_options.keys()).index(s_name_default) if s_name_default in char_options else 0
                source_name = st.selectbox("源角色 (Source)", options=list(char_options.keys()), index=s_index, key="rel_source")
            with t_col:
                t_index = list(char_options.keys()).index(t_name_default) if t_name_default in char_options else 0
                target_name = st.selectbox("目标角色 (Target)", options=list(char_options.keys()), index=t_index, key="rel_target")
                
            # Relationship Type
            current_type = rel_data.get("relation_type", "Friend") if is_edit else "Friend"
            type_index = COMMON_RELATIONS.index(current_type) if current_type in COMMON_RELATIONS else 0
            
            rel_type = st.selectbox("关系类型", options=COMMON_RELATIONS + ["Other"], index=type_index)
            if rel_type == "Other":
                custom_val = current_type if is_edit and current_type not in COMMON_RELATIONS else ""
                rel_type = st.text_input("输入自定义关系类型", value=custom_val)
            
            details_val = json.dumps(rel_data.get("details", {}), ensure_ascii=False) if is_edit else "{}"
            details = st.text_area("关系详情/备注 (JSON)", value=details_val)
            
            submitted = st.form_submit_button("💾 保存关系" if not is_edit else "💾 更新关系")
            
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
                            "details": json.loads(details)
                        }
                        
                        if is_edit:
                            res = requests.put(f"{API_URL}/characters/relationships/{rel_data['id']}", json=payload)
                        else:
                            res = requests.post(f"{API_URL}/characters/relationships", json=payload)
                            
                        if res.status_code == 200:
                            st.success("操作成功！")
                            st.session_state.edit_rel_data = None
                            st.rerun()
                        else:
                            st.error(f"操作失败: {res.text}")
                    except Exception as e:
                        st.error(f"错误: {e}")

        if is_edit:
            if st.button("❌ 取消编辑", key="cancel_rel_edit"):
                st.session_state.edit_rel_data = None
                st.rerun()

    # --- Left Column: Relationship List ---
    with col_list:
        st.subheader("📋 关系列表")
        if relationships:
            for rel in relationships:
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 2, 1])
                    s_name = char_map.get(rel["source_id"], f"ID:{rel['source_id']}")
                    t_name = char_map.get(rel["target_id"], f"ID:{rel['target_id']}")
                    
                    c1.markdown(f"**{s_name}** ↔️ **{t_name}**")
                    c2.caption(f"类型: {rel['relation_type']}")
                    
                    if c3.button("🗑️", key=f"del_rel_{rel['id']}"):
                         requests.delete(f"{API_URL}/characters/relationships/{rel['id']}")
                         st.rerun()
                         
                    if c3.button("✏️", key=f"edit_rel_{rel['id']}"):
                        st.session_state.edit_rel_data = rel
                        st.rerun()
        else:
            st.info("暂无关系数据。")
