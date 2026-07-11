import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://26.14.184.149:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://26.14.184.149:8000',
        changeOrigin: true,
      },
    },
  },
});
