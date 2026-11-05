export const apiBase = import.meta.env.VITE_API_BASE_URL || '/api'
let generation = 0

export function invalidateRequests() { generation += 1 }

export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const started = generation
  const response = await fetch(input, { ...init, credentials: 'include' })
  const check = () => {
    if (started !== generation) throw new Error('账号已切换，旧请求已取消')
  }
  check()
  if (response.status === 401 && !input.includes('/auth/')) {
    window.dispatchEvent(new Event('teacher-session-expired'))
    throw new Error('登录已过期，请重新登录')
  }
  const parse = response.json.bind(response)
  response.json = async () => { const value = await parse(); check(); return value }
  return response
}

export function errorDetail(value: { detail?: unknown }): string {
  if (typeof value.detail === 'string') return value.detail
  if (Array.isArray(value.detail)) return '填写的数据格式不正确，请检查必填项、字数和时间。'
  return '请求失败，请稍后重试'
}
