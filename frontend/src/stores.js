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

const MAX_TOASTS = 4;
let toastSeq = 0;

export function dismissToast(id) {
  toasts.update((list) => list.filter((t) => t.id !== id));
}

// ttl is seconds; 0 keeps the toast until it is clicked. `action` is {id, label} when
// ctx.toast was given one (IND-160). The shell itself also uses this for a message that
// needs no server (a "Copied" toast, IND-158).
export function showToast(message, kind = "info", ttl = 4, action = null) {
  const id = ++toastSeq;
  toasts.update((list) => [...list, { id, message, kind, ttl, action }].slice(-MAX_TOASTS));
  if (ttl > 0) setTimeout(() => dismissToast(id), ttl * 1000);
}

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
