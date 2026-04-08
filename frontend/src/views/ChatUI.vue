<template>
  <div class="chat-layout">
    <!-- Left: Conversation List -->
    <div class="conv-panel">
      <div class="panel-header">
        <span class="panel-title">对话列表</span>
        <button class="btn btn-primary" style="padding:6px 12px;font-size:12px" @click="handleNewConv">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          新建
        </button>
      </div>
      <div class="conv-list">
        <div v-for="c in chat.conversations" :key="c.id"
          class="conv-item" :class="{ active: chat.activeConvId === c.id }"
          @click="selectConversation(c.id)">
          <div class="conv-title">{{ c.title }}</div>
          <div class="conv-meta">{{ formatDate(c.updated_at) }}</div>
        </div>
        <div v-if="!chat.conversations.length" class="empty-hint">暂无对话，点击新建开始</div>
      </div>
    </div>

    <!-- Center: Chat Area -->
    <div class="chat-main">
      <!-- Top bar -->
      <div class="chat-topbar">
        <div class="conv-info">
          <span class="conv-name">{{ currentConvTitle }}</span>
          <span class="tag">{{ currentScenario }}</span>
        </div>
        <div class="topbar-actions">
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
          <div v-for="msg in chat.messages" :key="msg.id"
            class="msg-wrapper" :class="msg.role">
            <!-- Avatar -->
            <div class="msg-avatar" :style="{ background: getCharacterColor(msg.character_name) }">
              {{ avatarLetter(msg.character_name) }}
            </div>

            <div class="msg-body">
              <div class="msg-meta-top">
                <span class="msg-author">{{ msg.character_name || msg.role }}</span>
                <span class="msg-time">{{ formatTime(msg.created_at) }}</span>
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

              <!-- Analysis Layer (AI messages only) -->
              <div v-if="msg.role === 'assistant' && msg.inner_monologue" class="analysis-layer">
                <button class="analysis-toggle" @click="toggleAnalysis(msg.id)">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                  </svg>
                  深层分析
                  <span v-if="msg.emotion_label" class="tag" style="font-size:10px;padding:1px 7px">{{ msg.emotion_label }}</span>
                </button>

                <div v-if="expandedIds.has(msg.id)" class="analysis-content fade-up">
                  <div class="analysis-row">
                    <span class="a-label">内心独白</span>
                    <span class="a-value">{{ msg.inner_monologue }}</span>
                  </div>
                  <div class="analysis-row">
                    <span class="a-label">隐含动机</span>
                    <span class="a-value">{{ msg.subtext }}</span>
                  </div>
                  <div class="analysis-row" v-if="msg.psychological_tag">
                    <span class="a-label">心理侧写</span>
                    <span class="tag violet" style="font-size:11px">{{ msg.psychological_tag }}</span>
                  </div>
                  <div class="analysis-row" v-if="msg.emotion_score != null">
                    <span class="a-label">情绪强度</span>
                    <div class="emotion-bar">
                      <div class="emotion-fill" :style="{ width: (msg.emotion_score * 100) + '%', background: emotionColor(msg.emotion_score) }"></div>
                    </div>
                    <span class="a-pct">{{ Math.round(msg.emotion_score * 100) }}%</span>
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
              @click="currentSpeaker = role.name; currentCharId = role.id">
              <span class="role-dot"></span>{{ role.name }}
            </button>
            <button class="role-pill add-role" @click="showRoleModal = true">＋</button>
          </div>
        </div>

        <div class="input-row">
          <textarea
            ref="inputEl"
            v-model="inputText"
            class="chat-input"
            placeholder="输入消息…  Shift+Enter 换行，Enter 发送"
            rows="1"
            @keydown.enter.exact.prevent="handleSend"
            @input="autoResize"
          />
          <button class="send-btn" :disabled="chat.streaming || !inputText.trim()" @click="handleSend">
            <svg v-if="!chat.streaming" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
            <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation:spin 1s linear infinite">
              <circle cx="12" cy="12" r="10" stroke-dasharray="40" stroke-dashoffset="10"/>
            </svg>
          </button>
        </div>
      </div>
    </div>

    <!-- Right: Emotion Panel -->
    <div class="emotion-panel" :class="{ open: showEmotionPanel }">
      <div class="panel-header">
        <span class="panel-title">情绪追踪</span>
        <button class="btn btn-ghost" style="padding:4px 8px;font-size:11px" @click="refreshEmotionCurve">刷新</button>
      </div>
      <div v-if="activeRoles.length" style="padding:0 16px">
        <div class="label">追踪角色</div>
        <select class="input" v-model="trackingCharacter" @change="refreshEmotionCurve" style="margin-bottom:16px">
          <option v-for="r in activeRoles" :key="r.name" :value="r.name">{{ r.name }}</option>
        </select>
      </div>
      <div v-if="emotionData.emotions?.length" class="emotion-chart-wrap">
        <div class="emotion-trend">
          趋势：<span class="tag" :class="trendClass(emotionData.trend)">{{ trendLabel(emotionData.trend) }}</span>
        </div>
        <div v-if="emotionData.turning_point" class="turning-point">
          ⚡ {{ emotionData.turning_point }}
        </div>
        <!-- Simple bar chart -->
        <div class="emotion-bars">
          <div v-for="(e, i) in emotionData.emotions" :key="i" class="ebar-row">
            <span class="ebar-label">{{ e.label }}</span>
            <div class="ebar-track">
              <div class="ebar-fill" :style="{ width: (e.score*100)+'%', background: emotionColor(e.score) }"></div>
            </div>
            <span class="ebar-pct">{{ Math.round(e.score*100) }}%</span>
          </div>
        </div>
      </div>
      <div v-else class="empty-hint" style="padding:24px 16px">发送几条消息后可查看情绪曲线</div>
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
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useChatStore } from '../stores/chat.js'
import { useCharacterStore } from '../stores/characters.js'
import { chatApi } from '../api/index.js'

const chat = useChatStore()
const chars = useCharacterStore()

const messagesEl = ref(null)
const inputEl = ref(null)
const inputText = ref('')
const showRoleModal = ref(false)
const showEmotionPanel = ref(false)
const expandedIds = ref(new Set())
const currentSpeaker = ref('用户')
const currentCharId = ref(null)
const selectedChars = ref([])
const customRoleName = ref('')
const trackingCharacter = ref('')
const emotionData = ref({ emotions: [], trend: 'stable', turning_point: null })

// Active roles in current conversation
const activeRoles = ref([{ name: '用户', color: '#00d4ff', id: null }])

const currentConvTitle = computed(() => {
  const c = chat.conversations.find(c => c.id === chat.activeConvId)
  return c?.title || '选择或新建对话'
})
const currentScenario = computed(() => {
  const c = chat.conversations.find(c => c.id === chat.activeConvId)
  return c?.scenario || 'general'
})

onMounted(async () => {
  await Promise.all([chat.loadConversations(), chars.fetchAll()])
  if (chat.conversations.length) selectConversation(chat.conversations[0].id)
})

watch(() => chat.messages.length, () => {
  nextTick(() => {
    if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
  })
})

function avatarLetter(name) { return (name || '?')[0].toUpperCase() }
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
function emotionColor(score) {
  if (score < 0.3) return '#10b981'
  if (score < 0.6) return '#f59e0b'
  return '#ef4444'
}
function trendLabel(t) { return { rising:'上升', falling:'下降', stable:'平稳', volatile:'波动' }[t] || t }
function trendClass(t) { return { rising:'amber', falling:'red', stable:'green', volatile:'violet' }[t] || '' }

function toggleAnalysis(id) {
  const s = new Set(expandedIds.value)
  s.has(id) ? s.delete(id) : s.add(id)
  expandedIds.value = s
}
function toggleEmotionPanel() {
  showEmotionPanel.value = !showEmotionPanel.value
  if (showEmotionPanel.value && trackingCharacter.value) refreshEmotionCurve()
}

async function selectConversation(id) {
  await chat.loadMessages(id)
}
async function handleNewConv() {
  await chat.newConversation('新对话 ' + new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'}))
}

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || chat.streaming) return
  inputText.value = ''
  await nextTick()
  if (inputEl.value) inputEl.value.style.height = 'auto'

  if (!chat.activeConvId) await chat.newConversation()

  await chat.sendMessage({
    speaker: currentSpeaker.value,
    content: text,
    characterId: currentCharId.value,
  })
}

function autoResize() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

function addCustomRole() {
  const name = customRoleName.value.trim()
  if (!name) return
  if (!activeRoles.value.find(r => r.name === name)) {
    activeRoles.value.push({ name, color: '#94a3b8', id: null })
  }
  customRoleName.value = ''
}
function confirmRoles() {
  for (const c of selectedChars.value) {
    if (!activeRoles.value.find(r => r.name === c.name)) {
      activeRoles.value.push({ name: c.name, color: c.avatar_color, id: c.id })
    }
  }
  if (!currentSpeaker.value && activeRoles.value.length) currentSpeaker.value = activeRoles.value[0].name
  if (!trackingCharacter.value && activeRoles.value.length) trackingCharacter.value = activeRoles.value[0].name
  showRoleModal.value = false
}

async function branchFrom(messageId) {
  if (!confirm('从此消息创建分支？之后的消息将被移除。')) return
  await chat.createBranch(messageId)
}

async function refreshEmotionCurve() {
  if (!chat.activeConvId || !trackingCharacter.value) return
  try {
    const res = await chatApi.getEmotionCurve(chat.activeConvId, trackingCharacter.value)
    emotionData.value = res.data
  } catch {}
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
  width: 220px;
  flex-shrink: 0;
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
}
.panel-header {
  padding: 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.panel-title { font-size: 12px; font-family: var(--font-mono); color: var(--text-muted); text-transform: uppercase; letter-spacing:.08em; }
.conv-list { flex:1; overflow-y:auto; padding: 8px; }
.conv-item {
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: var(--transition);
  margin-bottom: 2px;
}
.conv-item:hover { background: var(--bg-hover); }
.conv-item.active { background: var(--cyan-dim); border: 1px solid rgba(0,212,255,0.2); }
.conv-title { font-size: 13px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.conv-meta { font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); margin-top: 2px; }
.empty-hint { text-align:center; color:var(--text-muted); font-size:12px; padding:24px 0; }

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

.msg-wrapper { display:flex; gap:12px; align-items:flex-start; }
.msg-wrapper.user .msg-body { align-items: flex-end; }
.msg-wrapper.user { flex-direction: row-reverse; }

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

/* Emotion Panel */
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
  width: 260px;
  border-left-width: 1px;
}
.emotion-chart-wrap { padding: 0 16px 16px; }
.emotion-trend { font-size:12px; color:var(--text-muted); margin-bottom:8px; display:flex; align-items:center; gap:6px; }
.turning-point { font-size:11px; color:var(--amber); margin-bottom:12px; line-height:1.5; }
.emotion-bars { display:flex; flex-direction:column; gap:8px; }
.ebar-row { display:flex; align-items:center; gap:8px; }
.ebar-label { font-size:11px; color:var(--text-muted); min-width:48px; font-family:var(--font-mono); }
.ebar-track { flex:1; height:6px; background:var(--bg-base); border-radius:3px; overflow:hidden; }
.ebar-fill { height:100%; border-radius:3px; transition:width .4s; }
.ebar-pct { font-size:11px; font-family:var(--font-mono); color:var(--text-muted); min-width:30px; text-align:right; }

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

/* Transitions */
.msg-enter-active { transition: all .3s ease; }
.msg-enter-from   { opacity:0; transform:translateY(8px); }
</style>
