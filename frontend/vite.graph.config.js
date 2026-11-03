import { defineConfig } from "vite";
import { transform } from "esbuild";

// The graph renderer is its own ES module, fetched lazily by the shell on the first `graph`
// render (ADR-0042, ADR-0048), like the map and the editor. Output: dist-graph/graph.js (copied to
// src/indah/static/). Same full-minify pass as the map build: Vite's library mode keeps
// whitespace in an ES build, and the target must stay "esnext" so it does not re-print it.
const minifyFully = {
  name: "minify-fully",
  enforce: "post",
  async renderChunk(code) {
    const out = await transform(code, {
      minify: true,
      target: "es2020",
      format: "esm",
      legalComments: "inline",
    });
    return { code: out.code, map: null };
  },
};

export default defineConfig({
  plugins: [minifyFully],
  build: {
    outDir: "dist-graph",
    emptyOutDir: true,
    target: "esnext",
    minify: false,
    lib: { entry: "graph/graph.js", formats: ["es"], fileName: () => "graph.js" },
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
});
