<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { api } from '../api'
import { useRealtime } from '../composables/useRealtime'

const { realtime } = useRealtime()
const loading = ref(false)
const dashboard = ref({ camera_count: 0, online_count: 0, today_alarms: 0, unhandled: 0, recent: [] })
const model = ref({ classes: {} })
const settings = ref({})

const modelName = computed(() => {
  const names = Object.values(model.value.classes || {})
  return names.length ? names.join(' + ') : '加载中'
})

const metrics = computed(() => [
  { label: '监控点位', value: dashboard.value.camera_count ?? 0, unit: '路' },
  { label: '在线视频源', value: dashboard.value.online_count ?? 0, unit: '路' },
  { label: '今日告警', value: dashboard.value.today_alarms ?? 0, unit: '条' },
  { label: '待处理', value: dashboard.value.unhandled ?? 0, unit: '条' }
])

const trend = computed(() => {
  if (dashboard.value.trend?.length) return dashboard.value.trend
  return Array.from({ length: 7 }, (_, i) => {
    const date = new Date()
    date.setDate(date.getDate() - (6 - i))
    return { label: `${date.getMonth() + 1}/${date.getDate()}`, fire: 0, smoke: 0, total: 0 }
  })
})

let chart = null

function renderChart() {
  if (!chart) chart = echarts.init(document.getElementById('trendChart'))
  const data = trend.value
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { top: 0, data: ['明火', '烟雾', '总告警'] },
    grid: { left: 48, right: 20, top: 42, bottom: 30 },
    xAxis: { type: 'category', data: data.map((item) => item.label) },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      {
        name: '明火',
        type: 'bar',
        stack: 'alarm',
        barWidth: 22,
        data: data.map((item) => item.fire),
        itemStyle: { color: '#e5484d' }
      },
      {
        name: '烟雾',
        type: 'bar',
        stack: 'alarm',
        barWidth: 22,
        data: data.map((item) => item.smoke),
        itemStyle: { color: '#e6a23c', borderRadius: [4, 4, 0, 0] }
      },
      {
        name: '总告警',
        type: 'line',
        smooth: true,
        symbolSize: 7,
        data: data.map((item) => item.total),
        itemStyle: { color: '#1f4d78' },
        lineStyle: { width: 2 }
      }
    ]
  }, true)
}

async function load() {
  loading.value = true
  try {
    const [dash, modelInfo, currentSettings] = await Promise.all([
      api.dashboard(), api.modelInfo(), api.settings()
    ])
    dashboard.value = dash
    model.value = modelInfo
    settings.value = currentSettings
    renderChart()
  } catch (error) {
    ElMessage.error(`加载总览失败：${error.message}（请确认后端已启动）`)
  } finally {
    loading.value = false
  }
}

const onResize = () => chart && chart.resize()
onMounted(() => {
  load()
  window.addEventListener('resize', onResize)
  timer = setInterval(load, 15000)
})

let timer = null
watch(() => realtime.lastAlarm, (alarm) => {
  if (alarm) load()
})
onUnmounted(() => {
  clearInterval(timer)
  window.removeEventListener('resize', onResize)
  chart && chart.dispose()
})
</script>

<template>
  <div v-loading="loading" class="dashboard">
    <div class="toolbar">
      <el-button :icon="Refresh" @click="load">刷新</el-button>
      <el-tag size="small" type="info">模型 {{ modelName }}</el-tag>
      <el-tag size="small" :type="settings.tiling_enabled ? 'warning' : 'info'">
        远距离 {{ settings.tiling_enabled ? '开' : '关' }}
      </el-tag>
      <el-tag size="small" :type="settings.verify_enabled ? 'success' : 'info'">
        告警复核 {{ settings.verify_enabled ? '开' : '关' }}
      </el-tag>
      <span class="hint">数据每 15 秒自动刷新，收到新告警时立即刷新</span>
    </div>
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

    <el-row :gutter="16" class="second-row">
      <el-col :span="15">
        <el-card shadow="never">
          <template #header>近 7 天告警趋势</template>
          <div id="trendChart" style="height: 300px" />
        </el-card>
      </el-col>
      <el-col :span="9">
        <el-card shadow="never">
          <template #header>最近告警</template>
          <div v-if="(dashboard.recent || []).length === 0" class="empty">暂无告警记录</div>
          <div v-for="item in dashboard.recent" :key="item.id" class="recent-item">
            <el-tag :type="item.alarm_type === 'fire' ? 'danger' : 'warning'" size="small">
              {{ item.alarm_type === 'fire' ? '明火' : '烟雾' }}
            </el-tag>
            <span class="camera">{{ item.camera_name }}</span>
            <span class="time">{{ (item.created_at || '').slice(11) }}</span>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.dashboard { position: relative; min-height: 400px; }
.toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.hint { color: #9aa2b0; font-size: 12px; }
.metric span { color: #7b8494; }
.metric strong { display: block; font-size: 26px; margin-top: 6px; }
.metric small { font-size: 13px; color: #9aa2b0; margin-left: 4px; font-weight: 400; }
.second-row { margin-top: 16px; }
.recent-item { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px dashed #eceff3; }
.recent-item .camera { flex: 1; color: #374151; }
.recent-item .time { color: #9aa2b0; font-size: 12px; }
.empty { color: #9aa2b0; padding: 12px 0; }
</style>
