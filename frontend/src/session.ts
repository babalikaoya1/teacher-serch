import { ref } from 'vue'
import { apiBase, apiFetch, invalidateRequests } from './api'

export const currentUser = ref<{ id: number; username: string } | null>(null)
export const sessionReady = ref(false)
export function setUser(user: { id: number; username: string } | null) {
  invalidateRequests()
  currentUser.value = user
}
export async function loadSession() {
  try {
    const response = await apiFetch(`${apiBase}/auth/me`)
    setUser(response.ok ? await response.json() : null)
  } finally { sessionReady.value = true }
}
export async function logout() {
  const response = await apiFetch(`${apiBase}/auth/logout`, { method: 'POST' })
  if (!response.ok) throw new Error('退出失败，请重试')
  setUser(null)
}
window.addEventListener('teacher-session-expired', () => setUser(null))
