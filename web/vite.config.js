import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
const backend = process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8080';
export default defineConfig({
    plugins: [react()],
    server: {
        proxy: {
            '/healthz': backend,
            '/sessions': backend,
            '/approvals': backend,
            '/rag': backend,
            '/mcp': backend,
            '/model': backend,
            '/evaluation': backend,
            '/qq': backend
        }
    },
    build: {
        chunkSizeWarningLimit: 1200,
        rollupOptions: {
            output: {
                manualChunks: {
                    antd: ['antd', '@ant-design/icons']
                }
            }
        }
    }
});
