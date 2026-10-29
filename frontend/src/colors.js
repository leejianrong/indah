// Colours that follow the theme (ADR-0046). A canvas cannot read CSS variables, so a value such
// as "var(--x-explore)" is resolved against the element it is drawn in, and the drawing is
// redone when the light/dark switch changes the page's data-theme.

const VAR = /^var\(\s*(--[a-z0-9-]+)\s*(?:,\s*([^)]+))?\)$/i;

// A plain colour passes through. A var(--name[, fallback]) is looked up on `el` (so a token set
// on :root or on an ancestor is found), falling back to the fallback, then to the input.
export function resolveColor(el, value) {
  if (typeof value !== "string") return value;
  const m = VAR.exec(value.trim());
  if (!m) return value;
  const found = el ? getComputedStyle(el).getPropertyValue(m[1]).trim() : "";
  return found || (m[2] ? m[2].trim() : value);
}

// Call `fn` whenever the theme switches. Returns the function that stops listening.
export function onThemeChange(fn) {
  if (typeof MutationObserver === "undefined" || typeof document === "undefined") return () => {};
  const mo = new MutationObserver(fn);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => mo.disconnect();
}
