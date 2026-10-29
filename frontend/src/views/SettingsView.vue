<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

const defaults = {
  fire_threshold: 0.4,
  smoke_threshold: 0.25,
  continuous_frames: 3,
  alarm_cooldown: 8,
  tiling_enabled: 1,
  tile_size: 640,
  tile_overlap: 0.2,
  tile_interval: 2,
  verify_enabled: 1,
  verify_threshold: 0.25
}
const form = ref({ ...defaults })
const loading = ref(false)
const saving = ref(false)

const notify = ref({ enabled: 0, sendkey_masked: '', name: '', daily_limit: 5, configured: false, sent_today: 0, records: [], last_skip: '' })
const notifyForm = ref({ enabled: 0, sendkey: '', name: '', daily_limit: 5 })
const notifySaving = ref(false)
const testing = ref(false)
// 推送配置是否成功读取：读不到时禁用保存/测试，避免用默认值覆盖已保存的配置
const notifyLoaded = ref(false)
const notifyError = ref('')

const thresholdFields = [
  { key: 'fire_threshold', label: '明火置信度阈值', min: 0.05, max: 0.99, step: 0.01 },
  { key: 'smoke_threshold', label: '烟雾置信度阈值', min: 0.05, max: 0.99, step: 0.01 },
]

const alarmFields = [
  { key: 'continuous_frames', label: '连续帧数', min: 1, max: 30 },
  { key: 'alarm_cooldown', label: '告警冷却(秒)', min: 1, max: 120 }
]

const tilingFields = [
  { key: 'tile_size', label: '瓦片尺寸(px)', min: 320, max: 1280, step: 32 },
  { key: 'tile_overlap', label: '瓦片重叠率', min: 0, max: 0.5, step: 0.05 },
  { key: 'tile_interval', label: '扫描间隔(秒)', min: 1, max: 10 }
]

async function load() {
  loading.value = true
  try {
    form.value = await api.settings()
  } catch (error) {
    ElMessage.error(`读取参数失败：${error.message}（请确认后端已启动）`)
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    await api.saveSettings(form.value)
    ElMessage.success('参数保存成功，检测 worker 会立即生效')
  } catch (error) {
    ElMessage.error(`保存失败：${error.message}`)
  } finally {
    saving.value = false
  }
}

function reset() {
  form.value = { ...defaults }
}

async function loadNotify() {
  try {
    const data = await api.notifyConfig()
    notify.value = data
    notifyForm.value = {
      enabled: data.enabled,
      sendkey: data.sendkey_masked,
      name: data.name,
      daily_limit: data.daily_limit
    }
    notifyLoaded.value = true
    notifyError.value = ''
  } catch (error) {
    notifyLoaded.value = false
    notifyError.value = error.message
    ElMessage.error(`读取推送配置失败：${error.message}`)
  }
}

async function saveNotify() {
  if (!notifyLoaded.value) return
  notifySaving.value = true
  try {
    const data = await api.saveNotify(notifyForm.value)
    notify.value = data
    notifyForm.value = {
      enabled: data.enabled,
      sendkey: data.sendkey_masked,
      name: data.name,
      daily_limit: data.daily_limit
    }
    ElMessage.success('推送配置已保存')
  } catch (error) {
    ElMessage.error(`保存失败：${error.message}`)
  } finally {
    notifySaving.value = false
  }
}

async function testNotify() {
  if (!notifyLoaded.value) return
  testing.value = true
  try {
    const result = await api.testNotify({})
    if (result.ok) ElMessage.success('测试通知已发送，请查看微信')
    else ElMessage.error(`发送失败：${result.message || '未知原因'}（code=${result.code}）`)
    await loadNotify()
  } catch (error) {
    ElMessage.error(`测试失败：${error.message}`)
  } finally {
    testing.value = false
  }
}

async function resetNotify() {
  if (!notifyLoaded.value) return
  try {
    await ElMessageBox.confirm('重置后，各视频源在本次运行中可再次收到推送。确定重置？', '重置推送记录', { type: 'warning' })
    const result = await api.resetNotify()
    ElMessage.success(`已重置 ${result.cleared} 条推送记录`)
    await loadNotify()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(`重置失败：${error.message || error}`)
  }
}

onMounted(() => {
  load()
  loadNotify()
})
</script>

<template>
  <el-card v-loading="loading" shadow="never" class="settings">
    <el-alert
      type="info"
      :closable="false"
      title="参数修改后立即作用于所有正在运行的视频源。远距离模式会周期性把画面切成瓦片做高分辨率扫描，能提升远处小目标召回，但单次推理耗时更高。"
      class="tips"
    />
    <el-form label-width="180px" style="max-width: 620px">
      <div class="section-title">告警判定</div>
      <el-form-item v-for="item in thresholdFields" :key="item.key" :label="item.label">
        <el-slider
          v-if="item.step"
          v-model="form[item.key]"
          :min="item.min"
          :max="item.max"
          :step="item.step"
          show-input
        />
        <el-input-number v-else v-model="form[item.key]" :min="item.min" :max="item.max" />
      </el-form-item>
      <el-form-item v-for="item in alarmFields" :key="item.key" :label="item.label">
        <el-input-number v-model="form[item.key]" :min="item.min" :max="item.max" />
      </el-form-item>
      <el-form-item label="告警二次复核">
        <el-switch v-model="form.verify_enabled" :active-value="1" :inactive-value="0" />
        <span class="switch-hint is-wide">触发告警时放大局部区域再检测一次，复核不通过则抑制</span>
      </el-form-item>
      <el-form-item label="复核置信度阈值">
        <el-slider v-model="form.verify_threshold" :min="0.05" :max="0.9" :step="0.05" show-input />
      </el-form-item>

      <el-divider />
      <div class="section-title">远距离识别</div>
      <el-form-item label="启用切片扫描">
        <el-switch v-model="form.tiling_enabled" :active-value="1" :inactive-value="0" />
        <span class="switch-hint">开启后每隔一段时间对整帧做一次瓦片扫描</span>
      </el-form-item>
      <el-form-item v-for="item in tilingFields" :key="item.key" :label="item.label">
        <el-slider
          v-if="item.step"
          v-model="form[item.key]"
          :min="item.min"
          :max="item.max"
          :step="item.step"
          show-input
        />
        <el-input-number v-else v-model="form[item.key]" :min="item.min" :max="item.max" />
      </el-form-item>

      <el-form-item>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        <el-button @click="reset">恢复默认</el-button>
        <el-button @click="load">重新读取</el-button>
      </el-form-item>
    </el-form>

    <el-divider />
    <div class="section-title">告警推送</div>
    <el-alert
      type="warning"
      :closable="false"
      class="tips"
      title="采用 Server酱 推送到微信：免费版每天 5 条，按视频源去重（同一路本次运行只推第一条）。修改配置后需点保存生效。"
    />
    <el-alert
      v-if="notifyError"
      type="error"
      :closable="false"
      :title="`推送配置未读取成功：${notifyError}`"
      class="tips"
    >
      <span class="switch-hint is-wide">当前显示的是默认值；读取成功前保存与测试已禁用，以免覆盖已保存的推送配置。</span>
      <el-button size="small" text type="primary" @click="loadNotify">重新读取</el-button>
    </el-alert>
    <el-form label-width="180px" style="max-width: 760px">
      <el-form-item label="启用推送">
        <el-switch v-model="notifyForm.enabled" :active-value="1" :inactive-value="0" />
        <span class="switch-hint">当前状态：{{ notify.enabled ? '已启用' : '未启用' }}</span>
      </el-form-item>
      <el-form-item label="SendKey">
        <el-input v-model="notifyForm.sendkey" placeholder="在 sct.ftqq.com 微信扫码后获取" show-password />
        <div class="switch-hint is-wide">
          已配置：{{ notify.configured ? '是' : '否' }}；输入框显示的是掩码，不改动则保留原 Key。
        </div>
      </el-form-item>
      <el-form-item label="接收人备注">
        <el-input v-model="notifyForm.name" placeholder="如：组长手机" />
      </el-form-item>
      <el-form-item label="每日上限">
        <el-input-number v-model="notifyForm.daily_limit" :min="1" :max="1000" />
        <span class="switch-hint">今日已发送 {{ notify.sent_today }} 条</span>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="notifySaving" :disabled="!notifyLoaded" @click="saveNotify">保存推送配置</el-button>
        <el-button :loading="testing" :disabled="!notifyLoaded" @click="testNotify">发送测试通知</el-button>
        <el-button :disabled="!notifyLoaded" @click="resetNotify">重置推送记录</el-button>
      </el-form-item>
      <el-form-item v-if="notify.last_skip" label="最近一次跳过原因">
        <span class="switch-hint is-wide">{{ notify.last_skip }}</span>
      </el-form-item>
    </el-form>
    <div class="section-title">推送记录</div>
    <el-table :data="notify.records" size="small" empty-text="本轮尚未推送任何视频源">
      <el-table-column prop="created_at" label="时间" width="200" />
      <el-table-column prop="title" label="标题" min-width="280" show-overflow-tooltip />
      <el-table-column label="结果" width="120">
        <template #default="{ row }">
          <el-tag :type="row.ok ? 'success' : 'danger'" size="small" effect="plain">
            {{ row.ok ? '成功' : '失败' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="message" label="返回信息" min-width="180" show-overflow-tooltip />
    </el-table>
  </el-card>
</template>

<style scoped>
.tips { margin-bottom: 18px; }
.section-title { font-weight: 600; color: #303133; margin: 4px 0 16px; }
.switch-hint { margin-left: 12px; color: #9aa2b0; font-size: 0.875rem; }
/* 较长的说明文字单独占一行，避免最后一个字被挤到下一行 */
.switch-hint.is-wide { flex: 1 0 100%; margin-left: 0; margin-top: 2px; }
</style>
