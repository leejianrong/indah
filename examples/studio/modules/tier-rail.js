// A tier rail: one dot per step, the chosen one filled. The demo module for indah's
// web-component bridge (ADR-0039).
//
// The contract: the default export is an HTMLElement class (indah picks its tag name), props
// arrive as properties (`steps`, `value`, `label`), and interaction leaves as CustomEvents
// (`change` with {value}, written back to the bound signal, and `pick` with {index, label}).
// Colours come from the shell's CSS variables, so the rail follows light and dark. Text goes in
// with textContent, never innerHTML: a prop is data, not markup.

const CSS = `
  :host { display: block; font-family: var(--font-body, system-ui, sans-serif); color: var(--text, #222); }
  .label { color: var(--muted, #666); font-size: 0.85rem; margin-bottom: 0.4rem; }
  .rail { display: flex; align-items: center; gap: 0.35rem; flex-wrap: wrap; }
  button {
    font: inherit; cursor: pointer; padding: 0.3rem 0.7rem;
    border: 1px solid var(--outline, #999); border-radius: var(--radius-control, 999px);
    background: var(--surface, #fff); color: inherit;
  }
  button[aria-pressed="true"] { background: var(--primary, #b5296b); border-color: var(--primary, #b5296b); color: var(--on-primary, #fff); }
  button:focus-visible { outline: 2px solid var(--primary, #b5296b); outline-offset: 2px; }
  .bar { width: 0.8rem; height: 2px; background: var(--outline, #999); }
`;

let sheet = null;
try {
  sheet = new CSSStyleSheet(); // a constructable stylesheet needs no inline <style>, so no nonce
  sheet.replaceSync(CSS);
} catch (_) {
  sheet = null;
}

export default class TierRail extends HTMLElement {
  #steps = [];
  #value = 0;
  #label = "";
  #buttons = [];
  #labelEl;
  #rail;

  constructor() {
    super();
    const root = this.attachShadow({ mode: "open" });
    if (sheet) root.adoptedStyleSheets = [sheet];
    this.#labelEl = document.createElement("div");
    this.#labelEl.className = "label";
    this.#rail = document.createElement("div");
    this.#rail.className = "rail";
    this.#rail.setAttribute("role", "group");
    root.append(this.#labelEl, this.#rail);
  }

  set steps(v) {
    this.#steps = Array.isArray(v) ? v.map(String) : [];
    this.#sync();
  }
  get steps() {
    return this.#steps;
  }
  set value(v) {
    this.#value = Number(v) || 0;
    this.#sync();
  }
  get value() {
    return this.#value;
  }
  set label(v) {
    this.#label = String(v ?? "");
    this.#sync();
  }
  get label() {
    return this.#label;
  }

  connectedCallback() {
    if (!sheet && !this.shadowRoot.querySelector("style")) {
      // No constructable stylesheets: use a <style> with the page nonce, which the shell sets on
      // the element before it is attached (the constructor runs too early to see it).
      const style = document.createElement("style");
      style.setAttribute("nonce", this.cspNonce || "");
      style.textContent = CSS;
      this.shadowRoot.prepend(style);
    }
    this.#sync();
  }

  // Update in place so a focused button keeps focus; rebuild only when the count changes.
  #sync() {
    this.#labelEl.textContent = this.#label;
    this.#labelEl.hidden = !this.#label;
    this.#rail.setAttribute("aria-label", this.#label || "Tiers");
    if (this.#buttons.length !== this.#steps.length) {
      this.#rail.replaceChildren();
      this.#buttons = this.#steps.map((_, i) => {
        const b = document.createElement("button");
        b.type = "button";
        b.addEventListener("click", () => this.#choose(i));
        if (i) {
          const bar = document.createElement("span");
          bar.className = "bar";
          this.#rail.appendChild(bar);
        }
        this.#rail.appendChild(b);
        return b;
      });
    }
    this.#buttons.forEach((b, i) => {
      b.textContent = this.#steps[i];
      b.setAttribute("aria-pressed", String(i === this.#value));
    });
  }

  #choose(i) {
    this.#value = i;
    this.#sync();
    this.dispatchEvent(new CustomEvent("change", { detail: { value: i } }));
    this.dispatchEvent(new CustomEvent("pick", { detail: { index: i, label: this.#steps[i] } }));
  }
}
