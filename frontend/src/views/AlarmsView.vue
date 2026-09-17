<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Download, Refresh, Search } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { api } from '../api'
import { useRealtime } from '../composables/useRealtime'

const { realtime } = useRealtime()
const rows = ref([])
const loading = ref(false)
const statusTab = ref('unhandled')
const keyword = ref('')
const activeGroups = ref(['critical', 'warning'])
const pageCritical = ref(1)
const pageWarning = ref(1)
const PAGE_SIZE = 8
const detail = ref(null)
const detailVisible = ref(false)
const busyKey = ref('')

let typeChart = null
let trendChart = null

const filtered = computed(() => {
  const key = keyword.value.trim().toLowerCase()
  return rows.value.filter((row) => {
    const statusOk = statusTab.value === 'all' || row.status === statusTab.value
    const keyOk = !key || (row.camera_name || '').toLowerCase().includes(key)
    return statusOk && keyOk
  })
})

const criticalRows = computed(() => filtered.value.filter((r) => r.level === 'critical'))
const warningRows = computed(() => filtered.value.filter((r) => r.level === 'warning'))

function slice(list, pageRef) {
  const maxPage = Math.max(1, Math.ceil(list.length / PAGE_SIZE))
  if (pageRef.value > maxPage) pageRef.value = maxPage
  const start = (pageRef.value - 1) * PAGE_SIZE
  return list.slice(start, start + PAGE_SIZE)
}

const pagedCritical = computed(() => slice(criticalRows.value, pageCritical))
const pagedWarning = computed(() => slice(warningRows.value, pageWarning))

const metrics = computed(() => {
  const today = new Date().toISOString().slice(0, 10)
  return [
    { label: '今日告警', value: rows.value.filter((r) => (r.created_at || '').startsWith(today)).length, tone: '#1f4d78' },
    { label: '严重告警', value: rows.value.filter((r) => r.level === 'critical').length, tone: '#e5484d' },
    { label: '待处理', value: rows.value.filter((r) => r.status === 'unhandled').length, tone: '#e6a23c' },
    { label: '已处理', value: rows.value.filter((r) => r.status === 'handled').length, tone: '#23a06b' }
  ]
})

const counts = computed(() => ({
  all: rows.value.length,
  unhandled: rows.value.filter((r) => r.status === 'unhandled').length,
  handled: rows.value.filter((r) => r.status === 'handled').length
}))

async function load(showError = true) {
  loading.value = true
  try {
    rows.value = await api.alarms(500)
  } catch (error) {
    if (showError) ElMessage.error(`加载告警失败：${error.message}`)
  } finally {
    loading.value = false
  }
}

async function ack(row) {
  busyKey.value = `one-${row.id}`
  try {
    await ElMessageBox.confirm(`确认处理告警 #${row.id}（${row.camera_name}）？`, '确认处理', { type: 'warning' })
    await api.ackAlarm(row.id)
    ElMessage.success('已确认处理')
    detailVisible.value = false
    await load(false)
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(`操作失败：${error.message}`)
  } finally {
    busyKey.value = ''
  }
}

async function ackGroup(level) {
  const targets = (level === 'critical' ? criticalRows.value : warningRows.value).filter((r) => r.status === 'unhandled')
  if (targets.length === 0) {
    ElMessage.warning('该分组下没有待处理的告警')
    return
  }
  busyKey.value = `group-${level}`
  try {
    await ElMessageBox.confirm(`确认批量处理 ${targets.length} 条告警？`, '批量处理', { type: 'warning' })
    await Promise.all(targets.map((r) => api.ackAlarm(r.id)))
    ElMessage.success(`已处理 ${targets.length} 条告警`)
    await load(false)
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(`批量处理失败：${error.message}`)
  } finally {
    busyKey.value = ''
  }
}

function openDetail(row) {
  detail.value = row
  detailVisible.value = true
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
  const countsByDay = []
  for (let i = 6; i >= 0; i -= 1) {
    const date = new Date()
    date.setDate(date.getDate() - i)
    const key = date.toISOString().slice(0, 10)
    days.push(`${date.getMonth() + 1}/${date.getDate()}`)
    countsByDay.push(rows.value.filter((r) => (r.created_at || '').startsWith(key)).length)
  }
  trendChart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 32, right: 12, top: 20, bottom: 24 },
    xAxis: { type: 'category', data: days },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{ type: 'line', smooth: true, areaStyle: {}, data: countsByDay, itemStyle: { color: '#1f4d78' } }]
  })
}

const onResize = () => {
  typeChart && typeChart.resize()
  trendChart && trendChart.resize()
}

watch(rows, () => nextTick(renderCharts))
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
          <template #header>
            <div class="head">
              <el-radio-group v-model="statusTab" size="default">
                <el-radio-button value="unhandled">待处理（{{ counts.unhandled }}）</el-radio-button>
                <el-radio-button value="handled">已处理（{{ counts.handled }}）</el-radio-button>
                <el-radio-button value="all">全部（{{ counts.all }}）</el-radio-button>
              </el-radio-group>
              <el-input
                v-model="keyword"
                placeholder="按视频源搜索"
                clearable
                style="width: 180px"
                :prefix-icon="Search"
              />
              <el-button :icon="Refresh" @click="load()">刷新</el-button>
              <el-button :icon="Download" @click="exportCsv">导出</el-button>
            </div>
          </template>

          <el-collapse v-model="activeGroups">
            <el-collapse-item name="critical">
              <template #title>
                <div class="group-title">
                  <span class="dot critical" />
                  <b>严重告警（明火）</b>
                  <el-tag type="danger" size="small" effect="plain">{{ criticalRows.length }} 条</el-tag>
                  <el-button
                    size="small"
                    type="danger"
                    plain
                    :icon="Check"
                    :loading="busyKey === 'group-critical'"
                    @click.stop="ackGroup('critical')"
                  >
                    全部确认
                  </el-button>
                </div>
              </template>
              <el-table v-loading="loading" :data="pagedCritical" size="small" empty-text="暂无严重告警">
                <el-table-column prop="created_at" label="时间" width="170" />
                <el-table-column prop="camera_name" label="视频源" min-width="140" show-overflow-tooltip />
                <el-table-column label="置信度" width="180">
                  <template #default="{ row }">
                    <el-progress :percentage="Math.round((row.confidence || 0) * 100)" :stroke-width="8" color="#e5484d" />
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="150" fixed="right">
                  <template #default="{ row }">
                    <el-button size="small" text @click="openDetail(row)">详情</el-button>
                    <el-button
                      v-if="row.status === 'unhandled'"
                      size="small"
                      type="primary"
                      :loading="busyKey === `one-${row.id}`"
                      @click="ack(row)"
                    >
                      确认
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
              <div class="pager">
                <el-pagination
                  v-model:current-page="pageCritical"
                  :page-size="PAGE_SIZE"
                  :total="criticalRows.length"
                  layout="total, prev, pager, next"
                  small
                  background
                />
              </div>
            </el-collapse-item>

            <el-collapse-item name="warning">
              <template #title>
                <div class="group-title">
                  <span class="dot warning" />
                  <b>预警（烟雾）</b>
                  <el-tag type="warning" size="small" effect="plain">{{ warningRows.length }} 条</el-tag>
                  <el-button
                    size="small"
                    type="warning"
                    plain
                    :icon="Check"
                    :loading="busyKey === 'group-warning'"
                    @click.stop="ackGroup('warning')"
                  >
                    全部确认
                  </el-button>
                </div>
              </template>
              <el-table v-loading="loading" :data="pagedWarning" size="small" empty-text="暂无预警记录">
                <el-table-column prop="created_at" label="时间" width="170" />
                <el-table-column prop="camera_name" label="视频源" min-width="140" show-overflow-tooltip />
                <el-table-column label="置信度" width="180">
                  <template #default="{ row }">
                    <el-progress :percentage="Math.round((row.confidence || 0) * 100)" :stroke-width="8" color="#e6a23c" />
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="150" fixed="right">
                  <template #default="{ row }">
                    <el-button size="small" text @click="openDetail(row)">详情</el-button>
                    <el-button
                      v-if="row.status === 'unhandled'"
                      size="small"
                      type="primary"
                      :loading="busyKey === `one-${row.id}`"
                      @click="ack(row)"
                    >
                      确认
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
              <div class="pager">
                <el-pagination
                  v-model:current-page="pageWarning"
                  :page-size="PAGE_SIZE"
                  :total="warningRows.length"
                  layout="total, prev, pager, next"
                  small
                  background
                />
              </div>
            </el-collapse-item>
          </el-collapse>
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
      </el-col>
    </el-row>

    <el-drawer v-model="detailVisible" title="告警详情" size="400px">
      <el-descriptions v-if="detail" :column="1" border>
        <el-descriptions-item label="告警编号">{{ detail.id }}</el-descriptions-item>
        <el-descriptions-item label="发生时间">{{ detail.created_at }}</el-descriptions-item>
        <el-descriptions-item label="视频源">{{ detail.camera_name }}</el-descriptions-item>
        <el-descriptions-item label="告警类型">{{ detail.alarm_type === 'fire' ? '明火' : '烟雾' }}</el-descriptions-item>
        <el-descriptions-item label="告警级别">{{ detail.level === 'critical' ? '严重（红色）' : '预警（黄色）' }}</el-descriptions-item>
        <el-descriptions-item label="置信度">{{ ((detail.confidence || 0) * 100).toFixed(1) }}%</el-descriptions-item>
        <el-descriptions-item label="处理状态">{{ detail.status === 'handled' ? '已处理' : '待处理' }}</el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button
          v-if="detail && detail.status === 'unhandled'"
          type="primary"
          :loading="busyKey === `one-${detail.id}`"
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
.head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.head .el-input { margin-left: auto; }
.group-title { display: flex; align-items: center; gap: 10px; }
.group-title b { font-size: 14px; color: #1f2937; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.dot.critical { background: #e5484d; }
.dot.warning { background: #e6a23c; }
.pager { display: flex; justify-content: flex-end; margin-top: 8px; }
.chart-card { margin-bottom: 16px; }
</style>
