<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { api } from '../api'
import { useRealtime } from '../composables/useRealtime'

const { realtime } = useRealtime()
const loading = ref(false)
const dashboard = ref({ camera_count: 0, online_count: 0, today_alarms: 0, unhandled: 0, recent: [] })
const alarmList = ref([])

const metrics = computed(() => [
  { label: '监控点位', value: dashboard.value.camera_count ?? 0, unit: '路' },
  { label: '在线视频源', value: dashboard.value.online_count ?? 0, unit: '路' },
  { label: '今日告警', value: dashboard.value.today_alarms ?? 0, unit: '条' },
  { label: '待处理', value: dashboard.value.unhandled ?? 0, unit: '条' }
])

const trend = computed(() => {
  const days = []
  const counts = []
  for (let i = 6; i >= 0; i -= 1) {
    const date = new Date()
    date.setDate(date.getDate() - i)
    const key = date.toISOString().slice(0, 10)
    days.push(`${date.getMonth() + 1}/${date.getDate()}`)
    counts.push(alarmList.value.filter((item) => (item.created_at || '').startsWith(key)).length)
  }
  return { days, counts }
})

let chart = null

function renderChart() {
  if (!chart) chart = echarts.init(document.getElementById('trendChart'))
  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 20, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: trend.value.days },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{
      name: '告警数',
      type: 'bar',
      barWidth: 28,
      data: trend.value.counts,
      itemStyle: { color: '#e5484d', borderRadius: [4, 4, 0, 0] }
    }]
  })
}

async function load() {
  loading.value = true
  try {
    const [dash, alarms] = await Promise.all([api.dashboard(), api.alarms(200)])
    dashboard.value = dash
    alarmList.value = alarms
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
.metric span { color: #7b8494; }
.metric strong { display: block; font-size: 26px; margin-top: 6px; }
.metric small { font-size: 13px; color: #9aa2b0; margin-left: 4px; font-weight: 400; }
.second-row { margin-top: 16px; }
.recent-item { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px dashed #eceff3; }
.recent-item .camera { flex: 1; color: #374151; }
.recent-item .time { color: #9aa2b0; font-size: 12px; }
.empty { color: #9aa2b0; padding: 12px 0; }
</style>
