<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { apiBase, apiFetch, errorDetail } from './api'
import { currentUser, sessionReady, loadSession, logout } from './session'
import AccountPanel from './AccountPanel.vue'
import SyncPanel, { type ReviewMessage } from './SyncPanel.vue'
import { loadAmapSdk, type AMapApi, type AMapInstance, type MapPoint } from './mapSdk'
import { wgs84ToGcj02 } from './coordinates'

function asUtc(value: string): string {
  return /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`
}

type Job = {
  id?: number
  subject: string | null
  grade: string | null
  gender: string | null
  city: string | null
  location: string | null
  teaching_mode: string | null
  salary: number | null
  salary_unit: string | null
  salary_basis: string | null
  salary_is_minimum: boolean
  schedule: string | null
  order_code: string | null
  student_notes: string | null
  requirements: string | null
  location_lat: number | null
  location_lng: number | null
  geocode_status: string
  geocode_error?: string | null
  geocoded_address?: string
  geocode_attempted_address?: string
  raw_text: string
  distance_km?: number | null
  source_group?: string | null
  status?: string
  created_at?: string
  published_at?: string | null
}

const tab = ref<'jobs' | 'import'>('jobs')
const jobs = ref<Job[]>([])
const drafts = ref<Job[]>([])
const ignoredLines = ref(0)
const busy = ref(false)
const message = ref('')
const sourceGroup = ref('')
const currentCity = ref('')
const reviewMessageId = ref<number | null>(null)
const reviewSentAt = ref('')
const citySettingsOpen = ref(false)
const cityDraft = ref(currentCity.value)
const mapConfig = ref({ sdk_url: null as string | null, public_key: null as string | null, web_sdk_configured: false, geocoding_api_configured: false, server_geocoding_configured: false, js_security_proxy_configured: false, js_service_proxy_url: null as string | null, routing_api_configured: false, provider_name: null as string | null })
const mapPickerOpen = ref(false)
const mapContainer = ref<HTMLDivElement | null>(null)
const mapSearch = ref('')
const mapPickedAddress = ref('')
const mapError = ref('')
const mapBusy = ref(false)
let amapApi: AMapApi | null = null
let amapInstance: AMapInstance | null = null
let amapMarker: InstanceType<AMapApi['Marker']> | null = null
let mapPickTarget: { kind: 'order'; draft: Job } | { kind: 'saved'; job: Job } | { kind: 'origin' } | null = null
let jobRequestId = 0
let jobSearchTimer: number | undefined
const mapPendingPoint = ref<MapPoint | null>(null)
const mapPendingCity = ref('')
const MAP_LOOKUP_TIMEOUT_MS = 3500
const aiConfig = ref({ configured: false, model: null as string | null })
const aiQuery = ref('')
const aiBusy = ref(false)
const aiResultsMode = ref(false)
const aiReasons = ref<Record<number, string>>({})
const filters = reactive({ subject: '', location: '', source_group: '', min_salary: '', max_salary: '', max_distance_km: '', origin_lat: '', origin_lng: '' })
const fileInput = ref<HTMLInputElement | null>(null)
const chatText = ref('')
const filteredJobs = computed(() => jobs.value)
const backfillNotice = ref('')
const backfillRequests = new Map<string, Promise<{ attempted: number; resolved: number; failed: number; errors: string[] }>>()

function backfillMissingCoordinates(city: string) {
  const key = cityLabelKey(city) || 'all-cities'
  const existing = backfillRequests.get(key)
  if (existing) return existing
  const params = new URLSearchParams()
  if (city) params.set('city', city)
  const request = apiFetch(`${apiBase}/jobs/geocode-missing?${params}`, { method: 'POST' })
    .then(async (response) => {
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || '旧订单地址补全失败')
      if (result.failed) window.setTimeout(() => { if (backfillRequests.get(key) === request) backfillRequests.delete(key) }, 30000)
      return result
    })
  backfillRequests.set(key, request)
  return request
}

async function loadJobs() {
  if (!currentUser.value) return
  const requestId = ++jobRequestId
  backfillNotice.value = ''
  aiResultsMode.value = false
  aiReasons.value = {}
  const hasLatitude = Boolean(filters.origin_lat)
  const hasLongitude = Boolean(filters.origin_lng)
  if (filters.max_distance_km && !(hasLatitude && hasLongitude)) {
    jobs.value = []
    message.value = '按距离筛选前，请先使用当前位置或地图选择起点坐标。'
    return
  }
  const params = new URLSearchParams()
  if (filters.subject) params.set('subject', filters.subject)
  if (filters.location) params.set('location', filters.location)
  if (filters.source_group) params.set('source_group', filters.source_group)
  if (filters.min_salary) params.set('min_salary', filters.min_salary)
  if (filters.max_salary) params.set('max_salary', filters.max_salary)
  if (hasLatitude && hasLongitude) {
    params.set('origin_lat', filters.origin_lat)
    params.set('origin_lng', filters.origin_lng)
  }
  if (filters.max_distance_km) params.set('max_distance_km', filters.max_distance_km)
  if (filters.max_distance_km && currentCity.value.trim()) params.set('city', currentCity.value.trim())
  try {
    if (filters.max_distance_km) {
      const backfill = await backfillMissingCoordinates(currentCity.value.trim()).catch((error) => ({
        attempted: 0, resolved: 0, failed: 1, errors: [error instanceof Error ? error.message : '旧订单地址补全失败'],
      }))
      if (backfill.attempted) {
        backfillNotice.value = backfill.failed
          ? `已尝试补全 ${backfill.attempted} 条旧订单地址，成功 ${backfill.resolved} 条，失败 ${backfill.failed} 条：${backfill.errors[0] || '请检查地址或服务配置。'}`
          : `已为 ${backfill.resolved} 条旧订单补全上课坐标。`
      } else if (backfill.failed) {
        backfillNotice.value = backfill.errors[0] || '旧订单地址补全失败'
      }
    }
    const response = await apiFetch(`${apiBase}/jobs?${params}`)
    if (!response.ok) {
      const result = await response.json()
      throw new Error(result.detail || '查询失败')
    }
    const results: Job[] = await response.json()
    if (requestId !== jobRequestId) return
    const expiredCount = Number(response.headers.get('X-Expired-Jobs-Deleted') || 0)
    jobs.value = results
    const hasFilters = Boolean(filters.subject || filters.location || filters.source_group || filters.min_salary || filters.max_salary || filters.max_distance_km)
    message.value = results.length || !hasFilters ? '' : '没有找到符合当前筛选条件的订单。检查筛选项，或为订单补充上课地点坐标后再按距离筛选。'
    if (!results.length && backfillNotice.value) message.value = `${message.value} ${backfillNotice.value}`.trim()
    if (expiredCount > 0) message.value = `已自动清理 ${expiredCount} 条超过三天有效期的订单。${message.value}`
  } catch (error) {
    if (requestId !== jobRequestId) return
    jobs.value = []
    message.value = error instanceof Error ? error.message : '暂时连接不上服务，请确认后端已启动。'
  }
}

function scheduleJobSearch() {
  if (jobSearchTimer !== undefined) window.clearTimeout(jobSearchTimer)
  jobSearchTimer = window.setTimeout(() => void loadJobs(), 250)
}

function cityLabelKey(city: string) {
  return city.trim().replace(/\s+/g, '').replace(/(市|地区|自治州|盟)$/u, '')
}

async function openCitySettings() {
  cityDraft.value = currentCity.value
  citySettingsOpen.value = true
}

async function saveCitySetting() {
  const selectedCity = cityDraft.value.trim()
  if (!selectedCity) {
    message.value = '请填写所在地级市，例如：北京市。'
    return
  }
  currentCity.value = selectedCity
  localStorage.setItem(`teacher-search-city-${currentUser.value?.id}`, selectedCity)
  backfillRequests.delete(cityLabelKey(selectedCity) || 'all-cities')
  citySettingsOpen.value = false

  for (const draft of drafts.value) {
    if (draft.location_lat == null || draft.location_lng == null) {
      draft.city = selectedCity
      draft.geocode_status = 'pending'
      draft.geocode_error = null
    }
  }
  if (drafts.value.length) {
    message.value = `所在地级市已更新为${selectedCity}；未定位地址会在确认导入时由后端重新查询。`
  } else if (filters.max_distance_km) {
    await loadJobs()
  }
}

async function loadAIConfig() {
  try {
    const response = await apiFetch(`${apiBase}/ai/config`)
    if (response.ok) aiConfig.value = await response.json()
  } catch {
    aiConfig.value = { configured: false, model: null }
  }
}

async function searchWithAI() {
  if (aiQuery.value.trim().length < 2) {
    message.value = '请至少输入两个字描述你的接单需求。'
    return
  }
  aiBusy.value = true
  message.value = ''
  try {
    const response = await apiFetch(`${apiBase}/ai/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: aiQuery.value.trim() }),
    })
    const result = await response.json()
    if (!response.ok) throw new Error(result.detail || 'AI 查询失败')
    const matches: Array<{ job: Job; reason: string }> = result.matches
    jobs.value = matches.map((match) => match.job)
    aiReasons.value = Object.fromEntries(matches.map((match) => [match.job.id || 0, match.reason]))
    aiResultsMode.value = true
    message.value = matches.length ? `AI 根据“${aiQuery.value.trim()}”找到 ${matches.length} 条匹配订单。` : '没有找到符合描述的订单，可以换一种说法或调整需求。'
  } catch (error) {
    const detail = error instanceof Error ? error.message : '模型服务返回未知错误，请稍后重试。'
    message.value = `AI 查询失败：${detail}`
  } finally {
    aiBusy.value = false
  }
}

async function preview(text: string, file?: File) {
  busy.value = true
  message.value = '正在由后端解析订单地址并转换上课坐标…'
  const form = new FormData()
  if (sourceGroup.value.trim()) form.append('source_group', sourceGroup.value.trim())
  if (currentCity.value.trim()) form.append('city', currentCity.value.trim())
  if (file) form.append('file', file)
  else form.append('text', text)
  try {
    const response = await apiFetch(`${apiBase}/import/preview`, { method: 'POST', body: form })
    const result = await response.json()
    if (!response.ok) throw new Error(result.detail || '解析失败')
    drafts.value = result.jobs
    ignoredLines.value = result.ignored_lines
    if (drafts.value.length === 0) {
      message.value = '没有识别到家教单。请确认文本中包含科目或家教相关描述。'
    } else {
      const resolved = drafts.value.filter((draft) => draft.geocode_status === 'resolved').length
      const failed = drafts.value.filter((draft) => draft.geocode_status === 'failed').length
      message.value = failed
        ? `后端已自动定位 ${resolved} 条订单，${failed} 条未能定位；每条订单已显示原因，可在定位失败后手动选点。`
        : resolved
          ? `后端已自动定位 ${resolved} 条订单地址，坐标将在确认导入时保存。`
          : '已解析订单；没有可自动定位的线下地址，确认后可继续筛选。'
    }
  } catch (error) {
    message.value = error instanceof Error ? error.message : '导入解析失败'
  } finally {
    busy.value = false
  }
}

async function loadMapConfig(timeoutMs = 2500) {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await apiFetch(`${apiBase}/maps/config`, { signal: controller.signal })
    if (response.ok) {
      const config = await response.json()
      mapConfig.value = {
        ...config,
        js_service_proxy_url: config.js_service_proxy_url ? new URL(config.js_service_proxy_url, new URL(apiBase, window.location.origin)).toString() : null,
      }
    }
  } catch {
    mapConfig.value = { sdk_url: null, public_key: null, web_sdk_configured: false, geocoding_api_configured: false, server_geocoding_configured: false, js_security_proxy_configured: false, js_service_proxy_url: null, routing_api_configured: false, provider_name: null }
  } finally {
    window.clearTimeout(timer)
  }
}

function markDraftAddressChanged(draft: Job) {
  draft.location_lat = null
  draft.location_lng = null
  draft.geocode_status = 'pending'
  draft.geocode_error = null
  if (!draft.city) draft.city = currentCity.value || null
}

function normalizeMapAddress(address: string) {
  return address.trim().replace(/[，,;；\s]*(附近|周边|周围|一带|周边地区)+[，,;；\s]*$/u, '').trim()
}

function cityFromAddress(value: string | string[] | undefined, fallback?: string) {
  const city = Array.isArray(value) ? value.find(Boolean) : value
  return city || fallback || ''
}

function geocoderLookup(api: AMapApi, address: string, timeoutMs: number): Promise<{ point: MapPoint; address: string; city: string } | null> {
  return new Promise((resolve) => {
    let complete = false
    const timer = window.setTimeout(() => {
      complete = true
      resolve(null)
    }, timeoutMs)
    try {
      new api.Geocoder().getLocation(address, (status, result) => {
        if (complete) return
        complete = true
        window.clearTimeout(timer)
        const location = result.geocodes?.[0]?.location
        const addressResult = result.geocodes?.[0]
        resolve(status === 'complete' && location
          ? {
              point: { lat: location.getLat(), lng: location.getLng() },
              address: addressResult?.formattedAddress || address,
              city: cityFromAddress(addressResult?.addressComponent?.city, addressResult?.addressComponent?.province),
            }
          : null)
      })
    } catch {
      if (!complete) {
        complete = true
        window.clearTimeout(timer)
        resolve(null)
      }
    }
  })
}

function placeSearchLookup(api: AMapApi, keywords: string, timeoutMs: number, city: string): Promise<{ point: MapPoint; address: string; city: string } | null> {
  return new Promise((resolve) => {
    let complete = false
    const timer = window.setTimeout(() => {
      complete = true
      resolve(null)
    }, timeoutMs)
    try {
      new api.PlaceSearch({ pageSize: 1, city }).search(keywords, (status, result) => {
        if (complete) return
        complete = true
        window.clearTimeout(timer)
        const poi = result.poiList?.pois?.[0]
        if (status !== 'complete' || !poi?.location) {
          resolve(null)
          return
        }
        resolve({
          point: { lat: poi.location.getLat(), lng: poi.location.getLng() },
          address: poi.address || poi.name || keywords,
          city: poi.cityname || poi.pname || city,
        })
      })
    } catch {
      if (!complete) {
        complete = true
        window.clearTimeout(timer)
        resolve(null)
      }
    }
  })
}

async function findMapAddress(api: AMapApi, input: string, timeoutMs: number, preferredCity = currentCity.value.trim()) {
  const original = input.trim()
  const normalized = normalizeMapAddress(original)
  const deadline = Date.now() + timeoutMs
  if (!normalized) return null
  const contextual = preferredCity && !normalized.includes(preferredCity)
    ? `${preferredCity}${normalized}`
    : normalized
  let remaining = deadline - Date.now()
  if (remaining <= 0) return null
  const geocoded = await geocoderLookup(api, contextual, Math.min(1400, remaining))
  if (geocoded) return geocoded

  remaining = deadline - Date.now()
  if (remaining <= 0) return null
  const place = await placeSearchLookup(api, normalized, Math.min(1400, remaining), preferredCity)
  if (place) return place

  if (contextual !== normalized) {
    remaining = deadline - Date.now()
    if (remaining > 0) return geocoderLookup(api, normalized, remaining)
  } else if (original !== normalized) {
    remaining = deadline - Date.now()
    if (remaining > 0) return geocoderLookup(api, original, remaining)
  }
  return null
}

function applyMapPoint(point: MapPoint, address = '', city = '') {
  if (mapPickTarget?.kind === 'order') {
    mapPickTarget.draft.location_lat = point.lat
    mapPickTarget.draft.location_lng = point.lng
    mapPickTarget.draft.geocode_status = address ? 'resolved' : 'manual'
    mapPickTarget.draft.geocode_error = null
    mapPickTarget.draft.geocode_attempted_address = address || mapPickTarget.draft.location?.trim()
    mapPickTarget.draft.city = city || mapPickTarget.draft.city || currentCity.value || null
    if (address) {
      mapPickTarget.draft.location = address
      mapPickTarget.draft.geocoded_address = address
    }
  } else if (mapPickTarget?.kind === 'origin') {
    filters.origin_lat = point.lat.toFixed(6)
    filters.origin_lng = point.lng.toFixed(6)
    scheduleJobSearch()
  } else if (mapPickTarget?.kind === 'saved') {
    mapPendingPoint.value = point
    mapPendingCity.value = city || mapPickTarget.job.city || currentCity.value
  }
  if (address) mapPickedAddress.value = address
}

function setMapMarker(point: MapPoint) {
  const position: [number, number] = [point.lng, point.lat]
  amapInstance?.setCenter(position)
  amapMarker?.setPosition(position)
  applyMapPoint(point)
}

async function openMapPicker(target: { kind: 'order'; draft: Job } | { kind: 'saved'; job: Job } | { kind: 'origin' }) {
  await loadMapConfig()
  if (!mapConfig.value.sdk_url || !mapConfig.value.public_key) {
    message.value = '地图配置未就绪，请检查 backend/.env 中的 MAP_WEB_SDK_URL 和 MAP_WEB_PUBLIC_KEY。'
    return
  }
  mapPickTarget = target
  mapError.value = ''
  mapSearch.value = target.kind === 'order' ? target.draft.location || '' : target.kind === 'saved' ? target.job.location || '' : ''
  mapPickedAddress.value = ''
  mapPendingPoint.value = null
  mapPendingCity.value = ''
  mapPickerOpen.value = true
  await nextTick()
  try {
    amapApi = await loadAmapSdk(mapConfig.value.sdk_url, mapConfig.value.public_key, mapConfig.value.js_service_proxy_url)
    const selectedJob = target.kind === 'order' ? target.draft : target.kind === 'saved' ? target.job : null
    const initialPoint = selectedJob
      ? { lat: selectedJob.location_lat || 39.9042, lng: selectedJob.location_lng || 116.4074 }
      : { lat: Number(filters.origin_lat) || 39.9042, lng: Number(filters.origin_lng) || 116.4074 }
    const center: [number, number] = [initialPoint.lng, initialPoint.lat]
    amapInstance?.destroy()
    amapInstance = new amapApi.Map(mapContainer.value!, { zoom: 12, center })
    amapMarker = new amapApi.Marker({ position: center })
    amapInstance.add(amapMarker)
    amapInstance.on('click', (event) => {
      const point = { lat: event.lnglat.getLat(), lng: event.lnglat.getLng() }
      setMapMarker(point)
      if (amapApi) new amapApi.Geocoder().getAddress(event.lnglat, (status, result) => {
        if (status === 'complete' && result.regeocode?.formattedAddress) {
          const component = result.regeocode.addressComponent
          applyMapPoint(point, result.regeocode.formattedAddress, cityFromAddress(component?.city, component?.province))
        }
      })
    })
  } catch (error) {
    mapError.value = error instanceof Error ? error.message : '地图加载失败。'
  }
}

async function searchMapAddress() {
  if (!amapApi || !mapSearch.value.trim()) return
  mapBusy.value = true
  mapError.value = ''
  try {
    const found = await findMapAddress(amapApi, mapSearch.value.trim(), MAP_LOOKUP_TIMEOUT_MS + 1500, currentCity.value)
    mapBusy.value = false
    if (!found) {
      mapError.value = '地址未找到或查询超时；可缩短地址、去掉“附近”等词，或直接在地图上点选。'
      return
    }
    setMapMarker(found.point)
    applyMapPoint(found.point, found.address, found.city)
    mapPickedAddress.value = found.address
  } catch {
    mapError.value = '地图地址查询失败，请检查 SDK 配置或直接在地图上点选。'
  } finally {
    mapBusy.value = false
  }
}

function closeMapPicker() {
  mapPickerOpen.value = false
  amapInstance?.destroy()
  amapInstance = null
  amapMarker = null
  mapPickTarget = null
}

async function confirmMapSelection() {
  if (mapPickTarget?.kind === 'saved' && mapPendingPoint.value && mapPickTarget.job.id) {
    mapBusy.value = true
    try {
      const response = await apiFetch(`${apiBase}/jobs/${mapPickTarget.job.id}/location`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          location_lat: mapPendingPoint.value.lat,
          location_lng: mapPendingPoint.value.lng,
          location: mapPickedAddress.value || mapPickTarget.job.location,
          city: mapPendingCity.value || mapPickTarget.job.city || currentCity.value,
        }),
      })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || '保存订单地点失败。')
      jobs.value = jobs.value.map((job) => job.id === result.id ? result : job)
      closeMapPicker()
      await loadJobs()
    } catch (error) {
      mapError.value = error instanceof Error ? error.message : '保存订单地点失败。'
    } finally {
      mapBusy.value = false
    }
    return
  }
  const selectingOrigin = mapPickTarget?.kind === 'origin'
  closeMapPicker()
  if (selectingOrigin) void loadJobs()
}

function locateCurrentPosition() {
  if (!navigator.geolocation) {
    message.value = '当前浏览器不支持定位，请手动填写坐标。'
    return
  }
  navigator.geolocation.getCurrentPosition(
    (position) => {
      const gcj02 = wgs84ToGcj02(position.coords.latitude, position.coords.longitude)
      filters.origin_lat = gcj02.lat.toFixed(6)
      filters.origin_lng = gcj02.lng.toFixed(6)
      message.value = '已取得当前位置，仅用于本次距离筛选。'
      void loadJobs()
    },
    () => { message.value = '无法取得位置权限，请允许浏览器定位或手动填写坐标。' },
    { enableHighAccuracy: true, timeout: 10000 },
  )
}

function handleFile(event: Event) {
  reviewMessageId.value = null
  const file = (event.target as HTMLInputElement).files?.[0]
  if (file) void preview('', file)
}

async function confirmImport() {
  busy.value = true
  try {
    for (const draft of drafts.value) {
      const onlineOrder = (draft.teaching_mode || '').includes('线上') || (draft.location || '').includes('线上')
      if (!onlineOrder && !draft.city && currentCity.value) draft.city = currentCity.value
    }
    const draftCount = drafts.value.length
    if (reviewMessageId.value !== null) {
      if (!reviewSentAt.value) throw new Error('请填写这条消息实际发布的时间')
      const response = await apiFetch(`${apiBase}/wechat-sync/reviews/${reviewMessageId.value}/approve`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sent_at: new Date(reviewSentAt.value).toISOString(), jobs: drafts.value }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(errorDetail(data))
      reviewMessageId.value = null
      drafts.value = []
      message.value = '已提交后台处理，订单按原消息发布时间计算有效期。'
      return
    }
    const response = await apiFetch(`${apiBase}/import/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jobs: drafts.value }),
    })
    if (!response.ok) throw new Error('保存失败，请检查数据后重试。')
    const saved: Job[] = await response.json()
    const unresolvedAddresses = saved.filter((job) => job.geocode_status === 'failed' && job.location && !job.location.includes('线上'))
    const firstGeocodeError = unresolvedAddresses.find((job) => job.geocode_error)?.geocode_error
    drafts.value = []
    await loadJobs()
    message.value = `已导入 ${saved.length} 条家教单${saved.length < draftCount ? '，重复内容已跳过' : ''}${unresolvedAddresses.length ? `；${unresolvedAddresses.length} 条地址未能自动定位，可手动选点。${firstGeocodeError || ''}` : '。'}`
    tab.value = 'jobs'
  } catch (error) {
    message.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    busy.value = false
  }
}

async function reviewSyncMessage(item: ReviewMessage) {
  sourceGroup.value = item.source_group
  chatText.value = item.text
  reviewSentAt.value = item.sent_at ? new Date(new Date(asUtc(item.sent_at)).getTime() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) : ''
  await preview(item.text)
  reviewMessageId.value = item.id
}

async function signOut() {
  try { await logout() } catch (error) { message.value = error instanceof Error ? error.message : '退出失败' }
}

watch(() => currentUser.value?.id, () => {
  ++jobRequestId
  window.clearTimeout(jobSearchTimer)
  jobs.value = []; drafts.value = []; chatText.value = ''; sourceGroup.value = ''
  aiReasons.value = {}; aiQuery.value = ''; aiResultsMode.value = false
  message.value = ''; backfillRequests.clear(); reviewMessageId.value = null
  Object.assign(filters, { subject: '', location: '', source_group: '', min_salary: '', max_salary: '', max_distance_km: '', origin_lat: '', origin_lng: '' })
  closeMapPicker(); citySettingsOpen.value = false
  currentCity.value = currentUser.value ? localStorage.getItem(`teacher-search-city-${currentUser.value.id}`) || '' : ''
  if (currentUser.value) { void loadJobs(); void loadMapConfig(); void loadAIConfig() }
})
onMounted(() => void loadSession().catch(() => { message.value = '暂时无法连接服务，请检查后端是否启动。' }))
</script>

<template>
  <main class="shell">
    <header class="topbar">
      <a class="brand" href="#" @click.prevent="tab = 'jobs'">
        <span class="brand-mark">课</span>
        <span>课遇<span class="brand-dot">.</span></span>
      </a>
      <div class="header-note"><span class="status-dot"></span>把合适的课，留给合适的你</div>
      <button v-if="currentUser" class="city-setting-button" @click="openCitySettings">⚙ 所在城市：{{ currentCity || '未设置' }}</button>
      <button v-if="currentUser" class="account-button" @click="signOut">{{ currentUser.username }} · 退出</button>
    </header>

    <section class="hero">
      <div class="hero-copy">
        <span class="eyebrow">TEACHING OPPORTUNITIES · 2026</span>
        <h1>好老师，<em>值得</em><br />遇见好机会。</h1>
        <p>从群消息里解放出来，把时间花在真正重要的事情上。</p>
      </div>
      <div class="hero-art" aria-hidden="true">
        <div class="sun"></div><div class="orbit orbit-one"></div><div class="orbit orbit-two"></div>
        <div class="art-card"><span>本周新单</span><strong>+ 12</strong><small>机会正在靠近</small></div>
        <span class="spark spark-one">✳</span><span class="spark spark-two">✳</span>
      </div>
    </section>

    <p v-if="!sessionReady" class="notice">正在检查登录状态…</p>
    <AccountPanel v-else-if="!currentUser" />
    <template v-if="currentUser">
    <nav class="tabs" aria-label="主导航">
      <button :class="{ active: tab === 'jobs' }" @click="tab = 'jobs'">发现好课 <span>{{ jobs.length }}</span></button>
      <button :class="{ active: tab === 'import' }" @click="tab = 'import'">导入群消息 <span class="tab-icon">↗</span></button>
      <div class="tabs-rule"></div>
      <span class="privacy"><span>✳</span> 订单与群来源仅自己可见</span>
    </nav>

    <div v-if="message" class="notice" role="status">{{ message }}</div>

    <section v-if="tab === 'jobs'" class="content-grid">
      <aside class="filters panel">
        <div class="section-heading"><div><span class="eyebrow">YOUR PREFERENCES</span><h2>筛选偏好</h2></div><span class="filter-symbol">⌘</span></div>
        <label>想教什么科目<input v-model="filters.subject" placeholder="例如：数学" @input="scheduleJobSearch" /></label>
        <label>期望上课区域<input v-model="filters.location" placeholder="例如：海淀区" @input="scheduleJobSearch" /></label>
        <label>来源群聊<input v-model="filters.source_group" placeholder="筛选订单来源" @input="scheduleJobSearch" /></label>
        <div class="distance-controls">
          <div class="salary-label">通勤范围 <span>直线估算</span></div>
          <input v-model="filters.max_distance_km" type="number" min="0.1" step="0.5" placeholder="最大距离（公里）" @input="scheduleJobSearch" />
          <button class="locate-button" @click="locateCurrentPosition">⌖ 使用当前位置</button>
          <button class="locate-button map-open-button" @click="openMapPicker({ kind: 'origin' })">在地图上选择起点</button>
          <div class="coord-fields">
            <input v-model="filters.origin_lat" type="number" step="any" placeholder="起点纬度" aria-label="起点纬度" @change="loadJobs" />
            <input v-model="filters.origin_lng" type="number" step="any" placeholder="起点经度" aria-label="起点经度" @change="loadJobs" />
          </div>
          <p class="map-hint">{{ mapConfig.server_geocoding_configured ? '后端地址转换凭证已配置；导入时会显示高德实际校验结果，筛选会先补全当前城市的旧订单地址。' : '后端尚未配置地图服务凭证；新导入地址无法自动转成坐标。' }} 距离按地图坐标计算直线通勤范围。</p>
        </div>
        <div class="salary-label">课时费范围 <span>元 / 小时</span></div>
        <div class="salary-fields"><input v-model="filters.min_salary" type="number" min="0" placeholder="最低" @input="scheduleJobSearch" /><span>—</span><input v-model="filters.max_salary" type="number" min="0" placeholder="最高" @input="scheduleJobSearch" /></div>
        <button class="reset-button" @click="Object.assign(filters, { subject: '', location: '', source_group: '', min_salary: '', max_salary: '', max_distance_km: '', origin_lat: '', origin_lng: '' }); loadJobs()">清除筛选 <span>↺</span></button>
      </aside>

      <div class="job-area">
        <section class="ai-search panel" aria-label="AI 模糊查找">
          <div class="ai-search-copy"><span class="ai-star">✳</span><div><strong>用一句话找课</strong><p>{{ aiConfig.configured ? `由 ${aiConfig.model} 理解需求，并从已导入订单中筛选` : '填写服务端模型配置后即可使用自然语言筛选订单' }}</p></div></div>
          <form class="ai-search-form" @submit.prevent="searchWithAI"><input v-model="aiQuery" maxlength="1000" placeholder="例如：顺义附近，初中英语，周末上课，时薪 150 元以上" aria-label="描述想找的家教订单" /><button class="primary-button" :disabled="aiBusy || aiQuery.trim().length < 2">{{ aiBusy ? '正在查找…' : 'AI 查找' }} <span>↗</span></button></form>
        </section>
        <div class="list-heading"><div><span class="eyebrow">CURATED FOR YOU</span><h2>正在招募的好机会 <span class="count">{{ jobs.length.toString().padStart(2, '0') }}</span></h2></div></div>
        <div v-if="filteredJobs.length" class="job-list">
          <article v-for="job in filteredJobs" :key="job.id" class="job-card">
            <div class="job-top"><span class="subject-pill">{{ job.subject || '家教' }}</span><span v-if="job.grade" class="grade-pill">{{ job.grade }}</span><span v-if="job.city" class="city-pill">{{ job.city }}</span><time>{{ job.order_code || '家教订单' }}<small v-if="job.published_at"> · 发布于 {{ new Date(asUtc(job.published_at)).toLocaleString('zh-CN') }}</small><small v-if="job.created_at"> · 导入于 {{ new Date(asUtc(job.created_at)).toLocaleDateString('zh-CN') }}</small></time></div>
            <h3>{{ job.raw_text }}</h3>
            <p v-if="aiResultsMode && job.id && aiReasons[job.id]" class="ai-reason">AI 匹配说明：{{ aiReasons[job.id] }}</p>
            <div class="job-meta"><span>⌖ {{ job.location || '地点待确认' }}<template v-if="job.teaching_mode"> · {{ job.teaching_mode }}</template></span><span>◷ {{ job.schedule || '时间待沟通' }}</span><span v-if="job.distance_km != null">约 {{ job.distance_km }} 公里（直线）</span></div>
            <small v-if="job.geocode_error && job.location_lat == null" class="geo-error">坐标补全失败：{{ job.geocode_error }}</small>
            <button v-if="job.id && (job.location_lat == null || job.location_lng == null)" class="job-location-button" @click="openMapPicker({ kind: 'saved', job })">定位失败，手动搜索/选择地点</button>
            <div class="job-bottom"><div class="salary">{{ job.salary != null ? `¥${job.salary}${job.salary_is_minimum ? '+' : ''}` : '薪资面议' }}<small v-if="job.salary != null"> / {{ job.salary_unit || job.salary_basis || '待确认' }}</small></div><span class="source-mark">来源：{{ job.source_group || '未填写' }}</span></div>
          </article>
        </div>
        <div v-else class="empty-state"><span class="empty-icon">⌕</span><h3>这里暂时还没有课</h3><p>导入群聊里的家教消息，合适的机会就会出现在这里。</p><button class="primary-button" @click="tab = 'import'">去导入消息 <span>↗</span></button></div>
        <div class="list-foot"><span>每一份认真，都值得被看见。</span><span>共 {{ jobs.length }} 条机会</span></div>
      </div>
    </section>

    <section v-else class="import-section">
      <SyncPanel :key="currentUser.id" :city="currentCity" @review="reviewSyncMessage" />
      <div class="import-intro"><span class="eyebrow">BRING YOUR OPPORTUNITIES</span><h2>把群里的好机会，<em>带过来。</em></h2><p>粘贴聊天内容或上传 TXT、CSV 文件。确认信息后再保存，原始消息会保留方便核对。</p></div>
      <div class="import-panel panel">
        <label class="source-input">来源群聊名称 <span>用于后续联系群管理员</span><input v-model="sourceGroup" required maxlength="120" placeholder="例如：顺义大学生家教群" /></label>
        <div class="import-tools"><span class="step-label"><b>01</b> 添加群聊消息</span><button class="upload-button" @click="fileInput?.click()">上传 TXT / CSV <span>↑</span></button><input ref="fileInput" class="hidden-input" type="file" accept=".txt,.csv,text/plain,text/csv" @change="handleFile" /></div>
        <textarea id="chat-text" v-model="chatText" placeholder="把群里的聊天内容粘贴在这里…&#10;&#10;例如：初中数学家教，周末上课，薪资 150元/小时，地址在海淀区" @input="drafts = []; message = ''"></textarea>
      <div class="import-hint"><span>✳</span> 支持 TXT、CSV 和直接粘贴；新订单地址自动定位最多等待 12 秒，超时会跳过坐标定位但仍继续导入全部订单。</div>
        <div class="import-actions"><span>先填写来源群聊，解析后可逐条核对来源</span><button class="primary-button" :disabled="busy || !sourceGroup.trim()" @click="preview(chatText)">{{ busy ? '处理中…' : '解析并预览' }} <span>↗</span></button></div>
      </div>
      <div v-if="drafts.length" class="preview-panel panel">
        <label v-if="reviewMessageId !== null" class="review-time">原消息发布时间（用于三天有效期）<input v-model="reviewSentAt" type="datetime-local" required /><button class="reset-button" @click="reviewMessageId = null; drafts = []">取消核对</button></label>
        <div class="preview-heading"><div><span class="step-label"><b>02</b> 检查并确认</span><h3>识别到 {{ drafts.length }} 条可能的家教单</h3></div><span class="ignored">跳过 {{ ignoredLines }} 行无关内容</span></div>
        <p class="review-tip">请检查并修改不准确的字段，保存前都可以调整。</p>
        <article v-for="(draft, index) in drafts" :key="index" class="draft-card">
          <div class="draft-number">{{ (index + 1).toString().padStart(2, '0') }}</div>
          <div class="draft-fields">
            <label>原始消息<textarea v-model="draft.raw_text" rows="2"></textarea></label>
            <div class="field-row"><label>订单编号<input v-model="draft.order_code" placeholder="未识别" /></label><label>来源群聊<input v-model="draft.source_group" placeholder="请填写来源" /></label><label>授课方式<input v-model="draft.teaching_mode" placeholder="线上/线下" /></label></div>
            <div class="field-row"><label>科目<input v-model="draft.subject" placeholder="待填写" /></label><label>年级 / 性别<input v-model="draft.grade" placeholder="待填写" /></label><label>学生性别<input v-model="draft.gender" placeholder="待填写" /></label></div>
            <div class="field-row"><label>上课地址<input v-model="draft.location" placeholder="待填写" @change="markDraftAddressChanged(draft)" /><small class="geo-status" :class="{ resolved: draft.location_lat != null }">{{ draft.location_lat != null ? '后端已取得坐标，可参与距离筛选' : draft.geocode_status === 'failed' ? `后端定位失败：${draft.geocode_error || '暂无服务商错误详情'}` : '确认导入时将由后端自动定位' }}</small></label><label>所属地级市<input v-model="draft.city" :placeholder="currentCity || '定位后自动填写'" @change="markDraftAddressChanged(draft)" /></label><label>薪资金额<input v-model.number="draft.salary" type="number" min="0" placeholder="待填写" /></label></div>
            <div class="field-row"><label>上课时间<input v-model="draft.schedule" placeholder="待填写" /></label><label>地点纬度<input v-model.number="draft.location_lat" type="number" step="any" placeholder="地图选点后填写" /></label><label>地点经度<input v-model.number="draft.location_lng" type="number" step="any" placeholder="地图选点后填写" /></label></div>
            <button v-if="draft.geocode_status === 'failed'" class="locate-button draft-map-button" @click="openMapPicker({ kind: 'order', draft })">⌖ 自动定位超时，手动搜索/选择地点</button>
            <div class="field-row"><label>学员情况<input v-model="draft.student_notes" placeholder="待填写" /></label><label>教员要求<input v-model="draft.requirements" placeholder="待填写" /></label><label>薪资类型<select v-model="draft.salary_basis"><option value="">待确认</option><option value="hour">时薪</option><option value="week">周薪</option><option value="session">按次</option></select></label></div>
          </div>
        </article>
        <div class="confirm-row"><span>确认后才会写入家教单列表</span><button class="primary-button" :disabled="busy" @click="confirmImport">{{ busy ? '保存中…' : '确认导入' }} <span>↗</span></button></div>
      </div>
    </section>

    <div v-if="mapPickerOpen" class="map-dialog-backdrop" role="presentation" @click.self="closeMapPicker">
      <section class="map-dialog panel" role="dialog" aria-modal="true" aria-label="地图选点">
        <div class="map-dialog-heading"><div><span class="eyebrow">MAP LOCATION</span><h2>搜索地址或在地图上点选</h2></div><button class="map-close" aria-label="关闭地图" @click="closeMapPicker">×</button></div>
        <form class="map-search-form" @submit.prevent="searchMapAddress"><input v-model="mapSearch" placeholder="输入地址或地点名称" aria-label="搜索地图地址" /><button class="primary-button" :disabled="mapBusy || !mapSearch.trim()">{{ mapBusy ? '搜索中…' : '搜索' }}</button></form>
        <p v-if="mapPickedAddress || mapPendingPoint" class="map-picked">已选：{{ mapPickedAddress || '地图点位' }}（{{ mapPickTarget?.kind === 'order' ? mapPickTarget.draft.location_lat?.toFixed(5) : mapPickTarget?.kind === 'saved' ? mapPendingPoint?.lat.toFixed(5) : filters.origin_lat }}，{{ mapPickTarget?.kind === 'order' ? mapPickTarget.draft.location_lng?.toFixed(5) : mapPickTarget?.kind === 'saved' ? mapPendingPoint?.lng.toFixed(5) : filters.origin_lng }}）</p>
        <p v-if="mapError" class="map-error" role="alert">{{ mapError }}</p>
        <div ref="mapContainer" class="map-canvas"></div>
        <p class="map-dialog-note">地址查询最多等待 5 秒；超时后可缩短关键词或直接点选。选择结果用于订单坐标或本次距离筛选。</p>
        <div class="map-dialog-actions"><button class="upload-button" @click="closeMapPicker">取消</button><button class="primary-button" :disabled="mapBusy" @click="confirmMapSelection">确认选点</button></div>
      </section>
    </div>

    <div v-if="citySettingsOpen" class="map-dialog-backdrop" role="presentation" @click.self="citySettingsOpen = false">
      <section class="city-settings-dialog panel" role="dialog" aria-modal="true" aria-label="所在地级市设置">
        <div class="map-dialog-heading"><div><span class="eyebrow">SYSTEM SETTINGS</span><h2>设置所在地级市</h2></div><button class="map-close" aria-label="关闭设置" @click="citySettingsOpen = false">×</button></div>
        <form @submit.prevent="saveCitySetting">
          <label class="city-setting-label">所在地级市<input v-model="cityDraft" list="prefecture-city-options" placeholder="输入或选择，例如：北京市" maxlength="80" required /></label>
          <datalist id="prefecture-city-options"><option value="北京市" /><option value="上海市" /><option value="天津市" /><option value="重庆市" /><option value="南京市" /><option value="杭州市" /><option value="苏州市" /><option value="成都市" /><option value="武汉市" /><option value="广州市" /><option value="深圳市" /><option value="西安市" /></datalist>
          <p class="map-dialog-note">该城市用于补全模糊订单地址，并在距离筛选时优先筛选同一城市的订单。其他地级市可直接输入。</p>
          <div class="map-dialog-actions"><button type="button" class="upload-button" @click="citySettingsOpen = false">取消</button><button type="submit" class="primary-button">保存城市</button></div>
        </form>
      </section>
    </div>

    </template>
    <footer><span>课遇 <span class="brand-dot">.</span> 让每一次认真，都有回响。</span><span>谨慎核验信息，安心选择机会。</span></footer>
  </main>
</template>
