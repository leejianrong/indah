// <indah-live page="chapter/page">: a Studio page in the docs (ADR-0041). Nothing heavy loads on page
// view; "Run it" opens frame.html (the shell plus a Pyodide worker) in an iframe. One runs at a time.
(() => {
  if (customElements.get("indah-live")) return;
  const here = document.currentScript && document.currentScript.src;
  const base = new URL("../assets/live/", here || location.href).href;
  let active = null;
  let pages = null;
  const getPages = () => (pages ||= fetch(base + "pages.json").then((r) => r.json()));
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  class IndahLive extends HTMLElement {
    connectedCallback() {
      if (this._ready) return;
      this._ready = true;
      (this.querySelector(".indah-live-card") ? Promise.resolve() : this._render()).then(() => this._wire());
    }
    disconnectedCallback() {
      if (active === this) this.stop();
    }
    async _render() {
      const id = this.getAttribute("page");
      const page = (await getPages()).find((p) => p.id === id);
      if (!page) {
        this.textContent = "No Studio page " + id;
        return;
      }
      const action = page.runnable
        ? '<button type="button" class="indah-live-run" hidden>Run it</button> <span class="indah-live-note">Loads about 9 MB, then runs in your browser.</span>'
        : '<span class="indah-live-note">This example needs a server: ' + esc(page.local_only || "") + ". Run <code>make demo</code> to try it.</span>";
      this.innerHTML =
        '<figure class="indah-live-card"><figcaption><strong>' + esc(page.title) + "</strong> - " + esc(page.summary) +
        '</figcaption><pre class="indah-live-source"><code class="language-python">' + esc(page.source || "") +
        '</code></pre><p class="indah-live-actions">' + action +
        ' <a href="https://github.com/leejianrong/indah/blob/main/docs/STUDIO.md">Open in the Studio</a></p>' +
        '<div class="indah-live-status" role="status" aria-live="polite"></div><div class="indah-live-stage"></div></figure>';
    }
    _wire() {
      this._btn = this.querySelector(".indah-live-run");
      if (!this._btn) return;
      this._btn.hidden = false;
      this._btn.addEventListener("click", () => (this._frame ? this.stop() : this.run()));
    }
    _say(text) {
      this.querySelector(".indah-live-status").textContent = text;
    }
    run() {
      if (active && active !== this) active.stop();
      active = this;
      const title = this.querySelector("figcaption strong");
      const frame = document.createElement("iframe");
      frame.className = "indah-live-frame";
      frame.title = (title ? title.textContent : "Live example") + " (live)";
      frame.src = base + "frame.html?page=" + encodeURIComponent(this.getAttribute("page"));
      this._frame = frame;
      this._on = (e) => {
        const m = e.data;
        if (e.source !== frame.contentWindow || !m || m.source !== "indah-live") return;
        if (m.type === "progress") this._say(m.text + "...");
        else if (m.type === "ready") this._say("Running. Interact with it below.");
        else if (m.type === "height") frame.style.height = Math.min(Math.max(m.height + 4, 120), 900) + "px";
        else if (m.type === "error") this._say("Could not start: " + m.message + " Run `make demo` to try it locally.");
      };
      addEventListener("message", this._on);
      this._btn.textContent = "Stop";
      this._say("Loading about 9 MB...");
      this.querySelector(".indah-live-stage").append(frame);
    }
    stop() {
      if (this._on) removeEventListener("message", this._on);
      if (this._frame) this._frame.remove();
      this._frame = this._on = null;
      if (active === this) active = null;
      if (this._btn) this._btn.textContent = "Run it";
      this._say("");
    }
  }
  customElements.define("indah-live", IndahLive);
})();
