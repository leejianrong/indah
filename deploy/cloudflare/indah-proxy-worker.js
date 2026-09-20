// Cloudflare Worker: path-proxy for indah.abangai.dev.
//
// DNS can only route a whole hostname to one origin, and indah has two independent
// origins that both need to live under this one subdomain:
//   - the Fly-hosted demo gallery (the "first thing users see" landing page)
//   - the Zensical docs, built and published separately to GitHub Pages
//
// This Worker sits in front of the (Cloudflare-proxied) indah.abangai.dev DNS record
// and picks an origin per request path, so the two pipelines stay fully independent -
// no code change needed in either the gallery app or the docs build to deploy this.
//
// Route: indah.abangai.dev/*  (configured via the Workers Routes API / dashboard)

const GALLERY_ORIGIN = "https://indah-demos.fly.dev";
// indah's docs are a GitHub *project* Pages site (repo "indah", not a user/org root
// pages site), so they're served under a /indah/ path prefix on github.io.
const DOCS_ORIGIN = "https://leejianrong.github.io";
const DOCS_PATH_PREFIX = "/indah";

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const isDocs = url.pathname === "/docs" || url.pathname.startsWith("/docs/");

    let target;
    if (isDocs) {
      const rest = url.pathname.slice("/docs".length) || "/";
      target = new URL(DOCS_ORIGIN);
      target.pathname = DOCS_PATH_PREFIX + rest;
    } else {
      target = new URL(GALLERY_ORIGIN);
      target.pathname = url.pathname;
    }
    target.search = url.search;

    const originRequest = new Request(target, request);
    originRequest.headers.set("Host", target.host);
    return fetch(originRequest);
  },
};
