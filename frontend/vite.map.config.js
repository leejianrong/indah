import { defineConfig } from "vite";
import { transform } from "esbuild";

// The map is its own ES module, fetched lazily by the shell on the first `map` render
// (ADR-0042). It is not inlined into index.html, so apps that never show a map do not download
// Leaflet. Output: dist-map/map.js (copied to src/indah/static/).
//
// Vite's library mode keeps whitespace in an ES build (it skips whitespace minification so it
// can keep /*#__PURE__*/ hints), which doubles the module (307 KB raw, 72 KB gzip against 151 KB
// and 43 KB). Nothing consumes those hints here, so minify fully in a last pass. The build target
// must stay "esnext": any other makes Vite re-print the minified code with whitespace afterwards.
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
    outDir: "dist-map",
    emptyOutDir: true,
    // "esnext" so Vite's own transpile step leaves the output alone; minifyFully targets es2020.
    target: "esnext",
    minify: false,
    lib: { entry: "map/map.js", formats: ["es"], fileName: () => "map.js" },
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
});
