<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'

const cameras = ref([
  { id: 1, name: '仓库东区-01', location: '原料仓库东侧', source: 'rtsp://demo/camera01', enabled: true },
  { id: 2, name: '生产线-02', location: '二号生产线', source: 'rtsp://demo/camera02', enabled: true },
  { id: 3, name: '配电室-03', location: '一层配电室', source: 'rtsp://demo/camera03', enabled: false },
  { id: 4, name: '停车区-04', location: '厂区停车区', source: 'rtsp://demo/camera04', enabled: true }
])

const uploadVisible = ref(false)

async function uploadFile({ file }) {
  const form = new FormData()
  form.append('file', file)
  try {
    const res = await fetch('/api/uploads', { method: 'POST', body: form })
    if (!res.ok) throw new Error('上传失败: HTTP ' + res.status)
    ElMessage.success('上传成功，已加入视频源列表')
    uploadVisible.value = false
  } catch (err) {
    ElMessage.error(err.message + '（请确认后端已启动）')
  }
}
</script>

<template>
  <div>
    <el-button type="primary" @click="uploadVisible = true">上传本地视频</el-button>
    <el-row :gutter="16" class="list">
      <el-col v-for="c in cameras" :key="c.id" :span="12" class="cell">
        <el-card shadow="never">
          <div class="row">
            <div>
              <b>{{ c.name }}</b>
              <p>{{ c.location }}</p>
              <small>{{ c.source }}</small>
            </div>
            <el-switch :model-value="c.enabled" disabled />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="uploadVisible" title="上传本地视频" width="480px">
      <el-upload drag :auto-upload="false" :show-file-list="true" accept=".mp4,.mov" :http-request="uploadFile">
        <el-icon size="36"><Upload /></el-icon>
        <div>将 MP4/MOV 拖到此处，或点击选择文件</div>
      </el-upload>
    </el-dialog>
  </div>
</template>

<style scoped>
.list { margin-top: 16px; }
.cell { margin-bottom: 16px; }
.row { display: flex; justify-content: space-between; align-items: center; }
.row p { margin: 4px 0; color: #7b8494; }
.row small { color: #9aa2b0; }
</style>
