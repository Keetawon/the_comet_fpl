/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const ATOMIC_DASHBOARD_DATA_DIRECTORY =
  /(?:^|[\\/])public[\\/]\.data\.[^\\/]+\.(?:tmp|previous)(?:[\\/]|$)/

/** Keep Vite away from publish generations while Windows atomically swaps them into place. */
export function isAtomicDashboardPublishPath(path: string): boolean {
  return ATOMIC_DASHBOARD_DATA_DIRECTORY.test(path)
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': import.meta.dirname + '/src',
    },
  },
  server: {
    watch: {
      // The publisher creates and immediately renames/removes these siblings of public/data.
      // Watching an in-flight generation can raise EBUSY on Windows. The installed data
      // directory remains watched, so a completed publish still triggers Vite's normal reload.
      ignored: isAtomicDashboardPublishPath,
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})
