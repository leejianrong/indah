import { defineConfig } from "vite";
import { transform } from "esbuild";

// The code editor is its own ES module, fetched lazily by the shell on the first
// `codeeditor` render (ADR-0032). It is not inlined into index.html, so apps that never use
// one do not download it. Output: dist-editor/editor.js (copied to src/indah/static/).
//
// Vite's library mode keeps whitespace in an ES build (it skips whitespace minification so it
// can keep /*#__PURE__*/ hints), so the module was indented and about 2x its minified size. Nothing
// consumes those hints here, so minify fully in a last pass (the same as the map module, ADR-0042).
// The build target must stay "esnext": any other makes Vite re-print the minified code with
// whitespace afterwards.
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
    outDir: "dist-editor",
    emptyOutDir: true,
    // "esnext" so Vite's own transpile step leaves the output alone; minifyFully targets es2020.
    target: "esnext",
    minify: false,
    lib: { entry: "editor/editor.js", formats: ["es"], fileName: () => "editor.js" },
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
});
