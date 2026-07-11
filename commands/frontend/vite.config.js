import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import checker from 'vite-plugin-checker'

export default defineConfig({
  plugins: [
    react(),
    checker({ typescript: true }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8766',
        changeOrigin: true,
      },
    },
  },
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: 'charts',
              test: /node_modules[\\/](?:echarts|echarts-for-react|zrender)[\\/]/,
              maxSize: 400 * 1024,
              priority: 40,
              includeDependenciesRecursively: false,
            },
            {
              name: 'antd',
              test: /node_modules[\\/](?:antd|@ant-design|@rc-component|rc-[^\\/]+)[\\/]/,
              maxSize: 400 * 1024,
              priority: 30,
              includeDependenciesRecursively: false,
            },
            {
              name: 'markdown',
              test: /node_modules[\\/](?:react-markdown|remark-|rehype-|unified|micromark|mdast-|hast-|unist-)/,
              maxSize: 400 * 1024,
              priority: 20,
              includeDependenciesRecursively: false,
            },
            {
              name: 'react-platform',
              test: /node_modules[\\/](?:react|react-dom|react-router|react-router-dom|scheduler|@tanstack)[\\/]/,
              maxSize: 400 * 1024,
              priority: 10,
              includeDependenciesRecursively: false,
            },
          ],
        },
      },
    },
  },
})
