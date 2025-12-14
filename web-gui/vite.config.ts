import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0', // 监听所有网络接口，允许局域网访问
    port: 5173, // 默认端口，可以自定义
    proxy: {
      '/v1': {
        target: '',
        changeOrigin: true,
      }
    }
  }
})
