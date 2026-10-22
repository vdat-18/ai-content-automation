import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const proxyTarget = env.VITE_PROXY_TARGET || "http://127.0.0.1:8000";

  return {
    plugins: [react()],
    base: "/dashboard/",
    server: {
      proxy: {
        "/api": { target: proxyTarget },
        "/artifacts": { target: proxyTarget },
        "/health": { target: proxyTarget },
      },
    },
    build: {
      outDir: "dist",
      emptyOutDir: true,
      rollupOptions: {
        output: {
          manualChunks: {
            charts: ["recharts"],
            react: ["react", "react-dom", "react-router-dom", "@tanstack/react-query"],
          },
        },
      },
    },
  };
});
