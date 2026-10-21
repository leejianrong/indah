// The lazily loaded code editor (ADR-0032). CodeMirror 6, built to src/indah/static/editor.js
// as its own ES module and fetched from the same origin on the first `codeeditor` render,
// so an app that never uses one pays nothing. It is styled only through the shell's design
// tokens (ADR-0014, ADR-0031), so light/dark and an app Theme apply with no editor-specific
// colours.
import { Annotation, Compartment, EditorState } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  MatchDecorator,
  ViewPlugin,
  drawSelection,
  dropCursor,
  highlightActiveLine,
  highlightActiveLineGutter,
  highlightSpecialChars,
  keymap,
  lineNumbers,
  rectangularSelection,
  crosshairCursor,
  placeholder,
} from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import {
  HighlightStyle,
  StreamLanguage,
  bracketMatching,
  foldGutter,
  foldKeymap,
  indentOnInput,
  syntaxHighlighting,
} from "@codemirror/language";
import { closeBrackets, closeBracketsKeymap } from "@codemirror/autocomplete";
import { highlightSelectionMatches, searchKeymap } from "@codemirror/search";
import { lintGutter, lintKeymap, linter } from "@codemirror/lint";
import { json, jsonParseLinter } from "@codemirror/lang-json";
import { yaml } from "@codemirror/lang-yaml";
import { tags as t } from "@lezer/highlight";

const External = Annotation.define();

// `{{name}}` template placeholders (semula answers carry {{now}}, {{uuid}}) get a token
// colour in every language, so they read as slots rather than as text. Highlight only: the
// names are not completed or validated (IND-138).
const placeholderMatcher = new MatchDecorator({
  regexp: /\{\{[^{}\n]*\}\}/g,
  decoration: Decoration.mark({ class: "cm-tpl" }),
});
const placeholderTokens = ViewPlugin.fromClass(
  class {
    constructor(view) {
      this.decorations = placeholderMatcher.createDeco(view);
    }
    update(update) {
      this.decorations = placeholderMatcher.updateDeco(update, this.decorations);
    }
  },
  { decorations: (plugin) => plugin.decorations },
);

export const LANGUAGES = ["json", "yaml", "text"];

// JSON and YAML to start (data and config, not code). Both are bundled: together they add a
// few KB over the editor core, so there is nothing to gain from splitting them.
const LANGUAGES_SUPPORT = {
  json: () => ({ support: json(), lint: jsonParseLinter() }),
  yaml: () => ({ support: yaml() }),
};

async function loadLanguage(name) {
  const make = LANGUAGES_SUPPORT[name];
  return make ? make() : { support: [] };
}

// Colours come from the shell's tokens, so the editor follows light/dark and any app Theme.
const highlight = HighlightStyle.define([
  { tag: [t.keyword, t.operatorKeyword, t.modifier, t.controlKeyword], color: "var(--primary)" },
  { tag: [t.string, t.special(t.string), t.regexp], color: "var(--secondary)" },
  { tag: [t.number, t.bool, t.null, t.atom], color: "var(--warn)" },
  { tag: [t.propertyName, t.attributeName], color: "var(--text)", fontWeight: "600" },
  { tag: [t.function(t.variableName), t.function(t.propertyName), t.className, t.typeName], color: "var(--primary)" },
  { tag: [t.comment, t.lineComment, t.blockComment], color: "var(--muted)", fontStyle: "italic" },
  { tag: [t.heading], color: "var(--primary)", fontWeight: "700" },
  { tag: [t.emphasis], fontStyle: "italic" },
  { tag: [t.strong], fontWeight: "700" },
  { tag: [t.link, t.url], color: "var(--secondary)", textDecoration: "underline" },
  { tag: [t.meta, t.punctuation, t.separator, t.bracket], color: "var(--muted)" },
  { tag: t.invalid, color: "var(--err)" },
]);

const theme = EditorView.theme({
  "&": {
    color: "var(--text)",
    backgroundColor: "var(--surface-2)",
    border: "1px solid var(--outline)",
    borderRadius: "var(--radius-sm)",
    fontSize: "0.85rem",
  },
  "&.cm-focused": {
    outline: "none",
    borderColor: "var(--primary)",
    boxShadow: "0 0 0 3px color-mix(in srgb, var(--primary) 22%, transparent)",
  },
  ".cm-scroller": { fontFamily: "var(--font-mono)", lineHeight: "1.5", overflow: "auto" },
  ".cm-content": { caretColor: "var(--primary)", padding: "0.4rem 0" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--primary)" },
  "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, ::selection": {
    backgroundColor: "color-mix(in srgb, var(--primary) 24%, transparent)",
  },
  ".cm-gutters": {
    backgroundColor: "var(--surface-3)",
    color: "var(--muted)",
    border: "none",
    borderRight: "1px solid var(--outline-soft)",
    borderRadius: "var(--radius-sm) 0 0 var(--radius-sm)",
  },
  ".cm-activeLine": { backgroundColor: "color-mix(in srgb, var(--primary) 7%, transparent)" },
  ".cm-activeLineGutter": { backgroundColor: "var(--surface-2)", color: "var(--text)" },
  ".cm-foldPlaceholder": {
    backgroundColor: "var(--surface-3)",
    border: "1px solid var(--outline)",
    color: "var(--muted)",
  },
  "&.cm-focused .cm-matchingBracket": {
    backgroundColor: "color-mix(in srgb, var(--secondary) 28%, transparent)",
    outline: "1px solid var(--secondary)",
  },
  "&.cm-focused .cm-nonmatchingBracket": {
    backgroundColor: "color-mix(in srgb, var(--err) 25%, transparent)",
  },
  ".cm-selectionMatch": { backgroundColor: "color-mix(in srgb, var(--secondary) 20%, transparent)" },
  ".cm-placeholder": { color: "var(--muted)" },
  ".cm-tpl": {
    color: "var(--secondary)",
    backgroundColor: "color-mix(in srgb, var(--secondary) 16%, transparent)",
    borderRadius: "3px",
  },
  ".cm-panels": {
    backgroundColor: "var(--surface)",
    color: "var(--text)",
    borderTop: "1px solid var(--outline)",
  },
  ".cm-panels input, .cm-panels button": { font: "inherit", fontSize: "0.8rem" },
  ".cm-tooltip": {
    backgroundColor: "var(--surface)",
    color: "var(--text)",
    border: "1px solid var(--outline)",
    borderRadius: "var(--radius-sm)",
    boxShadow: "var(--shadow)",
  },
  ".cm-diagnostic": { fontFamily: "var(--font-body)", fontSize: "0.8rem" },
  ".cm-diagnostic-error": { borderLeft: "3px solid var(--err)" },
  ".cm-lintRange-error": { backgroundImage: "none", textDecoration: "underline wavy var(--err)" },
});

/**
 * Mount an editor in `parent`.
 *   doc, language, readOnly, lint, height, label, placeholder
 *   onChange(text)  called on every user edit (never on setDoc)
 *   onSave(text)    called on Mod-s (Ctrl/Cmd-S); without it the browser keeps the key
 * Returns {setDoc, getDoc, focus, hasFocus, destroy}.
 */
export function createEditor(parent, opts = {}) {
  const lang = new Compartment();
  const readOnly = new Compartment();
  const lintC = new Compartment();
  // Tab indents by default; Ctrl-M turns that off so a keyboard user can Tab out (WCAG 2.1.2).
  const tabKey = new Compartment();
  let tabTraps = true;

  // The current language and lint switch; applied once the language chunk has loaded.
  let current = { language: opts.language ?? "text", lint: opts.lint !== false };
  let token = 0; // so a slow chunk for an old language never overwrites a newer choice
  async function applyLanguage() {
    const mine = ++token;
    const { language, lint } = current;
    const loaded = await loadLanguage(language).catch(() => ({ support: [] }));
    if (mine !== token) return;
    view.dispatch({
      effects: [
        lang.reconfigure(loaded.support),
        lintC.reconfigure(lint && loaded.lint ? [linter(loaded.lint), lintGutter()] : []),
      ],
    });
  }

  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc: opts.doc ?? "",
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        highlightSpecialChars(),
        history(),
        foldGutter(),
        drawSelection(),
        dropCursor(),
        EditorState.allowMultipleSelections.of(true),
        indentOnInput(),
        syntaxHighlighting(highlight, { fallback: true }),
        bracketMatching(),
        closeBrackets(),
        rectangularSelection(),
        crosshairCursor(),
        highlightActiveLine(),
        highlightSelectionMatches(),
        EditorView.lineWrapping,
        placeholderTokens,
        theme,
        opts.placeholder ? placeholder(opts.placeholder) : [],
        lang.of([]),
        lintC.of([]),
        readOnly.of([EditorState.readOnly.of(!!opts.readOnly), EditorView.editable.of(!opts.readOnly)]),
        tabKey.of(keymap.of([indentWithTab])),
        keymap.of([
          {
            key: "Mod-s",
            preventDefault: true,
            run: (v) => {
              opts.onSave?.(v.state.doc.toString());
              return !!opts.onSave;
            },
          },
          {
            key: "Mod-m",
            run: () => {
              tabTraps = !tabTraps;
              view.dispatch({
                effects: tabKey.reconfigure(tabTraps ? keymap.of([indentWithTab]) : []),
              });
              return true;
            },
          },
          ...closeBracketsKeymap,
          ...defaultKeymap,
          ...searchKeymap,
          ...historyKeymap,
          ...foldKeymap,
          ...lintKeymap,
        ]),
        EditorView.contentAttributes.of({
          "aria-label": opts.label || "Code editor",
          "aria-multiline": "true",
        }),
        EditorView.updateListener.of((u) => {
          if (u.docChanged && !u.transactions.every((tr) => tr.annotation(External))) {
            opts.onChange?.(u.state.doc.toString());
          }
        }),
      ],
    }),
  });

  applyLanguage();

  return {
    getDoc: () => view.state.doc.toString(),
    // Replace the whole document from outside (a server value). Not reported to onChange.
    setDoc(text) {
      if (text === view.state.doc.toString()) return;
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: text },
        annotations: External.of(true),
      });
    },
    configure({ language, readOnly: ro, lint }) {
      if (ro !== undefined) {
        view.dispatch({
          effects: readOnly.reconfigure([
            EditorState.readOnly.of(!!ro),
            EditorView.editable.of(!ro),
          ]),
        });
      }
      if (language !== undefined || lint !== undefined) {
        current = { language: language ?? current.language, lint: lint ?? current.lint };
        applyLanguage();
      }
    },
    focus: () => view.focus(),
    hasFocus: () => view.hasFocus,
    destroy: () => view.destroy(),
  };
}

