<script setup>
import { computed, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useRealtime } from '../composables/useRealtime'

const route = useRoute()
const router = useRouter()
const { realtime, unhandledCount } = useRealtime()
const now = ref(new Date())
const timer = setInterval(() => (now.value = new Date()), 1000)
onUnmounted(() => clearInterval(timer))
const pageTitle = computed(() => route.meta.title || '')
const pageSub = computed(() => route.meta.sub || '')
const activeMenu = computed(() => route.name)

const menus = [
  { name: 'dashboard', label: '监控总览', icon: 'Odometer' },
  { name: 'monitor', label: '实时监控', icon: 'VideoCamera' },
  { name: 'phone', label: '手机接入向导', icon: 'Iphone' },
  { name: 'alarms', label: '告警中心', icon: 'Bell' },
  { name: 'cameras', label: '视频源管理', icon: 'Monitor' },
  { name: 'settings', label: '系统设置', icon: 'Setting' }
]

function go(name) {
  router.push({ name })
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="brand">
        <div class="brand-mark">FG</div>
        <div>
          <b>FireGuard AI</b>
          <small>火灾智能监测预警</small>
        </div>
      </div>
      <el-menu :default-active="activeMenu" class="menu" background-color="#12161f" text-color="#aab2c0" active-text-color="#23d18b">
        <el-menu-item v-for="m in menus" :key="m.name" :index="m.name" @click="go(m.name)">
          {{ m.label }}
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <div>
          <h2>{{ pageTitle }}</h2>
          <span>{{ pageSub }}</span>
        </div>
        <div class="status">
          <span class="dot" :class="{ online: realtime.connected }" />
          <span class="status-text">{{ realtime.connected ? '实时通道已连接' : '实时通道未连接' }}</span>
          <el-badge v-if="unhandledCount > 0" :value="unhandledCount" class="badge">
            <span class="alarm-text">本次会话新告警</span>
          </el-badge>
          <span class="clock">{{ now.toLocaleString('zh-CN', { hour12: false }) }}</span>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout { height: 100vh; }
.aside { background: #12161f; }
.brand { display: flex; gap: 10px; align-items: center; padding: 18px 16px; color: #fff; }
.brand-mark { width: 36px; height: 36px; line-height: 36px; text-align: center; border-radius: 8px; background: #e5484d; font-weight: 700; }
.brand small { display: block; color: #aab2c0; }
.menu { border-right: none; }
.header { display: flex; align-items: center; justify-content: space-between; background: #fff; border-bottom: 1px solid #e5e7eb; }
.header h2 { margin: 0; }
.header span { color: #7b8494; font-size: 13px; }
.clock { color: #4b5563; }
.status { display: flex; align-items: center; gap: 10px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #c0c4cc; display: inline-block; }
.dot.online { background: #23d18b; }
.status-text { color: #7b8494; font-size: 12px; }
.alarm-text { color: #e5484d; font-size: 12px; }
.main { background: #f3f5f8; }
</style>
