<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { useRealtime } from '../composables/useRealtime'

const router = useRouter()
const { realtime } = useRealtime()
const loading = ref(false)
const info = ref({ agents: [], metrics: {}, settings: {}, pipeline: [] })
const cameras = ref([])
const sample = ref(null)
const recent = ref([])
const paused = ref(false)
let timer = null

const latest = computed(() => sample.value)
const metrics = computed(() => info.value.metrics || {})
const risk = computed(() => latest.value?.risk ?? 0)
const riskColor = computed(() => (risk.value >= 80 ? '#e5484d' : risk.value >= 45 ? '#e6a23c' : '#23a06b'))

const statusText = computed(() => {
  const status = latest.value?.status
  return status === 'critical' ? '严重告警' : status === 'warning' ? '预警' : status === 'normal' ? '正常' : '等待数据'
})

const statusType = computed(() => {
  const status = latest.value?.status
  return status === 'critical' ? 'danger' : status === 'warning' ? 'warning' : 'success'
})

const verifyText = computed(() => {
  const v = latest.value?.agents?.verification
  if (!v) return '等待数据'
  if (!v.active) return '已关闭'
  if (v.passed === null) return v.triggered ? '复核中' : '待触发'
  return v.passed ? `通过 · ${Math.round(v.confidence * 100)}%` : '已拦截'
})

const activeStage = computed(() => {
  const t = latest.value?.agents
  if (!t) return ''
  if (t.verification.triggered) return 'verification'
  if (t.decision.alarm) return 'decision'
  if (t.farfield.active) return 'farfield'
  return 'perception'
})

const metricBlocks = computed(() => [
  { label: '官方 test mAP50', value: pct(metrics.value.map50), note: '验收线 ≥70%' },
  { label: '远景小目标召回', value: pct(metrics.value.farfield_recall), note: `旧模型 ${pct(metrics.value.farfield_old)}` },
  { label: '整图 → 切片召回', value: `${pct(metrics.value.tiling_plain)} → ${pct(metrics.value.tiling_tiled)}`, note: '每 2 秒低频扫描' },
  { label: 'SmokeFire 烟雾召回', value: pct(metrics.value.smokefire_smoke), note: '未参与训练的跨域集' },
  { label: '校准后 fire 误报', value: pct(metrics.value.calibrated_fire_fpr), note: '困难负样本，阈值 0.40' }
])

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
            ? `局部复核通过，置信度 ${Math.round(t.verification.confidence * 100)}%`
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
    return { text: `${t.perception.objects} 个候选`, type: t.perception.objects ? 'success' : 'info' }
  }
  if (key === 'farfield') {
    return { text: t.farfield.active ? '切片扫描中' : '整图模式', type: t.farfield.active ? 'warning' : 'info' }
  }
  if (key === 'temporal') {
    return { text: `${t.temporal.smoke_streak}/${t.temporal.required} 帧`, type: t.temporal.smoke_streak ? 'warning' : 'info' }
  }
  if (key === 'verification') {
    const v = t.verification
    if (!v.active) return { text: '已关闭', type: 'info' }
    if (v.passed === null) return { text: v.triggered ? '复核中' : '待触发', type: 'info' }
    return v.passed ? { text: '已通过', type: 'success' } : { text: '已拦截', type: 'danger' }
  }
  const d = t.decision
  return { text: d.alarm ? '已生成告警' : d.status, type: d.alarm ? 'danger' : d.status === 'normal' ? 'success' : 'warning' }
}

function nodeState(key) {
  const type = liveState(key).type
  return { 'state-ok': type === 'success', 'state-warn': type === 'warning', 'state-danger': type === 'danger' }
}

function syncSample() {
  if (paused.value) return
  sample.value = realtime.traces[0] || null
  recent.value = realtime.traces.slice(0, 10)
}

function togglePause() {
  paused.value = !paused.value
  if (!paused.value) syncSample()
}

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

onMounted(async () => {
  await load()
  syncSample()
  timer = setInterval(syncSample, 3000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div v-loading="loading" class="agents-page">
    <div class="page-head">
      <div>
        <h2>多智能体协同检测</h2>
        <p>五个专业化 Agent 按流水线协作，每个结论都带可解释证据</p>
      </div>
      <div class="head-actions">
        <el-tag :type="paused ? 'info' : 'success'" effect="dark" size="small">
          {{ paused ? '已暂停' : '实时采样 · 3 秒' }}
        </el-tag>
        <el-button size="small" @click="togglePause">{{ paused ? '继续刷新' : '暂停刷新' }}</el-button>
        <el-button size="small" type="primary" plain @click="router.push('/monitor')">打开实时监控</el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :span="15">
        <el-card shadow="never" class="pipeline-panel">
          <template #header>
            <div class="panel-head">
              <b>Agent 流水线</b>
              <span class="sub">当前画面：{{ latest ? cameraName(latest.camera_id) : '等待视频源' }}</span>
            </div>
          </template>

          <div class="pipeline">
            <template v-for="(agent, index) in info.agents" :key="agent.key">
              <div class="node" :class="[nodeState(agent.key), { active: activeStage === agent.key }]">
                <div class="node-top">
                  <span class="node-num">{{ index + 1 }}</span>
                  <b>{{ agent.name }}</b>
                </div>
                <div class="node-role">{{ agent.role }}</div>
                <div class="node-status">{{ liveState(agent.key).text }}</div>
              </div>
              <span v-if="index < info.agents.length - 1" class="connector">→</span>
            </template>
          </div>

          <div class="evidence">
            <div class="evidence-title">
              最新决策轨迹
              <span>每 3 秒采样一次，避免数字闪烁</span>
            </div>
            <div v-if="timeline.length === 0" class="empty">等待检测数据，请先到「实时监控」打开视频源。</div>
            <div v-for="item in timeline" :key="item.key" class="evidence-row">
              <span class="evidence-dot" />
              <b>{{ item.title }}</b>
              <span>{{ item.detail }}</span>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="9">
        <el-card shadow="never" class="decision-panel">
          <template #header>
            <div class="panel-head">
              <b>当前决策</b>
              <el-tag :type="statusType" size="small">{{ statusText }}</el-tag>
            </div>
          </template>
          <div class="gauge">
            <el-progress type="dashboard" :percentage="risk" :color="riskColor" :width="150">
              <template #default>
                <div class="gauge-value">{{ risk }}</div>
                <div class="gauge-label">风险分</div>
              </template>
            </el-progress>
          </div>
          <div class="decision-meta">
            <span>{{ latest ? cameraName(latest.camera_id) : '—' }}</span>
            <span>{{ latest ? (latest.timestamp || '').slice(11) : '—' }}</span>
            <span>{{ latest ? `${latest.fps ?? '—'} FPS` : '—' }}</span>
          </div>
          <div class="decision-rows">
            <div><span>感知</span><b>{{ latest?.agents?.perception?.objects ?? '—' }} 个候选</b></div>
            <div><span>远场</span><b>{{ latest?.agents?.farfield?.active ? '切片扫描' : '整图模式' }}</b></div>
            <div><span>复核</span><b>{{ verifyText }}</b></div>
            <div><span>告警</span><b>{{ latest?.agents?.decision?.alarm ? '已生成' : '未触发' }}</b></div>
          </div>
          <p class="decision-note">主链路本地运行，不依赖云端大模型；VLM 只作为可选灰区复核。</p>
        </el-card>
      </el-col>
    </el-row>

    <div class="metric-band">
      <div v-for="item in metricBlocks" :key="item.label" class="metric-block">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.note }}</small>
      </div>
    </div>

    <el-card shadow="never" class="recent-panel">
      <template #header>
        <div class="panel-head">
          <b>最近 Agent 轨迹</b>
          <span class="sub">最近 10 条 · 3 秒采样</span>
        </div>
      </template>
      <el-table :data="recent" size="small" empty-text="等待检测数据">
        <el-table-column label="时间" width="84">
          <template #default="{ row }">{{ (row.timestamp || '').slice(11) }}</template>
        </el-table-column>
        <el-table-column label="视频源" min-width="130">
          <template #default="{ row }">{{ cameraName(row.camera_id) }}</template>
        </el-table-column>
        <el-table-column label="感知" width="70">
          <template #default="{ row }">{{ row.objects }}</template>
        </el-table-column>
        <el-table-column label="远场" width="70">
          <template #default="{ row }">{{ row.tiled ? '切片' : '整图' }}</template>
        </el-table-column>
        <el-table-column label="复核" width="82">
          <template #default="{ row }">
            {{ row.agents.verification.passed === null ? '—' : row.agents.verification.passed ? '通过' : '拦截' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'critical' ? 'danger' : row.status === 'warning' ? 'warning' : 'success'">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="risk" label="风险" width="64" />
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.agents-page { position: relative; min-height: 480px; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 14px; }
.page-head h2 { margin: 0 0 4px; font-size: 20px; }
.page-head p { margin: 0; color: #8b93a1; font-size: 13px; }
.head-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.panel-head { display: flex; align-items: center; justify-content: space-between; }
.sub { color: #9aa2b0; font-size: 12px; }
.pipeline { display: flex; align-items: stretch; gap: 2px; padding: 10px 0 14px; }
.node {
  flex: 1; min-width: 0; padding: 10px; border: 1px solid #e5e7eb; border-left: 3px solid #c0c4cc;
  border-radius: 10px; background: #fafbfc; transition: all .2s;
}
.node.active { background: #fff; border-color: #1f4d78; box-shadow: 0 0 0 2px rgba(31, 77, 120, .12); }
.node.state-ok { border-left-color: #23a06b; }
.node.state-warn { border-left-color: #e6a23c; }
.node.state-danger { border-left-color: #e5484d; }
.node-top { display: flex; align-items: center; gap: 6px; }
.node-num { color: #1f4d78; font-weight: 700; font-size: 11px; }
.node-top b { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.node-role { color: #9aa2b0; font-size: 11px; margin: 4px 0 8px; }
.node-status { color: #303133; font-size: 12px; font-weight: 600; min-height: 18px; }
.connector { align-self: center; color: #c0c4cc; font-size: 18px; padding: 0 2px; }
.evidence { border-top: 1px dashed #e5e7eb; padding-top: 12px; }
.evidence-title { display: flex; align-items: baseline; gap: 8px; font-weight: 600; font-size: 13px; margin-bottom: 8px; }
.evidence-title span { color: #9aa2b0; font-weight: 400; font-size: 11px; }
.evidence-row { display: flex; align-items: baseline; gap: 8px; padding: 5px 0; font-size: 12px; color: #606776; }
.evidence-row b { width: 74px; flex: 0 0 74px; color: #303133; }
.evidence-dot { width: 6px; height: 6px; border-radius: 50%; background: #1f4d78; flex: 0 0 6px; }
.empty { color: #9aa2b0; font-size: 12px; padding: 10px 0; }
.gauge { display: flex; justify-content: center; padding: 4px 0 2px; }
.gauge-value { font-size: 28px; font-weight: 700; color: #1f2d3d; }
.gauge-label { color: #9aa2b0; font-size: 12px; }
.decision-meta { display: flex; justify-content: space-around; color: #8b93a1; font-size: 12px; margin: 4px 0 12px; }
.decision-rows { display: grid; gap: 8px; }
.decision-rows div { display: flex; justify-content: space-between; font-size: 13px; padding: 6px 8px; background: #fafbfc; border-radius: 6px; }
.decision-rows span { color: #8b93a1; }
.decision-rows b { color: #303133; }
.decision-note { color: #9aa2b0; font-size: 11px; line-height: 1.6; margin: 12px 0 0; }
.metric-band {
  display: flex; gap: 0; margin-top: 16px; background: #fff; border: 1px solid #e5e7eb;
  border-radius: 8px; overflow: hidden;
}
.metric-block { flex: 1; padding: 12px 16px; border-right: 1px solid #eef0f4; }
.metric-block:last-child { border-right: none; }
.metric-block span { display: block; color: #8b93a1; font-size: 11px; }
.metric-block strong { display: block; font-size: 20px; margin: 4px 0 2px; color: #1f2d3d; }
.metric-block small { color: #a8b0bd; font-size: 11px; }
.recent-panel { margin-top: 16px; }
@media (max-width: 1200px) {
  .pipeline { flex-wrap: wrap; }
  .node { flex: 1 1 150px; }
  .connector { display: none; }
  .metric-band { flex-wrap: wrap; }
  .metric-block { flex: 1 1 30%; border-bottom: 1px solid #eef0f4; }
}
</style>
