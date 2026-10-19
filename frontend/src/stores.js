import { readable, writable } from "svelte/store";

// The tree skeleton: {id, type, children:[...]} with no props (props live in
// nodeProps so a patch updates only the affected entries).
export const structure = writable(null);

// id -> props object. Patches merge into these entries.
export const nodeProps = writable(new Map());

export const status = writable({ live: false, text: "connecting…" });

// Transient messages, newest last: [{id, message, kind, ttl}]. A failed handler
// pushes an "error" one; ctx.toast pushes any kind (ADR-0030).
export const toasts = writable([]);

// The current time in ms, ticking once a second while anything is subscribed, so every
// relative-time cell on the page ("3s ago") is refreshed from one shared timer.
export const now = readable(Date.now(), (set) => {
  const id = setInterval(() => set(Date.now()), 1000);
  return () => clearInterval(id);
});

// Keyboard shortcuts registered by mounted `shortcuts` nodes (ADR-0030): node id ->
// [{keys, label}]. The `?` help overlay lists them all; helpOpen toggles it.
export const shortcutRegistry = writable(new Map());
export const helpOpen = writable(false);
