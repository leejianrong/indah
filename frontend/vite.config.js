import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { viteSingleFile } from "vite-plugin-singlefile";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

// The shell loads the map module by a content-hashed URL (api/map.js?v=<hash>, ADR-0039/0042), so
// a new release is fetched at once and an old one is cached for good. The hash is the first 16
// hex digits of the file's SHA-1, the same value the server uses for its ETag. `npm run build`
// builds dist-map first, so the file exists here.
let mapHash = "dev"; // `vite` (the dev server) runs without a built map module
try {
  mapHash = createHash("sha1").update(readFileSync("dist-map/map.js")).digest("hex").slice(0, 16);
} catch {}

// Bundle everything (JS + CSS) into a single index.html so the Python server
// serves one self-contained file over one port, with no external asset requests
// to break behind Colab/Runpod proxy base paths (ADR-0001, ADR-0004).
export default defineConfig({
  plugins: [svelte(), viteSingleFile()],
  define: { __MAP_HASH__: JSON.stringify(mapHash) },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2020",
  },
});
