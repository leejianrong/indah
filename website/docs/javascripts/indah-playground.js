// <indah-playground>: edit indah code and run it in your own browser (ADR-0041, IND-83).
// The markup (a textarea, the buttons, a list of starting points) is in the page, filled at build
// time, so it reads without JavaScript. Nothing heavy loads on page view: Run opens frame.html (the
// shell plus a Pyodide worker) in an iframe and hands it the code. The code runs in a worker in this
// browser tab and is sent nowhere. Stop, or a worker that stops answering, throws the iframe away.
(() => {
  if (customElements.get("indah-playground")) return;
  const here = document.currentScript && document.currentScript.src;
  const base = new URL("../assets/live/", here || location.href).href;
  const STUCK_MS = 5000; // a worker that has not beaten for this long is in an endless loop

  class IndahPlayground extends HTMLElement {
    connectedCallback() {
      if (this._ready) return;
      this._ready = true;
      const q = (s) => this.querySelector(s);
      this._code = q(".indah-play-code");
      this._status = q(".indah-play-status");
      this._error = q(".indah-play-error");
      this._stage = q(".indah-play-stage");
      this._run = q(".indah-play-run");
      this._stop = q(".indah-play-stop");
      this._reset = q(".indah-play-reset");
      this._pick = q(".indah-play-pick");
      if (!this._code || !this._run) return;
      this._starters = {};
      for (const pre of this.querySelectorAll("[data-starter]")) {
        this._starters[pre.dataset.starter] = pre.textContent;
      }
      for (const el of this.querySelectorAll("[hidden].indah-play-js")) el.hidden = false;
      this._run.addEventListener("click", () => this.run());
      this._stop.addEventListener("click", () => this.stop("Stopped."));
      this._reset.addEventListener("click", () => this._load(this._pick.value));
      this._pick.addEventListener("change", () => this._load(this._pick.value));
      this._code.addEventListener("keydown", (e) => this._keys(e));
      this._code.addEventListener("blur", () => (this._trap = true));
      this._trap = true;
    }
    disconnectedCallback() {
      this.stop("");
    }
    _load(id) {
      if (id in this._starters) this._code.value = this._starters[id];
      this._code.focus();
    }
    // Tab indents inside the editor; Escape lets Tab leave it (no keyboard trap); Ctrl/Cmd+Enter runs.
    _keys(e) {
      if (e.key === "Escape") {
        this._trap = false;
        this._say("Tab now leaves the editor.");
      } else if (e.key === "Tab" && this._trap && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
        e.preventDefault();
        const t = this._code;
        t.setRangeText("    ", t.selectionStart, t.selectionEnd, "end");
      } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        this.run();
      } else if (e.key !== "Tab" && e.key !== "Shift") {
        this._trap = true;
      }
    }
    _say(text) {
      this._status.textContent = text;
    }
    _fail(text) {
      this._error.textContent = text;
      this._error.hidden = !text;
    }
    run() {
      this.stop("");
      this._fail("");
      const frame = document.createElement("iframe");
      frame.className = "indah-live-frame indah-play-frame";
      frame.title = "Your app (live)";
      frame.src = base + "frame.html?playground=1";
      this._frame = frame;
      this._running = false;
      this._beat = Date.now();
      this._on = (e) => {
        const m = e.data;
        if (e.source !== frame.contentWindow || !m || m.source !== "indah-live") return;
        if (m.type === "need-code") {
          frame.contentWindow.postMessage(
            { source: "indah-playground", type: "code", code: this._code.value },
            "*",
          );
        } else if (m.type === "progress") this._say(m.text + "...");
        else if (m.type === "running") {
          this._running = true; // from here a silent worker means an endless loop
          this._beat = Date.now();
        } else if (m.type === "beat") this._beat = Date.now();
        else if (m.type === "ready") {
          this._running = true;
          this._say("Running. Interact with it below.");
        } else if (m.type === "height") frame.style.height = Math.min(Math.max(m.height + 4, 120), 900) + "px";
        else if (m.type === "error") {
          const own = m.user === true;
          this.stop(own ? "Your code raised an error." : "Could not start.");
          this._fail(m.message);
        }
      };
      addEventListener("message", this._on);
      this._watch = setInterval(() => {
        if (this._running && Date.now() - this._beat > STUCK_MS) {
          this.stop("Stopped: the code did not return for 5 seconds (is there an endless loop?).");
        }
      }, 500);
      this._run.disabled = false;
      this._stop.disabled = false;
      this._say("Loading about 9 MB the first time...");
      this._stage.append(frame);
    }
    stop(message) {
      if (this._on) removeEventListener("message", this._on);
      if (this._watch) clearInterval(this._watch);
      // Removing the iframe ends its worker, which is the only way to stop Python that never returns.
      if (this._frame) this._frame.remove();
      this._frame = this._on = this._watch = null;
      this._running = false;
      if (this._stop) this._stop.disabled = true;
      if (this._status) this._say(message);
    }
  }
  customElements.define("indah-playground", IndahPlayground);
})();
