<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { useRealtime } from '../composables/useRealtime'

const router = useRouter()
const { realtime } = useRealtime()
const loading = ref(false)
const info = ref({ agents: [], metrics: {}, settings: {}, pipeline: [] })
const cameras = ref([])

const latest = computed(() => realtime.traces[0] || null)
const recent = computed(() => realtime.traces.slice(0, 12))
const metrics = computed(() => info.value.metrics || {})

const metricCards = computed(() => [
  { label: '官方 test mAP50', value: pct(metrics.value.map50), note: '验收线 ≥70%' },
  { label: '远景小目标召回', value: pct(metrics.value.farfield_recall), note: `旧模型 ${pct(metrics.value.farfield_old)}` },
  { label: '整图 → 切片召回', value: `${pct(metrics.value.tiling_plain)} → ${pct(metrics.value.tiling_tiled)}`, note: '每 2 秒低频扫描' },
  { label: 'SmokeFire 烟雾召回', value: pct(metrics.value.smokefire_smoke), note: '未参与训练的跨域集' },
  { label: '校准后 fire 误报', value: pct(metrics.value.calibrated_fire_fpr), note: '困难负样本，阈值 0.40' }
])

function pct(value) {
  return value === undefined || value === null ? '—' : `${(value * 100).toFixed(1)}%`
}

function cameraName(id) {
  return cameras.value.find((c) => c.id === id)?.name || `视频源 ${id}`
}

function liveState(key) {
  const t = latest.value?.agents
  if (!t) return { text: '等待数据', type: 'info' }
  if (key === 'perception') {
    return { text: `${t.perception.objects} 个候选 · 最高 ${t.perception.top_confidence}`, type: t.perception.objects ? 'success' : 'info' }
  }
  if (key === 'farfield') {
    return { text: t.farfield.active ? '切片扫描中' : `整图模式 · 间隔 ${t.farfield.interval}s`, type: t.farfield.active ? 'warning' : 'info' }
  }
  if (key === 'temporal') {
    return { text: `烟雾连续 ${t.temporal.smoke_streak}/${t.temporal.required} 帧`, type: t.temporal.smoke_streak ? 'warning' : 'info' }
  }
  if (key === 'verification') {
    const v = t.verification
    if (!v.active) return { text: '已关闭', type: 'info' }
    if (v.passed === null) return { text: v.triggered ? '复核中' : '待触发', type: 'info' }
    return v.passed
      ? { text: `通过 · ${(v.confidence * 100).toFixed(0)}%`, type: 'success' }
      : { text: '已拦截', type: 'danger' }
  }
  const d = t.decision
  const type = d.alarm ? 'danger' : d.status === 'normal' ? 'success' : 'warning'
  return { text: `${d.status} · 风险 ${d.risk}${d.alarm ? ' · 已告警' : ''}`, type }
}

const timeline = computed(() => {
  const t = latest.value?.agents
  if (!t) return []
  return [
    { key: 'perception', title: '感知 Agent', detail: `检出 ${t.perception.objects} 个候选，最高置信度 ${t.perception.top_confidence}` },
    { key: 'farfield', title: '远场 Agent', detail: t.farfield.active ? `执行 ${t.farfield.tile_size} 瓦片扫描` : `整图模式，保留切片结果 ${t.farfield.held} 个` },
    { key: 'temporal', title: '时序 Agent', detail: `烟雾连续 ${t.temporal.smoke_streak}/${t.temporal.required} 帧，冷却 ${t.temporal.cooldown}s` },
    {
      key: 'verification',
      title: '复核 Agent',
      detail: t.verification.active
        ? t.verification.passed === null
          ? (t.verification.triggered ? '局部复核进行中' : '未触发（当前无告警）')
          : t.verification.passed
            ? `局部复核通过，置信度 ${(t.verification.confidence * 100).toFixed(0)}%`
            : '局部复核不通过，已抑制告警'
        : '复核关闭'
    },
    {
      key: 'decision',
      title: '决策 Agent',
      detail: `状态 ${t.decision.status}，风险 ${t.decision.risk}${t.decision.alarm ? '，已生成告警' : ''}`
    }
  ]
})

async function load() {
  loading.value = true
  try {
    const [agentInfo, cameraList] = await Promise.all([api.agents(), api.cameras()])
    info.value = agentInfo
    cameras.value = cameraList
  } catch (error) {
    ElMessage.error(`加载智能体信息失败：${error.message}`)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="agents-page">
    <el-alert
      type="info"
      :closable="false"
      title="多智能体协同：感知 → 远场 → 时序 → 复核 → 决策。每个 Agent 职责单一，输出可解释证据；主链路不依赖云端大模型。"
      class="intro"
    />

    <div class="pipeline">
      <template v-for="(agent, index) in info.agents" :key="agent.key">
        <el-card shadow="never" class="agent-card">
          <div class="agent-head">
            <span class="agent-index">{{ String(index + 1).padStart(2, '0') }}</span>
            <b>{{ agent.name }}</b>
          </div>
          <p class="role">{{ agent.role }}</p>
          <p class="desc">{{ agent.desc }}</p>
          <el-tag :type="liveState(agent.key).type" size="small" effect="light">{{ liveState(agent.key).text }}</el-tag>
        </el-card>
        <span v-if="index < info.agents.length - 1" class="arrow">→</span>
      </template>
    </div>

    <div class="metrics">
      <el-card v-for="item in metricCards" :key="item.label" shadow="never" class="metric-card">
        <div class="metric-label">{{ item.label }}</div>
        <div class="metric-value">{{ item.value }}</div>
        <div class="metric-note">{{ item.note }}</div>
      </el-card>
    </div>

    <el-row :gutter="16">
      <el-col :span="11">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="panel-head">
              <b>最新决策轨迹</b>
              <el-tag v-if="latest" size="small" type="info">{{ cameraName(latest.camera_id) }}</el-tag>
            </div>
          </template>
          <div v-if="!latest" class="empty">等待检测数据，请先到「实时监控」打开一路视频源。</div>
          <el-timeline v-else>
            <el-timeline-item
              v-for="item in timeline"
              :key="item.key"
              :timestamp="item.title"
              placement="top"
            >
              {{ item.detail }}
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-col>
      <el-col :span="13">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="panel-head">
              <b>最近 Agent 轨迹</b>
              <el-button size="small" text type="primary" @click="router.push('/monitor')">打开实时监控</el-button>
            </div>
          </template>
          <el-table :data="recent" size="small" empty-text="等待检测数据">
            <el-table-column label="时间" width="82">
              <template #default="{ row }">{{ (row.timestamp || '').slice(11) }}</template>
            </el-table-column>
            <el-table-column label="视频源" min-width="120">
              <template #default="{ row }">{{ cameraName(row.camera_id) }}</template>
            </el-table-column>
            <el-table-column label="感知" width="66">
              <template #default="{ row }">{{ row.objects }}</template>
            </el-table-column>
            <el-table-column label="远场" width="66">
              <template #default="{ row }">{{ row.tiled ? '切片' : '整图' }}</template>
            </el-table-column>
            <el-table-column label="复核" width="78">
              <template #default="{ row }">
                {{ row.agents.verification.passed === null ? '—' : row.agents.verification.passed ? '通过' : '拦截' }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="92">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === 'critical' ? 'danger' : row.status === 'warning' ? 'warning' : 'success'">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="risk" label="风险" width="62" />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.agents-page { position: relative; min-height: 460px; }
.intro { margin-bottom: 14px; }
.pipeline { display: flex; align-items: stretch; gap: 8px; overflow-x: auto; padding-bottom: 6px; }
.agent-card { width: 190px; flex: 0 0 190px; }
.agent-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.agent-index { color: #1f4d78; font-weight: 700; font-size: 12px; }
.role { color: #303133; font-size: 13px; margin: 0 0 4px; }
.desc { color: #909399; font-size: 12px; line-height: 1.5; min-height: 54px; margin: 0 0 8px; }
.arrow { align-self: center; color: #c0c4cc; font-size: 20px; }
.metrics { display: flex; gap: 12px; margin-top: 14px; }
.metric-card { flex: 1; min-width: 150px; }
.metric-label { color: #7b8494; font-size: 12px; }
.metric-value { font-size: 22px; font-weight: 600; margin: 4px 0; color: #1f2d3d; }
.metric-note { color: #9aa2b0; font-size: 11px; }
.panel { margin-top: 16px; }
.panel-head { display: flex; align-items: center; justify-content: space-between; }
.empty { color: #9aa2b0; padding: 24px 0; text-align: center; }
@media (max-width: 1200px) {
  .agent-card { width: 170px; flex-basis: 170px; }
}
</style>
