import path from "node:path"
import { defineConfig, loadEnv } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

export default defineConfig(({ mode }) => {
  // Load .env from the repo root so ASSET_PUBLIC_BASE_URL and the Access
  // service-token credentials are available for the /assets dev proxy below.
  const env = loadEnv(mode, path.resolve(__dirname, ".."), "")
  const assetBase = env.ASSET_PUBLIC_BASE_URL?.replace(/\/$/, "")
  const accessId = env.CLOUDFLARE_ACCESS_CLIENT_ID
  const accessSecret = env.CLOUDFLARE_ACCESS_CLIENT_SECRET
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      proxy: {
        "/api": "http://localhost:8787",
        "/health": "http://localhost:8787",
        // /assets/* is served by the deployed worker (production R2). Local
        // worker uses --local and has no R2 state; proxy to the live origin
        // so image previews match production. Cloudflare Access protects
        // the deployed origin, so the proxy must forward the service-token
        // headers from .env (per the dashboard's Service Auth policy).
        "/assets": {
          target: assetBase || "http://localhost:8787",
          changeOrigin: true,
          headers: {
            ...(accessId && { "Cf-Access-Client-Id": accessId }),
            ...(accessSecret && { "Cf-Access-Client-Secret": accessSecret }),
          },
        },
      },
    },
  }
})
