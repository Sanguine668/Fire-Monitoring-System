<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Delete, Download, Refresh, Search } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { alarmFrameUrl, api } from '../api'
import { chartFont } from '../utils/chartFont'
import { useRealtime } from '../composables/useRealtime'

const { realtime, markAllSeen, markHandled, syncAlarms, clearSessionAlarms } = useRealtime()
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
const frameVariant = ref('first')
const frameError = ref(false)
const detailBoxes = ref([])

let typeChart = null
let trendChart = null

const filteredRows = computed(() => {
  const key = keyword.value.trim().toLowerCase()
  return rows.value.filter((row) => {
    const statusOk = statusTab.value === 'all' || row.status === statusTab.value
    const keyOk = !key || (row.camera_name || '').toLowerCase().includes(key)
    return statusOk && keyOk
  })
})

/**
 * 未处理的告警按"视频源 + 告警类型"合并为一条：
 * 同一路视频源、同一位置的同类预警未处理时只显示最新一条，并记录累计次数与时间范围。
 */
const displayRows = computed(() => {
  if (statusTab.value !== 'unhandled') {
    return filteredRows.value.map((row) => ({
      ...row,
      count: 1,
      firstAt: row.created_at,
      latestAt: row.created_at,
      firstSnapshotId: row.snapshot_first ? row.id : null
    }))
  }
  const groups = new Map()
  for (const row of filteredRows.value) {
    const key = `${row.camera_id}:${row.alarm_type}`
    const exist = groups.get(key)
    if (!exist) {
      groups.set(key, {
        ...row,
        count: row.count || 1,
        firstAt: row.created_at,
        latestAt: row.created_at,
        maxConfidence: row.confidence,
        verified: Boolean(row.verified),
        firstSnapshotId: row.snapshot_first ? row.id : null
      })
      continue
    }
    exist.count += row.count || 1
    exist.verified = Boolean(exist.verified || row.verified)
    if ((row.created_at || '') > (exist.latestAt || '')) {
      exist.latestAt = row.created_at
      exist.id = row.id
      exist.confidence = row.confidence
      exist.camera_name = row.camera_name
      exist.snapshot_latest = row.snapshot_latest
    }
    if ((row.created_at || '') < (exist.firstAt || '')) exist.firstAt = row.created_at
    exist.maxConfidence = Math.max(exist.maxConfidence || 0, row.confidence || 0)
  }
  return [...groups.values()].sort((a, b) => (b.latestAt || '').localeCompare(a.latestAt || ''))
})

const criticalRows = computed(() => displayRows.value.filter((r) => r.level === 'critical'))
const warningRows = computed(() => displayRows.value.filter((r) => r.level === 'warning'))

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
  const unhandledGroups = new Set(
    rows.value.filter((r) => r.status === 'unhandled').map((r) => `${r.camera_id}:${r.alarm_type}`)
  )
  return [
    { label: '今日告警', value: rows.value.filter((r) => (r.created_at || '').startsWith(today)).length, tone: '#1f4d78' },
    { label: '严重告警', value: rows.value.filter((r) => r.level === 'critical').length, tone: '#e5484d' },
    { label: '待处理事件（已合并）', value: unhandledGroups.size, tone: '#e6a23c' },
    { label: '已处理', value: rows.value.filter((r) => r.status === 'handled').length, tone: '#23a06b' }
  ]
})

const counts = computed(() => {
  const unhandledGroups = new Set(
    rows.value.filter((r) => r.status === 'unhandled').map((r) => `${r.camera_id}:${r.alarm_type}`)
  )
  return {
    unhandled: unhandledGroups.size,
    handled: rows.value.filter((r) => r.status === 'handled').length,
    all: rows.value.length
  }
})

async function load(showError = true) {
  loading.value = true
  try {
    rows.value = await api.alarms(500)
    syncAlarms(rows.value)
    markAllSeen()
  } catch (error) {
    if (showError) ElMessage.error(`加载告警失败：${error.message}`)
  } finally {
    loading.value = false
  }
}

async function clearAll() {
  try {
    await ElMessageBox.confirm('确定清空全部告警记录？该操作不可恢复。', '清空告警', { type: 'warning' })
    const result = await api.clearAlarms()
    clearSessionAlarms()
    ElMessage.success(`已清空 ${result.deleted ?? 0} 条告警`)
    await load(false)
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(`清空失败：${error.message || error}`)
  }
}

async function ack(row) {
  busyKey.value = `one-${row.camera_id}-${row.alarm_type}`
  try {
    await ElMessageBox.confirm(
      row.count > 1
        ? `该视频源「${row.camera_name}」的${row.alarm_type === 'fire' ? '明火' : '烟雾'}告警共 ${row.count} 次，确认全部处理？`
        : `确认处理告警 #${row.id}（${row.camera_name}）？`,
      '确认处理',
      { type: 'warning' }
    )
    if (row.count > 1 || statusTab.value === 'unhandled') {
      await api.ackAlarmGroup({ camera_id: row.camera_id, alarm_type: row.alarm_type })
      markHandled({ camera_id: row.camera_id, alarm_type: row.alarm_type })
    } else {
      await api.ackAlarm(row.id)
      markHandled({ id: row.id })
    }
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
  const total = targets.reduce((sum, r) => sum + (r.count || 1), 0)
  busyKey.value = `group-${level}`
  try {
    await ElMessageBox.confirm(`该分组共 ${total} 条告警（合并后 ${targets.length} 个事件），确认全部处理？`, '批量处理', { type: 'warning' })
    await Promise.all(targets.map((r) => api.ackAlarmGroup({ camera_id: r.camera_id, alarm_type: r.alarm_type })))
    targets.forEach((row) => markHandled({ camera_id: row.camera_id, alarm_type: row.alarm_type }))
    ElMessage.success(`已处理 ${total} 条告警`)
    await load(false)
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(`批量处理失败：${error.message}`)
  } finally {
    busyKey.value = ''
  }
}

async function openDetail(row) {
  detail.value = row
  detailBoxes.value = []
  frameVariant.value = 'first'
  frameError.value = false
  detailVisible.value = true
  try {
    const data = await api.alarmDetail(row.id)
    detailBoxes.value = Array.isArray(data.boxes) ? data.boxes : []
  } catch {
    detailBoxes.value = []
  }
}

const firstFrameId = computed(() => detail.value?.firstSnapshotId || null)
const latestFrameId = computed(() => detail.value?.id || null)
const currentFrameId = computed(() =>
  frameVariant.value === 'first' ? firstFrameId.value : latestFrameId.value
)
const frameUrl = computed(() =>
  currentFrameId.value && !frameError.value ? alarmFrameUrl(currentFrameId.value, frameVariant.value) : ''
)
const hasAnyFrame = computed(() => Boolean(firstFrameId.value || detail.value?.snapshot_latest))

function switchVariant(value) {
  frameVariant.value = value
  frameError.value = false
}

function exportCsv() {
  if (displayRows.value.length === 0) {
    ElMessage.warning('当前没有可导出的告警记录')
    return
  }
  const header = ['时间(最新)', '视频源', '类型', '级别', '置信度', '累计次数', '首次出现', '状态']
  const lines = displayRows.value.map((r) =>
    [
      r.latestAt || r.created_at,
      r.camera_name,
      r.alarm_type === 'fire' ? '明火' : '烟雾',
      r.level === 'critical' ? '严重' : '预警',
      ((r.maxConfidence || r.confidence || 0) * 100).toFixed(1) + '%',
      r.count || 1,
      r.firstAt || r.created_at,
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
  ElMessage.success(`已导出 ${displayRows.value.length} 条记录`)
}

function renderCharts() {
  const typeBox = document.getElementById('alarmTypeChart')
  const trendBox = document.getElementById('alarmTrendChart')
  if (!typeBox || !trendBox) return
  if (!typeChart) typeChart = echarts.init(typeBox)
  if (!trendChart) trendChart = echarts.init(trendBox)

  const fire = rows.value.filter((r) => r.alarm_type === 'fire').length
  const smoke = rows.value.filter((r) => r.alarm_type === 'smoke').length
  const font = chartFont()
  typeChart.setOption({
    tooltip: { trigger: 'item' },
    textStyle: { fontSize: font },
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
    textStyle: { fontSize: font },
    grid: { left: Math.round(font * 2.4), right: 12, top: 20, bottom: Math.round(font * 1.7) },
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
    if (alarm) {
      markAllSeen()
      load(false)
    }
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
    <el-alert
      v-if="statusTab === 'unhandled'"
      type="info"
      :closable="false"
      class="tip"
      title="未处理的同类告警已按视频源合并为一条，处理后会从该列表移除。"
    />

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
      <el-col :span="17">
        <el-card shadow="never">
          <template #header>
            <div class="head">
              <el-radio-group v-model="statusTab" size="default">
                <el-radio-button value="unhandled">待处理（{{ counts.unhandled }}）</el-radio-button>
                <el-radio-button value="handled">已处理（{{ counts.handled }}）</el-radio-button>
                <el-radio-button value="all">全部（{{ counts.all }}）</el-radio-button>
              </el-radio-group>
              <el-input v-model="keyword" placeholder="按视频源搜索" clearable style="width: 220px" :prefix-icon="Search" />
              <el-button :icon="Refresh" @click="load()">刷新</el-button>
              <el-button :icon="Download" @click="exportCsv">导出</el-button>
              <el-button :icon="Delete" plain type="danger" @click="clearAll">清空</el-button>
            </div>
          </template>

          <el-collapse v-model="activeGroups">
            <el-collapse-item name="critical">
              <template #title>
                <div class="group-title">
                  <span class="dot critical" />
                  <b>严重告警（明火）</b>
                  <el-tag type="danger" size="small" effect="plain">{{ criticalRows.length }} 个事件</el-tag>
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
                <el-table-column label="最近出现" width="170">
                  <template #default="{ row }">{{ row.latestAt || row.created_at }}</template>
                </el-table-column>
                <el-table-column label="画面" width="96">
                  <template #default="{ row }">
                    <el-image
                      v-if="row.snapshot_latest"
                      :src="alarmFrameUrl(row.id, 'latest')"
                      fit="cover"
                      class="thumb"
                      :preview-src-list="[alarmFrameUrl(row.id, 'latest')]"
                      preview-teleported
                    />
                    <span v-else class="muted">—</span>
                  </template>
                </el-table-column>
                <el-table-column prop="camera_name" label="视频源" min-width="156" show-overflow-tooltip />
                <el-table-column label="累计次数" width="92">
                  <template #default="{ row }">
                    <el-tag v-if="row.count > 1" type="danger" size="small" effect="plain">{{ row.count }} 次</el-tag>
                    <span v-else>1 次</span>
                  </template>
                </el-table-column>
                <el-table-column label="智能体" width="84">
                  <template #default="{ row }">
                    <el-tag v-if="row.verified" type="success" size="small" effect="plain">已复核</el-tag>
                    <span v-else class="muted">—</span>
                  </template>
                </el-table-column>
                <el-table-column label="最高置信度" width="140">
                  <template #default="{ row }">
                    <el-progress :percentage="Math.round((row.maxConfidence || row.confidence || 0) * 100)" :stroke-width="8" color="#e5484d" />
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="150" fixed="right">
                  <template #default="{ row }">
                    <el-button size="small" text @click="openDetail(row)">详情</el-button>
                    <el-button
                      v-if="row.status === 'unhandled'"
                      size="small"
                      type="primary"
                      :loading="busyKey === `one-${row.camera_id}-${row.alarm_type}`"
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
                  <el-tag type="warning" size="small" effect="plain">{{ warningRows.length }} 个事件</el-tag>
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
                <el-table-column label="最近出现" width="170">
                  <template #default="{ row }">{{ row.latestAt || row.created_at }}</template>
                </el-table-column>
                <el-table-column label="画面" width="96">
                  <template #default="{ row }">
                    <el-image
                      v-if="row.snapshot_latest"
                      :src="alarmFrameUrl(row.id, 'latest')"
                      fit="cover"
                      class="thumb"
                      :preview-src-list="[alarmFrameUrl(row.id, 'latest')]"
                      preview-teleported
                    />
                    <span v-else class="muted">—</span>
                  </template>
                </el-table-column>
                <el-table-column prop="camera_name" label="视频源" min-width="156" show-overflow-tooltip />
                <el-table-column label="累计次数" width="92">
                  <template #default="{ row }">
                    <el-tag v-if="row.count > 1" type="warning" size="small" effect="plain">{{ row.count }} 次</el-tag>
                    <span v-else>1 次</span>
                  </template>
                </el-table-column>
                <el-table-column label="智能体" width="84">
                  <template #default="{ row }">
                    <el-tag v-if="row.verified" type="success" size="small" effect="plain">已复核</el-tag>
                    <span v-else class="muted">—</span>
                  </template>
                </el-table-column>
                <el-table-column label="最高置信度" width="140">
                  <template #default="{ row }">
                    <el-progress :percentage="Math.round((row.maxConfidence || row.confidence || 0) * 100)" :stroke-width="8" color="#e6a23c" />
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="150" fixed="right">
                  <template #default="{ row }">
                    <el-button size="small" text @click="openDetail(row)">详情</el-button>
                    <el-button
                      v-if="row.status === 'unhandled'"
                      size="small"
                      type="primary"
                      :loading="busyKey === `one-${row.camera_id}-${row.alarm_type}`"
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

      <el-col :span="7">
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

    <el-drawer v-model="detailVisible" title="告警详情" size="560px">
      <div v-if="detail" class="frame-panel">
        <div class="frame-head">
          <el-radio-group :model-value="frameVariant" size="small" @update:model-value="switchVariant">
            <el-radio-button value="first" :disabled="!firstFrameId">触发帧</el-radio-button>
            <el-radio-button value="latest" :disabled="!latestFrameId">最近帧</el-radio-button>
          </el-radio-group>
          <span class="frame-time">{{ detail.latestAt || detail.created_at }}</span>
        </div>
        <img v-if="frameUrl" :src="frameUrl" class="frame-img" alt="告警画面" @error="frameError = true" />
        <div v-else class="frame-empty">
          {{ hasAnyFrame ? '画面读取失败（文件可能已被清理）' : '该告警产生于功能上线前，无画面留存' }}
        </div>
        <div v-if="detailBoxes.length" class="box-list">
          <div class="box-title">检测结果（{{ detailBoxes.length }}）</div>
          <div v-for="(item, index) in detailBoxes" :key="index" class="box-row">
            <el-tag :type="item.type === 'fire' ? 'danger' : 'warning'" size="small" effect="plain">
              {{ item.type === 'fire' ? '明火' : '烟雾' }}
            </el-tag>
            <span class="box-conf">{{ (item.confidence * 100).toFixed(1) }}%</span>
            <span class="box-coord">框 x{{ item.bbox[0] }} y{{ item.bbox[1] }} w{{ item.bbox[2] }} h{{ item.bbox[3] }}</span>
          </div>
        </div>
      </div>
      <el-descriptions v-if="detail" :column="1" border>
        <el-descriptions-item label="视频源">{{ detail.camera_name }}</el-descriptions-item>
        <el-descriptions-item label="告警类型">{{ detail.alarm_type === 'fire' ? '明火' : '烟雾' }}</el-descriptions-item>
        <el-descriptions-item label="告警级别">{{ detail.level === 'critical' ? '严重（红色）' : '预警（黄色）' }}</el-descriptions-item>
        <el-descriptions-item label="累计出现次数">{{ detail.count || 1 }} 次</el-descriptions-item>
        <el-descriptions-item label="首次出现">{{ detail.firstAt || detail.created_at }}</el-descriptions-item>
        <el-descriptions-item label="最近出现">{{ detail.latestAt || detail.created_at }}</el-descriptions-item>
        <el-descriptions-item label="最高置信度">
          {{ ((detail.maxConfidence || detail.confidence || 0) * 100).toFixed(1) }}%
        </el-descriptions-item>
        <el-descriptions-item label="处理状态">{{ detail.status === 'handled' ? '已处理' : '待处理' }}</el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button
          v-if="detail && detail.status === 'unhandled'"
          type="primary"
          :loading="busyKey === `one-${detail.camera_id}-${detail.alarm_type}`"
          @click="ack(detail)"
        >
          确认处理
        </el-button>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.muted { color: #c0c4cc; }
.tip { margin-bottom: 12px; }
.metrics { margin-bottom: 16px; }
.metric { display: flex; justify-content: space-between; align-items: center; }
.metric span { color: #7b8494; font-size: 0.9375rem; }
.metric strong { font-size: 1.5rem; }
.head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.head .el-input { margin-left: auto; }
.group-title { display: flex; align-items: center; gap: 10px; }
.group-title b { font-size: 1rem; color: #1f2937; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.dot.critical { background: #e5484d; }
.dot.warning { background: #e6a23c; }
.pager { display: flex; justify-content: flex-end; margin-top: 8px; }
.chart-card { margin-bottom: 16px; }
.thumb { width: 3.5rem; height: 2.25rem; border-radius: 4px; cursor: zoom-in; }
.frame-panel { margin-bottom: 1rem; }
.frame-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.5rem; }
.frame-time { color: #9aa2b0; font-size: 0.875rem; }
.frame-img { width: 100%; border-radius: 6px; background: #0f141c; display: block; }
.frame-empty {
  height: 8rem; display: flex; align-items: center; justify-content: center;
  background: #f3f5f8; color: #9aa2b0; border-radius: 6px; font-size: 0.875rem; text-align: center; padding: 0 1rem;
}
.box-list { margin-top: 0.75rem; }
.box-title { font-size: 0.875rem; color: #4b5563; margin-bottom: 0.375rem; }
.box-row { display: flex; align-items: center; gap: 0.5rem; padding: 0.25rem 0; font-size: 0.875rem; }
.box-conf { color: #1f2d3d; font-weight: 600; }
.box-coord { color: #9aa2b0; }
</style>
