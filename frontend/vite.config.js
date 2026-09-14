import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { viteSingleFile } from "vite-plugin-singlefile";

// Bundle everything (JS + CSS) into a single index.html so the Python server
// serves one self-contained file over one port, with no external asset requests
// to break behind Colab/Runpod proxy base paths (ADR-0001, ADR-0004).
export default defineConfig({
  plugins: [svelte(), viteSingleFile()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2020",
  },
});
