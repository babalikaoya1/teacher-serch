<script setup lang="ts">
import { ref } from 'vue'
import { apiBase, apiFetch, errorDetail } from './api'
import { setUser } from './session'

const register = ref(false)
const username = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')
async function submit() {
  busy.value = true
  error.value = ''
  try {
    const response = await apiFetch(`${apiBase}/auth/${register.value ? 'register' : 'login'}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: username.value.trim(), password: password.value }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(errorDetail(data))
    password.value = ''
    setUser(data)
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '暂时无法登录' }
  finally { busy.value = false }
}
</script>

<template>
  <section class="account-panel panel">
    <h2>{{ register ? '创建你的私人订单库' : '登录你的订单库' }}</h2>
    <p>群聊来源、订单和同步设备仅自己可见。这里登录的是网站账号。</p>
    <form @submit.prevent="submit">
      <label>账号<input v-model="username" autocomplete="username" minlength="3" maxlength="40" required placeholder="至少三个字，可使用中文、字母、数字或下划线" /></label>
      <label>密码<input v-model="password" type="password" :autocomplete="register ? 'new-password' : 'current-password'" minlength="10" maxlength="128" required placeholder="至少十位" /></label>
      <p v-if="error" class="map-error" role="alert">{{ error }}</p>
      <button class="primary-button" :disabled="busy">{{ busy ? '请稍候…' : register ? '注册并登录' : '登录' }}</button>
      <button class="upload-button" type="button" @click="register = !register; error = ''">{{ register ? '已有账号，去登录' : '创建账号' }}</button>
    </form>
  </section>
</template>
