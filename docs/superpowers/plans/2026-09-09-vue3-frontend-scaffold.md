# Vue3 基础系统页面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在仓库根目录新建 `frontend/` Vue3 + Element Plus 工程，搭出监控总览、实时监控、告警中心、视频源管理、系统设置五个基础页面与统一布局，可在无后端时独立运行。

**Architecture:** Vite + Vue3 SPA，vue-router 使用 hash 模式（便于演示期由 FastAPI 直接托管构建产物，无需服务端 rewrite）；Element Plus 全量引入；ECharts 在 Dashboard 直接使用；开发期 Vite proxy 将 `/api`、`/stream`、`/ws` 转发到本机 FastAPI(8000)。

**Tech Stack:** Vue 3、Vite、Element Plus、vue-router、ECharts、JavaScript

## Global Constraints

- 运行环境：Node ≥ 20（本机实测 v24.15.0）、npm 11。
- 新建目录必须为仓库根下 `frontend/`；不得修改 `archive/早期演示系统/FireGuard_AI_Demo_Windows/`（它仅作视觉参考）。
- 路由统一使用 `createWebHashHistory`；五个页面路径：`/`、`/monitor`、`/alarms`、`/cameras`、`/settings`。
- UI 文案使用简体中文；视觉基调参考 demo（深色侧栏 + 内容区）。
- 接口契约（来自设计文档 4.4/4.5）：WebSocket 事件含 `detection`/`alarm`/`camera_online`/`camera_offline`；REST 路径以 `/api/...` 开头，实时画面流为 `GET /stream/{id}`。
- 每个任务结束必须 `npm run build` 通过并提交 Git。

## File Structure

```
frontend/
├─ package.json                  # 依赖与脚本（脚手架生成 + 追加依赖）
├─ vite.config.js                # dev server、proxy
├─ index.html                    # SPA 入口
└─ src/
   ├─ main.js                    # 装配 Vue/Element Plus/router
   ├─ App.vue                    # 仅 <router-view/>
   ├─ router/index.js            # hash 路由与页面标题
   ├─ layouts/MainLayout.vue     # 侧栏 + 顶栏 + 内容区
   ├─ styles/base.css            # 全局基础样式
   └─ views/
      ├─ DashboardView.vue       # 监控总览
      ├─ MonitorView.vue         # 实时监控
      ├─ AlarmsView.vue          # 告警中心
      ├─ CamerasView.vue         # 视频源管理（含上传入口）
      └─ SettingsView.vue        # 系统设置
```

---

### Task 1: Vite 脚手架与依赖

**Files:**
- Create: `frontend/`（脚手架生成）
- Modify: `frontend/vite.config.js`
- Test: 构建产物 `frontend/dist/`

**Interfaces:**
- Consumes: 无
- Produces: `npm run dev` / `npm run build` 脚本；开发代理规则。

- [ ] **Step 1: 生成脚手架并安装依赖**

在仓库根目录执行：

```bash
npm create vite@latest frontend -- --template vue
cd frontend
npm install
npm install element-plus @element-plus/icons-vue vue-router echarts
```

预期：命令无报错退出。

- [ ] **Step 2: 写入 Vite 配置**

用下面内容整体替换 `frontend/vite.config.js`：

```js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/stream': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true }
    }
  }
})
```

- [ ] **Step 3: 验证构建**

运行：`npm run build`
预期：Vite 构建成功，输出 `frontend/dist/`。

- [ ] **Step 4: 提交**

```bash
git add frontend
git commit -m "feat(frontend): 初始化 Vue3 + Element Plus 工程"
```

---

### Task 2: 统一布局与五个页面骨架

**Files:**
- Create: `frontend/src/router/index.js`、`frontend/src/layouts/MainLayout.vue`、`frontend/src/styles/base.css`
- Create: `frontend/src/views/DashboardView.vue`、`MonitorView.vue`、`AlarmsView.vue`、`CamerasView.vue`、`SettingsView.vue`（本任务先放占位卡片）
- Modify: `frontend/src/main.js`、`frontend/src/App.vue`
- Delete: `frontend/src/components/HelloWorld.vue`（脚手架示例组件）

**Interfaces:**
- Consumes: Task 1 的工程与依赖。
- Produces: `main.js` 导出 Vue 实例；路由名 `dashboard/monitor/alarms/cameras/settings`；后续任务只需替换各 View 文件内容。

- [ ] **Step 1: 替换入口与根组件**

整体替换 `frontend/src/main.js`：

```js
import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import App from './App.vue'
import router from './router'
import './styles/base.css'

createApp(App)
  .use(ElementPlus, { locale: zhCn })
  .use(router)
  .mount('#app')
```

整体替换 `frontend/src/App.vue`：

```vue
<template>
  <router-view />
</template>
```

删除示例组件：`Remove-Item frontend/src/components/HelloWorld.vue`

- [ ] **Step 2: 写入路由**

创建 `frontend/src/router/index.js`：

```js
import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { title: '监控总览', sub: '园区重点区域安全态势实时监测' } },
  { path: '/monitor', name: 'monitor', component: () => import('../views/MonitorView.vue'), meta: { title: '实时监控', sub: 'AI 视频分析与火灾烟雾识别' } },
  { path: '/alarms', name: 'alarms', component: () => import('../views/AlarmsView.vue'), meta: { title: '告警中心', sub: '统一处置烟雾、明火及高风险事件' } },
  { path: '/cameras', name: 'cameras', component: () => import('../views/CamerasView.vue'), meta: { title: '视频源管理', sub: 'RTSP / 视频流设备统一管理' } },
  { path: '/settings', name: 'settings', component: () => import('../views/SettingsView.vue'), meta: { title: '系统设置', sub: '检测阈值、告警策略与模型参数配置' } }
]

export default createRouter({ history: createWebHashHistory(), routes })
```

- [ ] **Step 3: 写入布局**

创建 `frontend/src/layouts/MainLayout.vue`：

```vue
<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
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
```

- [ ] **Step 4: 写入全局样式**

创建 `frontend/src/styles/base.css`：

```css
* { box-sizing: border-box; }
html, body, #app { margin: 0; height: 100%; font-family: 'Microsoft YaHei', system-ui, sans-serif; }
```

- [ ] **Step 5: 替换五个页面为占位骨架**

五个文件统一先放占位内容（后续任务逐个充实）。以 `DashboardView.vue` 为例，其余四个只改标题文字：

```vue
<script setup>
</script>

<template>
  <el-card shadow="never">
    <template #header>监控总览</template>
    <el-empty description="页面骨架已就绪，图表与指标数据将在后续任务接入" />
  </el-card>
</template>
```

分别创建 `MonitorView.vue`（标题"实时监控"）、`AlarmsView.vue`（"告警中心"）、`CamerasView.vue`（"视频源管理"）、`SettingsView.vue`（"系统设置"）。

- [ ] **Step 6: 让根组件使用布局**

整体替换 `frontend/src/App.vue`：

```vue
<template>
  <MainLayout />
</template>

<script setup>
import MainLayout from './layouts/MainLayout.vue'
</script>
```

- [ ] **Step 7: 验证构建**

运行：`npm run build`
预期：构建成功。

- [ ] **Step 8: 提交**

```bash
git add frontend/src
git commit -m "feat(frontend): 加入布局与五个页面路由骨架"
```

---

### Task 3: 监控总览页（指标卡 + ECharts 趋势）

**Files:**
- Modify: `frontend/src/views/DashboardView.vue`
- Test: `npm run build`

**Interfaces:**
- Consumes: 无（本任务使用静态演示数据，后端 `/api/dashboard` 联调在后续任务替换）。
- Produces: Dashboard 页展示 4 个指标卡 + 1 个 ECharts 柱状图，为后续真实 API 数据预留 `metrics` 与 `trend` 两个数据源常量。

- [ ] **Step 1: 写入页面代码**

整体替换 `frontend/src/views/DashboardView.vue`：

```vue
<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import * as echarts from 'echarts'

const metrics = ref([
  { label: '监控点位', value: '4', unit: '路', tone: 'primary' },
  { label: '今日告警', value: '0', unit: '条', tone: 'danger' },
  { label: '严重告警', value: '0', unit: '条', tone: 'warning' },
  { label: '待处理', value: '0', unit: '条', tone: 'success' }
])

const trend = [
  { day: '周一', count: 2 },
  { day: '周二', count: 4 },
  { day: '周三', count: 1 },
  { day: '周四', count: 5 },
  { day: '周五', count: 3 },
  { day: '周六', count: 6 },
  { day: '今日', count: 2 }
]

let chart = null

function renderChart() {
  chart = echarts.init(document.getElementById('trendChart'))
  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 20, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: trend.map(t => t.day) },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{
      name: '告警数',
      type: 'bar',
      barWidth: 28,
      data: trend.map(t => t.count),
      itemStyle: { color: '#e5484d', borderRadius: [4, 4, 0, 0] }
    }]
  })
}

const onResize = () => chart && chart.resize()
onMounted(() => {
  renderChart()
  window.addEventListener('resize', onResize)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  chart && chart.dispose()
})
</script>

<template>
  <div class="dashboard">
    <el-row :gutter="16">
      <el-col v-for="m in metrics" :key="m.label" :span="6">
        <el-card shadow="never">
          <div class="metric">
            <span>{{ m.label }}</span>
            <strong>{{ m.value }}<small>{{ m.unit }}</small></strong>
          </div>
        </el-card>
      </el-col>
    </el-row>
    <el-card shadow="never" class="chart-card">
      <template #header>本周告警趋势</template>
      <div id="trendChart" style="height: 320px" />
    </el-card>
  </div>
</template>

<style scoped>
.metric span { color: #7b8494; }
.metric strong { display: block; font-size: 26px; margin-top: 6px; }
.metric small { font-size: 13px; color: #9aa2b0; margin-left: 4px; font-weight: 400; }
.chart-card { margin-top: 16px; }
</style>
```

- [ ] **Step 2: 验证构建**

运行：`npm run build`；预期成功。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/DashboardView.vue
git commit -m "feat(frontend): 监控总览指标卡与告警趋势图"
```

---

### Task 4: 实时监控页（视频墙骨架）

**Files:**
- Modify: `frontend/src/views/MonitorView.vue`
- Test: `npm run build`

**Interfaces:**
- Consumes: 无（本任务为静态演示数据）。
- Produces: 2x2 视频墙卡片；卡片协议字段 `{ id, name, location, online }`，后续用真实摄像头接口替换 `mockCameras`。

- [ ] **Step 1: 写入页面代码**

整体替换 `frontend/src/views/MonitorView.vue`：

```vue
<script setup>
const mockCameras = [
  { id: 1, name: '仓库东区-01', location: '原料仓库东侧', online: true },
  { id: 2, name: '生产线-02', location: '二号生产线', online: true },
  { id: 3, name: '配电室-03', location: '一层配电室', online: false },
  { id: 4, name: '停车区-04', location: '厂区停车区', online: true }
]
</script>

<template>
  <el-row :gutter="16">
    <el-col v-for="c in mockCameras" :key="c.id" :span="12" class="cell">
      <el-card shadow="never" :body-style="{ padding: '0' }">
        <div class="stage" :class="{ offline: !c.online }">
          <el-tag :type="c.online ? 'success' : 'info'" size="small" class="tag">
            {{ c.online ? '在线' : '离线' }}
          </el-tag>
          <el-empty v-if="!c.online" description="视频源离线" :image-size="60" />
          <div v-else class="placeholder">
            <p>MJPEG 画面占位</p>
            <small>后端 /stream/{{ c.id }} 就绪后在此接入</small>
          </div>
        </div>
        <div class="meta">
          <b>{{ c.name }}</b>
          <span>{{ c.location }}</span>
        </div>
      </el-card>
    </el-col>
  </el-row>
</template>

<style scoped>
.cell { margin-bottom: 16px; }
.stage { height: 230px; background: #10131a; color: #fff; position: relative; }
.tag { position: absolute; top: 8px; left: 8px; z-index: 1; }
.placeholder { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #aab2c0; }
.stage.offline { background: #eef0f4; }
.meta { display: flex; justify-content: space-between; padding: 10px 14px; color: #4b5563; }
</style>
```

- [ ] **Step 2: 验证构建**：`npm run build` 成功。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/MonitorView.vue
git commit -m "feat(frontend): 实时监控页视频墙骨架"
```

---

### Task 5: 告警中心页（表格骨架）

**Files:**
- Modify: `frontend/src/views/AlarmsView.vue`
- Test: `npm run build`

**Interfaces:**
- Consumes: 无。
- Produces: `alarmRows` 演示数据与 `el-table` 列结构，后续由 `/api/alarms` 替换。

- [ ] **Step 1: 写入页面代码**

整体替换 `frontend/src/views/AlarmsView.vue`：

```vue
<script setup>
const alarmRows = [
  { created_at: '2026-09-09 10:00:12', camera_name: '仓库东区-01', alarm_type: 'fire', level: 'critical', confidence: 0.92, status: 'unhandled' }
]
</script>

<template>
  <el-card shadow="never">
    <el-table :data="alarmRows" stripe empty-text="暂无告警记录">
      <el-table-column prop="created_at" label="时间" width="180" />
      <el-table-column prop="camera_name" label="视频源" width="160" />
      <el-table-column label="类型" width="120">
        <template #default="{ row }">
          <el-tag :type="row.alarm_type === 'fire' ? 'danger' : 'warning'">
            {{ row.alarm_type === 'fire' ? '明火' : '烟雾' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="级别" width="120">
        <template #default="{ row }">
          <el-tag :type="row.level === 'critical' ? 'danger' : 'warning'" effect="plain">
            {{ row.level === 'critical' ? '严重' : '预警' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="置信度">
        <template #default="{ row }">{{ (row.confidence * 100).toFixed(1) }}%</template>
      </el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="row.status === 'handled' ? 'success' : 'info'" effect="plain">
            {{ row.status === 'handled' ? '已处理' : '待处理' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>
```

- [ ] **Step 2: 验证构建**：`npm run build` 成功。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/AlarmsView.vue
git commit -m "feat(frontend): 告警中心表格骨架"
```

---

### Task 6: 视频源管理页（列表 + 上传入口）

**Files:**
- Modify: `frontend/src/views/CamerasView.vue`
- Test: `npm run build`

**Interfaces:**
- Consumes: 无。
- Produces: 视频源卡片列表（演示数据）与上传对话框；上传使用 `POST /api/uploads`（multipart 字段名 `file`），后端就绪后即生效。

- [ ] **Step 1: 写入页面代码**

整体替换 `frontend/src/views/CamerasView.vue`：

```vue
<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'

const cameras = ref([
  { id: 1, name: '仓库东区-01', location: '原料仓库东侧', source: 'rtsp://demo/camera01', enabled: true },
  { id: 2, name: '生产线-02', location: '二号生产线', source: 'rtsp://demo/camera02', enabled: true },
  { id: 3, name: '配电室-03', location: '一层配电室', source: 'rtsp://demo/camera03', enabled: false },
  { id: 4, name: '停车区-04', location: '厂区停车区', source: 'rtsp://demo/camera04', enabled: true }
])

const uploadVisible = ref(false)

async function uploadFile({ file }) {
  const form = new FormData()
  form.append('file', file)
  try {
    const res = await fetch('/api/uploads', { method: 'POST', body: form })
    if (!res.ok) throw new Error('上传失败: HTTP ' + res.status)
    ElMessage.success('上传成功，已加入视频源列表')
    uploadVisible.value = false
  } catch (err) {
    ElMessage.error(err.message + '（请确认后端已启动）')
  }
}
</script>

<template>
  <div>
    <el-button type="primary" @click="uploadVisible = true">上传本地视频</el-button>
    <el-row :gutter="16" class="list">
      <el-col v-for="c in cameras" :key="c.id" :span="12" class="cell">
        <el-card shadow="never">
          <div class="row">
            <div>
              <b>{{ c.name }}</b>
              <p>{{ c.location }}</p>
              <small>{{ c.source }}</small>
            </div>
            <el-switch :model-value="c.enabled" disabled />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="uploadVisible" title="上传本地视频" width="480px">
      <el-upload drag :auto-upload="false" :show-file-list="true" accept=".mp4,.mov" :http-request="uploadFile">
        <el-icon size="36"><Upload /></el-icon>
        <div>将 MP4/MOV 拖到此处，或点击选择文件</div>
      </el-upload>
    </el-dialog>
  </div>
</template>

<style scoped>
.list { margin-top: 16px; }
.cell { margin-bottom: 16px; }
.row { display: flex; justify-content: space-between; align-items: center; }
.row p { margin: 4px 0; color: #7b8494; }
.row small { color: #9aa2b0; }
</style>
```

- [ ] **Step 2: 验证构建**：`npm run build` 成功。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/CamerasView.vue
git commit -m "feat(frontend): 视频源管理页与上传入口"
```

---

### Task 7: 系统设置页（表单骨架）

**Files:**
- Modify: `frontend/src/views/SettingsView.vue`
- Test: `npm run build`

**Interfaces:**
- Consumes: 无。
- Produces: 表单字段与 `settings` 默认值，保存时调用 `GET/PUT /api/settings`，后端就绪后即生效。

- [ ] **Step 1: 写入页面代码**

整体替换 `frontend/src/views/SettingsView.vue`：

```vue
<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

const defaults = { fire_threshold: 0.62, smoke_threshold: 0.55, continuous_frames: 4, alarm_cooldown: 8 }
const form = ref({ ...defaults })

onMounted(async () => {
  try {
    const res = await fetch('/api/settings')
    if (res.ok) form.value = await res.json()
  } catch { /* 后端未启动时保留默认值 */ }
})

async function save() {
  try {
    const res = await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value)
    })
    if (!res.ok) throw new Error('HTTP ' + res.status)
    ElMessage.success('参数保存成功')
  } catch (err) {
    ElMessage.error('保存失败：' + err.message)
  }
}
</script>

<template>
  <el-card shadow="never" class="settings">
    <el-form label-width="180px" style="max-width: 560px">
      <el-form-item label="明火置信度阈值">
        <el-slider v-model="form.fire_threshold" :min="0.1" :max="0.99" :step="0.01" show-input />
      </el-form-item>
      <el-form-item label="烟雾置信度阈值">
        <el-slider v-model="form.smoke_threshold" :min="0.1" :max="0.99" :step="0.01" show-input />
      </el-form-item>
      <el-form-item label="连续帧数">
        <el-input-number v-model="form.continuous_frames" :min="1" :max="30" />
      </el-form-item>
      <el-form-item label="告警冷却(秒)">
        <el-input-number v-model="form.alarm_cooldown" :min="1" :max="120" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="save">保存</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>
```

- [ ] **Step 2: 验证构建**：`npm run build` 成功。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/SettingsView.vue
git commit -m "feat(frontend): 系统设置页表单骨架"
```

---

### Task 8: 整体冒烟与验收

**Files:** 无新增
**Test:** 浏览器人工冒烟

**Interfaces:**
- Consumes: Task 1~7 全部产物。
- Produces: 可演示的 Vue3 基础系统页面。

- [ ] **Step 1: 启动开发服务器**

运行：`npm run dev`，打开 http://localhost:5173

- [ ] **Step 2: 逐页检查**

点击侧栏五个菜单：监控总览、实时监控、告警中心、视频源管理、系统设置。预期：路由切换正常、页面标题与子标题正确、各页骨架元素可见、Dashboard 图表渲染出 7 根柱。

- [ ] **Step 3: 停止服务器并提交验收记录**

`Ctrl+C` 停止 dev server；创建目录与记录文件：

```powershell
New-Item -ItemType Directory -Force -Path "docs\test-records" | Out-Null
```

创建 `docs/test-records/2026-09-09-frontend-smoke.md`，内容为：

```markdown
# 2026-09-09 前端基础页面冒烟记录

结果：通过
检查项：五个页面路由切换正常；页面标题与子标题正确；Dashboard 图表渲染 7 根柱；各页骨架元素可见。
```

然后：

```bash
git add .
git commit -m "test(frontend): 基础页面整体冒烟通过"
```
