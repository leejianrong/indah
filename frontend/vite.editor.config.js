import { defineConfig } from "vite";

// The code editor is its own ES module, fetched lazily by the shell on the first
// `codeeditor` render (ADR-0032). It is not inlined into index.html, so apps that never use
// one do not download it. Output: dist-editor/editor.js (copied to src/indah/static/).
export default defineConfig({
  build: {
    outDir: "dist-editor",
    emptyOutDir: true,
    target: "es2020",
    minify: "esbuild",
    lib: { entry: "editor/editor.js", formats: ["es"], fileName: () => "editor.js" },
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
});
