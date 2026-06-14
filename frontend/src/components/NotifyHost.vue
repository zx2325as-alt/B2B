<template>
  <Teleport to="body">
    <!-- Toasts -->
    <div class="toast-stack">
      <TransitionGroup name="toast">
        <div v-for="t in notifyState.toasts" :key="t.id" class="toast-item" :class="t.type">
          <span class="toast-icon">{{ icon(t.type) }}</span>
          <span class="toast-msg">{{ t.message }}</span>
        </div>
      </TransitionGroup>
    </div>

    <!-- Confirm dialog -->
    <div v-if="notifyState.confirm" class="confirm-overlay" @click.self="resolveConfirm(false)">
      <div class="confirm-box">
        <div class="confirm-msg">{{ notifyState.confirm.message }}</div>
        <div class="confirm-actions">
          <button class="confirm-btn ghost" @click="resolveConfirm(false)">取消</button>
          <button class="confirm-btn primary" @click="resolveConfirm(true)">确认</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { notifyState, resolveConfirm } from '../utils/notify.js'

function icon(type) {
  return { success: '✓', error: '✕', info: 'ⓘ' }[type] || 'ⓘ'
}
</script>

<style scoped>
.toast-stack {
  position: fixed;
  top: 18px;
  right: 18px;
  z-index: 3000;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 380px;
}
.toast-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 8px;
  background: var(--bg-elevated, #16202f);
  border: 1px solid var(--border, #2a3648);
  color: var(--text-primary, #e8eef7);
  font-size: 13px;
  line-height: 1.5;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.35);
  word-break: break-word;
}
.toast-item.success { border-color: rgba(16, 185, 129, 0.5); }
.toast-item.success .toast-icon { color: #10b981; }
.toast-item.error { border-color: rgba(239, 68, 68, 0.5); }
.toast-item.error .toast-icon { color: #ef4444; }
.toast-item.info .toast-icon { color: var(--cyan, #00d4ff); }
.toast-icon { font-weight: 700; flex-shrink: 0; }

.toast-enter-active, .toast-leave-active { transition: all 0.25s ease; }
.toast-enter-from { opacity: 0; transform: translateX(16px); }
.toast-leave-to { opacity: 0; transform: translateY(-8px); }

.confirm-overlay {
  position: fixed;
  inset: 0;
  z-index: 3100;
  background: rgba(8, 12, 22, 0.7);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
}
.confirm-box {
  width: 360px;
  max-width: calc(100vw - 40px);
  background: var(--bg-surface, #101827);
  border: 1px solid var(--border, #2a3648);
  border-radius: 12px;
  padding: 22px;
  box-shadow: 0 12px 48px rgba(0, 0, 0, 0.5);
}
.confirm-msg { font-size: 14px; color: var(--text-primary, #e8eef7); line-height: 1.7; white-space: pre-wrap; }
.confirm-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
.confirm-btn {
  padding: 7px 18px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  border: 1px solid var(--border, #2a3648);
  background: transparent;
  color: var(--text-secondary, #aebacd);
  transition: all 0.15s;
}
.confirm-btn.ghost:hover { color: var(--text-primary, #e8eef7); border-color: var(--text-muted, #5b6b82); }
.confirm-btn.primary {
  background: var(--cyan, #00d4ff);
  border-color: var(--cyan, #00d4ff);
  color: #080c16;
  font-weight: 600;
}
.confirm-btn.primary:hover { filter: brightness(1.1); }
</style>
