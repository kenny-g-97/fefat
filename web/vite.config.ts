import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react"
import { configDefaults, defineConfig } from "vitest/config"

// The dev server proxies the API to `fefat up`, so that its session cookie stays on one origin.
const server = `http://127.0.0.1:${process.env.FEFAT_SERVER_PORT ?? "8765"}`
const proxied = { target: server, changeOrigin: true }

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
  build: { assetsInlineLimit: 0, chunkSizeWarningLimit: 1024 },
  server: {
    proxy: { "/v1": proxied, "/docs": proxied, "/openapi.json": proxied },
  },
  test: { exclude: [...configDefaults.exclude, "e2e/**"] },
})
