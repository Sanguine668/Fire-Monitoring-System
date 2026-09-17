<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Refresh } from '@element-plus/icons-vue'
import { api } from '../api'
import { useRealtime } from '../composables/useRealtime'

const { realtime } = useRealtime()
const rows = ref([])
const loading = ref(false)
const typeFilter = ref('')
const statusFilter = ref('')

const filtered = computed(() => rows.value.filter((row) => {
  const typeOk = !typeFilter.value || row.alarm_type === typeFilter.value
  const statusOk = !statusFilter.value || row.status === statusFilter.value
  return typeOk && statusOk
}))

async function load() {
  loading.value = true
  try {
    rows.value = await api.alarms(200)
  } catch (error) {
    ElMessage.error(`加载告警失败：${error.message}`)
  } finally {
    loading.value = false
  }
}

async function ack(row) {
  try {
    await ElMessageBox.confirm(`确认处理告警 #${row.id}（${row.camera_name}）？`, '确认处理', { type: 'warning' })
    await api.ackAlarm(row.id)
    ElMessage.success('已确认处理')
    await load()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(`操作失败：${error.message}`)
  }
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

watch(() => realtime.lastAlarm, (alarm) => {
  if (alarm) load()
})

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <div class="toolbar">
      <el-select v-model="typeFilter" placeholder="全部类型" clearable style="width: 140px">
        <el-option label="明火" value="fire" />
        <el-option label="烟雾" value="smoke" />
      </el-select>
      <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 140px">
        <el-option label="待处理" value="unhandled" />
        <el-option label="已处理" value="handled" />
      </el-select>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
      <el-button :icon="Download" @click="exportCsv">导出 CSV</el-button>
      <span class="count">共 {{ filtered.length }} 条</span>
    </div>

    <el-table v-loading="loading" :data="filtered" stripe empty-text="暂无告警记录">
      <el-table-column prop="created_at" label="时间" width="180" />
      <el-table-column prop="camera_name" label="视频源" width="160" />
      <el-table-column label="类型" width="100">
        <template #default="{ row }">
          <el-tag :type="row.alarm_type === 'fire' ? 'danger' : 'warning'">
            {{ row.alarm_type === 'fire' ? '明火' : '烟雾' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="级别" width="100">
        <template #default="{ row }">
          <el-tag :type="row.level === 'critical' ? 'danger' : 'warning'" effect="plain">
            {{ row.level === 'critical' ? '严重' : '预警' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="置信度" width="110">
        <template #default="{ row }">{{ (row.confidence * 100).toFixed(1) }}%</template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="row.status === 'handled' ? 'success' : 'info'" effect="plain">
            {{ row.status === 'handled' ? '已处理' : '待处理' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button v-if="row.status === 'unhandled'" size="small" type="primary" @click="ack(row)">确认处理</el-button>
          <span v-else>—</span>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.count { color: #7b8494; margin-left: auto; font-size: 13px; }
</style>
