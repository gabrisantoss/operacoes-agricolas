import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/balanca/",
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("lucide-react")) return "icons";
          if (id.includes("react")) return "react-vendor";
          return "vendor";
        }
      }
    }
  },
  server: {
    host: "127.0.0.1",
    port: 8873,
    strictPort: true,
    allowedHosts: [
      "localhost",
      "127.0.0.1"
    ]
  }
});
