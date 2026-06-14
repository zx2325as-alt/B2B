<template>
  <div class="app-layout">
    <!-- Sidebar -->
    <nav class="sidebar">
      <div class="sidebar-logo">
        <span class="logo-mark">Bt</span><span class="logo-b">B</span>
        <span class="logo-sub">INTELLIGENCE</span>
      </div>

      <div class="nav-links">
        <router-link to="/chat" class="nav-link" :class="{ active: $route.path === '/chat' }">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          <span>智能对话</span>
        </router-link>

        <router-link to="/admin" class="nav-link" :class="{ active: $route.path === '/admin' }">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>
          </svg>
          <span>角色管理</span>
        </router-link>

        <router-link to="/ai-updates" class="nav-link" :class="{ active: $route.path === '/ai-updates' }">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M7 4h10l3 3v13H4V4h3z"/><path d="M8 9h8M8 13h8M8 17h5"/>
          </svg>
          <span>AI更新记录</span>
        </router-link>
      </div>

      <!-- 对话列表：并入导航栏，仅智能对话页显示（不再单列一栏） -->
      <div v-if="$route.path === '/chat'" class="conv-rail">
        <div class="conv-rail-head">
          <span class="conv-rail-title">对话</span>
          <button class="conv-new-btn" @click="newConv">＋ 新建</button>
        </div>
        <div class="conv-rail-list">
          <div v-for="c in chat.conversations" :key="c.id"
            class="conv-rail-item" :class="{ active: chat.activeConvId === c.id }"
            @click="selectConv(c.id)">
            <div class="cri-main">
              <div class="cri-title">{{ c.title }}</div>
              <div class="cri-meta">{{ fmtDate(c.updated_at) }}</div>
            </div>
            <button class="cri-del" @click.stop="delConv(c.id)" title="删除对话">✕</button>
          </div>
          <div v-if="!chat.conversations.length" class="cri-empty">暂无对话，点「新建」开始</div>
        </div>
      </div>
      <div v-else class="nav-spacer"></div>

      <div class="sidebar-footer">
        <div class="status-dot"></div>
        <span class="status-text">AI Harness 在线</span>
      </div>
    </nav>

    <!-- Main -->
    <div class="main-content">
      <router-view v-slot="{ Component }">
        <transition name="page" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </div>

    <NotifyHost />
  </div>
</template>

<script setup>
import { onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import NotifyHost from './components/NotifyHost.vue'
import { useChatStore } from './stores/chat.js'
import { toast, confirmDialog } from './utils/notify.js'

const chat = useChatStore()
const route = useRoute()

function fmtDate(dt) {
  if (!dt) return ''
  return new Date(dt).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}
async function ensureConversations() {
  try { await chat.loadConversations() } catch { /* 拦截器已提示 */ }
}
onMounted(() => { if (route.path === '/chat') ensureConversations() })
watch(() => route.path, (p) => { if (p === '/chat') ensureConversations() })

async function selectConv(id) {
  if (chat.activeConvId === id) return
  await chat.loadMessages(id)   // ChatUI 通过 watch(activeConvId/messages) 完成每会话设置
}
async function newConv() {
  const title = '新对话 ' + new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  await chat.newConversation(title, 'general')
}
async function delConv(id) {
  if (!await confirmDialog('确定删除这个对话吗？相关分析与检索记录将一并清理。')) return
  await chat.deleteConversation(id)
  toast.success('对话已删除')
  if (chat.activeConvId === id) {
    if (chat.conversations.length) {
      await chat.loadMessages(chat.conversations[0].id)
    } else {
      chat.activeConvId = null
      chat.messages = []
    }
  }
}
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
.sidebar {
  width: 220px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  background: var(--bg-surface);
  padding-top: 24px;
}
.main-content {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.sidebar-logo {
  padding: 0 20px 24px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 16px;
  display: flex;
  align-items: baseline;
  gap: 2px;
  flex-wrap: wrap;
}
.logo-mark { font-size: 22px; font-weight: 700; color: var(--text-primary); letter-spacing: -1px; }
.logo-b    { font-size: 22px; font-weight: 700; color: var(--cyan); }
.logo-sub  {
  width: 100%;
  font-size: 9px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  letter-spacing: 0.15em;
  margin-top: -6px;
}

.nav-links { flex: 0 0 auto; padding: 0 10px; display: flex; flex-direction: column; gap: 4px; }
.nav-spacer { flex: 1; }

/* 对话列表并入导航栏（单列，不再独占一栏） */
.conv-rail { flex: 1; min-height: 0; display: flex; flex-direction: column; margin-top: 10px; border-top: 1px solid var(--border); }
.conv-rail-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 18px 8px; }
.conv-rail-title { font-size: 11px; font-family: var(--font-mono); color: var(--text-muted); text-transform: uppercase; letter-spacing: .08em; }
.conv-new-btn { background: var(--cyan-dim); border: 1px solid rgba(0,212,255,0.2); color: var(--cyan); font-size: 11px; padding: 3px 10px; border-radius: 100px; cursor: pointer; transition: var(--transition); }
.conv-new-btn:hover { background: var(--cyan); color: #080c16; }
.conv-rail-list { flex: 1; overflow-y: auto; padding: 0 8px 8px; display: flex; flex-direction: column; gap: 2px; }
.conv-rail-item { display: flex; align-items: center; gap: 6px; padding: 8px 10px; border-radius: var(--radius-sm); cursor: pointer; transition: var(--transition); border: 1px solid transparent; }
.conv-rail-item:hover { background: var(--bg-hover); }
.conv-rail-item.active { background: var(--cyan-dim); border-color: rgba(0,212,255,0.2); }
.cri-main { flex: 1; min-width: 0; }
.cri-title { font-size: 13px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cri-meta { font-size: 10px; color: var(--text-muted); font-family: var(--font-mono); margin-top: 1px; }
.cri-del { background: transparent; border: none; color: var(--text-muted); cursor: pointer; font-size: 11px; opacity: 0; padding: 2px 4px; border-radius: 4px; transition: var(--transition); flex-shrink: 0; }
.conv-rail-item:hover .cri-del { opacity: .5; }
.cri-del:hover { opacity: 1 !important; color: var(--red); }
.cri-empty { font-size: 12px; color: var(--text-muted); text-align: center; padding: 18px 8px; line-height: 1.6; }
.nav-link {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  transition: var(--transition);
}
.nav-link:hover { background: var(--bg-hover); color: var(--text-primary); }
.nav-link.active { background: var(--cyan-dim); color: var(--cyan); }
.nav-link.active svg { stroke: var(--cyan); }

.sidebar-footer {
  padding: 16px 20px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 8px;
}
.status-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--green);
  animation: pulse-cyan 2s infinite;
}
.status-text { font-size: 11px; font-family: var(--font-mono); color: var(--text-muted); }

.page-enter-active, .page-leave-active { transition: opacity 0.2s, transform 0.2s; }
.page-enter-from { opacity: 0; transform: translateX(8px); }
.page-leave-to   { opacity: 0; transform: translateX(-8px); }
</style>
