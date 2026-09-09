<script setup>
import { computed, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const now = ref(new Date())
const timer = setInterval(() => (now.value = new Date()), 1000)
onUnmounted(() => clearInterval(timer))
const pageTitle = computed(() => route.meta.title || '')
const pageSub = computed(() => route.meta.sub || '')
const activeMenu = computed(() => route.name)

const menus = [
  { name: 'dashboard', label: '监控总览', icon: 'Odometer' },
  { name: 'monitor', label: '实时监控', icon: 'VideoCamera' },
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
        <div class="clock">{{ now.toLocaleString('zh-CN', { hour12: false }) }}</div>
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
.main { background: #f3f5f8; }
</style>
