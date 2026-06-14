<template>
  <div class="chat-layout">
    <!-- 对话列表已并入左侧全局导航栏（App.vue），此处不再单列一栏 -->

    <!-- Center: Chat Area -->
    <div class="chat-main">
      <!-- Top bar -->
      <div class="chat-topbar">
        <div class="conv-info">
          <span class="conv-name">{{ currentConvTitle }}</span>
          <button class="tag scene-tag" @click="openSceneEditor" :title="currentConversation?.scene_brief || '点击设定场景背景'">
            {{ scenarioLabel(currentScenario) }}
            <span v-if="currentConversation?.scene_brief" class="scene-dot"></span>
          </button>
          <span v-if="currentConversation?.is_readonly" class="tag amber">只读导入</span>
          <select
            v-if="branches.length"
            class="input branch-select"
            v-model="activeBranchModel"
            @change="handleSwitchBranch"
            title="切换对话分支"
          >
            <option value="">主线</option>
            <option v-for="b in branches" :key="b.branch_id" :value="b.branch_id">
              分支@消息{{ b.branch_point_id }}（{{ b.message_count }}条）
            </option>
          </select>
        </div>
        <div class="topbar-actions">
          <button class="btn btn-ghost" style="font-size:12px;padding:6px 12px" @click="openSceneEditor">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16v16H4z"/><path d="M9 4v16"/><path d="M4 9h16"/></svg>
            场景设定
          </button>
          <button class="btn btn-ghost" style="font-size:12px;padding:6px 12px" @click="handleArchiveConversation">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 8v13H3V8"/><path d="M1 3h22v5H1z"/><path d="M10 12h4"/></svg>
            一键归档
          </button>
          <button class="btn btn-ghost" style="font-size:12px;padding:6px 12px" @click="showRoleModal = true">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>
            角色管理
          </button>
          <button class="btn btn-ghost" style="font-size:12px;padding:6px 12px" @click="toggleEmotionPanel">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
            情绪面板
          </button>
        </div>
      </div>

      <!-- Messages -->
      <div class="messages-area" ref="messagesEl">
        <div v-if="!chat.messages.length" class="welcome-screen">
          <div class="welcome-icon">◈</div>
          <div class="welcome-title">深度对话分析引擎</div>
          <div class="welcome-desc">AI Harness 实时解析对话潜台词<br>内心独白 · 情绪动态 · 隐含动机</div>
        </div>

        <TransitionGroup name="msg">
          <div v-for="msg in visibleMessages" :key="msg.id"
            :data-msg-id="msg.id"
            class="msg-wrapper" :class="msg.role">
            <div class="msg-head">
            <!-- Avatar -->
            <div class="msg-avatar" :style="{ background: getCharacterColor(msg.character_name) }">
              {{ avatarLetter(msg.character_name) }}
            </div>

            <div class="msg-body">
              <div class="msg-meta-top">
                <span class="msg-author">{{ msg.character_name || msg.role }}</span>
                <span v-if="msg.receiver_name" class="tag" style="font-size:10px;padding:1px 7px">{{ msg.character_name || msg.role }} → {{ msg.receiver_name }}</span>
                <span class="msg-time">{{ formatTime(msg.created_at) }}</span>
                <!-- Edit button -->
                <button v-if="msg.role === 'user' && !msg._streaming" class="branch-btn" @click="openEditMessage(msg)" title="编辑内容并重新分析">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z"/>
                  </svg>
                </button>
                <!-- Branch button -->
                <button v-if="msg.role === 'user'" class="branch-btn" @click="branchFrom(msg.id)" title="从此处创建分支">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/>
                    <circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>
                  </svg>
                </button>
              </div>

              <!-- Content bubble -->
              <div class="msg-bubble" :class="{ streaming: msg._streaming, error: msg._error }">
                <span>{{ msg.content }}</span>
                <span v-if="msg._streaming" class="cursor-blink">▌</span>
              </div>

              <div v-if="msg.role === 'assistant' && getAnalysisTags(msg).length" class="analysis-tags">
                <button
                  v-for="tag in getAnalysisTags(msg)"
                  :key="tag"
                  class="tag tag-btn"
                  @click="focusAnalysis(msg.id, 'strategy')"
                >
                  {{ tag }}
                </button>
              </div>
            </div><!-- /msg-body -->
            </div><!-- /msg-head -->

              <!-- 发言消息：多视角分析（全宽横向展开；发言者自述目的 + 在场各旁观者解读） -->
              <div v-if="msg.role === 'user' && userPerspectives(msg).length" class="analysis-layer analysis-full">
                <button class="analysis-toggle" @click="toggleAnalysis(msg.id)">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                  </svg>
                  查看分析
                  <span class="tag" style="font-size:10px;padding:1px 7px">{{ userPerspectives(msg).length }} 个视角</span>
                </button>
                <div v-if="expandedIds.has(msg.id)" class="analysis-content fade-up">
                  <div class="persp-tabs">
                    <button
                      v-for="p in userPerspectives(msg)"
                      :key="`utab-${msg.id}-${p.viewer_name}-${p.stance}`"
                      class="persp-tab"
                      :class="{ active: activeUserViewer(msg) === p.viewer_name }"
                      :style="{ '--vc': getCharacterColor(p.viewer_name) }"
                      @click="setViewer(msg.id, p.viewer_name)"
                    >
                      <span class="persp-dot"></span>{{ p.viewer_name }}<span class="persp-primary">{{ p.stance === 'speaker' ? '·自述' : (p.is_primary ? '·答' : '') }}</span>
                    </button>
                  </div>
                  <div class="persp-hint">
                    {{ curUserPersp(msg)?.stance === 'speaker'
                        ? `${msg.character_name} 说这句话的目的`
                        : `${curUserPersp(msg)?.viewer_name} 看「${msg.character_name}」这句话` }}
                  </div>
                  <div v-if="userPerspMonologue(msg)" class="analysis-row">
                    <span class="a-label">内心独白</span>
                    <span class="a-value">{{ userPerspMonologue(msg) }}</span>
                  </div>
                  <div v-if="curUserPersp(msg)?.emotion_label" class="analysis-row">
                    <span class="a-label">情绪归因</span><span class="a-value">{{ curUserPersp(msg).emotion_label }}</span>
                  </div>
                  <div v-if="curUserPersp(msg)?.subtext" class="analysis-row">
                    <span class="a-label">策略动机</span><span class="a-value">{{ curUserPersp(msg).subtext }}</span>
                  </div>
                  <div v-if="userPerspTags(msg).length" class="analysis-tags">
                    <span v-for="t in userPerspTags(msg)" :key="`upt-${t}`" class="tag">{{ t }}</span>
                  </div>
                  <!-- 建议回答（仅旁观者视角；接收方回复已整体并入此处） -->
                  <div v-if="curUserPersp(msg)?.suggested_reply" class="persp-reply">
                    <span class="a-label">建议回答</span>
                    <span class="reply-text">{{ curUserPersp(msg).suggested_reply }}</span>
                    <button class="btn btn-ghost reply-use-btn" @click="useSuggestedReply(curUserPersp(msg))" title="以该角色身份采用这句回答">采用</button>
                  </div>
                  <button
                    class="btn btn-ghost"
                    style="align-self:flex-start;font-size:11px;padding:4px 10px;margin-top:4px"
                    @click="reanalyzeUserMessage(msg)"
                  >
                    重新分析
                  </button>
                </div>
              </div>

              <!-- Analysis Layer (AI messages only) -->
              <div v-if="msg.role === 'assistant'" class="analysis-layer analysis-full">
                <button class="analysis-toggle" @click="toggleAnalysis(msg.id)">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                  </svg>
                  查看分析
                  <span v-if="msg.emotion_label" class="tag" style="font-size:10px;padding:1px 7px">{{ msg.emotion_label }}</span>
                </button>

                <div v-if="expandedIds.has(msg.id)" class="analysis-content fade-up">
                  <button
                    v-if="needsReanalysis(msg)"
                    class="btn btn-ghost"
                    style="align-self:flex-start;font-size:11px;padding:4px 10px"
                    @click="reanalyzeMessage(msg)"
                  >
                    补全分析
                  </button>

                  <!-- 多视角分析：在场每个角色站在自己立场看这句话 -->
                  <template v-if="getPerspectives(msg).length">
                    <div class="persp-tabs">
                      <button
                        v-for="p in getPerspectives(msg)"
                        :key="`ptab-${msg.id}-${p.viewer_name}`"
                        class="persp-tab"
                        :class="{ active: activeViewer(msg) === p.viewer_name }"
                        :style="{ '--vc': getCharacterColor(p.viewer_name) }"
                        @click="setViewer(msg.id, p.viewer_name)"
                      >
                        <span class="persp-dot"></span>{{ p.viewer_name }}<span v-if="p.is_primary" class="persp-primary">·答</span>
                      </button>
                    </div>
                    <div class="persp-hint">{{ currentPersp(msg)?.viewer_name }} 看「{{ msg.character_name || '对方' }}」这句话：</div>
                    <div v-if="perspMonologue(msg)" class="analysis-row">
                      <span class="a-label">内心独白</span><span class="a-value">{{ perspMonologue(msg) }}</span>
                    </div>
                    <div v-if="currentPersp(msg)?.emotion_label" class="analysis-row">
                      <span class="a-label">情绪归因</span><span class="a-value">{{ currentPersp(msg).emotion_label }}</span>
                    </div>
                    <div v-if="currentPersp(msg)?.subtext" class="analysis-row">
                      <span class="a-label">策略动机</span><span class="a-value">{{ currentPersp(msg).subtext }}</span>
                    </div>
                    <div v-if="perspTags(msg).length" class="analysis-tags">
                      <span v-for="t in perspTags(msg)" :key="`pt-${t}`" class="tag">{{ t }}</span>
                    </div>
                  </template>

                  <!-- 单视角回退（历史消息无多视角数据时） -->
                  <template v-else>
                    <div v-if="msg.inner_monologue" class="analysis-row" :class="{ focused: isFieldFocused(msg.id, 'monologue') }">
                      <span class="a-label">接收方内心独白</span>
                      <span class="a-value">{{ msg.inner_monologue }}</span>
                    </div>
                    <div v-if="msg.emotion_label" class="analysis-row" :class="{ focused: isFieldFocused(msg.id, 'emotion') }">
                      <span class="a-label">情绪归因标签</span>
                      <span class="a-value">{{ msg.emotion_label }}</span>
                    </div>
                    <div v-if="msg.subtext" class="analysis-row" :class="{ focused: isFieldFocused(msg.id, 'strategy') }">
                      <span class="a-label">策略性动机</span>
                      <span class="a-value">{{ msg.subtext }}</span>
                    </div>
                    <div class="analysis-row" v-if="msg.emotion_score != null">
                      <span class="a-label">情绪强度</span>
                      <div class="emotion-bar">
                        <div class="emotion-fill" :style="{ width: (msg.emotion_score * 100) + '%', background: emotionColor(msg.emotion_score) }"></div>
                      </div>
                      <span class="a-pct">{{ Math.round(msg.emotion_score * 100) }}%</span>
                    </div>
                  </template>

                  <!-- 深度诊断（按需触发，不阻塞对话主链路） -->
                  <div v-if="msg.parent_id" class="diagnosis-section">
                    <button
                      class="btn btn-ghost"
                      style="align-self:flex-start;font-size:11px;padding:4px 10px"
                      :disabled="diagnosingIds.has(msg.id)"
                      @click="runDiagnosis(msg)"
                    >
                      {{ diagnosingIds.has(msg.id) ? '诊断中…' : (diagnosisMap[msg.id] ? '重新诊断' : '深度诊断') }}
                    </button>
                    <div v-if="diagnosisMap[msg.id]" class="diagnosis-box">
                      <div class="diagnosis-head">
                        <span class="tag" :class="diagnosisStatusClass(diagnosisMap[msg.id].status)">{{ diagnosisStatusLabel(diagnosisMap[msg.id].status) }}</span>
                        <span class="a-pct">置信度 {{ Math.round((diagnosisMap[msg.id].confidence || 0) * 100) }}%</span>
                      </div>
                      <div class="diagnosis-summary">{{ diagnosisSummary(diagnosisMap[msg.id]) }}</div>
                    </div>
                  </div>
                </div>
              </div>
          </div>
        </TransitionGroup>
      </div>

      <!-- Input Area -->
      <div class="input-area">
        <!-- Role selector bar -->
        <div class="role-bar">
          <span class="label" style="margin:0">以…身份发言：</span>
          <div class="role-pills">
            <button v-for="role in activeRoles" :key="role.id || role.name"
              class="role-pill" :class="{ active: currentSpeaker === role.name }"
              :style="{ '--rc': role.color }"
              @click="handleSelectSpeaker(role)">
              <span class="role-dot"></span>{{ role.name }}
            </button>
            <button class="role-pill add-role" @click="showRoleModal = true">＋</button>
          </div>
          <template v-if="receiverOptions.length > 1">
            <span class="label" style="margin:0 0 0 8px">对谁说：</span>
            <select class="input receiver-select" v-model="currentReceiver" title="为空时由 AI 自动判定主要接收方">
              <option value="">自动判定</option>
              <option v-for="r in receiverOptions" :key="r.name" :value="r.name">{{ r.name }}</option>
            </select>
          </template>
        </div>
        <div v-if="!currentSpeaker" class="empty-hint" style="padding:0 0 10px;text-align:left">请先选择发言角色</div>
        <div v-if="currentConversation?.is_readonly" class="empty-hint" style="padding:0 0 10px;text-align:left">当前对话为导入生成的只读对话，仅支持查看与分析，不支持继续发送。</div>

        <div class="input-row">
          <textarea
            ref="inputEl"
            v-model="inputText"
            class="chat-input"
            placeholder="输入消息…  Shift+Enter 换行，Enter 发送"
            rows="1"
            :disabled="currentConversation?.is_readonly"
            @keydown.enter.exact.prevent="handleSend"
            @input="autoResize"
          />
          <button class="send-btn" :disabled="currentConversation?.is_readonly || (!chat.streaming && !inputText.trim())" @click="handleSend">
            <svg v-if="!chat.streaming" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
            <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <rect x="7" y="7" width="10" height="10" rx="2"/>
            </svg>
          </button>
        </div>
      </div>
    </div>

    <!-- Right: 状态 · 张力面板 -->
    <div class="emotion-panel" :class="{ open: showEmotionPanel }">
      <div class="panel-header">
        <span class="panel-title">状态 · 张力</span>
        <button class="btn btn-ghost" style="padding:4px 8px;font-size:11px" @click="refreshEmotionCurve">刷新</button>
      </div>

      <div class="epanel-scroll">
        <!-- 上半：在场各角色此刻被推断出的心理状态 -->
        <div class="epanel-block">
          <div class="block-title">在场角色状态</div>
          <div v-if="stateCards.length" class="state-cards">
            <div v-for="card in stateCards" :key="card.name" class="state-card" :style="{ '--rc': getCharacterColor(card.name) }">
              <div class="sc-head">
                <span class="sc-avatar" :style="{ background: getCharacterColor(card.name) }">{{ avatarLetter(card.name) }}</span>
                <span class="sc-name">{{ card.name }}</span>
                <span class="sc-emotion">{{ card.headline_emotion }}</span>
              </div>
              <div class="sc-intensity">
                <div class="sc-bar"><div class="sc-fill" :style="{ width: (card.headline_score*100)+'%' }"></div></div>
                <span class="sc-pct">{{ Math.round(card.headline_score*100) }}%</span>
              </div>
              <div v-if="card.current_goal" class="sc-row"><span class="sc-k">目标</span><span class="sc-v">{{ card.current_goal }}</span></div>
              <div v-if="card.defense_style" class="sc-row"><span class="sc-k">防御</span><span class="sc-v">{{ card.defense_style }}</span></div>
              <div v-if="card.last_intent" class="sc-row"><span class="sc-k">近期意图</span><span class="sc-v">{{ card.last_intent }}</span></div>
              <div v-if="card.beliefs?.length" class="sc-beliefs">
                <span v-for="b in card.beliefs" :key="b.target" class="tag" style="font-size:10px;padding:1px 8px">对{{ b.target }}：{{ b.belief }}</span>
              </div>
            </div>
          </div>
          <div v-else class="empty-hint" style="padding:14px 0">对话几轮后，这里会显示各角色被推断出的实时心理状态（情绪 / 目标 / 防御 / 意图）。</div>
        </div>

        <!-- 下半：某一对角色之间的关系张力走势 -->
        <div class="epanel-block">
          <div class="block-title">关系张力走势</div>
          <select v-if="rolePairs.length" class="input" v-model="trackingPair" @change="refreshEmotionCurve" style="margin-bottom:12px">
            <option v-for="pair in rolePairs" :key="pair.value" :value="pair.value">{{ pair.label }}</option>
          </select>
          <template v-if="emotionData.emotions?.length">
            <div class="emotion-trend">趋势：<span class="tag" :class="trendClass(emotionData.trend)">{{ trendLabel(emotionData.trend) }}</span></div>
            <div v-if="emotionData.turning_point" class="turning-point">⚡ 转折：{{ emotionData.turning_point }}</div>
            <div class="label" style="margin-top:10px">表层情绪逐句走势（点击跳转）</div>
            <div class="emotion-bars">
              <div v-for="(e, i) in emotionData.emotions" :key="i" class="ebar-row clickable" @click="scrollToMessage(e.message_id)">
                <span class="ebar-label">{{ e.label }}</span>
                <div class="ebar-track"><div class="ebar-fill" :style="{ width: (e.score*100)+'%', background: emotionColor(e.score) }"></div></div>
                <span class="ebar-pct">{{ Math.round(e.score*100) }}%</span>
              </div>
            </div>
            <div v-if="emotionData.deep_emotions?.length" style="margin-top:14px">
              <div class="label">深层情绪</div>
              <div class="emotion-bars">
                <div v-for="(e, i) in emotionData.deep_emotions" :key="`deep-${i}`" class="ebar-row clickable" @click="scrollToMessage(e.message_id)">
                  <span class="ebar-label">{{ e.label }}</span>
                  <div class="ebar-track"><div class="ebar-fill" :style="{ width: (e.score*100)+'%', background: 'var(--violet)' }"></div></div>
                  <span class="ebar-pct">{{ Math.round(e.score*100) }}%</span>
                </div>
              </div>
            </div>
            <div v-if="emotionData.strategy_trajectory?.length" style="margin-top:14px">
              <div class="label">策略轨迹</div>
              <div class="strategy-list">
                <button v-for="item in emotionData.strategy_trajectory" :key="`strategy-${item.message_id}`" class="strategy-item" @click="scrollToMessage(item.message_id)">
                  <span>{{ item.short_term || '短期策略未识别' }}</span>
                  <small>{{ item.long_term || '长期模式未识别' }}</small>
                </button>
              </div>
            </div>
          </template>
          <div v-else class="empty-hint" style="padding:14px 0">选择一对角色，发送几条消息后即可看到两人之间的张力走势。</div>
        </div>
      </div>
    </div>

    <!-- Role Management Modal -->
    <Teleport to="body">
      <div v-if="showRoleModal" class="modal-overlay" @click.self="showRoleModal = false">
        <div class="modal card fade-up" style="width:480px;max-height:80vh;overflow-y:auto">
          <div class="modal-header">
            <span>角色配置</span>
            <button class="btn-close" @click="showRoleModal = false">✕</button>
          </div>
          <div style="padding:20px">
            <div class="label">当前对话角色</div>
            <div class="role-pills" style="margin-bottom:16px;flex-wrap:wrap">
              <span v-for="r in activeRoles" :key="r.name" class="role-pill active" :style="{ '--rc': r.color, 'cursor':'default', 'padding-right':'6px' }">
                <span class="role-dot"></span>{{ r.name }}
                <button @click="removeRole(r.name)" style="background:none;border:none;color:inherit;cursor:pointer;padding:2px;margin-left:4px;border-radius:4px" title="移除角色">✕</button>
              </span>
            </div>

            <div class="label">从已有角色选择加入对话</div>
            <div class="char-select-list">
              <label v-for="c in chars.characters" :key="c.id" class="char-select-item">
                <input type="checkbox" :value="c" v-model="selectedChars" style="accent-color:var(--cyan)"/>
                <span class="char-dot" :style="{ background: c.avatar_color }">{{ c.name[0] }}</span>
                <div>
                  <div style="font-weight:500;font-size:13px">{{ c.name }}</div>
                  <div style="font-size:11px;color:var(--text-muted)">{{ c.role }}</div>
                </div>
              </label>
            </div>
            <div class="label" style="margin-top:16px">自定义角色名</div>
            <div style="display:flex;gap:8px">
              <input class="input" v-model="customRoleName" placeholder="角色名称" style="flex:1"/>
              <button class="btn btn-ghost" @click="addCustomRole">添加</button>
            </div>
            <button class="btn btn-primary" style="width:100%;margin-top:20px;justify-content:center" @click="confirmRoles">
              确认 ({{ activeRoles.length }} 个角色)
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Edit Message Modal -->
    <Teleport to="body">
      <div v-if="editingMsg" class="modal-overlay" @click.self="editingMsg = null">
        <div class="modal card fade-up" style="width:520px">
          <div class="modal-header">
            <span>编辑对话内容（保存后将重新分析）</span>
            <button class="btn-close" @click="editingMsg = null">✕</button>
          </div>
          <div style="padding:20px;display:flex;flex-direction:column;gap:14px">
            <div class="label" style="margin:0">{{ editingMsg.character_name }} 的发言</div>
            <textarea class="input" v-model="editingMsg.content" rows="5" style="resize:vertical;line-height:1.6"></textarea>
            <div style="display:flex;gap:8px;justify-content:flex-end">
              <button class="btn btn-ghost" @click="editingMsg = null">取消</button>
              <button class="btn btn-primary" :disabled="editSaving || !editingMsg.content.trim()" @click="saveEditedMessage">
                {{ editSaving ? '重新分析中…' : '保存并重新分析' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="showScenarioModal" class="modal-overlay" @click.self="showScenarioModal = false">
        <div class="modal card fade-up" style="width:520px;max-height:84vh;overflow-y:auto">
          <div class="modal-header">
            <span>场景设定</span>
            <button class="btn-close" @click="showScenarioModal = false">✕</button>
          </div>
          <div style="padding:20px;display:flex;flex-direction:column;gap:16px">
            <div>
              <div class="label">场景类型（点选可快填背景模板）</div>
              <div class="scene-preset-chips">
                <button v-for="preset in scenarioOptions" :key="preset.key"
                  class="scene-chip" :class="{ active: sceneForm.scenario === preset.key }"
                  @click="pickScenePreset(preset.key)">{{ preset.label }}</button>
              </div>
            </div>
            <div>
              <div class="label">场景背景说明（注入分析，约束 AI 对每句话的理解）</div>
              <textarea class="input" v-model="sceneForm.scene_brief" rows="5"
                placeholder="例如：双方在收购谈判的最后一轮，气氛紧张，甲方急于成交、乙方仍在试探底线……"
                style="resize:vertical;line-height:1.6"></textarea>
              <div class="scene-hint">单纯一个场景标签没有意义，背景说明才真正决定分析视角。聊天中可随时来此修改，立即对后续对话分析生效（不会新建对话）。</div>
            </div>
            <div style="display:flex;gap:8px;justify-content:flex-end">
              <button class="btn btn-ghost" @click="showScenarioModal = false">取消</button>
              <button class="btn btn-primary" @click="saveScene">保存场景</button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useChatStore } from '../stores/chat.js'
import { useCharacterStore } from '../stores/characters.js'
import { chatApi } from '../api/index.js'
import { toast, confirmDialog } from '../utils/notify.js'

const chat = useChatStore()
const chars = useCharacterStore()

// 场景仅作为「背景设定」的快捷模板，不再注入任何虚构默认角色。
// 角色一律来自真实角色库 / 用户手动添加；brief 为该场景的默认背景说明草稿。
const SCENE_PRESETS = {
  general:      { label: '通用对话', brief: '' },
  bar_chat:     { label: '老友闲聊', brief: '多年好友久别重逢，在轻松随意的场合叙旧，气氛温和但各有心事。' },
  business:     { label: '商务谈判', brief: '双方就一笔关键合作展开谈判，立场存在分歧，都想争取对自己最有利的结果。' },
  hr_interview: { label: 'HR面试',   brief: '面试官与候选人初次见面，一方在评估另一方，双方都在管理自己的呈现。' },
  counseling:   { label: '心理咨询', brief: '来访者带着困扰寻求帮助，咨询师在建立信任并引导其袒露真实感受。' },
}

const messagesEl = ref(null)
const inputEl = ref(null)
const inputText = ref('')
const showRoleModal = ref(false)
const showScenarioModal = ref(false)
const showEmotionPanel = ref(false)
const expandedIds = ref(new Set())
const analysisFocus = ref({ id: null, field: '' })
const currentSpeaker = ref('')
const currentCharId = ref(null)
const selectedChars = ref([])
const customRoleName = ref('')
const trackingPair = ref('')
const emotionData = ref({ emotions: [], trend: 'stable', turning_point: null })
const stateCards = ref([])                 // 各在场角色当前心理状态卡
const activeRoles = ref([])
const currentReceiver = ref('')            // '' = 后端自动判定主要接收方
const branches = ref([])
const activeBranchModel = ref('')
const diagnosisMap = ref({})               // analysisMsgId -> diagnosis
const diagnosingIds = ref(new Set())

const currentConvTitle = computed(() => {
  const c = chat.conversations.find(c => c.id === chat.activeConvId)
  return c?.title || '选择或新建对话'
})
const currentConversation = computed(() => chat.conversations.find(c => c.id === chat.activeConvId) || null)
const currentScenario = computed(() => {
  const c = chat.conversations.find(c => c.id === chat.activeConvId)
  return c?.scenario || 'general'
})
const scenarioOptions = computed(() => Object.entries(SCENE_PRESETS).map(([key, value]) => ({ key, label: value.label })))
const rolePairs = computed(() => {
  const pairs = []
  for (const source of activeRoles.value) {
    for (const target of activeRoles.value) {
      if (source.name === target.name) continue
      pairs.push({ value: `${source.name}→${target.name}`, label: `${source.name} → ${target.name}` })
    }
  }
  return pairs
})
const receiverOptions = computed(() => activeRoles.value.filter(r => r.name !== currentSpeaker.value))
// 只显示发言（user）消息；接收方的回复已并入多视角分析的"建议回答"，不再单独成气泡。
// 流式占位（_streaming 的 assistant）也不显示——它会在加载时闪现、生成完后被过滤掉而消失，
// 造成"先出现又消失"的割裂感。生成状态由发送按钮的停止图标（chat.streaming）反馈。
const visibleMessages = computed(() => chat.messages.filter(m => m.role === 'user'))

watch(currentSpeaker, () => {
  // 发言人变化后，若接收方与发言人相同则重置为自动
  if (currentReceiver.value && currentReceiver.value === currentSpeaker.value) currentReceiver.value = ''
})

onMounted(async () => {
  await Promise.all([chat.loadConversations(), chars.fetchAll()])
  if (chat.activeConvId) {
    // 已有活动对话（从其它页返回）：仅做一次本地设置
    applyScenePresetRoles(currentScenario.value, false)
    await refreshBranches()
  } else if (chat.conversations.length) {
    await chat.loadMessages(chat.conversations[0].id)  // 触发下方 watch 完成每会话设置
  } else {
    applyScenePresetRoles('general')
  }
})

// 对话切换（activeConvId 变化，由左侧导航栏选择驱动）：重置分支与诊断
watch(() => chat.activeConvId, async (id) => {
  diagnosisMap.value = {}
  if (id) {
    await refreshBranches()
  } else {
    branches.value = []
    activeBranchModel.value = ''
  }
})

// 消息数量变化（含发送时的乐观插入）：滚动到底 + 情绪面板刷新
watch(() => chat.messages.length, () => {
  nextTick(() => {
    if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
  })
  if (showEmotionPanel.value && !chat.streaming) refreshEmotionCurve()
})
// 消息集合被整体替换（载入 / 切换会话 / 发送后重载）：按真实数据重算在场角色
watch(() => chat.messages, () => {
  applyScenePresetRoles(currentScenario.value, false)
  nextTick(() => {
    if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
  })
})
watch(rolePairs, (pairs) => {
  if (!pairs.length) {
    trackingPair.value = ''
    return
  }
  if (!pairs.find(pair => pair.value === trackingPair.value)) {
    trackingPair.value = pairs[0].value
  }
})

function avatarLetter(name) { return (name || '?')[0].toUpperCase() }
function roleDescOf(name) {
  return chars.characters.find(c => c.name === name)?.role || ''
}
function getCharacterColor(name) {
  const c = chars.characters.find(ch => ch.name === name)
  if (c) return c.avatar_color
  const colors = ['#00d4ff','#7c3aed','#10b981','#f59e0b','#ef4444']
  let h = 0; for (const ch of (name || '')) h = (h * 31 + ch.charCodeAt(0)) % colors.length
  return colors[h]
}
function formatDate(dt) {
  if (!dt) return ''
  return new Date(dt).toLocaleDateString('zh-CN', { month:'short', day:'numeric' })
}
function formatTime(dt) {
  if (!dt) return ''
  return new Date(dt).toLocaleTimeString('zh-CN', { hour:'2-digit', minute:'2-digit' })
}
function scenarioLabel(key) { return SCENE_PRESETS[key]?.label || key }
function emotionColor(score) {
  if (score < 0.3) return '#10b981'
  if (score < 0.6) return '#f59e0b'
  return '#ef4444'
}
function trendLabel(t) { return { rising:'上升', falling:'下降', stable:'平稳', volatile:'波动' }[t] || t }
function trendClass(t) { return { rising:'amber', falling:'red', stable:'green', volatile:'violet' }[t] || '' }
function isFieldFocused(id, field) { return analysisFocus.value.id === id && analysisFocus.value.field === field }
function getAnalysisTags(msg) {
  return (msg.psychological_tag || '')
    .split('|')
    .map(tag => tag.trim())
    .filter(Boolean)
    .slice(0, 3)
}
function needsReanalysis(msg) {
  return msg.role === 'assistant' && !msg._streaming && !msg._error && !msg.inner_monologue && !getPerspectives(msg).length && !!msg.parent_id
}

// ── 多视角分析 ────────────────────────────────────────────────
const viewerSel = ref({})  // userMsgId -> 选中的 viewer 名
function getPerspectives(msg) {
  // 分析挂在 assistant 消息上，但视角数据按其 parent(user 消息) id 索引
  const uid = msg.parent_id
  if (!uid) return []
  return chat.perspectives?.[uid] || []
}
function activeViewer(msg) {
  const list = getPerspectives(msg)
  if (!list.length) return ''
  const sel = viewerSel.value[msg.parent_id]
  if (sel && list.some(p => p.viewer_name === sel)) return sel
  const primary = list.find(p => p.is_primary)
  return (primary || list[0]).viewer_name
}
function setViewer(userMsgId, viewer) {
  viewerSel.value = { ...viewerSel.value, [userMsgId]: viewer }
}
function currentPersp(msg) {
  const list = getPerspectives(msg)
  const v = activeViewer(msg)
  return list.find(p => p.viewer_name === v) || list[0] || null
}
function perspMonologue(msg) {
  const p = currentPersp(msg)
  if (!p) return ''
  const im = p.analysis_json?.inner_monologue
  if (im && typeof im === 'object') {
    return [im.first_reaction && `第一反应：${im.first_reaction}`, im.defense && `防御：${im.defense}`, im.tendency && `行为倾向：${im.tendency}`].filter(Boolean).join('  ')
  }
  return p.inner_monologue || ''
}
function perspTags(msg) {
  const t = currentPersp(msg)?.analysis_json?.tags || {}
  return [t.primary && `主:${t.primary}`, t.secondary && `次:${t.secondary}`, t.relation && `关系:${t.relation}`].filter(Boolean)
}

// ── 发言消息的多视角（自述 + 解读，挂在 user 消息 id 上） ──────
function userPerspectives(msg) {
  return chat.perspectives?.[msg.id] || []
}
function activeUserViewer(msg) {
  const list = userPerspectives(msg)
  if (!list.length) return ''
  const sel = viewerSel.value[msg.id]
  if (sel && list.some(p => p.viewer_name === sel)) return sel
  return list[0].viewer_name   // 后端已把发言者自述排在首位
}
function curUserPersp(msg) {
  const list = userPerspectives(msg)
  const v = activeUserViewer(msg)
  return list.find(p => p.viewer_name === v) || list[0] || null
}
function userPerspMonologue(msg) {
  const p = curUserPersp(msg)
  if (!p) return ''
  const im = p.analysis_json?.inner_monologue
  if (im && typeof im === 'object') {
    return [im.first_reaction, im.defense, im.tendency].filter(Boolean).join('  ')
  }
  return p.inner_monologue || ''
}
function userPerspTags(msg) {
  const t = curUserPersp(msg)?.analysis_json?.tags || {}
  return [t.primary && `主:${t.primary}`, t.secondary && `次:${t.secondary}`, t.relation && `关系:${t.relation}`].filter(Boolean)
}
async function reanalyzeUserMessage(msg) {
  try {
    await chatApi.reanalyzeMessage(msg.id)
    await chat.loadMessages(chat.activeConvId)
    toast.success('已重新分析')
  } catch { /* 错误已由拦截器提示 */ }
}
// 采用某视角的建议回答：切到该角色身份，并把建议回答填进输入框（用户可改后发送）
function useSuggestedReply(persp) {
  if (!persp?.suggested_reply) return
  const role = activeRoles.value.find(r => r.name === persp.viewer_name)
  if (role) handleSelectSpeaker(role)
  currentReceiver.value = persp.speaker_name || ''
  inputText.value = persp.suggested_reply
  nextTick(() => { inputEl.value?.focus(); autoResize() })
  toast.info(`已切换为「${persp.viewer_name}」并填入建议回答`)
}
function focusAnalysis(id, field) {
  analysisFocus.value = { id, field }
  if (!expandedIds.value.has(id)) toggleAnalysis(id)
}
function handleSelectSpeaker(role) {
  currentSpeaker.value = role.name
  currentCharId.value = role.id
}
function resolveRoleByName(name) {
  const char = chars.characters.find(item => item.name === name)
  return {
    id: char?.id ?? null,
    name,
    color: char?.avatar_color || getCharacterColor(name),
  }
}
function applyScenePresetRoles(scenario, withDefaults = true) {
  // 角色只来自真实数据：会话持久化的参与角色（含从未发言的听者）+ 历史消息中出现过的发言者。
  // 不再注入任何场景预设里的虚构角色。
  const savedParticipants = (currentConversation.value?.participants || []).map(p => p.name).filter(Boolean)
  const messageRoles = [...new Set(chat.messages.filter(msg => msg.role === 'user' && msg.character_name).map(msg => msg.character_name))]
  const roleNames = [...new Set([...savedParticipants, ...messageRoles])]
  activeRoles.value = roleNames.map(resolveRoleByName)
  selectedChars.value = chars.characters.filter(char => activeRoles.value.some(role => role.id === char.id))
  if (!withDefaults && currentSpeaker.value && activeRoles.value.find(role => role.name === currentSpeaker.value)) return
  const nextSpeaker = activeRoles.value.find(role => role.name === currentSpeaker.value) || activeRoles.value[0]
  currentSpeaker.value = nextSpeaker?.name || ''
  currentCharId.value = nextSpeaker?.id || null
}

function toggleAnalysis(id) {
  const s = new Set(expandedIds.value)
  s.has(id) ? s.delete(id) : s.add(id)
  expandedIds.value = s
}
function toggleEmotionPanel() {
  showEmotionPanel.value = !showEmotionPanel.value
  if (showEmotionPanel.value) refreshEmotionCurve()
}

async function refreshBranches() {
  if (!chat.activeConvId) { branches.value = []; return }
  try {
    const res = await chatApi.listBranches(chat.activeConvId)
    branches.value = res.data.branches || []
    activeBranchModel.value = res.data.active_branch_id || ''
  } catch {
    branches.value = []
  }
}

async function handleSwitchBranch() {
  await chat.switchBranch(activeBranchModel.value || null)
  await refreshBranches()
  toast.success(activeBranchModel.value ? '已切换到分支' : '已回到主线')
}
// 对话的新建 / 选择 / 删除已移至左侧全局导航栏（App.vue），本组件通过 watch(activeConvId/messages) 响应

// ── 场景设定（可在聊天中随时编辑，立即对后续分析生效，无需新建对话） ──
const sceneForm = ref({ scenario: 'general', scene_brief: '' })
function openSceneEditor() {
  const c = currentConversation.value
  sceneForm.value = {
    scenario: c?.scenario || 'general',
    scene_brief: c?.scene_brief || '',
  }
  showScenarioModal.value = true
}
// 选中某预设：填入其默认背景说明草稿（仅当当前背景为空或用户未改过时）
function pickScenePreset(key) {
  const preset = SCENE_PRESETS[key]
  if (!preset) return
  const prevBrief = SCENE_PRESETS[sceneForm.value.scenario]?.brief || ''
  sceneForm.value.scenario = key
  if (!sceneForm.value.scene_brief.trim() || sceneForm.value.scene_brief.trim() === prevBrief.trim()) {
    sceneForm.value.scene_brief = preset.brief || ''
  }
}
async function saveScene() {
  if (!chat.activeConvId) {
    // 还没有对话时，先建一个再写场景
    await chat.newConversation('新对话 ' + new Date().toLocaleTimeString('zh-CN', { hour:'2-digit', minute:'2-digit' }), sceneForm.value.scenario)
  }
  const id = chat.activeConvId
  const res = await chatApi.updateConversation(id, {
    scenario: sceneForm.value.scenario,
    scene_brief: sceneForm.value.scene_brief.trim(),
  })
  // 同步本地会话对象，使顶栏场景标签 / 背景立即更新
  const conv = chat.conversations.find(c => c.id === id)
  if (conv) Object.assign(conv, res.data)
  showScenarioModal.value = false
  toast.success('场景已更新，将对后续对话分析生效')
}
async function handleArchiveConversation() {
  if (!chat.activeConvId || !activeRoles.value.length) return
  const confirmed = await confirmDialog(`将当前对话归档到以下角色：${activeRoles.value.map(role => role.name).join('、')}。是否继续？`)
  if (!confirmed) return
  const res = await chatApi.archiveConversation(chat.activeConvId, {
    role_names: activeRoles.value.map(role => role.name),
  })
  toast.success(`归档完成：${res.data.archived_roles.join('、')}${res.data.observations_created ? `，并生成 ${res.data.observations_created} 条待审核建议` : ''}`)
}

async function handleSend() {
  if (chat.streaming) {
    chat.cancelStreaming()
    return
  }
  if (currentConversation.value?.is_readonly) {
    toast.error('当前为只读导入对话，不能继续发送新消息')
    return
  }
  const text = inputText.value.trim()
  if (!text) return
  if (!currentSpeaker.value) {
    toast.error('请先选择发言角色')
    return
  }
  inputText.value = ''
  await nextTick()
  if (inputEl.value) inputEl.value.style.height = 'auto'

  if (!chat.activeConvId) {
    await chat.newConversation('新对话', currentScenario.value || 'general')
  }

  await chat.sendMessage({
    speaker: currentSpeaker.value,
    content: text,
    characterId: currentCharId.value,
    receiverName: currentReceiver.value || null,
    activeCharacters: activeRoles.value.map(r => ({ id: r.id, name: r.name })),
  })
}

// ── 深度诊断（按需触发） ──────────────────────────────────────
async function runDiagnosis(msg) {
  if (!msg.parent_id || diagnosingIds.value.has(msg.id)) return
  diagnosingIds.value = new Set([...diagnosingIds.value, msg.id])
  try {
    const res = await chatApi.diagnoseMessage(msg.parent_id)
    diagnosisMap.value = { ...diagnosisMap.value, [msg.id]: res.data }
  } finally {
    const next = new Set(diagnosingIds.value)
    next.delete(msg.id)
    diagnosingIds.value = next
  }
}
function diagnosisStatusLabel(status) {
  return { approved: '诊断通过', downgraded: '已降级', insufficient: '证据不足', rejected: '已驳回' }[status] || status
}
function diagnosisStatusClass(status) {
  return { approved: 'green', downgraded: 'amber', insufficient: '', rejected: 'red' }[status] || ''
}
function diagnosisSummary(diagnosis) {
  const critic = diagnosis.critic_json || {}
  const result = diagnosis.result_json || {}
  return critic.revised_summary || result.summary || '（无摘要）'
}

function autoResize() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

function removeRole(name) {
  activeRoles.value = activeRoles.value.filter(r => r.name !== name)
  selectedChars.value = selectedChars.value.filter(c => c.name !== name)
  if (currentSpeaker.value === name) {
    currentSpeaker.value = activeRoles.value[0]?.name || ''
    currentCharId.value = activeRoles.value[0]?.id || null
  }
}

function addCustomRole() {
  const name = customRoleName.value.trim()
  if (!name) return
  if (!activeRoles.value.find(r => r.name === name)) {
    activeRoles.value.push({ name, color: '#94a3b8', id: null })
  }
  customRoleName.value = ''
}
async function confirmRoles() {
  const selectedIds = selectedChars.value.map(c => c.id)
  activeRoles.value = activeRoles.value.filter(r => {
    if (r.id === null) return true
    return selectedIds.includes(r.id)
  })

  for (const c of selectedChars.value) {
    if (!activeRoles.value.find(r => r.name === c.name)) {
      activeRoles.value.push({ name: c.name, color: c.avatar_color, id: c.id })
    }
  }
  // 持久化参与角色到会话（含从未发言的听者，重进会话不丢）
  if (chat.activeConvId) {
    await chat.saveParticipants(activeRoles.value.map(r => ({ id: r.id, name: r.name })))
  }
  const currentExists = activeRoles.value.find(r => r.name === currentSpeaker.value)
  if (!currentExists) {
    currentSpeaker.value = activeRoles.value[0]?.name || ''
    currentCharId.value = activeRoles.value[0]?.id || null
  }
  showRoleModal.value = false
}

async function branchFrom(messageId) {
  if (!await confirmDialog('从此消息创建新分支？此后的消息会留在原分支中，可随时通过顶部下拉切换回去。')) return
  await chat.createBranch(messageId)
  await refreshBranches()
  toast.success('已创建并切换到新分支')
}

async function loadStates() {
  if (!chat.activeConvId) { stateCards.value = []; return }
  try {
    const res = await chatApi.getStates(chat.activeConvId)
    stateCards.value = res.data.states || []
  } catch {
    stateCards.value = []
  }
}
async function refreshEmotionCurve() {
  await loadStates()
  if (!chat.activeConvId || !trackingPair.value) return
  try {
    const [source, target] = trackingPair.value.split('→')
    const res = await chatApi.getEmotionTension(chat.activeConvId, source, target)
    emotionData.value = res.data
  } catch {
    emotionData.value = { emotions: [], trend: 'stable', turning_point: null }
  }
}
async function reanalyzeMessage(msg) {
  const res = await chatApi.reanalyzeMessage(msg.parent_id)
  const index = chat.messages.findIndex(item => item.id === msg.id)
  if (index >= 0) {
    chat.messages[index] = { ...chat.messages[index], ...res.data }
  }
}

// ── 编辑对话内容并重新分析 ────────────────────────────────────
const editingMsg = ref(null)
const editSaving = ref(false)
function openEditMessage(msg) {
  editingMsg.value = { id: msg.id, character_name: msg.character_name, content: msg.content }
}
async function saveEditedMessage() {
  if (!editingMsg.value || editSaving.value) return
  editSaving.value = true
  try {
    await chatApi.editMessage(editingMsg.value.id, editingMsg.value.content.trim())
    editingMsg.value = null
    await chat.loadMessages(chat.activeConvId)
    toast.success('内容已更新，分析已重建')
  } finally {
    editSaving.value = false
  }
}
function scrollToMessage(messageId) {
  nextTick(() => {
    const target = document.querySelector(`[data-msg-id="${messageId}"]`)
    if (!target) return
    target.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
}
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* ── Conv Panel ── */
.conv-panel {
  width: 250px;
  flex-shrink: 0;
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.panel-section { display: flex; flex-direction: column; min-height: 0; }
.conv-section { flex: 0 0 auto; max-height: 46%; }
.roster-section { flex: 1 1 auto; border-top: 1px solid var(--border); min-height: 120px; }
.panel-header {
  padding: 13px 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}
.panel-title { font-size: 12px; font-family: var(--font-mono); color: var(--text-muted); text-transform: uppercase; letter-spacing:.08em; }
.conv-list { flex:1; overflow-y:auto; padding: 8px; }
.conv-item {
  padding: 9px 11px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: var(--transition);
  margin-bottom: 2px;
  display: flex;
  align-items: center;
}
.conv-item:hover { background: var(--bg-hover); }
.conv-item.active { background: var(--cyan-dim); border: 1px solid rgba(0,212,255,0.2); }
.conv-title { font-size: 13px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.conv-meta { font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); margin-top: 2px; }
.conv-del { background:transparent; border:none; color:var(--text-muted); cursor:pointer; font-size:12px; opacity:.45; padding:2px 5px; border-radius:4px; transition:var(--transition); }
.conv-del:hover { opacity:1; color:var(--red); }
.empty-hint { text-align:center; color:var(--text-muted); font-size:12px; padding:24px 0; }

/* 在场角色（人物信息左置） */
.roster-list { flex:1; overflow-y:auto; padding:8px; display:flex; flex-direction:column; gap:6px; }
.roster-card {
  display:flex; align-items:center; gap:10px;
  padding:8px 10px; border-radius:var(--radius-sm);
  border:1px solid var(--border); background:var(--bg-elevated);
  cursor:pointer; text-align:left; transition:var(--transition);
}
.roster-card:hover { border-color:var(--border-strong); }
.roster-card.speaking { border-color: var(--rc, var(--cyan)); background: color-mix(in srgb, var(--rc, var(--cyan)) 13%, transparent); }
.roster-avatar { width:30px; height:30px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700; color:#080c16; flex-shrink:0; }
.roster-info { display:flex; flex-direction:column; min-width:0; flex:1; }
.roster-name { font-size:13px; font-weight:500; color:var(--text-primary); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.roster-role { font-size:11px; color:var(--text-muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.roster-badge { font-size:10px; font-family:var(--font-mono); color:var(--rc, var(--cyan)); border:1px solid var(--rc, var(--cyan)); border-radius:100px; padding:1px 7px; flex-shrink:0; }

/* ── Chat Main ── */
.chat-main { flex:1; display:flex; flex-direction:column; overflow:hidden; min-width:0; }
.chat-topbar {
  padding: 14px 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}
.conv-info { display:flex; align-items:center; gap:10px; }
.conv-name { font-size:15px; font-weight:600; }
.topbar-actions { display:flex; gap:8px; }

.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.welcome-screen { flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center; opacity:.5; }
.welcome-icon { font-size: 48px; color: var(--cyan); margin-bottom: 16px; }
.welcome-title { font-size: 18px; font-weight: 600; margin-bottom: 8px; }
.welcome-desc { font-size: 13px; color: var(--text-muted); text-align: center; line-height: 1.8; }

.msg-wrapper { display:flex; flex-direction:column; gap:6px; }
.msg-head { display:flex; gap:12px; align-items:flex-start; }
.msg-wrapper.user .msg-head { flex-direction: row-reverse; }
.msg-wrapper.user .msg-body { align-items: flex-end; }
/* 查看分析框：脱离 70% 气泡宽度限制，横向铺满整条消息区 */
.analysis-full { width: 100%; }
.analysis-full .analysis-content { width: 100%; }

.msg-avatar {
  width: 36px; height: 36px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 700;
  color: #080c16;
  flex-shrink: 0;
}
.msg-body { display:flex; flex-direction:column; gap:4px; max-width: 70%; }
.msg-meta-top {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}
.msg-author { font-weight: 500; color: var(--text-secondary); }
.branch-btn {
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-muted);
  cursor: pointer;
  padding: 2px 5px;
  display: flex;
  align-items: center;
  transition: var(--transition);
}
.branch-btn:hover { border-color:var(--cyan); color:var(--cyan); }

.msg-bubble {
  padding: 11px 15px;
  border-radius: var(--radius-md);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  font-size: 14px;
  line-height: 1.65;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
  transition: border-color .2s;
}
.msg-wrapper.user .msg-bubble { background: var(--cyan-dim); border-color: rgba(0,212,255,0.25); }
.msg-bubble.streaming { border-color: var(--cyan); animation: pulse-cyan 1.5s infinite; }
.msg-bubble.error { border-color: rgba(239,68,68,.4); background: rgba(239,68,68,.05); }
.cursor-blink { animation: blink 1s step-end infinite; color: var(--cyan); }
.analysis-tags { display:flex; gap:6px; flex-wrap:wrap; margin-top:4px; }
.tag-btn { background: rgba(124,58,237,.12); border-color: rgba(124,58,237,.25); color:#c4b5fd; cursor:pointer; }

/* Analysis Layer */
.analysis-layer { margin-top: 4px; }
.analysis-toggle {
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-muted);
  font-size: 11px;
  padding: 4px 10px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 5px;
  transition: var(--transition);
  font-family: var(--font-mono);
}
.analysis-toggle:hover { border-color: var(--cyan); color: var(--cyan); }

.analysis-content {
  margin-top: 6px;
  padding: 12px 14px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.analysis-row { display:flex; align-items:flex-start; gap:10px; }
.analysis-row.focused { border: 1px solid rgba(0, 212, 255, 0.22); border-radius: 8px; padding: 8px; background: rgba(0, 212, 255, 0.05); }
.a-label {
  font-size: 10px; font-family: var(--font-mono);
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: .06em;
  white-space: nowrap;
  padding-top: 2px;
  min-width: 60px;
}
.a-value { font-size: 12px; color: var(--text-secondary); flex:1; line-height:1.6; }
.emotion-bar { flex:1; height:6px; background:var(--bg-base); border-radius:3px; overflow:hidden; align-self:center; }
.emotion-fill { height:100%; border-radius:3px; transition: width .5s; }
.a-pct { font-size:11px; font-family:var(--font-mono); color:var(--text-muted); }

/* Input Area */
.input-area {
  flex-shrink: 0;
  padding: 12px 20px 16px;
  border-top: 1px solid var(--border);
  background: var(--bg-surface);
}
.role-bar { display:flex; align-items:center; gap:10px; margin-bottom:10px; }
.role-pills { display:flex; gap:6px; flex-wrap:wrap; }
.role-pill {
  display: flex; align-items: center; gap: 5px;
  padding: 4px 12px;
  border-radius: 100px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: var(--transition);
}
.role-pill.active { border-color: var(--rc, var(--cyan)); color: var(--rc, var(--cyan)); background: color-mix(in srgb, var(--rc, var(--cyan)) 12%, transparent); }
.role-dot { width:7px; height:7px; border-radius:50%; background:var(--rc, var(--cyan)); }
.add-role { border-style: dashed; }

.input-row { display:flex; gap:10px; align-items:flex-end; }
.chat-input {
  flex: 1;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-family: var(--font-ui);
  font-size: 14px;
  padding: 10px 14px;
  outline: none;
  resize: none;
  transition: var(--transition);
  min-height: 44px;
  max-height: 160px;
  line-height: 1.5;
}
.chat-input:focus { border-color: var(--cyan); box-shadow: 0 0 0 3px rgba(0,212,255,.1); }
.chat-input::placeholder { color: var(--text-muted); }

.send-btn {
  width: 44px; height: 44px;
  border-radius: var(--radius-sm);
  background: var(--cyan);
  border: none;
  color: #080c16;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: var(--transition);
}
.send-btn:hover:not(:disabled) { background: #33dcff; box-shadow: var(--cyan-glow); }
.send-btn:disabled { opacity: .4; cursor: not-allowed; }

/* 状态 · 张力面板 */
.emotion-panel {
  width: 0;
  flex-shrink: 0;
  overflow: hidden;
  transition: width .3s cubic-bezier(.4,0,.2,1);
  border-left: 0 solid var(--border);
  background: var(--bg-surface);
  display: flex;
  flex-direction: column;
}
.emotion-panel.open {
  width: 308px;
  border-left-width: 1px;
}
.epanel-scroll { flex:1; overflow-y:auto; }
.epanel-block { padding: 14px 16px; border-bottom: 1px solid var(--border); }
.block-title { font-size:11px; font-family:var(--font-mono); color:var(--text-muted); text-transform:uppercase; letter-spacing:.08em; margin-bottom:10px; }

/* 角色状态卡 */
.state-cards { display:flex; flex-direction:column; gap:10px; }
.state-card {
  border:1px solid var(--border); border-left:3px solid var(--rc, var(--cyan));
  border-radius:var(--radius-sm); background:var(--bg-elevated);
  padding:10px 12px; display:flex; flex-direction:column; gap:7px;
}
.sc-head { display:flex; align-items:center; gap:8px; }
.sc-avatar { width:24px; height:24px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:700; color:#080c16; flex-shrink:0; }
.sc-name { font-size:13px; font-weight:600; color:var(--text-primary); flex:1; }
.sc-emotion { font-size:11px; font-family:var(--font-mono); color:var(--rc, var(--cyan)); }
.sc-intensity { display:flex; align-items:center; gap:8px; }
.sc-bar { flex:1; height:5px; background:var(--bg-base); border-radius:3px; overflow:hidden; }
.sc-fill { height:100%; border-radius:3px; background:var(--rc, var(--cyan)); transition:width .4s; }
.sc-pct { font-size:10px; font-family:var(--font-mono); color:var(--text-muted); min-width:28px; text-align:right; }
.sc-row { display:flex; gap:8px; align-items:flex-start; }
.sc-k { font-size:10px; font-family:var(--font-mono); color:var(--text-muted); min-width:44px; flex-shrink:0; padding-top:1px; }
.sc-v { font-size:12px; color:var(--text-secondary); line-height:1.5; flex:1; }
.sc-beliefs { display:flex; flex-wrap:wrap; gap:5px; margin-top:1px; }

.emotion-trend { font-size:12px; color:var(--text-muted); margin-bottom:8px; display:flex; align-items:center; gap:6px; }
.turning-point { font-size:11px; color:var(--amber); margin-bottom:12px; line-height:1.5; }
.emotion-bars { display:flex; flex-direction:column; gap:8px; }
.ebar-row { display:flex; align-items:center; gap:8px; }
.ebar-row.clickable { cursor:pointer; }
.ebar-label { font-size:11px; color:var(--text-muted); min-width:48px; font-family:var(--font-mono); }
.ebar-track { flex:1; height:6px; background:var(--bg-base); border-radius:3px; overflow:hidden; }
.ebar-fill { height:100%; border-radius:3px; transition:width .4s; }
.ebar-pct { font-size:11px; font-family:var(--font-mono); color:var(--text-muted); min-width:30px; text-align:right; }
.strategy-list { display:flex; flex-direction:column; gap:8px; }
.strategy-item {
  display:flex;
  flex-direction:column;
  gap:4px;
  text-align:left;
  padding:10px 12px;
  background:var(--bg-elevated);
  border:1px solid var(--border);
  border-radius:var(--radius-sm);
  color:var(--text-secondary);
  cursor:pointer;
}
.strategy-item small { color: var(--text-muted); line-height: 1.5; }

/* Modal */
.modal-overlay { position:fixed; inset:0; background:rgba(8,12,22,.7); backdrop-filter:blur(4px); z-index:1000; display:flex; align-items:center; justify-content:center; }
.modal { padding: 0; }
.modal-header { padding:18px 20px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; font-size:15px; font-weight:600; }
.btn-close { background:transparent; border:none; color:var(--text-muted); cursor:pointer; font-size:16px; }
.btn-close:hover { color:var(--text-primary); }
.char-select-list { display:flex; flex-direction:column; gap:6px; max-height:220px; overflow-y:auto; margin-bottom:4px; }
.char-select-item { display:flex; align-items:center; gap:10px; padding:8px 10px; border-radius:6px; cursor:pointer; border:1px solid transparent; }
.char-select-item:hover { background:var(--bg-hover); border-color:var(--border); }
.char-dot { width:30px; height:30px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700; color:#080c16; flex-shrink:0; }

/* Branch / Receiver selectors */
.branch-select, .receiver-select {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 12px;
  padding: 4px 8px;
  outline: none;
  max-width: 200px;
}
.branch-select:focus, .receiver-select:focus { border-color: var(--cyan); }

/* 多视角分析 */
.persp-tabs { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:4px; }
.persp-tab {
  display:flex; align-items:center; gap:5px;
  padding:3px 10px; border-radius:100px;
  border:1px solid var(--border); background:transparent;
  color:var(--text-secondary); font-size:11px; cursor:pointer;
  transition:var(--transition);
}
.persp-tab.active { border-color:var(--vc, var(--cyan)); color:var(--vc, var(--cyan)); background:color-mix(in srgb, var(--vc, var(--cyan)) 12%, transparent); }
.persp-dot { width:6px; height:6px; border-radius:50%; background:var(--vc, var(--cyan)); }
.persp-primary { font-size:9px; opacity:.7; }
.persp-hint { font-size:11px; color:var(--text-muted); margin:2px 0 4px; }
.persp-reply {
  display:flex; align-items:flex-start; gap:10px; margin-top:6px;
  padding:8px 10px; border-radius:8px;
  background:rgba(0,212,255,.06); border:1px solid rgba(0,212,255,.2);
}
.persp-reply .reply-text { flex:1; font-size:13px; color:var(--text-primary); line-height:1.6; }
.reply-use-btn { font-size:11px; padding:3px 10px; flex-shrink:0; }

/* Diagnosis */
.diagnosis-section { display:flex; flex-direction:column; gap:6px; margin-top:4px; }
.diagnosis-box {
  border: 1px solid rgba(124,58,237,.3);
  background: rgba(124,58,237,.07);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.diagnosis-head { display:flex; align-items:center; gap:8px; }
.diagnosis-summary { font-size:12px; color:var(--text-secondary); line-height:1.6; }

/* 场景标签 + 场景编辑器 */
.scene-tag { cursor:pointer; gap:5px; }
.scene-tag:hover { border-color: var(--cyan); }
.scene-dot { width:5px; height:5px; border-radius:50%; background:var(--cyan); }
.scene-preset-chips { display:flex; flex-wrap:wrap; gap:8px; }
.scene-chip { padding:6px 14px; border-radius:100px; border:1px solid var(--border); background:transparent; color:var(--text-secondary); font-size:12px; cursor:pointer; transition:var(--transition); }
.scene-chip:hover { border-color:var(--border-strong); color:var(--text-primary); }
.scene-chip.active { border-color:var(--cyan); color:var(--cyan); background:var(--cyan-dim); }
.scene-hint { font-size:11px; color:var(--text-muted); line-height:1.6; margin-top:8px; }

/* Transitions */
.msg-enter-active { transition: all .3s ease; }
.msg-enter-from   { opacity:0; transform:translateY(8px); }
</style>
