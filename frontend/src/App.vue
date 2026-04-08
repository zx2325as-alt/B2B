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
      </div>

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
  </div>
</template>

<style scoped>
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

.nav-links { flex: 1; padding: 0 10px; display: flex; flex-direction: column; gap: 4px; }
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
