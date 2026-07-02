# ADR-0001：chat.py 拆分 —— 本轮只拆 diagnosis，其余暂缓

- 状态：**已接受（收口）**
- 日期：2026-06-20
- 范围：`backend/app/api/chat.py` 的模块化拆分

## 背景

`chat.py` 约 2800 行，承载会话/消息/分析/归档/诊断/预演/目标等几乎所有逻辑。计划按
`routes + services` 分层拆分（chat_routes / perspective_service / archive_service /
conversation_service / diagnosis_service）。

## 决策

**本轮只完成 diagnosis 垂直拆分，其余切片暂缓。**

在动手第二刀前，把依赖图摸清后发现：剩余切片不是"抽一个 service"那么简单，已从
"降低复杂度"变成"组织性大搬家"，收益主要是结构洁癖，风险却显著上升。**现在停是工程判断，不是退缩。**

## 本轮已完成（可交付稳态）

- 抽出 `services/diagnosis_service.py`（结构化诊断 + Critic + 落库，按需触发）。
- 抽出 `services/analysis_store.py`（`create_memory_item` / `create_evidence_span`，被诊断与归档共用）。
- `chat.py` 经别名导入，调用点不变；**2800 → 2357 行**。
- 无循环 import；**44 测试绿**；后端重启验证健康。
- 同时修了真实 bug、补了关键路径测试（见下"里程碑事实"）。

## 关键发现：slice 2+ 的依赖耦合（为什么暂缓）

conversation / archive / perspective 三块**共用一批叶子级 helper**：

```
_visible_message_filter   _visible_messages_query   _recent_dialogue_text
_compose_scene (+ SCENARIO_PRESETS)   _dialogue_dynamics_hint
_find_or_create_character   _msg_emotion_strategy   _emotion_polarity
```

直接抽任一 service 会形成 **service → chat → service 的循环 import**；且
`edit-message → _reanalyze_user_message`、`archive → 关系/记忆回流`、`perspective = 分析核心`
都会牵动**分析核心**。

## 未来若继续拆，必须照此规程（playbook）

1. **第一刀必须是 `shared support` 模块**：先把上面 9 个叶子 helper（含 `SCENARIO_PRESETS`）
   搬进 `services/conversation_support.py`，chat 与各 service 都从它导入。
   **不要直接抽 conversation / archive / perspective。**
2. **搬 helper 前先补"行为锁定测试"**：覆盖 情绪四段 / 场景合成 / 可见消息过滤(分支) /
   多视角分析输出 / final 生成 —— 因为这些偏差是单测容易漏、体验上才暴露的。
3. **用 import 别名保持调用点不变**；每刀跑全套测试 + 重启验证，绝不裸拆。
4. **不轻动分析核心**（`_save_perspectives` / `analyze_multi_perspective` / final 生成）。

### 风险清单（继续拆时要盯死）

- 循环 import
- 分析行为回归
- 情绪 / 场景 / 可见消息过滤 偏差
- 测试覆盖挡不住的细微体验变化

## 里程碑事实（封存点）

- 单次推理出 final 的核心读主干（无后台 critic/debate/synthesize 覆盖、无时序错位）
- 关键路径测试覆盖：`test_send_e2e`（端到端）、`test_single_pass_final`、`test_archive_fix`、
  `test_diagnosis_no_crash`、`test_cold_start`、`test_quick_ingest`、`test_counterpart_memory`、
  `test_provider_fallback`、`test_context_maxed` 等，44 全绿
- 诊断已模块化（diagnosis_service + analysis_store）
- 真实 bug 已修：归档 `analysis`(None) 崩溃；诊断 `analysis_message_id=ai_msg.id` 守卫
- `chat.py` 2800 → 2357 行
