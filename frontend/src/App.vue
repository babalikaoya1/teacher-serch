<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

type Job = {
  id?: number
  subject: string | null
  grade: string | null
  location: string | null
  salary: number | null
  salary_unit: string | null
  schedule: string | null
  raw_text: string
  source_group?: string | null
  status?: string
}

const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api'
const tab = ref<'jobs' | 'import'>('jobs')
const jobs = ref<Job[]>([])
const drafts = ref<Job[]>([])
const ignoredLines = ref(0)
const busy = ref(false)
const message = ref('')
const filters = reactive({ subject: '', location: '', min_salary: '', max_salary: '' })
const fileInput = ref<HTMLInputElement | null>(null)
const chatText = ref('')
const filteredJobs = computed(() => jobs.value)

async function loadJobs() {
  const params = new URLSearchParams()
  if (filters.subject) params.set('subject', filters.subject)
  if (filters.location) params.set('location', filters.location)
  if (filters.min_salary) params.set('min_salary', filters.min_salary)
  if (filters.max_salary) params.set('max_salary', filters.max_salary)
  try {
    const response = await fetch(`${apiBase}/jobs?${params}`)
    if (!response.ok) throw new Error('查询失败')
    jobs.value = await response.json()
    message.value = ''
  } catch {
    message.value = '暂时连接不上服务，请确认后端已启动。'
  }
}

async function preview(text: string, file?: File) {
  busy.value = true
  message.value = ''
  const form = new FormData()
  if (file) form.append('file', file)
  else form.append('text', text)
  try {
    const response = await fetch(`${apiBase}/import/preview`, { method: 'POST', body: form })
    const result = await response.json()
    if (!response.ok) throw new Error(result.detail || '解析失败')
    drafts.value = result.jobs
    ignoredLines.value = result.ignored_lines
    if (drafts.value.length === 0) message.value = '没有识别到家教单。请确认文本中包含科目或家教相关描述。'
  } catch (error) {
    message.value = error instanceof Error ? error.message : '导入解析失败'
  } finally {
    busy.value = false
  }
}

function handleFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (file) void preview('', file)
}

async function confirmImport() {
  busy.value = true
  try {
    const response = await fetch(`${apiBase}/import/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jobs: drafts.value }),
    })
    if (!response.ok) throw new Error('保存失败，请检查数据后重试。')
    const saved: Job[] = await response.json()
    message.value = `已导入 ${saved.length} 条家教单${saved.length < drafts.value.length ? '，重复内容已跳过' : ''}。`
    drafts.value = []
    await loadJobs()
    tab.value = 'jobs'
  } catch (error) {
    message.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    busy.value = false
  }
}

onMounted(loadJobs)
</script>

<template>
  <main class="shell">
    <header class="topbar">
      <a class="brand" href="#" @click.prevent="tab = 'jobs'">
        <span class="brand-mark">课</span>
        <span>课遇<span class="brand-dot">.</span></span>
      </a>
      <div class="header-note"><span class="status-dot"></span>把合适的课，留给合适的你</div>
      <button class="avatar" aria-label="个人中心">林</button>
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

    <nav class="tabs" aria-label="主导航">
      <button :class="{ active: tab === 'jobs' }" @click="tab = 'jobs'">发现好课 <span>{{ jobs.length }}</span></button>
      <button :class="{ active: tab === 'import' }" @click="tab = 'import'">导入群消息 <span class="tab-icon">↗</span></button>
      <div class="tabs-rule"></div>
      <span class="privacy"><span>✳</span> 仅保存确认导入的内容</span>
    </nav>

    <div v-if="message" class="notice" role="status">{{ message }}</div>

    <section v-if="tab === 'jobs'" class="content-grid">
      <aside class="filters panel">
        <div class="section-heading"><div><span class="eyebrow">YOUR PREFERENCES</span><h2>筛选偏好</h2></div><span class="filter-symbol">⌘</span></div>
        <label>想教什么科目<input v-model="filters.subject" placeholder="例如：数学" @input="loadJobs" /></label>
        <label>期望上课区域<input v-model="filters.location" placeholder="例如：海淀区" @input="loadJobs" /></label>
        <div class="salary-label">课时费范围 <span>元 / 小时</span></div>
        <div class="salary-fields"><input v-model="filters.min_salary" type="number" min="0" placeholder="最低" @input="loadJobs" /><span>—</span><input v-model="filters.max_salary" type="number" min="0" placeholder="最高" @input="loadJobs" /></div>
        <button class="reset-button" @click="Object.assign(filters, { subject: '', location: '', min_salary: '', max_salary: '' }); loadJobs()">清除筛选 <span>↺</span></button>
        <div class="ai-card"><span class="ai-star">✳</span><div><strong>用一句话找课</strong><p>AI 模糊查找即将接入</p></div><span class="soon">即将上线</span></div>
      </aside>

      <div class="job-area">
        <div class="list-heading"><div><span class="eyebrow">CURATED FOR YOU</span><h2>正在招募的好机会 <span class="count">{{ jobs.length.toString().padStart(2, '0') }}</span></h2></div><button class="sort-button" @click="loadJobs">最近发布 <span>⌄</span></button></div>
        <div v-if="filteredJobs.length" class="job-list">
          <article v-for="job in filteredJobs" :key="job.id" class="job-card">
            <div class="job-top"><span class="subject-pill">{{ job.subject || '家教' }}</span><span v-if="job.grade" class="grade-pill">{{ job.grade }}</span><time>刚刚收录</time></div>
            <h3>{{ job.raw_text }}</h3>
            <div class="job-meta"><span>⌖ {{ job.location || '地点待确认' }}</span><span>◷ {{ job.schedule || '时间待沟通' }}</span></div>
            <div class="job-bottom"><div class="salary">{{ job.salary ? `¥${job.salary}` : '薪资面议' }}<small v-if="job.salary"> / {{ job.salary_unit || '小时' }}</small></div><button class="detail-button" @click="message = job.raw_text">查看详情 <span>↗</span></button></div>
          </article>
        </div>
        <div v-else class="empty-state"><span class="empty-icon">⌕</span><h3>这里暂时还没有课</h3><p>导入群聊里的家教消息，合适的机会就会出现在这里。</p><button class="primary-button" @click="tab = 'import'">去导入消息 <span>↗</span></button></div>
        <div class="list-foot"><span>每一份认真，都值得被看见。</span><span>共 {{ jobs.length }} 条机会</span></div>
      </div>
    </section>

    <section v-else class="import-section">
      <div class="import-intro"><span class="eyebrow">BRING YOUR OPPORTUNITIES</span><h2>把群里的好机会，<em>带过来。</em></h2><p>粘贴聊天内容或上传 TXT、CSV 文件。确认信息后再保存，原始消息会保留方便核对。</p></div>
      <div class="import-panel panel">
        <div class="import-tools"><span class="step-label"><b>01</b> 添加群聊消息</span><button class="upload-button" @click="fileInput?.click()">上传 TXT / CSV <span>↑</span></button><input ref="fileInput" class="hidden-input" type="file" accept=".txt,.csv,text/plain,text/csv" @change="handleFile" /></div>
        <textarea id="chat-text" v-model="chatText" placeholder="把群里的聊天内容粘贴在这里…&#10;&#10;例如：初中数学家教，周末上课，薪资 150元/小时，地址在海淀区" @input="drafts = []; message = ''"></textarea>
        <div class="import-hint"><span>✳</span> 支持 TXT、CSV 和直接粘贴；请勿导入与接单无关的敏感信息。</div>
        <div class="import-actions"><span>内容仅在确认后保存到本平台</span><button class="primary-button" :disabled="busy" @click="preview(chatText)">{{ busy ? '处理中…' : '解析并预览' }} <span>↗</span></button></div>
      </div>
      <div v-if="drafts.length" class="preview-panel panel">
        <div class="preview-heading"><div><span class="step-label"><b>02</b> 检查并确认</span><h3>识别到 {{ drafts.length }} 条可能的家教单</h3></div><span class="ignored">跳过 {{ ignoredLines }} 行无关内容</span></div>
        <p class="review-tip">请检查并修改不准确的字段，保存前都可以调整。</p>
        <article v-for="(draft, index) in drafts" :key="index" class="draft-card">
          <div class="draft-number">{{ (index + 1).toString().padStart(2, '0') }}</div>
          <div class="draft-fields">
            <label>原始消息<textarea v-model="draft.raw_text" rows="2"></textarea></label>
            <div class="field-row"><label>科目<input v-model="draft.subject" placeholder="待填写" /></label><label>年级<input v-model="draft.grade" placeholder="待填写" /></label><label>薪资（元）<input v-model.number="draft.salary" type="number" min="0" placeholder="待填写" /></label></div>
            <div class="field-row"><label>地点<input v-model="draft.location" placeholder="待填写" /></label><label>时间<input v-model="draft.schedule" placeholder="待填写" /></label><label>计薪方式<input v-model="draft.salary_unit" placeholder="元/小时" /></label></div>
          </div>
        </article>
        <div class="confirm-row"><span>确认后才会写入家教单列表</span><button class="primary-button" :disabled="busy" @click="confirmImport">{{ busy ? '保存中…' : '确认导入' }} <span>↗</span></button></div>
      </div>
    </section>

    <footer><span>课遇 <span class="brand-dot">.</span> 让每一次认真，都有回响。</span><span>谨慎核验信息，安心选择机会。</span></footer>
  </main>
</template>
