<script setup>
const mockCameras = [
  { id: 1, name: '仓库东区-01', location: '原料仓库东侧', online: true },
  { id: 2, name: '生产线-02', location: '二号生产线', online: true },
  { id: 3, name: '配电室-03', location: '一层配电室', online: false },
  { id: 4, name: '停车区-04', location: '厂区停车区', online: true }
]
</script>

<template>
  <el-row :gutter="16">
    <el-col v-for="c in mockCameras" :key="c.id" :span="12" class="cell">
      <el-card shadow="never" :body-style="{ padding: '0' }">
        <div class="stage" :class="{ offline: !c.online }">
          <el-tag :type="c.online ? 'success' : 'info'" size="small" class="tag">
            {{ c.online ? '在线' : '离线' }}
          </el-tag>
          <el-empty v-if="!c.online" description="视频源离线" :image-size="60" />
          <div v-else class="placeholder">
            <p>MJPEG 画面占位</p>
            <small>后端 /stream/{{ c.id }} 就绪后在此接入</small>
          </div>
        </div>
        <div class="meta">
          <b>{{ c.name }}</b>
          <span>{{ c.location }}</span>
        </div>
      </el-card>
    </el-col>
  </el-row>
</template>

<style scoped>
.cell { margin-bottom: 16px; }
.stage { height: 230px; background: #10131a; color: #fff; position: relative; }
.tag { position: absolute; top: 8px; left: 8px; z-index: 1; }
.placeholder { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #aab2c0; }
.stage.offline { background: #eef0f4; }
.meta { display: flex; justify-content: space-between; padding: 10px 14px; color: #4b5563; }
</style>
