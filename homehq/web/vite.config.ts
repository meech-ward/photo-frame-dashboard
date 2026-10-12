import { defineConfig } from 'vite';
import { resolve } from 'node:path';

export default defineConfig({
  build: {
    // Keep the same browser compatibility as Wes's original wall-frame app.
    target: 'chrome106', cssTarget: 'chrome61',
    rollupOptions: { input: { dashboard: resolve(import.meta.dirname, 'index.html'), editor: resolve(import.meta.dirname, 'editor.html') } },
  },
});
