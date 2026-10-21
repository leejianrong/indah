# ADR-0032: CodeEditor, a lazily loaded CodeMirror module for JSON and YAML

- Status: Accepted
- Date: 2026-10-21
- Deciders: Jian (owner)
- Amends: ADR-0004 (the shell fetches nothing at runtime)

## Context

The semula plan (`docs/SEMULA-REQUESTS-PLAN.md`, E3, Q4) gated a real editor on whether
`TextArea` plus `JsonTree` plus `Diff` was enough. The owner decided it is not: entry bodies
need highlighting, indentation, auto-closing brackets and quotes and the like. The owner scoped
it to JSON and YAML to start, for data and config, not general coding. semula confirmed the
shape: stored requests and answers are JSON, plain text matters too, YAML is not needed (we
keep it, it costs about 5 KB), bodies are 1 to 10 KB typically and up to 100 to 500 KB, and
it wants read-only snapshots, a format button that keeps key order, a lint error with its
position, a Save shortcut, and focus-safe typing.

CodeMirror 6 (MIT) is the editor. Inlined into `index.html` it would add about 60 percent to
every app's first load for a feature most never use.

## Decision

- **`CodeEditor(value, *, language="json" | "yaml" | "text", read_only=, lint=, height=,
  label=, placeholder=, format_button=, on_save=)`**, two-way bound to a `Signal[str]`.
- **A separate same-origin module.** The editor builds to `src/indah/static/editor.js` (its own
  Vite config, `frontend/vite.editor.config.js`) and is served at `GET /api/editor.js` with an
  ETag and `Cache-Control: no-cache`. The shell `import()`s it on the first `codeeditor`
  render, so an app without one never requests it. Measured: 633 KB raw, 179 KB gzip, JSON and
  YAML included. JSON and YAML are bundled together because they add a few KB; per-language
  chunks (tried for Python, Markdown, SQL, JavaScript) were dropped with those languages.
- **ADR-0004 amended.** "Fetches nothing at runtime" becomes "fetches nothing from a third
  party": a lazily loaded module served by the app itself is fine. The wheel stays Node-free at
  install and runtime (`make cleanroom` passes with the file inside it); CI's `frontend` job
  now also fails when `editor.js` is stale.
- **Features:** highlighting, auto-indent, auto-closing brackets and quotes, bracket matching,
  folding, search, line numbers, history, multiple cursors, and JSON lint (parse error with its
  position, in the gutter and inline). Tab indents; Ctrl/Cmd-M turns that off so the keyboard
  can leave the editor (WCAG 2.1.2).
- **Tokens only.** The editor theme and syntax colours are CSS variables from ADR-0014 and
  ADR-0031 (`--surface-2`, `--primary`, `--secondary`, `--warn`, `--muted`), so light, dark and an
  app `Theme` apply with no editor-specific colours.
- **Focus rule (ADR-0013).** The focused editor is client-owned: server values that arrive
  while it has focus are ignored. Edits are debounced 150 ms and flushed on blur. On blur the
  editor adopts the latest server value only when nothing was just sent (otherwise the old
  value would revert the typing before its echo arrives).
- **Format** is server-side for JSON (`json.dumps(json.loads(text), indent=2,
  ensure_ascii=False)`), so key order and big integers are preserved, and invalid text is left
  alone. **Save** posts `{value}` then calls `on_save`, so the handler sees the latest text.
- **Fallback.** If the module cannot load, the shell shows a plain `<textarea>` with the same
  binding.
- **Wire:** a new `codeeditor` node type with additive props and events (`protocol.md`). No
  `protocol_version` bump.

## Not in scope

Autocomplete, a JSON schema check (semula validates on the server), other languages, a
side-by-side diff inside the editor (use `Diff` next to it), and highlighting of `{{placeholder}}`
tokens in plain text (a possible later addition).

## Consequences

- The wheel grows by about 633 KB raw (179 KB gzip of it travels to a browser, and only when
  an editor renders).
- Large bodies are bounded by `max_event_bytes` (default 1 MiB); semula should raise it if its
  worst case reaches 500 KB of text plus overhead.
- Adding a language later is a small change in `frontend/editor/editor.js`; splitting languages
  into chunks is available if the set grows.
