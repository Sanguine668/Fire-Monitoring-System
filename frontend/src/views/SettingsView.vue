<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

const defaults = { fire_threshold: 0.1, smoke_threshold: 0.1, continuous_frames: 3, alarm_cooldown: 8 }
const form = ref({ ...defaults })
const loading = ref(false)
const saving = ref(false)

const fields = [
  { key: 'fire_threshold', label: '明火置信度阈值', min: 0.05, max: 0.99, step: 0.01 },
  { key: 'smoke_threshold', label: '烟雾置信度阈值', min: 0.05, max: 0.99, step: 0.01 },
  { key: 'continuous_frames', label: '连续帧数', min: 1, max: 30 },
  { key: 'alarm_cooldown', label: '告警冷却(秒)', min: 1, max: 120 }
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
      title="提示：首轮模型置信度整体偏低，默认阈值设为 0.1；修改后立即作用于所有正在运行的视频源。"
      class="tips"
    />
    <el-form label-width="180px" style="max-width: 620px">
      <el-form-item v-for="item in fields" :key="item.key" :label="item.label">
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
</style>
