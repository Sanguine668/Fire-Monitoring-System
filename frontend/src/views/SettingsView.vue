<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

const defaults = {
  fire_threshold: 0.4,
  smoke_threshold: 0.45,
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

onMounted(load)
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
        <span class="switch-hint">触发告警时放大局部区域再检测一次，复核不通过则抑制</span>
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
  </el-card>
</template>

<style scoped>
.tips { margin-bottom: 18px; }
.section-title { font-weight: 600; color: #303133; margin: 4px 0 16px; }
.switch-hint { margin-left: 12px; color: #9aa2b0; font-size: 12px; }
</style>
