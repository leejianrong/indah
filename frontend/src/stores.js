import { writable } from "svelte/store";

// The tree skeleton: {id, type, children:[...]} with no props (props live in
// nodeProps so a patch updates only the affected entries).
export const structure = writable(null);

// id -> props object. Patches merge into these entries.
export const nodeProps = writable(new Map());

export const status = writable({ live: false, text: "connecting…" });

// A transient error message shown as a toast when a handler fails server-side.
export const toast = writable(null);
