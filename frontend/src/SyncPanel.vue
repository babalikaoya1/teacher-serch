<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { apiBase, apiFetch, errorDetail } from './api'

type Device = { id: string; name: string; status: string; detail?: string; online: boolean; last_seen_at?: string }
type Source = { id: string; device_id: string; name: string; enabled: boolean; city?: string; status: string; detail?: string; earliest_at?: string; last_success_at?: string; counts: Record<string, number> }
export type ReviewMessage = { id: number; text: string; source_group: string; sent_at?: string; detail?: string }
const props = defineProps<{ city: string }>()
const emit = defineEmits<{ review: [message: ReviewMessage] }>()
const devices = ref<Device[]>([])
const sources = ref<Source[]>([])
const reviews = ref<ReviewMessage[]>([])
const code = ref('')
const expires = ref('')
const notice = ref('')
const busy = ref(false)
let timer: number | undefined
let alive = true
const states: Record<string, string> = {
  ready: '微信可读取', unsupported: '当前微信不支持读取', wechat_offline: '请打开并登录微信', locked: '电脑已锁屏，读取暂停',
  disconnected: '等待助手连接', waiting: '等待助手开始', paused: '已暂停', reading: '正在补读历史', live: '持续同步中',
  partial: '历史覆盖不完整', error: '读取失败',
}
function time(value?: string) { return value ? new Date(/[Z+]|-\d\d:\d\d$/.test(value.slice(10)) ? value : `${value}Z`).toLocaleString('zh-CN') : '尚无记录' }
async function request(path: string, method = 'GET', body?: unknown) {
  const response = await apiFetch(`${apiBase}/wechat-sync${path}`, { method, ...(body === undefined ? {} : {
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }) })
  const data = await response.json()
  if (!response.ok) throw new Error(errorDetail(data))
  return data
}
async function refresh() {
  try {
    const [status, pending] = await Promise.all([request('/status'), request('/reviews')])
    if (!alive) return
    devices.value = status.devices
    sources.value = status.sources
    reviews.value = pending
  } catch (error) { if (alive) notice.value = error instanceof Error ? error.message : '无法更新同步状态' }
}
async function action(fn: () => Promise<unknown>) {
  busy.value = true
  notice.value = ''
  try { await fn(); await refresh() }
  catch (error) { notice.value = error instanceof Error ? error.message : '操作失败' }
  finally { busy.value = false }
}
async function pair() {
  await action(async () => { const result = await request('/pairing-code', 'POST'); code.value = result.code; expires.value = result.expires_at })
}
async function toggle(source: Source) {
  await action(() => request(`/sources/${source.id}`, 'PATCH', { enabled: !source.enabled, city: source.city || props.city || null }))
}
async function revoke(device: Device) {
  if (!window.confirm(`解除“${device.name}”的绑定后，这台电脑将无法继续上传。确定解除？`)) return
  await action(() => request(`/devices/${device.id}`, 'DELETE'))
}
async function download() {
  await action(async () => {
    const response = await apiFetch(`${apiBase}/wechat-sync/download`)
    if (!response.ok) throw new Error(errorDetail(await response.json()))
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url; link.download = '微信同步助手.exe'; link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  })
}
onMounted(() => { void refresh(); timer = window.setInterval(() => void refresh(), 5000) })
onUnmounted(() => { alive = false; window.clearInterval(timer) })
</script>

<template>
  <section class="sync-panel panel">
    <div class="preview-heading"><div><h3>从电脑微信自动同步</h3><p>先检测微信是否支持读取，再选择群聊。支持时补读最近三天并持续同步。</p></div><button class="upload-button" :disabled="busy" @click="refresh">刷新</button></div>
    <div class="sync-actions"><button class="primary-button" :disabled="busy" @click="download">下载 Windows 助手</button><button class="upload-button" :disabled="busy" @click="pair">生成配对码</button></div>
    <p v-if="code" class="pair-code">在助手中填写配对码：<strong>{{ code }}</strong><small>有效期至 {{ time(expires) }}，使用一次后失效。</small></p>
    <p class="review-tip">在电脑助手里填写本网站地址并登录官方电脑微信。窗口不可读、锁屏或电脑离线时会暂停；手机仍可查看已同步订单。</p>
    <p v-if="notice" class="map-error" role="alert">{{ notice }}</p>
    <p v-if="!devices.length" class="review-tip">尚未绑定电脑。完成配对后，设备和可选择的群会显示在这里。</p>
    <article v-for="device in devices" :key="device.id" class="sync-device">
      <div class="section-heading"><strong>{{ device.name }}</strong><button class="upload-button" :disabled="busy" @click="revoke(device)">解除绑定</button></div>
      <p>{{ device.online ? states[device.status] || device.status : '助手离线' }} · 最近连接：{{ time(device.last_seen_at) }}</p>
      <p v-if="device.detail" class="map-error">{{ device.detail }}</p>
      <article v-for="source in sources.filter(s => s.device_id === device.id)" :key="source.id" class="sync-source">
        <div class="section-heading"><strong>{{ source.name }}</strong><button class="upload-button" :disabled="busy" @click="toggle(source)">{{ source.enabled ? '暂停' : '同步近三天并持续同步' }}</button></div>
        <p>{{ source.enabled && (!device.online || device.status !== 'ready') ? '采集暂停，等待设备恢复可读取状态' : states[source.status] || source.status }} · 最近读取成功：{{ time(source.last_success_at) }}</p>
        <p v-if="source.earliest_at">已读历史最早时间：{{ time(source.earliest_at) }}</p>
        <p>入库 {{ source.counts.orders || 0 }} 条订单 · 排队 {{ source.counts.queued || 0 }} · 待确认 {{ source.counts.review || 0 }} · 失败 {{ source.counts.failed || 0 }} · 已过滤 {{ source.counts.ignored || 0 }}</p>
        <p v-if="source.detail" class="review-tip">{{ source.detail }}</p>
      </article>
    </article>
    <div v-if="reviews.length" class="sync-reviews"><h3>需要你确认的消息</h3>
      <article v-for="review in reviews" :key="review.id" class="sync-source">
        <strong>{{ review.source_group }}</strong><p>{{ review.detail }}</p><p class="sync-message">{{ review.text }}</p>
        <button class="upload-button" :disabled="busy" @click="emit('review', review)">核对并导入</button>
        <button class="reset-button" :disabled="busy" @click="action(() => request(`/reviews/${review.id}`, 'DELETE'))">忽略</button>
      </article>
    </div>
  </section>
</template>
