<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

const defaults = { fire_threshold: 0.62, smoke_threshold: 0.55, continuous_frames: 4, alarm_cooldown: 8 }
const form = ref({ ...defaults })

onMounted(async () => {
  try {
    const res = await fetch('/api/settings')
    if (res.ok) form.value = await res.json()
  } catch { /* 后端未启动时保留默认值 */ }
})

async function save() {
  try {
    const res = await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value)
    })
    if (!res.ok) throw new Error('HTTP ' + res.status)
    ElMessage.success('参数保存成功')
  } catch (err) {
    ElMessage.error('保存失败：' + err.message)
  }
}
</script>

<template>
  <el-card shadow="never" class="settings">
    <el-form label-width="180px" style="max-width: 560px">
      <el-form-item label="明火置信度阈值">
        <el-slider v-model="form.fire_threshold" :min="0.1" :max="0.99" :step="0.01" show-input />
      </el-form-item>
      <el-form-item label="烟雾置信度阈值">
        <el-slider v-model="form.smoke_threshold" :min="0.1" :max="0.99" :step="0.01" show-input />
      </el-form-item>
      <el-form-item label="连续帧数">
        <el-input-number v-model="form.continuous_frames" :min="1" :max="30" />
      </el-form-item>
      <el-form-item label="告警冷却(秒)">
        <el-input-number v-model="form.alarm_cooldown" :min="1" :max="120" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="save">保存</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>
