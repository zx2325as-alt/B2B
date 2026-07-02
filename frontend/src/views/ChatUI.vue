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
          <button v-if="isSelfMode" class="btn btn-primary" style="font-size:12px;padding:6px 12px" :disabled="advising" @click="generateAdvice">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
            {{ advising ? `生成中… 剩${adviceRemaining}` : '生成应对建议' }}
          </button>
          <button
            v-if="visibleMessages.length && !currentConversation?.is_readonly"
            class="btn btn-ghost" style="font-size:12px;padding:6px 12px"
            :disabled="rollingBack || chat.streaming"
            title="删除最近一轮「我方发言 + 对方回复」，回到上一轮"
            @click="rollbackTurn">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/></svg>
            {{ rollingBack ? '回退中…' : '回退上一轮' }}
          </button>
          <button class="btn btn-ghost" style="font-size:12px;padding:6px 12px" @click="handleArchiveConversation">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 8v13H3V8"/><path d="M1 3h22v5H1z"/><path d="M10 12h4"/></svg>
            一键归档
          </button>
          <button v-if="!currentConversation?.is_readonly" class="btn btn-ghost" style="font-size:12px;padding:6px 12px" @click="openQuickIngest" title="把真实聊天记录整段粘贴，一次性导入并分析">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M9 12h6M9 16h4"/></svg>
            粘贴整段
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
        <!-- Q4 越用越准：关于对方，系统已经累积的认知 -->
        <div v-if="cpMem && (cpMem.count || (cpMem.prediction && cpMem.prediction.resolved))" class="cpmem-bar">
          <button class="cpmem-head" @click="cpMemOpen = !cpMemOpen">
            <span class="cpmem-brain">🧠</span>
            关于「{{ cpMem.name }}」，我已经知道
            <span class="tag" style="font-size:10px;padding:1px 7px">{{ cpMem.count }} 条</span>
            <span v-if="cpMem.prediction && cpMem.prediction.hit_rate !== null" class="tag green" style="font-size:10px;padding:1px 7px">
              预演命中 {{ Math.round(cpMem.prediction.hit_rate * 100) }}%（{{ cpMem.prediction.resolved }} 次）
            </span>
            <span class="cpmem-caret">{{ cpMemOpen ? '▾' : '▸' }}</span>
          </button>
          <div v-if="cpMemOpen" class="cpmem-body">
            <div v-for="(l, i) in cpMem.learnings" :key="`cpm-${i}`" class="cpmem-item">
              <span class="tag" :class="cpMemSourceClass(l.source)" style="font-size:10px">{{ l.source }}</span>
              <span class="cpmem-text">{{ l.content }}</span>
              <span v-if="l.confidence !== null && l.confidence !== undefined" class="cpmem-conf">{{ Math.round(l.confidence * 100) }}%</span>
            </div>
            <div v-if="!cpMem.learnings.length" class="cpmem-empty">还在积累中——多聊几轮、归档或做几次预演，这里会逐渐长出对他的认知。</div>
          </div>
        </div>

        <div v-if="!chat.messages.length" class="welcome-screen">
          <div class="welcome-icon">◈</div>
          <div class="welcome-title">深度对话分析引擎</div>
          <div class="welcome-desc">AI Harness 实时解析对话潜台词<br>内心独白 · 情绪动态 · 隐含动机</div>
        </div>

        <TransitionGroup name="msg">
          <div v-for="msg in visibleMessages" :key="msg.id"
            :data-msg-id="msg.id"
            class="msg-wrapper" :class="[msg.role, { mine: isMine(msg) }]">
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
                  <!-- 阶段2：指定了「我」且这句是对方说的 → 洞察(对方) ‖ 行动(我) 双栏 -->
                  <template v-if="selfTwoCol(msg)">
                    <div class="duo">
                      <div class="duo-col insight">
                        <div class="duo-head">洞察 · {{ msg.character_name }} 怎么想</div>
                        <div v-if="cpIntent(msg)" class="analysis-row"><span class="a-label">真实意图</span><span class="a-value">{{ cpIntent(msg) }}</span></div>
                        <div v-if="cpEmotion(msg)" class="analysis-row"><span class="a-label">情绪</span><span class="a-value">{{ cpEmotion(msg) }}</span></div>
                        <!-- 收敛后的单一结论：潜台词以 final 为准（复核纠偏 + 对抗调和后的版本） -->
                        <div v-if="cpFinalSubtext(msg)" class="analysis-row"><span class="a-label">潜台词/动机</span><span class="a-value">{{ cpFinalSubtext(msg) }}</span></div>
                        <div v-if="cpEvidence(msg)" class="duo-evidence">依据：“{{ cpEvidence(msg) }}”</div>
                        <div v-else class="duo-evidence" style="color:var(--text-muted)">⚠ 无明确原文依据 · 为推测</div>
                        <div class="conclusion-trust">
                          <span v-if="cpFinalConf(msg) !== null" class="tag" :class="confClass(cpFinalConf(msg))" style="font-size:10px">{{ confLabel(cpFinalConf(msg)) }}</span>
                          <span v-if="cpFinal(msg) && cpFinal(msg).verdict && cpFinal(msg).verdict !== 'approved'" class="tag" :class="criticClass(cpFinal(msg).verdict)" style="font-size:10px">{{ criticLabel(cpFinal(msg).verdict) }}</span>
                        </div>
                        <div v-if="cpFinal(msg) && cpFinal(msg).alternative" class="duo-evidence" style="border-left-color:var(--violet,#a78bfa)">⚖ 也可能：{{ cpFinal(msg).alternative }}</div>
                        <!-- 推演过程（复核 + 对抗）默认折叠，要看再展开，避免三块互相打架的观感 -->
                        <button v-if="cpCritic(msg) || cpDebate(msg)" class="reasoning-toggle" @click="toggleReasoning(msg.id)">
                          {{ reasoningOpen(msg.id) ? '▾' : '▸' }} 推演过程（复核·对抗）
                        </button>
                        <template v-if="reasoningOpen(msg.id)">
                          <div v-if="cpCritic(msg)" class="critic-box">
                            <span class="tag" :class="criticClass(cpCritic(msg).verdict)" style="font-size:10px">{{ criticLabel(cpCritic(msg).verdict) }}</span>
                            <div v-for="(iss, i) in cpCritic(msg).issues" :key="`cri-${msg.id}-${i}`" class="critic-issue">· {{ iss }}</div>
                          </div>
                          <div v-if="cpDebate(msg)" class="debate-box">
                            <span class="tag" :class="debateClass(cpDebate(msg).stronger)" style="font-size:10px">{{ debateLabel(cpDebate(msg).stronger) }}</span>
                            <div v-if="cpDebate(msg).alternative && cpDebate(msg).alternative.subtext" class="debate-alt">另一种可能：{{ cpDebate(msg).alternative.subtext }}</div>
                            <div v-if="cpDebate(msg).reconciled && cpDebate(msg).reconciled.subtext" class="debate-recon">⚖ 调和：{{ cpDebate(msg).reconciled.subtext }}</div>
                          </div>
                        </template>
                      </div>
                      <div class="duo-col action">
                        <!-- 我怎么想：我（旁观）对这句话的内心解读 -->
                        <div v-if="hasSelfRead(msg)" class="self-read">
                          <div class="duo-head" style="color:#a78bfa">我怎么想</div>
                          <div v-if="selfRead(msg).inner" class="analysis-row"><span class="a-label">第一反应</span><span class="a-value">{{ selfRead(msg).inner }}</span></div>
                          <div v-if="selfRead(msg).subtext" class="analysis-row"><span class="a-label">我读到</span><span class="a-value">{{ selfRead(msg).subtext }}</span></div>
                          <div v-if="selfRead(msg).emotion" class="analysis-row"><span class="a-label">我的情绪</span><span class="a-value">{{ selfRead(msg).emotion }}</span></div>
                        </div>
                        <div class="duo-head">行动 · 我该怎么接</div>
                        <div v-if="selfMoves(msg).length" class="move-list">
                          <div v-for="(mv, i) in selfMoves(msg)" :key="`mv-${msg.id}-${i}`" class="move-card">
                            <div class="move-top">
                              <span class="move-label">{{ mv.label || ('策略' + (i + 1)) }}</span>
                              <button class="btn btn-ghost reply-use-btn" @click="useMove(msg, mv)">采用</button>
                            </div>
                            <div class="move-reply">{{ mv.reply }}</div>
                            <div v-if="mv.consequence" class="move-conseq">→ {{ mv.consequence }}</div>
                          </div>
                        </div>
                        <div v-else-if="selfReply(msg)" class="persp-reply" style="margin-top:0">
                          <span class="reply-text">{{ selfReply(msg) }}</span>
                          <button class="btn btn-ghost reply-use-btn" @click="useMove(msg, selfReply(msg))">采用</button>
                        </div>
                        <div v-else class="empty-hint" style="padding:8px 0;text-align:left">暂无应对建议，可点「重新分析」</div>
                      </div>
                    </div>
                  </template>
                  <!-- 通用多视角（未指定我 / 这句是我自己说的） -->
                  <template v-else>
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
                  <div v-if="(upFinal(msg) && upFinal(msg).subtext) || curUserPersp(msg)?.subtext" class="analysis-row">
                    <span class="a-label">策略动机</span><span class="a-value">{{ (upFinal(msg) && upFinal(msg).subtext) || curUserPersp(msg).subtext }}</span>
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
                  <!-- 可信度（收敛后单一结论）：依据 + 置信 + verdict；推演过程默认折叠 -->
                  <div v-if="curUserPersp(msg)" class="trust-strip">
                    <div v-if="upEvidence(msg)" class="duo-evidence">依据：“{{ upEvidence(msg) }}”</div>
                    <div v-else-if="!upGrounded(msg)" class="duo-evidence" style="color:var(--text-muted)">⚠ 无明确原文依据 · 为推测</div>
                    <div class="conclusion-trust">
                      <span v-if="(upFinal(msg) ? upFinal(msg).confidence : upConfidence(msg)) !== null && (upFinal(msg) ? upFinal(msg).confidence : upConfidence(msg)) !== undefined" class="tag" :class="confClass(upFinal(msg) ? upFinal(msg).confidence : upConfidence(msg))" style="font-size:10px">{{ confLabel(upFinal(msg) ? upFinal(msg).confidence : upConfidence(msg)) }}</span>
                      <span v-if="upFinal(msg) && upFinal(msg).verdict && upFinal(msg).verdict !== 'approved'" class="tag" :class="criticClass(upFinal(msg).verdict)" style="font-size:10px">{{ criticLabel(upFinal(msg).verdict) }}</span>
                    </div>
                    <div v-if="upFinal(msg) && upFinal(msg).alternative" class="duo-evidence" style="border-left-color:var(--violet,#a78bfa)">⚖ 也可能：{{ upFinal(msg).alternative }}</div>
                    <button v-if="upCritic(msg) || upDebate(msg)" class="reasoning-toggle" @click="toggleReasoning(msg.id)">
                      {{ reasoningOpen(msg.id) ? '▾' : '▸' }} 推演过程（复核·对抗）
                    </button>
                    <template v-if="reasoningOpen(msg.id)">
                      <div v-if="upCritic(msg)" class="critic-box">
                        <span class="tag" :class="criticClass(upCritic(msg).verdict)" style="font-size:10px">{{ criticLabel(upCritic(msg).verdict) }}</span>
                        <div v-for="(iss, i) in upCritic(msg).issues" :key="`ucri-${msg.id}-${i}`" class="critic-issue">· {{ iss }}</div>
                      </div>
                      <div v-if="upDebate(msg)" class="debate-box">
                        <span class="tag" :class="debateClass(upDebate(msg).stronger)" style="font-size:10px">{{ debateLabel(upDebate(msg).stronger) }}</span>
                        <div v-if="upDebate(msg).alternative && upDebate(msg).alternative.subtext" class="debate-alt">另一种可能：{{ upDebate(msg).alternative.subtext }}</div>
                        <div v-if="upDebate(msg).reconciled && upDebate(msg).reconciled.subtext" class="debate-recon">⚖ 调和：{{ upDebate(msg).reconciled.subtext }}</div>
                      </div>
                    </template>
                  </div>
                  </template>
                  <div style="display:flex;gap:8px;align-items:center;margin-top:4px;flex-wrap:wrap">
                    <button
                      class="btn btn-ghost"
                      style="font-size:11px;padding:4px 10px"
                      @click="reanalyzeUserMessage(msg)"
                    >
                      重新分析
                    </button>
                    <button
                      class="btn btn-ghost"
                      style="font-size:11px;padding:4px 10px"
                      :disabled="critiquingIds.has(msg.id)"
                      title="让 AI 复核员逐视角审查是否过度推断，把脑补的判断下调为推测"
                      @click="critiqueUserMessage(msg)"
                    >
                      {{ critiquingIds.has(msg.id) ? '复核中…' : '🔍 核验' }}
                    </button>
                    <button
                      class="btn btn-ghost"
                      style="font-size:11px;padding:4px 10px"
                      :disabled="diagnosingIds.has(msg.id)"
                      title="结构化深度诊断：潜台词/人格信号/关系影响，带证据与复核"
                      @click="runDiagnosis(msg)"
                    >
                      {{ diagnosingIds.has(msg.id) ? '诊断中…' : (diagnosisMap[msg.id] ? '重新诊断' : '深度诊断') }}
                    </button>
                  </div>
                  <div v-if="diagnosisMap[msg.id]" class="diagnosis-box">
                    <div class="diagnosis-head">
                      <span class="tag" :class="diagnosisStatusClass(diagnosisMap[msg.id].status)">{{ diagnosisStatusLabel(diagnosisMap[msg.id].status) }}</span>
                      <span class="a-pct">置信度 {{ Math.round((diagnosisMap[msg.id].confidence || 0) * 100) }}%</span>
                    </div>
                    <div class="diagnosis-summary">{{ diagnosisSummary(diagnosisMap[msg.id]) }}</div>
                  </div>
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

                  <!-- 对方回复也出「洞察(他) ‖ 行动(我怎么接)」，与我发给他逻辑相同 -->
                  <template v-if="selfTwoCol(msg)">
                    <div class="duo">
                      <div class="duo-col insight">
                        <div class="duo-head">洞察 · {{ msg.character_name }} 这句什么意思</div>
                        <div v-if="cpIntent(msg)" class="analysis-row"><span class="a-label">真实意图</span><span class="a-value">{{ cpIntent(msg) }}</span></div>
                        <div v-if="cpEmotion(msg)" class="analysis-row"><span class="a-label">情绪</span><span class="a-value">{{ cpEmotion(msg) }}</span></div>
                        <div v-if="cpSubtext(msg)" class="analysis-row"><span class="a-label">潜台词/动机</span><span class="a-value">{{ cpSubtext(msg) }}</span></div>
                        <div v-if="cpEvidence(msg)" class="duo-evidence">依据：“{{ cpEvidence(msg) }}”</div>
                        <div v-else class="duo-evidence" style="color:var(--text-muted)">⚠ 无明确原文依据 · 以下为推测</div>
                        <span v-if="cpConfidence(msg) !== null" class="tag" :class="confClass(cpConfidence(msg))" style="font-size:10px;align-self:flex-start">{{ confLabel(cpConfidence(msg)) }}</span>
                        <div v-if="cpCritic(msg)" class="critic-box">
                          <span class="tag" :class="criticClass(cpCritic(msg).verdict)" style="font-size:10px">{{ criticLabel(cpCritic(msg).verdict) }}</span>
                          <div v-for="(iss, i) in cpCritic(msg).issues" :key="`acri-${msg.id}-${i}`" class="critic-issue">· {{ iss }}</div>
                          <div v-if="cpCritic(msg).revised_subtext" class="critic-revised">复核版潜台词：{{ cpCritic(msg).revised_subtext }}</div>
                        </div>
                      </div>
                      <div class="duo-col action">
                        <div class="duo-head">行动 · 我该怎么接</div>
                        <div v-if="selfMoves(msg).length" class="move-list">
                          <div v-for="(mv, i) in selfMoves(msg)" :key="`amv-${msg.id}-${i}`" class="move-card">
                            <div class="move-top">
                              <span class="move-label">{{ mv.label || ('策略' + (i + 1)) }}</span>
                              <button class="btn btn-ghost reply-use-btn" @click="useMove(msg, mv)">采用</button>
                            </div>
                            <div class="move-reply">{{ mv.reply }}</div>
                            <div v-if="mv.consequence" class="move-conseq">→ {{ mv.consequence }}</div>
                          </div>
                        </div>
                        <div v-else class="empty-hint" style="padding:8px 0;text-align:left">暂无应对建议，可点「刷新建议」</div>
                      </div>
                    </div>
                    <div style="display:flex;gap:8px;align-items:center;margin-top:4px">
                      <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px" :disabled="advisingIds.has(msg.id)" @click="adviseMessage(msg)">
                        {{ advisingIds.has(msg.id) ? '生成中…' : '刷新建议' }}
                      </button>
                      <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px" :disabled="critiquingIds.has(msg.id)" @click="critiqueUserMessage(msg)">
                        {{ critiquingIds.has(msg.id) ? '复核中…' : '🔍 核验' }}
                      </button>
                    </div>
                  </template>

                  <!-- 多视角分析：在场每个角色站在自己立场看这句话 -->
                  <template v-else-if="getPerspectives(msg).length">
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
        <!-- 阶段3/6：指定了「我」时出现的军师 + 预演面板（可折叠，默认收起，不占页面） -->
        <div v-if="isSelfMode && counterpartName" class="advisor-box" :class="{ collapsed: !advisorOpen }">
          <button type="button" class="advisor-toggle" @click="advisorOpen = !advisorOpen">
            <span class="advisor-toggle-caret">{{ advisorOpen ? '▾' : '▸' }}</span>
            军师工具
            <span class="advisor-toggle-sub">实时军师 · 发出前预演</span>
            <span v-if="!advisorOpen" class="advisor-toggle-hint">点击展开</span>
          </button>
          <div v-show="advisorOpen" class="advisor-panel">
          <!-- 目标进度：连续分段追踪对话有没有朝目标推进 -->
          <div v-if="currentConversation?.goal" class="goal-progress-card">
            <div class="gp-head">
              <span class="advisor-title">目标进度</span>
              <span class="gp-goal" :title="currentConversation.goal">{{ currentConversation.goal }}</span>
              <button class="btn btn-ghost gp-refresh" :disabled="gpLoading || chat.streaming" @click="refreshGoalProgress">{{ gpLoading ? '评估中…' : '刷新' }}</button>
            </div>
            <template v-if="goalProgress && (goalProgress.segments||[]).length">
              <div class="gp-bar-row">
                <div class="gp-bar"><div class="gp-fill" :style="{ width: Math.round((goalProgress.score||0)*100)+'%' }"></div></div>
                <span class="gp-pct">{{ Math.round((goalProgress.score||0)*100) }}%</span>
                <span class="tag" :class="gpTrendClass(goalProgress.trend)" style="font-size:10px">{{ gpTrendLabel(goalProgress.trend) }}</span>
              </div>
              <div v-if="goalProgress.blocker" class="gp-line"><span class="gp-k">卡点</span>{{ goalProgress.blocker }}</div>
              <div v-if="goalProgress.next_lever" class="gp-line" style="color:var(--cyan)"><span class="gp-k">下一步</span>{{ goalProgress.next_lever }}</div>
              <div class="gp-timeline">
                <span v-for="(s, i) in goalProgress.segments.slice(-14)" :key="`gp-${i}`" class="gp-seg" :class="s.direction"
                  :title="s.summary + (s.reason ? (' — ' + s.reason) : '')">{{ gpSegMark(s.direction) }}</span>
                <span class="gp-timeline-hint">推进▲ 停滞■ 倒退▼</span>
              </div>
            </template>
            <div v-else class="gp-empty">还没评估过——发几轮、或点「刷新」看离目标多近。</div>
          </div>

          <!-- 实时军师：粘贴对方的话即时分析（会发消息，仅非只读会话） -->
          <template v-if="!currentConversation?.is_readonly">
            <div class="advisor-head">
              <span class="advisor-title">实时军师</span>
              <span class="advisor-sub">粘贴「{{ counterpartName }}」刚说的话，看他什么意思、我该怎么接</span>
            </div>
            <div class="advisor-row" style="margin-bottom:8px">
              <textarea v-model="adviceInput" class="chat-input" rows="1"
                :placeholder="`「${counterpartName}」说了什么…  Enter 分析`"
                @keydown.enter.exact.prevent="askCounterpart"></textarea>
              <button class="btn btn-primary" :disabled="chat.streaming || !adviceInput.trim()" @click="askCounterpart">分析</button>
            </div>
          </template>

          <!-- 阶段6：反事实预演——发出前看对方会怎么反应（不发消息，只读会话也可用） -->
          <div class="advisor-head">
            <span class="advisor-title">发出前预演</span>
            <span class="advisor-sub">想好一句话，先看「{{ counterpartName }}」会怎么反应</span>
            <span v-if="predictionStats && predictionStats.resolved" class="tag" :class="(predictionStats.hit_rate||0)>=0.6?'green':((predictionStats.hit_rate||0)>=0.4?'amber':'red')" style="font-size:10px;margin-left:auto" :title="`对「${counterpartName}」累计预演 ${predictionStats.total} 次，已对账 ${predictionStats.resolved} 次`">
              命中率 {{ Math.round((predictionStats.hit_rate||0)*100) }}%（{{ predictionStats.hits }}/{{ predictionStats.resolved }}）
            </span>
          </div>
          <div class="advisor-row">
            <textarea v-model="predictInput" class="chat-input" rows="1"
              :placeholder="`我想说…  预演「${counterpartName}」的反应`"
              @keydown.enter.exact.prevent="runPredict"></textarea>
            <button class="btn btn-ghost" :disabled="predicting || !predictInput.trim()" @click="runPredict">{{ predicting ? '预演中…' : '预演' }}</button>
          </div>
          <div v-if="prediction" class="predict-card">
            <div class="predict-top">
              <span class="tag" :class="reactionClass(prediction.reaction_type)" style="font-size:10px">{{ prediction.reaction_type }}</span>
              <span v-if="prediction.emotion" class="predict-emo">情绪：{{ prediction.emotion }}</span>
              <span class="predict-succ">达成意图 {{ Math.round((prediction.success_likelihood||0)*100) }}%</span>
            </div>
            <div class="predict-reply">「{{ counterpartName }}」很可能回：{{ prediction.predicted_reply }}</div>
            <div v-if="prediction.inner_read" class="predict-sub">他心里：{{ prediction.inner_read }}</div>
            <div v-if="prediction.risk" class="predict-sub" style="color:var(--red)">风险：{{ prediction.risk }}</div>
            <div v-if="prediction.better_tip" class="predict-sub" style="color:var(--green)">更稳：{{ prediction.better_tip }}</div>
            <div class="predict-actions">
              <button class="btn btn-primary" style="font-size:11px;padding:4px 12px" :disabled="chat.streaming" @click="adoptAndSend"
                title="把这句以「我」的身份发出去；对方真实回复后会和这条预测自动对账、回流学习">
                采用并发送
              </button>
              <span class="predict-hint">发出后系统会拿对方的真实回复给这条预测打分，越用越准</span>
            </div>
          </div>
          <!-- 预演闭环：最近对账结果（现实验证过的教训，已回流到对这个人的建模） -->
          <div v-if="!prediction && recentVerdict" class="predict-card" style="opacity:.92">
            <div class="predict-top">
              <span class="predict-sub" style="margin:0">上次预演对账</span>
              <span class="tag" :class="verdictClass(recentVerdict.verdict)" style="font-size:10px">{{ verdictLabel(recentVerdict.verdict) }}</span>
            </div>
            <div v-if="recentVerdict.note" class="predict-sub">{{ recentVerdict.note }}</div>
            <div v-if="recentVerdict.lesson" class="predict-sub" style="color:var(--cyan)">学到：{{ recentVerdict.lesson }}</div>
          </div>
          </div><!-- /advisor-panel -->
        </div>

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
          <span class="label" style="margin:0 0 0 8px" title="指定哪一方是「我」后，对方发言会给出「他什么意思 / 我该怎么接」的应对建议">我是：</span>
          <select class="input receiver-select" :value="selfName" @change="setSelfName($event.target.value)" title="指定「我」是谁">
            <option value="">未指定</option>
            <option v-for="role in activeRoles" :key="`self-${role.name}`" :value="role.name">{{ role.name }}</option>
          </select>
          <template v-if="isSelfMode">
            <span class="label" style="margin:0 0 0 8px" title="设定你跟对方想达成的目标，应对策略会围绕它排序">目标：</span>
            <input class="input receiver-select" style="max-width:180px" :value="currentConversation?.goal || ''"
              @change="setGoal($event.target.value)" placeholder="如：争取合作/缓和/婉拒…" title="我跟对方想达成的目标" />
          </template>
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
        <!-- 对方画像：跨会话沉淀的持久档案（指定了「我」时显示） -->
        <div v-if="isSelfMode && counterpartChar" class="epanel-block">
          <div class="block-title">对方画像 · {{ counterpartChar.name }}</div>
          <div class="cp-card">
            <div v-if="counterpartChar.role" class="sc-row"><span class="sc-k">身份</span><span class="sc-v">{{ counterpartChar.role }}</span></div>
            <div v-if="counterpartChar.motivation" class="sc-row"><span class="sc-k">动机</span><span class="sc-v">{{ counterpartChar.motivation }}</span></div>
            <div v-if="counterpartChar.weakness" class="sc-row"><span class="sc-k">软肋</span><span class="sc-v">{{ counterpartChar.weakness }}</span></div>
            <div v-if="counterpartChar.speaking_style" class="sc-row"><span class="sc-k">说话</span><span class="sc-v">{{ counterpartChar.speaking_style }}</span></div>
            <div v-if="cpDimText('desires')" class="sc-row"><span class="sc-k">在意</span><span class="sc-v">{{ cpDimText('desires') }}</span></div>
            <div v-if="cpDimText('fears')" class="sc-row"><span class="sc-k">雷区</span><span class="sc-v">{{ cpDimText('fears') }}</span></div>
            <div v-if="(counterpartChar.personality_tags || []).length" class="sc-beliefs">
              <span v-for="t in counterpartChar.personality_tags.slice(0, 8)" :key="`cpt-${t}`" class="tag" style="font-size:10px;padding:1px 8px">{{ t }}</span>
            </div>
            <div v-if="!counterpartChar.motivation && !counterpartChar.weakness && !(counterpartChar.personality_tags||[]).length && !cpDimText('desires') && !cpDimText('fears')" class="empty-hint" style="padding:6px 0;text-align:left">
              档案还很薄——多导入几段与 TA 的聊天，画像会越来越准。
            </div>
          </div>
        </div>

        <!-- 信息差 / 心智模型(ToM)：对方知道什么、在隐瞒什么（按需推演） -->
        <div v-if="isSelfMode && counterpartName" class="epanel-block">
          <div class="block-title" style="display:flex;justify-content:space-between;align-items:center">
            <span>信息差 · {{ counterpartName }}</span>
            <button class="btn btn-ghost" style="font-size:10px;padding:2px 9px" :disabled="tomLoading" @click="runToM">{{ tomLoading ? '推演中…' : (tom ? '重新推演' : '推演') }}</button>
          </div>
          <template v-if="tom">
            <div v-if="tom.info_edge" class="tom-edge">{{ tom.info_edge }}</div>
            <div v-for="grp in tomGroups" :key="grp.key" class="tom-grp">
              <div class="tom-grp-label">{{ grp.label }}</div>
              <div v-for="(it, i) in grp.items" :key="`${grp.key}-${i}`" class="tom-item">· {{ it }}</div>
            </div>
          </template>
          <div v-else class="empty-hint" style="padding:8px 0;text-align:left">点「推演」：看对方知道什么 / 不知道什么 / 在隐瞒什么。</div>
        </div>

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

        <!-- 下半：某一对角色之间的关系仪表盘 + 张力走势 -->
        <div class="epanel-block">
          <div class="block-title">关系仪表盘</div>
          <select v-if="rolePairs.length" class="input" v-model="trackingPair" @change="refreshEmotionCurve" style="margin-bottom:12px">
            <option v-for="pair in rolePairs" :key="pair.value" :value="pair.value">{{ pair.label }}</option>
          </select>

          <!-- 多维走势：信任 / 亲密 / 主动权 / 张力 -->
          <template v-if="relTrajectory.points && relTrajectory.points.length">
            <div v-for="dim in relTrajectory.dims" :key="dim.key" class="rel-dim">
              <span class="rel-dim-label">{{ dim.label }}</span>
              <svg class="rel-spark" viewBox="0 0 100 24" preserveAspectRatio="none">
                <polyline :points="relSparkPoints(dim.key)" fill="none" :stroke="relColor(dim.key)" stroke-width="1.6" vector-effect="non-scaling-stroke"/>
              </svg>
              <span class="rel-dim-val" :style="{ color: relColor(dim.key) }">{{ Math.round((relTrajectory.current[dim.key]||0)*100) }}{{ relTrend(dim.key) }}</span>
            </div>
            <div v-if="relTrajectory.turning_points && relTrajectory.turning_points.length" style="margin-top:10px">
              <div class="label">关键转折</div>
              <button v-for="(tp, i) in relTrajectory.turning_points" :key="`rtp-${i}`" class="rel-turn" @click="scrollToMessage(tp.message_id)">
                <span class="tag" :class="tp.direction==='上升'?'green':'red'" style="font-size:10px">{{ tp.dim }}{{ tp.direction }}</span>
                <span class="rel-turn-txt">{{ tp.snippet }}</span>
              </button>
            </div>
          </template>
          <div v-else class="empty-hint" style="padding:10px 0">对话几轮后，这里会显示你俩关系的信任 / 亲密 / 主动权 / 张力走势与转折。</div>

          <div class="label" style="margin-top:14px">逐句张力 / 情绪</div>
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

    <!-- 整段粘贴秒录入 -->
    <Teleport to="body">
      <div v-if="qi.open" class="modal-overlay" @click.self="qi.open = false">
        <div class="modal card fade-up" style="width:600px;max-height:86vh;overflow-y:auto">
          <div class="modal-header">
            <span>粘贴整段聊天记录</span>
            <button class="btn-close" @click="qi.open = false">✕</button>
          </div>
          <div style="padding:20px;display:flex;flex-direction:column;gap:14px">
            <!-- 步骤1：粘贴 -->
            <template v-if="qi.step === 'paste'">
              <div class="label">把真实对话整段粘进来（一行一句，形如「昵称: 内容」识别最准；没标签也能解析）</div>
              <textarea class="input" v-model="qi.text" rows="9"
                placeholder="阿杰: 在吗&#10;小敏: 怎么了&#10;阿杰: 周末那个事还算数吗&#10;小敏: 随便吧 我无所谓"
                style="resize:vertical;line-height:1.7;font-size:13px"></textarea>
              <div style="display:flex;gap:8px;justify-content:flex-end">
                <button class="btn btn-ghost" @click="qi.open = false">取消</button>
                <button class="btn btn-primary" :disabled="qi.loading || !qi.text.trim()" @click="qiPreview">
                  {{ qi.loading ? '解析中…' : '解析预览' }}
                </button>
              </div>
            </template>

            <!-- 步骤2：预览 + 归位 + 设「我」 -->
            <template v-else>
              <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
                <span class="label" style="margin:0">我是：</span>
                <select class="input" style="max-width:160px" v-model="qi.selfName">
                  <option value="">未指定</option>
                  <option v-for="s in qi.speakers" :key="`qself-${s}`" :value="s">{{ s }}</option>
                </select>
                <span style="font-size:11px;color:var(--text-tertiary)">
                  共 {{ qi.segments.length }} 句 · {{ qi.method === 'ai' ? 'AI 解析' : '快速识别' }}
                </span>
                <label style="font-size:11px;color:var(--text-tertiary);margin-left:auto;display:flex;align-items:center;gap:6px">
                  <input type="checkbox" v-model="qi.analyzeAll" /> 全部分析
                  <template v-if="!qi.analyzeAll">
                    · 最近 <input type="number" v-model.number="qi.analyzeLast" min="0" max="99" style="width:46px" class="input" /> 句
                  </template>
                </label>
              </div>
              <div class="qi-preview">
                <div v-for="(seg, i) in qi.segments" :key="`qseg-${i}`" class="qi-row"
                  :class="{ mine: qi.selfName && seg.speaker === qi.selfName }">
                  <input class="input qi-spk" v-model="seg.speaker" placeholder="发言人" list="qi-speakers" />
                  <input class="input qi-content" v-model="seg.content" />
                  <button class="btn-close" style="flex:0 0 auto" @click="qi.segments.splice(i, 1)" title="删除这一句">✕</button>
                </div>
                <datalist id="qi-speakers">
                  <option v-for="s in qi.speakers" :key="`qopt-${s}`" :value="s" />
                </datalist>
              </div>
              <div style="display:flex;gap:8px;justify-content:space-between">
                <button class="btn btn-ghost" @click="qi.step = 'paste'">← 返回修改</button>
                <button class="btn btn-primary" :disabled="qi.loading || !qi.segments.length" @click="qiCommit">
                  {{ qi.loading ? '导入中…' : (qi.analyzeAll ? '确认导入并全部分析' : (qi.analyzeLast > 0 ? `确认导入并分析最近${qi.analyzeLast}句` : '确认导入')) }}
                </button>
              </div>
            </template>
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
const relTrajectory = ref({ points: [], turning_points: [], current: {}, dims: [] })  // 关系多维走势
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
// 默认只显示「我方/各角色发言」（user）；对方的 AI 回复一旦生成了「洞察‖行动」应对建议，
// 也显示出来，让"他回完我"之后能看到他在想什么 + 我该怎么接（D）。无分析的旧 AI 回复仍隐藏（保持去重）。
// 真实对话分析器：只显示手动输入的发言（user）。AI 不再模拟对方回复，旧的模拟 assistant 气泡一并隐藏。
const visibleMessages = computed(() => chat.messages.filter(m => m.role === 'user'))
// 微信式左右布局：是「我」说的靠右，对方靠左
function isMine(msg) { return !!selfName.value && (msg.character_name || '') === selfName.value }

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
    loadDiagnoses(id)   // 载入已有/后台自动生成的深度诊断
    loadCounterpartMemory(id)   // 载入"关于对方我已经知道"
  } else {
    cpMem.value = null
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
// E：回退上一轮对话——删最近一次「我方发言 + 对方回复」整轮
const rollingBack = ref(false)
async function rollbackTurn() {
  if (rollingBack.value || !chat.activeConvId) return
  if (!await confirmDialog('回退上一轮？将删除最近一次「我方发言 + 对方回复」，不可恢复。')) return
  rollingBack.value = true
  try {
    const res = await chatApi.rollbackConversation(chat.activeConvId)
    await chat.loadMessages(chat.activeConvId)
    toast.success(`已回退（删除 ${res.data.removed} 条）`)
  } catch (e) {
    toast.error('回退失败：' + (e?.response?.data?.detail || e?.message || ''))
  } finally {
    rollingBack.value = false
  }
}
// 阶段5：LLM 复核员（critic-revise）——对这条已存分析逐视角审过度推断，下调置信、标推测
const critiquingIds = ref(new Set())
async function critiqueUserMessage(msg) {
  if (critiquingIds.value.has(msg.id)) return
  critiquingIds.value = new Set(critiquingIds.value).add(msg.id)
  try {
    const res = await chatApi.critiqueAnalysis(msg.id)
    await chat.loadMessages(chat.activeConvId)
    const flagged = res.data?.flagged_count || 0
    toast[flagged ? 'info' : 'success'](
      flagged ? `复核完成：${flagged} 处判断过度推断，已下调置信` : '复核完成：各视角判断均有原文支撑'
    )
  } catch (e) {
    toast.error('复核失败：' + (e?.response?.data?.detail || e?.message || ''))
  } finally {
    const next = new Set(critiquingIds.value); next.delete(msg.id); critiquingIds.value = next
  }
}
// A+D：手动为「对方」发言（含对方回复）生成/刷新「洞察 ‖ 行动」应对建议（自动流程已生成，这是保留的手动按钮）
const advisingIds = ref(new Set())
async function adviseMessage(msg) {
  if (advisingIds.value.has(msg.id)) return
  advisingIds.value = new Set(advisingIds.value).add(msg.id)
  try {
    await chatApi.adviseMessage(msg.id)
    await chat.loadMessages(chat.activeConvId)
    const s = new Set(expandedIds.value); s.add(msg.id); expandedIds.value = s
    toast.success('应对建议已刷新')
  } catch (e) {
    toast.error('生成失败：' + (e?.response?.data?.detail || e?.message || ''))
  } finally {
    const next = new Set(advisingIds.value); next.delete(msg.id); advisingIds.value = next
  }
}
// 读取某视角的 critic 复核结果（无则 null）
function perspCritic(persp) {
  const c = persp?.analysis_json?.critic
  return (c && (c.issues?.length || c.verdict)) ? c : null
}
function cpCritic(msg) { return perspCritic(cpPersp(msg)) }
function criticClass(v) { return ({ approved: 'green', softened: 'amber', downgraded: 'red' })[v] || '' }
function criticLabel(v) { return ({ approved: '已复核 · 站得住', softened: '已复核 · 已收敛措辞', downgraded: '已复核 · 过度推断已下调' })[v] || '已复核' }
// Q1 多轮对抗：读某视角的 debate（另一种可能 + 调和）
function perspDebate(persp) {
  const d = persp?.analysis_json?.debate
  return (d && ((d.alternative && d.alternative.subtext) || (d.reconciled && d.reconciled.subtext))) ? d : null
}
function cpDebate(msg) { return perspDebate(cpPersp(msg)) }
function debateClass(s) { return ({ original: 'green', alternative: 'red', both: 'amber' })[s] || '' }
function debateLabel(s) { return ({ original: '已对抗 · 原判成立', alternative: '已对抗 · 改判', both: '已对抗 · 两种皆可能' })[s] || '已对抗' }
// 三层收敛后的单一结论（final = 调和 > 复核修订 > 原始）
function cpFinal(msg) { return cpPersp(msg)?.analysis_json?.final || null }
function cpFinalSubtext(msg) { return cpFinal(msg)?.subtext || cpSubtext(msg) }
function cpFinalConf(msg) { const f = cpFinal(msg); return (f && typeof f.confidence === 'number') ? f.confidence : cpConfidence(msg) }
function upFinal(msg) { return curUserPersp(msg)?.analysis_json?.final || null }
// 推演过程（复核+对抗）默认折叠，要看再展开
const reasoningOpenIds = ref(new Set())
function reasoningOpen(id) { return reasoningOpenIds.value.has(id) }
function toggleReasoning(id) { const s = new Set(reasoningOpenIds.value); s.has(id) ? s.delete(id) : s.add(id); reasoningOpenIds.value = s }
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

// ── 阶段2：「洞察(对方) ‖ 行动(我)」双栏（指定了「我」时启用） ──────────
const selfName = computed(() => currentConversation.value?.self_name || '')
const isSelfMode = computed(() => !!selfName.value)
function selfTwoCol(msg) {
  // 指定了「我」、且这句是「对方」说的 → 用双栏（他什么意思 / 我怎么接）
  return isSelfMode.value && msg.character_name && msg.character_name !== selfName.value && userPerspectives(msg).length > 0
}
function cpPersp(msg) {
  // 对方（发言者）自述视角 = 他的真实意图
  const list = userPerspectives(msg)
  return list.find(p => p.stance === 'speaker') || list.find(p => p.viewer_name === msg.character_name) || list[0] || null
}
function selfPersp(msg) {
  // 「我」的旁观视角 = 我的应对
  const list = userPerspectives(msg)
  return list.find(p => p.viewer_name === selfName.value && p.stance === 'observer')
    || list.find(p => p.viewer_name === selfName.value) || null
}
function cpIntent(msg) {
  const p = cpPersp(msg)
  const aj = p?.analysis_json || {}
  return (aj.tags?.primary || '').trim() || (aj.inner_monologue?.first_reaction || '').trim()
}
function cpEmotion(msg) { return cpPersp(msg)?.emotion_label || '' }
function cpSubtext(msg) { return cpPersp(msg)?.subtext || '' }
function cpEvidence(msg) { return (cpPersp(msg)?.analysis_json?.evidence || '').trim() }
function cpConfidence(msg) {
  const c = cpPersp(msg)?.analysis_json?.confidence
  return (typeof c === 'number') ? c : null
}
// 通用视角（curUserPersp）的可信度：依据 / 把握 / 复核 —— 让非双栏视角也看得见信任信号
function upEvidence(msg) { return (curUserPersp(msg)?.analysis_json?.evidence || '').trim() }
function upConfidence(msg) {
  const c = curUserPersp(msg)?.analysis_json?.confidence
  return (typeof c === 'number') ? c : null
}
function upGrounded(msg) { return curUserPersp(msg)?.analysis_json?.grounded !== false }
function upCritic(msg) { return perspCritic(curUserPersp(msg)) }
function upDebate(msg) { return perspDebate(curUserPersp(msg)) }
function selfMoves(msg) {
  const moves = selfPersp(msg)?.analysis_json?.moves
  return Array.isArray(moves) ? moves.filter(m => m && m.reply) : []
}
function selfReply(msg) { return selfPersp(msg)?.suggested_reply || '' }
// 「我怎么想」：我(旁观)对这句话的内心解读——第一反应/防御/倾向 + 我读到的潜台词 + 我的情绪
function selfRead(msg) {
  const p = selfPersp(msg)
  if (!p) return null
  const im = p.analysis_json?.inner_monologue
  const inner = (im && typeof im === 'object')
    ? [im.first_reaction, im.defense, im.tendency].filter(Boolean).join('；')
    : (p.inner_monologue || '')
  return { inner: inner || '', subtext: p.subtext || '', emotion: p.emotion_label || '' }
}
function hasSelfRead(msg) { const r = selfRead(msg); return !!(r && (r.inner || r.subtext || r.emotion)) }
function confLabel(c) { return c >= 0.7 ? `把握高 ${Math.round(c*100)}%` : (c >= 0.5 ? `中等 ${Math.round(c*100)}%` : `推测 ${Math.round(c*100)}%`) }
function confClass(c) { return c >= 0.7 ? 'green' : (c >= 0.5 ? 'amber' : 'red') }
// 采用某条应对话术：切到「我」身份、对着「对方」、填入话术
// 采用某条建议后，发送时回流为"这招对他有没有用"（Q5 结果反馈闭环）
const pendingAdoptedMove = ref(null)
function useMove(msg, move) {
  const reply = typeof move === 'string' ? move : (move && move.reply)
  if (!reply) return
  const role = activeRoles.value.find(r => r.name === selfName.value)
  if (role) handleSelectSpeaker(role)
  currentReceiver.value = msg.character_name || ''
  inputText.value = reply
  // 带后果的 move（非纯字符串）→ 记下来，发出后与对方实际回复对账
  pendingAdoptedMove.value = (move && typeof move === 'object' && move.consequence)
    ? { label: move.label || '', consequence: move.consequence } : null
  nextTick(() => { inputEl.value?.focus(); autoResize() })
  toast.info('已填入该应对话术，可直接发送或修改')
}
// 在聊天里指定「我」是谁（写入会话 self_name，立即驱动双栏与定向分析）
async function setSelfName(name) {
  if (!chat.activeConvId) return
  try {
    const res = await chatApi.updateConversation(chat.activeConvId, { self_name: name || '' })
    const conv = chat.conversations.find(c => c.id === chat.activeConvId)
    if (conv) Object.assign(conv, res.data)
    if (name) localStorage.setItem('btb_self_name', name)  // 记住「我」是谁，下次默认
    toast.success(name ? `已设定「${name}」为我；对方发言将给出我的应对建议` : '已取消「我」的指定')
  } catch { /* 拦截器已提示 */ }
}
// 默认「我是」：会话未指定 self_name 时，自动套用上次记住的「我」（默认 xxx），前提是该角色在场
function ensureDefaultSelfName() {
  const conv = currentConversation.value
  if (!conv || (conv.self_name || '').trim()) return
  const remembered = localStorage.getItem('btb_self_name') || 'xxx'
  if (activeRoles.value.some(r => r.name === remembered)) setSelfName(remembered)
}
// 会话或在场角色就绪时，自动套用默认「我」
watch([() => chat.activeConvId, activeRoles], () => ensureDefaultSelfName())
// 设定「我的目标」——应对策略 moves 会围绕它排序，预演也按它评估达成率
async function setGoal(val) {
  if (!chat.activeConvId) return
  try {
    const res = await chatApi.updateConversation(chat.activeConvId, { goal: val || '' })
    const conv = chat.conversations.find(c => c.id === chat.activeConvId)
    if (conv) Object.assign(conv, res.data)
    if ((val || '').trim()) toast.info('目标已设定，后续应对会围绕它排序')
  } catch { /* 拦截器已提示 */ }
}
// 为导入/历史会话里「对方」的每句发言批量生成洞察‖行动（分批续跑直到完成）
const advising = ref(false)
const adviceRemaining = ref(0)
async function generateAdvice() {
  if (!chat.activeConvId || advising.value) return
  if (!selfName.value) { toast.error('请先在「我是」里指定我是谁'); return }
  advising.value = true
  try {
    let guard = 0
    do {
      const res = await chatApi.generateAdvice(chat.activeConvId, 8)
      adviceRemaining.value = res.data.remaining || 0
    } while (adviceRemaining.value > 0 && guard++ < 80)
    await chat.loadMessages(chat.activeConvId)
    toast.success('应对建议已生成，展开对方发言即可看「洞察 ‖ 行动」')
  } catch (e) {
    toast.error('生成失败：' + (e?.response?.data?.detail || e?.message || ''))
  } finally {
    advising.value = false
    adviceRemaining.value = 0
  }
}

// ── 阶段3：实时「军师」——粘贴对方刚说的话，即时出洞察+应对 ──────────
const adviceInput = ref('')
const counterpartName = computed(() => {
  if (!selfName.value) return ''
  const others = activeRoles.value.filter(r => r.name !== selfName.value)
  return others.length ? others[0].name : ''
})
const counterpartChar = computed(() => chars.characters.find(c => c.name === counterpartName.value) || null)
// 从对方立体档案里取某一维(在意=desires/雷区=fears 等)的前几条，兼容字符串或对象元素
function cpDimText(key) {
  const arr = counterpartChar.value?.profile_json?.[key]
  if (!Array.isArray(arr) || !arr.length) return ''
  const META = ['content', 'confidence', 'evidence_ids', 'updated_at']
  return arr.slice(0, 3).map(it => {
    if (typeof it === 'string') return it
    if (it && typeof it === 'object') {
      if (it.content) return it.content   // 新规范形态
      return Object.entries(it).filter(([k, v]) => v && !META.includes(k)).map(([, v]) => v).join('：')
    }
    return String(it)
  }).filter(Boolean).join('；')
}

// 军师工具折叠：默认收起、不占页面；用到（预演/分析）时自动展开看结果
const advisorOpen = ref(false)
// ── 阶段6：反事实预演（发出前看对方反应） ────────────────────
const predictInput = ref('')
const prediction = ref(null)
const predicting = ref(false)
async function runPredict() {
  const text = predictInput.value.trim()
  if (!text || !counterpartName.value || !chat.activeConvId || predicting.value) return
  predicting.value = true; prediction.value = null
  try {
    const res = await chatApi.predictReaction(chat.activeConvId, text, selfName.value, counterpartName.value)
    prediction.value = res.data
    advisorOpen.value = true   // 出结果时自动展开
  } catch (e) { toast.error('预演失败：' + (e?.response?.data?.detail || e?.message || '')) }
  finally { predicting.value = false }
}
function reactionClass(t) { return ({ '暖化':'green','妥协':'green','激化':'red','回避':'amber','试探':'amber','无感':'' })[t] || '' }
// 预演闭环：采用预演的话并发送，带上 prediction_id，发出后对方真实回复会与这条预测对账、回流学习
const pendingPredictionId = ref(null)
const predictionStats = ref(null)
const recentVerdict = computed(() => (predictionStats.value?.recent || []).find(p => p.status === 'resolved' && p.verdict) || null)
// 目标进度：连续分段追踪对话有没有朝目标推进
const goalProgress = ref(null)
const gpLoading = ref(false)
async function loadGoalProgress() {
  if (!chat.activeConvId || !currentConversation.value?.goal) { goalProgress.value = null; return }
  try { const res = await chatApi.getGoalProgress(chat.activeConvId); goalProgress.value = res.data.progress || null }
  catch { goalProgress.value = null }
}
async function refreshGoalProgress() {
  if (!chat.activeConvId || gpLoading.value) return
  gpLoading.value = true
  try {
    const res = await chatApi.refreshGoalProgress(chat.activeConvId)
    goalProgress.value = res.data.progress || null
    toast.success('目标进度已更新')
  } catch (e) { toast.error('评估失败：' + (e?.response?.data?.detail || e?.message || '')) }
  finally { gpLoading.value = false }
}
function gpTrendClass(t) { return ({ rising: 'green', stalled: 'amber', falling: 'red' })[t] || '' }
function gpTrendLabel(t) { return ({ rising: '↑ 上升', stalled: '→ 停滞', falling: '↓ 下降' })[t] || t }
function gpSegMark(d) { return ({ advance: '▲', stall: '■', regress: '▼' })[d] || '·' }
async function loadPredictionStats() {
  if (!chat.activeConvId || !counterpartName.value) { predictionStats.value = null; return }
  try {
    const res = await chatApi.getPredictionStats(chat.activeConvId, counterpartName.value)
    predictionStats.value = res.data
  } catch { predictionStats.value = null }
}
async function adoptAndSend() {
  const p = prediction.value
  if (!p || !p.candidate || chat.streaming) return
  const meRole = activeRoles.value.find(r => r.name === selfName.value)
  if (meRole) handleSelectSpeaker(meRole)
  currentReceiver.value = counterpartName.value || ''
  inputText.value = p.candidate
  pendingPredictionId.value = p.prediction_id || null
  prediction.value = null
  await nextTick()
  await handleSend()
}
function verdictClass(v) { return ({ hit:'green', partial:'amber', miss:'red' })[v] || '' }
function verdictLabel(v) { return ({ hit:'命中', partial:'部分', miss:'落空' })[v] || v }

// ── 阶段5：信息差 / 心智模型(ToM) ────────────────────────────
const tom = ref(null)
const tomLoading = ref(false)
async function runToM() {
  if (!counterpartName.value || !chat.activeConvId || tomLoading.value) return
  tomLoading.value = true
  try {
    const res = await chatApi.theoryOfMind(chat.activeConvId, selfName.value, counterpartName.value)
    tom.value = res.data
  } catch (e) { toast.error('推演失败：' + (e?.response?.data?.detail || e?.message || '')) }
  finally { tomLoading.value = false }
}
const tomGroups = computed(() => {
  if (!tom.value) return []
  return [
    { key: 'knows', label: '他知道' }, { key: 'unaware', label: '他不知道/误以为' },
    { key: 'hiding', label: '在隐瞒/回避' }, { key: 'assumes', label: '对我的假设' },
  ].map(g => ({ ...g, items: tom.value[g.key] || [] })).filter(g => g.items.length)
})
// 切换会话时清空推演结果，避免串台
watch(() => chat.activeConvId, () => { tom.value = null; prediction.value = null; predictInput.value = ''; pendingPredictionId.value = null; goalProgress.value = null; loadPredictionStats(); loadGoalProgress() })
// 展开军师工具时拉一次命中率
watch(advisorOpen, (open) => { if (open) { loadPredictionStats(); loadGoalProgress() } })
async function askCounterpart() {
  const text = adviceInput.value.trim()
  if (!text) return
  if (!counterpartName.value) { toast.error('请先在「管理」里加入对方角色'); return }
  if (chat.streaming) return
  adviceInput.value = ''
  await nextTick()
  const role = activeRoles.value.find(r => r.name === counterpartName.value)
  // 以「对方」身份把这句话发给「我」——后端即产出他的意图 + 我的多策略应对
  await chat.sendMessage({
    speaker: counterpartName.value,
    content: text,
    characterId: role?.id || null,
    receiverName: selfName.value,
    activeCharacters: activeRoles.value.map(r => ({ id: r.id, name: r.name })),
  })
  // 自动展开这句对方发言的「洞察 ‖ 行动」
  await nextTick()
  const last = [...chat.messages].reverse().find(m => m.role === 'user' && m.character_name === counterpartName.value)
  if (last) { const s = new Set(expandedIds.value); s.add(last.id); expandedIds.value = s }
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

// ── 整段粘贴秒录入（P2）──────────────────────────────────────────────────
const qi = ref({ open: false, step: 'paste', text: '', loading: false,
  segments: [], speakers: [], method: '', selfName: '', analyzeAll: true, analyzeLast: 8 })

async function openQuickIngest() {
  if (!chat.activeConvId) {
    await chat.newConversation('新对话 ' + new Date().toLocaleTimeString('zh-CN', { hour:'2-digit', minute:'2-digit' }))
  }
  qi.value = { open: true, step: 'paste', text: '', loading: false,
    segments: [], speakers: [], method: '', selfName: selfName.value || '', analyzeAll: true, analyzeLast: 8 }
}

async function qiPreview() {
  if (!qi.value.text.trim()) return
  qi.value.loading = true
  try {
    const res = await chatApi.quickIngestPreview(chat.activeConvId, qi.value.text)
    qi.value.segments = (res.data.segments || []).map(s => ({ speaker: s.speaker || '', content: s.content || '' }))
    qi.value.speakers = res.data.speakers || []
    qi.value.method = res.data.method || ''
    if (!qi.value.selfName) qi.value.selfName = res.data.self_name || ''
    qi.value.step = 'review'
  } finally {
    qi.value.loading = false
  }
}

async function qiCommit() {
  const segments = qi.value.segments.filter(s => (s.content || '').trim())
  if (!segments.length) { toast.error('没有可导入的内容'); return }
  qi.value.loading = true
  try {
    const analyzeLast = qi.value.analyzeAll ? segments.length : (qi.value.analyzeLast || 0)
    const res = await chatApi.quickIngestCommit(chat.activeConvId, {
      segments, self_name: qi.value.selfName || null, analyze_last: analyzeLast,
    })
    qi.value.open = false
    await chat.loadMessages(chat.activeConvId)
    const n = res.data.created
    const a = (res.data.analyzing || []).length
    toast.success(`已导入 ${n} 句${a ? `，后台逐条分析 ${a} 句中…稍后自动显示` : ''}`)
    // 后台分析较慢（每条 opus 分析+复核），按条数放大轮询次数让结果逐步浮现
    if (a > 0) qiPollAnalysis(Math.min(40, a * 4 + 4))
  } finally {
    qi.value.loading = false
  }
}

// 整段录入后后台逐条分析较慢，轮询刷新让结果逐步显示
function qiPollAnalysis(times) {
  if (times <= 0) return
  setTimeout(async () => {
    if (chat.activeConvId) {
      await chat.loadMessages(chat.activeConvId)
      loadDiagnoses(chat.activeConvId)   // 整段录入后台诊断也逐步浮现
    }
    qiPollAnalysis(times - 1)
  }, 8000)
}

async function handleArchiveConversation() {
  if (!chat.activeConvId || !activeRoles.value.length) return
  const confirmed = await confirmDialog(`将当前对话归档到以下角色：${activeRoles.value.map(role => role.name).join('、')}。是否继续？`)
  if (!confirmed) return
  const res = await chatApi.archiveConversation(chat.activeConvId, {
    role_names: activeRoles.value.map(role => role.name),
  })
  toast.success(`归档完成：${res.data.archived_roles.join('、')}${res.data.observations_created ? `，并生成 ${res.data.observations_created} 条待审核建议` : ''}`)
  loadCounterpartMemory(chat.activeConvId)   // 归档后"我已经知道"可能新增，刷新
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

  const predictionId = pendingPredictionId.value
  pendingPredictionId.value = null  // 一次性消费，避免误关联到后续消息
  const adopted = pendingAdoptedMove.value
  pendingAdoptedMove.value = null   // 同样一次性消费
  await chat.sendMessage({
    speaker: currentSpeaker.value,
    content: text,
    characterId: currentCharId.value,
    receiverName: currentReceiver.value || null,
    activeCharacters: activeRoles.value.map(r => ({ id: r.id, name: r.name })),
    predictionId,
    adoptedConsequence: adopted ? adopted.consequence : null,
    adoptedLabel: adopted ? adopted.label : null,
  })
  if (predictionId || adopted) loadPredictionStats()  // 发完后刷新命中率（对账在后台进行）
}

// Q4 越用越准：关于对方系统已累积的认知（核心档案+假设+观察+预演教训+命中率）
const cpMem = ref(null)
const cpMemOpen = ref(false)
async function loadCounterpartMemory(cid) {
  if (!cid) { cpMem.value = null; return }
  try {
    const res = await chatApi.counterpartMemory(cid)
    cpMem.value = (res.data && res.data.name) ? res.data : null
  } catch { cpMem.value = null }
}
function cpMemSourceClass(s) { return s === '推测' ? 'amber' : 'green' }

// 载入会话已有的深度诊断（含后台自动生成的），按 message_id 取最新一条 → diagnosisMap
async function loadDiagnoses(cid) {
  if (!cid) return
  try {
    const res = await chatApi.listDiagnoses(cid, 80)
    const map = {}
    for (const d of (res.data || [])) {
      if (d.message_id && !map[d.message_id]) map[d.message_id] = d   // 列表按时间倒序，首条即最新
    }
    diagnosisMap.value = map
  } catch { /* 忽略诊断加载失败 */ }
}

// ── 深度诊断（按需触发 / 后台自动） ──────────────────────────────────────
async function runDiagnosis(msg) {
  if (diagnosingIds.value.has(msg.id)) return
  diagnosingIds.value = new Set([...diagnosingIds.value, msg.id])
  try {
    const res = await chatApi.diagnoseMessage(msg.id)   // 诊断直接挂在用户消息上
    diagnosisMap.value = { ...diagnosisMap.value, [msg.id]: res.data }
  } catch (e) {
    toast.error('诊断失败：' + (e?.response?.data?.detail || e?.message || ''))
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
  const [source, target] = trackingPair.value.split('→')
  try {
    const res = await chatApi.getEmotionTension(chat.activeConvId, source, target)
    emotionData.value = res.data
  } catch {
    emotionData.value = { emotions: [], trend: 'stable', turning_point: null }
  }
  try {
    const res = await chatApi.getRelationshipTrajectory(chat.activeConvId, source, target)
    relTrajectory.value = res.data
  } catch {
    relTrajectory.value = { points: [], turning_points: [], current: {}, dims: [] }
  }
}
// 关系维度 sparkline：把 points 映射成 SVG polyline 坐标串
const REL_DIM_COLORS = { trust: 'var(--green)', intimacy: 'var(--violet)', dominance: 'var(--amber)', tension: 'var(--red)' }
function relSparkPoints(dimKey) {
  const pts = relTrajectory.value.points || []
  if (pts.length < 2) return ''
  const W = 100, H = 24
  return pts.map((p, i) => `${((i / (pts.length - 1)) * W).toFixed(1)},${(H - (p[dimKey] || 0) * H).toFixed(1)}`).join(' ')
}
function relTrend(dimKey) {
  const pts = relTrajectory.value.points || []
  if (pts.length < 2) return ''
  const d = (pts[pts.length - 1][dimKey] || 0) - (pts[0][dimKey] || 0)
  return d > 0.08 ? '↑' : (d < -0.08 ? '↓' : '→')
}
function relColor(dimKey) { return REL_DIM_COLORS[dimKey] || 'var(--cyan)' }
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
/* 微信式左右布局：是「我」说的靠右、对方靠左（按发言者，不按 role） */
.msg-wrapper.mine .msg-head { flex-direction: row-reverse; }
.msg-wrapper.mine .msg-body { align-items: flex-end; }
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
.msg-wrapper.mine .msg-bubble { background: var(--cyan-dim); border-color: rgba(0,212,255,0.25); }
.msg-bubble.streaming { border-color: var(--cyan); animation: pulse-cyan 1.5s infinite; }
.msg-bubble.error { border-color: rgba(239,68,68,.4); background: rgba(239,68,68,.05); }
.cursor-blink { animation: blink 1s step-end infinite; color: var(--cyan); }
.analysis-tags { display:flex; gap:6px; flex-wrap:wrap; margin-top:4px; }
.tag-btn { background: rgba(124,58,237,.12); border-color: rgba(124,58,237,.25); color:#c4b5fd; cursor:pointer; }

/* Analysis Layer */
/* 分析层跟随消息左右：「我」靠右、对方靠左，查看分析贴在气泡同侧（不再单独占左侧整行） */
.analysis-layer { margin-top: 2px; display: flex; flex-direction: column; align-items: flex-start; }
.msg-wrapper.mine .analysis-layer { align-items: flex-end; }
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
.cp-card { display:flex; flex-direction:column; gap:6px; padding:10px 12px; border:1px solid var(--border); border-left:3px solid var(--cyan); border-radius:var(--radius-sm); background:var(--bg-elevated); }

/* 关系仪表盘 */
.rel-dim { display:flex; align-items:center; gap:8px; margin-bottom:7px; }
.rel-dim-label { font-size:11px; color:var(--text-secondary); min-width:48px; }
.rel-spark { flex:1; height:24px; background:var(--bg-base); border-radius:4px; }
.rel-dim-val { font-size:11px; font-family:var(--font-mono); min-width:42px; text-align:right; }
.rel-turn { display:flex; align-items:center; gap:8px; width:100%; text-align:left; background:transparent; border:none; cursor:pointer; padding:4px 2px; }
.rel-turn:hover { background:var(--bg-hover); border-radius:6px; }
.rel-turn-txt { font-size:11px; color:var(--text-muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; flex:1; }

/* 阶段6 反事实预演卡 */
.predict-card { margin-top:8px; padding:9px 11px; border-radius:8px; background:var(--bg-elevated); border:1px solid var(--border); display:flex; flex-direction:column; gap:5px; }
.predict-top { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.predict-emo { font-size:11px; color:var(--text-secondary); }
.predict-succ { font-size:11px; font-family:var(--font-mono); color:var(--cyan); margin-left:auto; }
.predict-reply { font-size:13px; color:var(--text-primary); line-height:1.6; }
.predict-sub { font-size:11px; color:var(--text-muted); line-height:1.5; }
.predict-actions { display:flex; align-items:center; gap:10px; margin-top:4px; flex-wrap:wrap; }
.predict-hint { font-size:10px; color:var(--text-muted); }

/* 阶段5 信息差/ToM */
.tom-edge { font-size:12px; color:var(--amber); line-height:1.6; padding:6px 8px; background:rgba(245,158,11,.08); border-radius:6px; margin-bottom:8px; }
.tom-grp { margin-bottom:8px; }
.tom-grp-label { font-size:11px; font-family:var(--font-mono); color:var(--text-muted); margin-bottom:3px; }
.tom-item { font-size:12px; color:var(--text-secondary); line-height:1.55; }

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

/* 阶段2：洞察(对方) ‖ 行动(我) 双栏 */
.duo { display:flex; gap:12px; align-items:stretch; flex-wrap:wrap; }
.duo-col { flex:1; min-width:240px; display:flex; flex-direction:column; gap:7px; padding:12px; border-radius:var(--radius-sm); border:1px solid var(--border); }
.duo-col.insight { background:rgba(124,58,237,.06); border-color:rgba(124,58,237,.22); }
.duo-col.action  { background:rgba(0,212,255,.05);  border-color:rgba(0,212,255,.2); }
.self-read { padding:8px 10px; margin-bottom:4px; border-radius:6px; background:rgba(124,58,237,.06); border-left:2px solid rgba(124,58,237,.4); display:flex; flex-direction:column; gap:5px; }
.duo-head { font-size:12px; font-weight:600; color:var(--text-primary); margin-bottom:2px; }
.duo-col.insight .duo-head { color:#a78bfa; }
.duo-col.action  .duo-head { color:var(--cyan); }
.duo-evidence { font-size:12px; color:var(--text-secondary); line-height:1.6; padding:6px 8px; border-left:2px solid var(--border-strong); background:rgba(255,255,255,.02); border-radius:4px; }
.move-list { display:flex; flex-direction:column; gap:8px; }
.move-card { padding:9px 11px; border-radius:8px; background:var(--bg-elevated); border:1px solid var(--border); display:flex; flex-direction:column; gap:5px; }
.move-top { display:flex; align-items:center; gap:8px; }
.move-label { flex:1; font-size:11px; font-family:var(--font-mono); color:var(--cyan); }
.move-reply { font-size:13px; color:var(--text-primary); line-height:1.6; }
.move-conseq { font-size:11px; color:var(--text-muted); line-height:1.5; }

/* 阶段5：LLM 复核员（critic-revise） */
.critic-box { display:flex; flex-direction:column; gap:4px; margin-top:6px; padding:6px 8px; border-radius:4px; border-left:2px solid var(--amber, #f59e0b); background:rgba(245,158,11,.06); }
.critic-issue { font-size:11px; color:var(--text-secondary); line-height:1.5; }
.critic-revised { font-size:11px; color:var(--text-primary); line-height:1.5; font-style:italic; }
/* Q1 多轮对抗：另一种可能 + 调和 */
.debate-box { display:flex; flex-direction:column; gap:4px; margin-top:6px; padding:6px 8px; border-radius:4px; border-left:2px solid var(--violet, #a78bfa); background:rgba(167,139,250,.07); }
.debate-alt { font-size:11px; color:var(--text-secondary); line-height:1.5; }
.debate-recon { font-size:11px; color:var(--text-primary); line-height:1.5; font-weight:500; }

/* Q4 越用越准：关于对方我已经知道 */
.cpmem-bar { margin:0 0 14px; border:1px solid var(--border); border-radius:10px; background:var(--bg-1, rgba(255,255,255,.02)); overflow:hidden; }
.cpmem-head { width:100%; display:flex; align-items:center; gap:8px; padding:8px 12px; background:none; border:none; color:var(--text-secondary); font-size:12px; cursor:pointer; text-align:left; }
.cpmem-head:hover { color:var(--text-primary); }
.cpmem-brain { font-size:14px; }
.cpmem-caret { margin-left:auto; color:var(--text-muted); }
.cpmem-body { padding:4px 12px 12px; display:flex; flex-direction:column; gap:6px; }
.cpmem-item { display:flex; align-items:flex-start; gap:8px; font-size:12px; line-height:1.5; }
.cpmem-text { color:var(--text-primary); flex:1; }
.cpmem-conf { color:var(--text-muted); font-size:10px; flex:0 0 auto; }
.cpmem-empty { font-size:11px; color:var(--text-muted); line-height:1.6; }

/* 阶段3：实时军师快捷输入 */
.advisor-box { margin-bottom:10px; padding:10px 12px; border-radius:var(--radius-sm); border:1px solid var(--border-strong); background:var(--cyan-dim); }
.advisor-box.collapsed { padding:0; background:transparent; border-color:var(--border); }
.advisor-toggle { width:100%; display:flex; align-items:center; gap:8px; padding:7px 10px; background:none; border:none; cursor:pointer; color:var(--text-secondary); font-size:12px; font-weight:600; }
.advisor-toggle:hover { color:var(--text-primary); }
.advisor-toggle-caret { color:var(--cyan); font-size:11px; }
.advisor-toggle-sub { font-weight:400; color:var(--text-muted); font-size:11px; }
.advisor-toggle-hint { margin-left:auto; font-weight:400; color:var(--text-muted); font-size:11px; }
.advisor-panel { padding-top:6px; }
/* 目标进度卡 */
.goal-progress-card { margin-bottom:10px; padding:9px 11px; border-radius:8px; border:1px solid var(--border-strong); background:rgba(0,212,255,.05); display:flex; flex-direction:column; gap:6px; }
.gp-head { display:flex; align-items:center; gap:8px; }
.gp-goal { flex:1; min-width:0; font-size:11px; color:var(--text-secondary); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.gp-refresh { font-size:11px; padding:3px 9px; }
.gp-bar-row { display:flex; align-items:center; gap:8px; }
.gp-bar { flex:1; height:7px; border-radius:4px; background:var(--bg-elevated); overflow:hidden; }
.gp-fill { height:100%; background:linear-gradient(90deg,var(--cyan),#7dd3fc); border-radius:4px; transition:width .4s; }
.gp-pct { font-size:12px; font-family:var(--font-mono); color:var(--text-primary); min-width:34px; text-align:right; }
.gp-line { font-size:11px; color:var(--text-secondary); line-height:1.5; }
.gp-k { display:inline-block; min-width:38px; color:var(--text-muted); }
.gp-timeline { display:flex; align-items:center; gap:3px; flex-wrap:wrap; margin-top:2px; }
.gp-seg { font-size:11px; cursor:default; }
.gp-seg.advance { color:var(--green); }
.gp-seg.stall { color:var(--text-muted); }
.gp-seg.regress { color:var(--red); }
.gp-timeline-hint { margin-left:6px; font-size:9px; color:var(--text-muted); }
.gp-empty { font-size:11px; color:var(--text-muted); }
.advisor-head { display:flex; align-items:baseline; gap:8px; margin-bottom:8px; flex-wrap:wrap; }
.advisor-title { font-size:12px; font-weight:600; color:var(--cyan); }
.advisor-sub { font-size:11px; color:var(--text-muted); }
.advisor-row { display:flex; gap:8px; align-items:flex-end; }
.advisor-row .chat-input { min-height:38px; }

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

.scene-hint { font-size:11px; color:var(--text-muted); line-height:1.6; margin-top:8px; }

/* 可信度信任条（通用视角） */
.trust-strip { display:flex; flex-direction:column; gap:5px; margin-top:7px; padding-top:7px; border-top:1px dashed var(--border); }
/* 收敛结论的信任行 + 推演过程折叠按钮 */
.conclusion-trust { display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
.reasoning-toggle { align-self:flex-start; background:none; border:none; color:var(--text-muted); font-size:11px; cursor:pointer; padding:2px 0; }
.reasoning-toggle:hover { color:var(--text-secondary); }

/* 整段粘贴预览 */
.qi-preview { display:flex; flex-direction:column; gap:6px; max-height:46vh; overflow-y:auto; padding:4px; border:1px solid var(--border); border-radius:10px; background:var(--bg-1, rgba(0,0,0,.12)); }
.qi-row { display:flex; align-items:center; gap:6px; }
.qi-row.mine { flex-direction:row-reverse; }
.qi-row.mine .qi-content { background:var(--cyan-dim); }
.qi-spk { flex:0 0 84px; font-size:12px; text-align:center; }
.qi-content { flex:1 1 auto; font-size:13px; }

/* Transitions */
.msg-enter-active { transition: all .3s ease; }
.msg-enter-from   { opacity:0; transform:translateY(8px); }
</style>
