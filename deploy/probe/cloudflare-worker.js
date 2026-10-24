// Cloudflare Worker for the probe (IND-170): a pass-through to the probe app, so the check goes
// through the same kind of hop production does (browser -> Cloudflare -> Worker fetch() -> Fly).
// It is a SECOND Worker on probe.abangai.dev. Production's `indah-proxy` Worker and its route
// (indah.abangai.dev/*) are not touched. Delete this Worker when the check is done.
const ORIGIN = "https://indah-probe.fly.dev";

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const target = new URL(ORIGIN);
    target.pathname = url.pathname;
    target.search = url.search;
    const originRequest = new Request(target, request);
    originRequest.headers.set("Host", target.host);
    return fetch(originRequest);
  },
};
