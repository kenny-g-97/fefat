import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react"
import { configDefaults, defineConfig } from "vitest/config"

// The dev server proxies the API to `fefat up`, so that its session cookie stays on one origin.
const server = `http://127.0.0.1:${process.env.FEFAT_SERVER_PORT ?? "8765"}`
const proxied = { target: server, changeOrigin: true }

/** zod and the module that turns its compiler off (src/app/zod-jitless.ts) share one chunk, so
 * that whichever chunk first loads zod also turns the compiler off before any schema is built:
 * a schema built first probes `new Function`, which the content security policy refuses and the
 * browser reports (step 5.8, where a lazy page's shared chunk took zod from the entry's). */
function zodChunk(moduleId: string): string | null {
  const id = moduleId.replaceAll("\\", "/")
  const zod = id.includes("/node_modules/") && id.includes("/zod/")
  return zod || id.endsWith("/src/app/zod-jitless.ts") ? "zod" : null
}

export default defineConfig({
  plugins: [
    tanstackRouter({
      target: "react",
      routesDirectory: "./src/app/routes",
      generatedRouteTree: "./src/app/routeTree.gen.ts",
    }),
    react(),
    tailwindcss(),
  ],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
  // The content security policy allows no data: font (01-architecture.md section 8), and the
  // app loads from this machine, where half a megabyte of script is no wait.
  build: {
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 1024,
    rolldownOptions: {
      output: { codeSplitting: { groups: [{ name: zodChunk }] } },
    },
  },
  server: {
    proxy: { "/v1": proxied, "/docs": proxied, "/openapi.json": proxied },
  },
  // A zone with daylight saving, so that a test of a time shown in the browser's zone is exact.
  test: {
    exclude: [...configDefaults.exclude, "e2e/**"],
    env: { TZ: "America/Chicago" },
  },
})
