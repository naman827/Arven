/// <reference types="vitest/config" />
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const backend = process.env.ARVEN_BACKEND_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: backend, changeOrigin: false } },
  },
  preview: { host: '127.0.0.1', port: 4173 },
  build: {
    sourcemap: false,
    rolldownOptions: {
      output: {
        // Split large libraries into their own cacheable chunks instead of one >500 kB bundle.
        codeSplitting: {
          groups: [
            { name: 'react', test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/, priority: 3 },
            {
              name: 'markdown',
              test: /node_modules[\\/](react-markdown|remark-|rehype-|micromark|mdast-|hast-|unified|unist-|vfile|property-information|decode-named-character-reference|character-entities|space-separated-tokens|comma-separated-tokens|zwitch|bail|trough|devlop|markdown-table|ccount|longest-streak|html-url-attributes|style-to-|inline-style-parser|estree-util|trim-lines|is-plain-obj)/,
              priority: 2,
            },
            { name: 'vendor', test: /node_modules/, priority: 1 },
          ],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/unit/**/*.test.{ts,tsx}'],
    css: false,
  },
})
