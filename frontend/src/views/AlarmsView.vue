<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Refresh, Search } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { api } from '../api'
import { useRealtime } from '../composables/useRealtime'

const { realtime } = useRealtime()
const rows = ref([])
const loading = ref(false)
const typeFilter = ref('')
const levelFilter = ref('')
const statusFilter = ref('')
const keyword = ref('')
const page = ref(1)
const pageSize = ref(10)
const selection = ref([])
const detail = ref(null)
const detailVisible = ref(false)
const busyId = ref(null)

let typeChart = null
let trendChart = null

const filtered = computed(() => {
  const key = keyword.value.trim().toLowerCase()
  return rows.value.filter((row) => {
    const typeOk = !typeFilter.value || row.alarm_type === typeFilter.value
    const levelOk = !levelFilter.value || row.level === levelFilter.value
    const statusOk = !statusFilter.value || row.status === statusFilter.value
    const keyOk = !key || (row.camera_name || '').toLowerCase().includes(key)
    return typeOk && levelOk && statusOk && keyOk
  })
})

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filtered.value.slice(start, start + pageSize.value)
})

const metrics = computed(() => {
  const today = new Date().toISOString().slice(0, 10)
  const list = rows.value
  return [
    { label: '今日告警', value: list.filter((r) => (r.created_at || '').startsWith(today)).length, tone: '#1f4d78' },
    { label: '严重告警', value: list.filter((r) => r.level === 'critical').length, tone: '#e5484d' },
    { label: '待处理', value: list.filter((r) => r.status === 'unhandled').length, tone: '#e6a23c' },
    { label: '已处理', value: list.filter((r) => r.status === 'handled').length, tone: '#23a06b' }
  ]
})

async function load(showError = true) {
  loading.value = true
  try {
    rows.value = await api.alarms(500)
    if ((page.value - 1) * pageSize.value >= filtered.value.length) page.value = 1
  } catch (error) {
    if (showError) ElMessage.error(`加载告警失败：${error.message}`)
  } finally {
    loading.value = false
  }
}

async function ack(row) {
  busyId.value = row.id
  try {
    await ElMessageBox.confirm(`确认处理告警 #${row.id}（${row.camera_name}）？`, '确认处理', { type: 'warning' })
    await api.ackAlarm(row.id)
    ElMessage.success('已确认处理')
    detailVisible.value = false
    await load(false)
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(`操作失败：${error.message}`)
  } finally {
    busyId.value = null
  }
}

async function ackSelected() {
  const targets = selection.value.filter((r) => r.status === 'unhandled')
  if (targets.length === 0) {
    ElMessage.warning('请先勾选待处理的告警')
    return
  }
  try {
    await ElMessageBox.confirm(`确认批量处理 ${targets.length} 条告警？`, '批量处理', { type: 'warning' })
    await Promise.all(targets.map((r) => api.ackAlarm(r.id)))
    ElMessage.success(`已处理 ${targets.length} 条告警`)
    await load(false)
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(`批量处理失败：${error.message}`)
  }
}

function openDetail(row) {
  detail.value = row
  detailVisible.value = true
}

function resetFilters() {
  typeFilter.value = ''
  levelFilter.value = ''
  statusFilter.value = ''
  keyword.value = ''
  page.value = 1
}

function exportCsv() {
  if (filtered.value.length === 0) {
    ElMessage.warning('当前没有可导出的告警记录')
    return
  }
  const header = ['ID', '时间', '视频源', '类型', '级别', '置信度', '状态']
  const lines = filtered.value.map((r) =>
    [
      r.id,
      r.created_at,
      r.camera_name,
      r.alarm_type === 'fire' ? '明火' : '烟雾',
      r.level === 'critical' ? '严重' : '预警',
      ((r.confidence || 0) * 100).toFixed(1) + '%',
      r.status === 'handled' ? '已处理' : '待处理'
    ].join(',')
  )
  const csv = '\uFEFF' + [header.join(','), ...lines].join('\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `告警记录_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
  ElMessage.success(`已导出 ${filtered.value.length} 条记录`)
}

function renderCharts() {
  const typeBox = document.getElementById('alarmTypeChart')
  const trendBox = document.getElementById('alarmTrendChart')
  if (!typeBox || !trendBox) return
  if (!typeChart) typeChart = echarts.init(typeBox)
  if (!trendChart) trendChart = echarts.init(trendBox)

  const fire = rows.value.filter((r) => r.alarm_type === 'fire').length
  const smoke = rows.value.filter((r) => r.alarm_type === 'smoke').length
  typeChart.setOption({
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [{
      type: 'pie',
      radius: ['45%', '68%'],
      center: ['50%', '45%'],
      label: { formatter: '{b}\n{c}' },
      data: [
        { name: '明火', value: fire, itemStyle: { color: '#e5484d' } },
        { name: '烟雾', value: smoke, itemStyle: { color: '#e6a23c' } }
      ]
    }]
  })

  const days = []
  const counts = []
  for (let i = 6; i >= 0; i -= 1) {
    const date = new Date()
    date.setDate(date.getDate() - i)
    const key = date.toISOString().slice(0, 10)
    days.push(`${date.getMonth() + 1}/${date.getDate()}`)
    counts.push(rows.value.filter((r) => (r.created_at || '').startsWith(key)).length)
  }
  trendChart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 32, right: 12, top: 20, bottom: 24 },
    xAxis: { type: 'category', data: days },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{ type: 'line', smooth: true, areaStyle: {}, data: counts, itemStyle: { color: '#1f4d78' } }]
  })
}

const onResize = () => {
  typeChart && typeChart.resize()
  trendChart && trendChart.resize()
}

watch([rows, filtered], () => {
  nextTick(renderCharts)
}, { deep: false })

watch(
  () => realtime.lastAlarm,
  (alarm) => {
    if (alarm) load(false)
  }
)

onMounted(async () => {
  await load()
  await nextTick()
  renderCharts()
  window.addEventListener('resize', onResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  typeChart && typeChart.dispose()
  trendChart && trendChart.dispose()
})
</script>

<template>
  <div>
    <el-row :gutter="16" class="metrics">
      <el-col v-for="m in metrics" :key="m.label" :span="6">
        <el-card shadow="never" :body-style="{ padding: '14px 16px' }">
          <div class="metric">
            <span>{{ m.label }}</span>
            <strong :style="{ color: m.tone }">{{ m.value }}</strong>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :span="16">
        <el-card shadow="never">
          <div class="toolbar">
            <el-select v-model="typeFilter" placeholder="全部类型" clearable style="width: 120px">
              <el-option label="明火" value="fire" />
              <el-option label="烟雾" value="smoke" />
            </el-select>
            <el-select v-model="levelFilter" placeholder="全部级别" clearable style="width: 120px">
              <el-option label="严重" value="critical" />
              <el-option label="预警" value="warning" />
            </el-select>
            <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 120px">
              <el-option label="待处理" value="unhandled" />
              <el-option label="已处理" value="handled" />
            </el-select>
            <el-input v-model="keyword" placeholder="视频源" clearable style="width: 140px" :prefix-icon="Search" />
            <el-button text @click="resetFilters">重置</el-button>
            <span class="spacer" />
            <el-button :icon="Refresh" @click="load()">刷新</el-button>
            <el-button :icon="Download" @click="exportCsv">导出</el-button>
            <el-button type="primary" :disabled="selection.length === 0" @click="ackSelected">
              批量处理（{{ selection.length }}）
            </el-button>
          </div>

          <el-table
            v-loading="loading"
            :data="paged"
            stripe
            height="520"
            empty-text="暂无告警记录"
            @selection-change="selection = $event"
          >
            <el-table-column type="selection" width="44" />
            <el-table-column prop="created_at" label="时间" width="170" />
            <el-table-column label="类型" width="86">
              <template #default="{ row }">
                <el-tag :type="row.alarm_type === 'fire' ? 'danger' : 'warning'" size="small">
                  {{ row.alarm_type === 'fire' ? '明火' : '烟雾' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="camera_name" label="视频源" min-width="130" show-overflow-tooltip />
            <el-table-column label="置信度" width="150">
              <template #default="{ row }">
                <el-progress
                  :percentage="Math.round((row.confidence || 0) * 100)"
                  :stroke-width="8"
                  :color="row.alarm_type === 'fire' ? '#e5484d' : '#e6a23c'"
                />
              </template>
            </el-table-column>
            <el-table-column label="级别" width="86">
              <template #default="{ row }">
                <el-tag :type="row.level === 'critical' ? 'danger' : 'warning'" effect="plain" size="small">
                  {{ row.level === 'critical' ? '严重' : '预警' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="86">
              <template #default="{ row }">
                <el-tag :type="row.status === 'handled' ? 'success' : 'info'" effect="plain" size="small">
                  {{ row.status === 'handled' ? '已处理' : '待处理' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button size="small" text @click="openDetail(row)">详情</el-button>
                <el-button
                  v-if="row.status === 'unhandled'"
                  size="small"
                  type="primary"
                  :loading="busyId === row.id"
                  @click="ack(row)"
                >
                  确认
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="pager">
            <el-pagination
              v-model:current-page="page"
              v-model:page-size="pageSize"
              :page-sizes="[10, 20, 50]"
              :total="filtered.length"
              layout="total, sizes, prev, pager, next, jumper"
              background
            />
          </div>
        </el-card>
      </el-col>

      <el-col :span="8">
        <el-card shadow="never" class="chart-card">
          <template #header>告警类型分布</template>
          <div id="alarmTypeChart" style="height: 220px" />
        </el-card>
        <el-card shadow="never" class="chart-card">
          <template #header>近 7 天告警趋势</template>
          <div id="alarmTrendChart" style="height: 220px" />
        </el-card>
        <el-card shadow="never" class="chart-card">
          <template #header>快速筛选</template>
          <div class="quick">
            <el-button size="small" @click="typeFilter = 'fire'">只看明火</el-button>
            <el-button size="small" @click="typeFilter = 'smoke'">只看烟雾</el-button>
            <el-button size="small" @click="statusFilter = 'unhandled'">只看待处理</el-button>
            <el-button size="small" @click="levelFilter = 'critical'">只看严重</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-drawer v-model="detailVisible" title="告警详情" size="420px">
      <el-descriptions v-if="detail" :column="1" border>
        <el-descriptions-item label="告警编号">{{ detail.id }}</el-descriptions-item>
        <el-descriptions-item label="发生时间">{{ detail.created_at }}</el-descriptions-item>
        <el-descriptions-item label="视频源">{{ detail.camera_name }}</el-descriptions-item>
        <el-descriptions-item label="告警类型">{{ detail.alarm_type === 'fire' ? '明火' : '烟雾' }}</el-descriptions-item>
        <el-descriptions-item label="告警级别">{{ detail.level === 'critical' ? '严重（红色）' : '预警（黄色）' }}</el-descriptions-item>
        <el-descriptions-item label="置信度">
          {{ ((detail.confidence || 0) * 100).toFixed(1) }}%
        </el-descriptions-item>
        <el-descriptions-item label="处理状态">{{ detail.status === 'handled' ? '已处理' : '待处理' }}</el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button
          v-if="detail && detail.status === 'unhandled'"
          type="primary"
          :loading="busyId === detail.id"
          @click="ack(detail)"
        >
          确认处理
        </el-button>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.metrics { margin-bottom: 16px; }
.metric { display: flex; justify-content: space-between; align-items: center; }
.metric span { color: #7b8494; font-size: 13px; }
.metric strong { font-size: 24px; }
.toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.spacer { flex: 1; }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }
.chart-card { margin-bottom: 16px; }
.quick { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
