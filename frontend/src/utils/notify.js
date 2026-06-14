// 轻量全局通知：toast + promise 风格 confirm，替代原生 alert/confirm
import { reactive } from 'vue'

let seed = 1

export const notifyState = reactive({
  toasts: [],          // { id, type: 'info'|'success'|'error', message }
  confirm: null,       // { message, resolve }
})

export function toast(message, type = 'info', duration = 3200) {
  const id = seed++
  notifyState.toasts.push({ id, type, message: String(message ?? '') })
  if (notifyState.toasts.length > 5) notifyState.toasts.shift()
  setTimeout(() => {
    const idx = notifyState.toasts.findIndex(t => t.id === id)
    if (idx >= 0) notifyState.toasts.splice(idx, 1)
  }, duration)
}

toast.success = (message) => toast(message, 'success')
toast.error = (message) => toast(message, 'error', 5000)
toast.info = (message) => toast(message, 'info')

export function confirmDialog(message) {
  return new Promise((resolve) => {
    // 同时只显示一个确认框；已有未决确认时直接取消旧的
    if (notifyState.confirm) notifyState.confirm.resolve(false)
    notifyState.confirm = { message: String(message ?? ''), resolve }
  })
}

export function resolveConfirm(result) {
  if (!notifyState.confirm) return
  notifyState.confirm.resolve(result)
  notifyState.confirm = null
}
