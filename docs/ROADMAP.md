# Roadmap: 0.4.1 to 1.0

- Status: **Proposed 2026-10-22.** Owner decisions of 2026-10-22 are recorded under "Decisions" below.
- Basis: `main` at 0.4.0 (on PyPI), the 38 open cards on board IND (id 30), `docs/SEMULA-REQUESTS-PLAN.md`,
  `docs/STUDIO.md`, `docs/RELEASING.md`, ADR-0005 (additive changes).
- Sizing: about 25 points is one release of about two weeks for one agent. The semula plan delivered
  99 points in about 36 engineer-days (about 2.75 points a day), so 25 leaves room for the
  release chores. Treat the points as the card's code only (see "Hidden cost" below).

## Summary

| Release | Theme | Points | Cards | Protocol |
|---------|-------|--------|-------|----------|
| 0.4.1 (patch, about 1 week) | Public demos work; hosted path verified | 8 | IND-167, IND-33, 2 new verification cards | 1 |
| 0.5.0 | Build your own, and the app skeleton | 24 | IND-149, 150, 146, 147, 151, 156, 144, 145 | 1 |
| 0.6.0 | Tables, text and small controls | 25 + 5 | IND-148, 166, 153, 154, 152, 160, 164, 158, 161, 168, plus the demo cleanup card (IND-172) | 1 |
| 0.7.0 (provisional) | Hosted Studio, command palette, promoted visuals, live docs | 28 | IND-173, 174, 175, 169, 176 (83a), 165, 157, 162, 163 | 1 |
| 0.8.0 (provisional) | Live media and annotation | 22 | IND-74 (split 3 ways), 64, 65, 71, 56, 62 | 1, decided in the ADR |
| Later | Needs a decision or has no demand yet | 24 | IND-57, 81, 66, 83b (IND-83), 61, 159 | - |
| Closed as folded | | 1 | IND-155 (into IND-166) | - |

All 38 cards are placed: 2 + 8 + 10 + 8 + 6 + 3 + 1 = 38 (0.4.1 also gets two new cards, not counted).

`protocol_version` stays **1** for every release above. No card forces a bump under ADR-0005's rule
(a new component type, prop or message type is additive). The one card that could change this is
IND-74 (WebSocket for live media): its ADR must show that the frames are the same JSON and that the
transport is a negotiated upgrade. If it needs a mandatory handshake or a change to an existing field,
that is a v2 and the release becomes 0.8.0 with a bump, decided by the owner.

## Decisions (owner, 2026-10-22)

1. Redeploy the Fly gallery when ready (IND-167). Needs `fly auth login` on the machine that deploys.
2. ADR-0039 (the web-component bridge) may be committed; it stays Proposed until the owner accepts it.
3. IND-166: **plain `Text` looks like normal body text**, not a title or header. The old readout look
   becomes opt-in. A new card, "Clean up and rework all demos and galleries after the Text redesign"
   (IND-172, 5 points), follows IND-166 in 0.6.0.

## Overlaps and ordering found

1. **IND-155 inside IND-166.** IND-166 already says it folds IND-155. Close IND-155 as folded. Both
   change the default look of `Text`, so the owner decides first (see 0.6.0). `Text(size="body")`
   from 0.4.0 stays as a supported alias so apps that adopted it do not break.
2. **IND-145 and the 0.4.0 `MultiSelect` change.** 0.4.0 changed only how `MultiSelect` renders (a
   checkbox list, same wire format). IND-145 changes where `options` come from and what happens to the
   selection when they change. No code conflict, but IND-145 must touch the checkbox list, and its
   "applies to Chips and Segmented" line means **IND-144 goes first**. Order: 144, then 145.
3. **IND-149 before IND-150.** The bridge build is blocked until the ADR is accepted. The ADR also
   decides how much of IND-157, 162 and 163 semula can build itself (next point).
4. **IND-157, 162, 163 against the bridge.** The bridge card says the tier rail, the activity strip and
   the shaded text otherwise wait for an indah release. Once IND-150 ships (0.5.0), semula can build
   these three itself. They are placed in 0.7.0 as *promotions*: build them in indah only if semula's
   versions prove general. If the owner prefers built-ins regardless, move them to 0.6.0 and push IND-159 and
   IND-161 out.
5. **IND-148 before IND-163.** Steps must work in a table cell (R2-5), which needs the rich cell spec.
6. **IND-146 before IND-147, IND-151, IND-156.** The rail is built from the layout primitives, and the
   NavItem and logo live in it.
7. **IND-168 before IND-169.** IND-169 is blocked by the Studio-home decision. IND-83 (Pyodide) is one of
   the two options IND-169 names, so a 3-point spike (83a) runs in the same release and decides it.
8. **IND-164 and IND-165 both use Shortcuts.** Build 164 (0.6.0) first and write down the key-routing
   rule; 165 follows it.
9. **IND-61 and IND-66 are no longer blocked.** Both cite gaps (G3 rich Table, G7 routing) that shipped in
   0.3.0. IND-66 probably duplicates the Studio's routed dashboard (`examples/semula_routes.py`); check
   and close or reframe it before spending 3 points.

## 0.4.1 (patch): fixes only, about 8 points

Theme: the first thing a visitor tries works, and the hosted path is checked on the real network.

| Card | Pts | Notes |
|------|-----|-------|
| IND-167 Fix the broken public demos | 3 | Mostly `deploy/` and `examples/`, so the wheel may not change. Adds the post-deploy smoke test. |
| IND-33 Manual Colab e2e from GitHub | 1 | Docs and process only (SLICES R2 note, `tests/e2e/README`). |
| NEW V1: verify `trusted_proxies` on Cloudflare Worker + Fly | 2 | Run against `indah.abangai.dev`, the path used for the latency numbers. |
| NEW V2: verify sticky sessions with 2 processes | 2 | Reproduce on Fly (2 machines) and write the working config into `website/docs/hosting.md`. |

ADRs first: none.

Risks:
- V1 may show the real edge sends the client address in a header indah does not read
  (for example `CF-Connecting-IP`). Reading a new header is new API, so it would move to 0.5.0; the
  patch then ships only the docs warning.
- The Fly and Neon migration to a homelab (board PAN, PAN-130) changes the path. Run V1 and V2 **before**
  it, and again after.
- If nothing under `src/` changes, do not cut 0.4.1. Deploy and docs fixes ship without a PyPI release.

Owner decides or does by hand:
- Whether to cut 0.4.1 at all (only if `src/` changed).
- If cut: approve the `pypi` environment run (the publish job waits for it; never bypass).
- Access to the live Cloudflare and Fly consoles for V1 and V2.

## 0.5.0: build your own, and the app skeleton, 24 points

Theme: semula can assemble its screens and build any bespoke visual itself.

| Order | Card | Pts |
|-------|------|-----|
| 1 | IND-149 ADR: web-component bridge | 3 |
| 2 | IND-150 Build the bridge (after the ADR is accepted) | 5 |
| 1 | IND-146 Layout primitives: justify, Spacer, Divider, Card variants | 3 |
| 2 | IND-147 AppShell | 5 |
| 3 | IND-151 NavItem with a live count badge | 2 |
| 3 | IND-156 Logo per colour scheme | 1 |
| 1 | IND-144 Chips and Segmented | 3 |
| 2 | IND-145 Reactive options | 2 |

ADRs first: the bridge ADR (IND-149: threat model, CSP nonce, lifecycle, theming, text fallback). Also a
short ADR-0014 amendment for AppShell and the rail (the design-framework ADR owns the shell layout).

Risks:
- The bridge loads author-supplied JavaScript, the most security-sensitive card in the plan. The whole
  e2e suite runs under `csp="strict"`, so the module must be same-origin and nonce-compatible, and a
  hosted app must not let a user choose the module.
- AppShell with `Router` and `spa=True` and a mobile drawer is the biggest UI card; budget for screenshots.
- Card variants and `Row`/`Column` gap must keep today's defaults. If a default has to move, stop and ask.
- Several cards edit `frontend/` and regenerate `src/indah/static/index.html`. See "Working rules".

Owner decides or does by hand:
- Accept the bridge ADR (blocks IND-150). Confirm the "same-origin only" rule.
- Confirm that `Card(variant=)` defaults to today's look.
- The release: bump, changelog, `make cleanroom`, tag, GitHub Release, approve the `pypi` environment.

## 0.6.0: tables, text and small controls, 25 points

Theme: the rest of semula's screens, and the one default-look change.

| Card | Pts |
|------|-----|
| IND-166 Redesign plain Text (folds IND-155) | 3 |
| IND-148 Rich table cells and truncation | 5 |
| IND-153 Async session factory and Skeleton | 3 |
| IND-164 Table keyboard navigation | 3 |
| IND-161 Menu with keyboard navigation | 3 |
| IND-152 Reactive page title and favicon | 2 |
| IND-158 Empty state and Code with copy | 2 |
| IND-172 Clean up and rework all demos and galleries (after IND-166) | 5 |
| IND-168 Plan a home for the Studio pages (ADR) | 2 |
| IND-154 ctx.every and ctx.spawn | 1 |
| IND-160 Toast actions | 1 |

ADRs first: the Text scale ADR (inside IND-166: compare at least four frameworks), an amendment to
ADR-0025 for the async factory, and the Studio-home ADR (IND-168). Do IND-166 first so later cards use the
new scale and a single screenshot review covers it.

Risks:
- With IND-172 this release is 30 points, over the 25 target. If it slips, move IND-168 and IND-158 to
  0.7.0 (IND-169 follows IND-168 there anyway) before cutting anything else.
- IND-166 changes every app that uses plain `Text`. It needs an "Upgrading" note and a review of every
  Studio page and example in screenshots.
- IND-153 runs an `await` inside session creation. With `secure=True` that happens in the signed-session
  path, so the time limit must not stall other requests, and a timeout must fall back to a skeleton, not an
  error. Keep sync factories byte-for-byte unchanged.
- IND-152: a favicon under `csp="strict"` must be served from the app, not a `data:` URL, unless the
  policy allows it. A new message type is additive.
- IND-160 needs a per-session handler table for toast actions; it must not be sent to other tabs.

Owner decides or does by hand:
- **IND-166 changes how apps look by default.** Decided: plain text is normal body text and the readout is
  opt-in. Still open for the ADR: the exact scale (the card proposes body, title, label, caption, mono) and
  whether plain text gets inline code and emphasis.
- Approve the `pypi` environment run.

## 0.7.0 (provisional): hosted Studio, command palette, promoted visuals, live docs, 28 points

Theme: host the Studio (ADR-0041), make the docs interactive, finish semula's list.

| Card | Pts |
|------|-----|
| IND-169 Interactive docs from the Studio | 5 |
| IND-165 CommandPalette | 3 |
| IND-157 Marked | 3 |
| IND-162 BarStrip | 3 |
| IND-163 Steps | 3 |
| IND-173 Studio hosted mode and /embed/ route (new, ADR-0041) | 3 |
| IND-174 Deploy the hosted Studio and post-deploy check (new, ADR-0041) | 3 |
| IND-176 Pyodide spike, IND-83a (new, split from IND-83) | 3 |
| IND-175 Release checklist: redeploy Studio and gallery (new) | 1 |

Splitting: IND-83 is 8 points. IND-176 (83a) is the timeboxed feasibility spike (3). IND-83 itself is now
the 5 point build (83b) and stays in "later" until the spike passes.

IND-61 (DataFrame explorer, 3) and IND-159 (InfoTip, 2) move to "later" to make room for the hosted Studio.

ADRs first: ADR-0041 (Studio home, Proposed) must be accepted before IND-173 starts. Order: IND-173, then
IND-174, then IND-169 and IND-175; IND-176 runs alongside and does not block IND-169.

Risks:
- IND-169 needs a deployed hosted Studio (IND-173, IND-174). Framing is allowed only on `/embed/` and only
  for the docs origin (`frame-ancestors`, no `X-Frame-Options`); every other route stays as strict as now.
  Deploying needs the owner's Fly access, and the image must stay free of Fly-specific code (PAN-130).
- Pyodide may not run indah's server dependencies; the spike must say so early.
- 157, 162, 163 may be dropped if semula's own bridge components make them redundant.

Owner decides:
- Built-in or semula-owned for 157, 162, 163.
- Accept ADR-0041: a hosted Studio as its own container beside the gallery, no playground, iframes in the docs.
- Approve the `pypi` environment run.

## 0.8.0 (provisional): live media and annotation, 22 points

Theme: the deferred live-media boundary (ADR-0017), only if the owner wants it.

IND-74 is 8 points and is split: **74a** ADR for the Tier-1 transport (2), **74b** server WebSocket
endpoint (3), **74c** shell client and fallback to SSE (3). Then IND-64 (3), IND-65 (2), IND-71 annotation
(3), IND-56 segmentation (3), IND-62 video detection (3).

Risks: Colab has no WebSocket proxy, so every feature must fall back to Tier 0 (SSE and POST); the CSP
`connect-src` policy and the origin guard must cover `ws:`; a protocol bump if the ADR cannot keep the
frames additive.

Owner decides: whether to build it at all (the card says "gated behind demand"), and the version if a
bump is needed.

## Later

- IND-57 RAG chat with citations (3), IND-81 LLM comparison charts (5, data goes stale), IND-66 (3, check
  the duplicate first), IND-83b (5, after the spike).

## 1.0

Not yet. A 1.0 should mean the public API and wire contract are frozen, and nothing here earns that until
the hosted layer has run for real users. Exit criteria:
1. semula runs in production on a released 0.6.x or 0.7.x for a few weeks without an indah workaround.
2. V1 and V2 pass and the hosting guide matches what runs.
3. A stated policy for breaking changes (deprecation window, `protocol_version` rule) and a decision on
   an external session store (today: in memory, sticky sessions).
4. The Studio coverage test, docs site and demos are green on the release candidate (`1.0.0rc1`, Colab and
   RunPod smoke test as in `docs/RELEASING.md`).
Earliest sensible date: after 0.7.0.

## Working rules

- Branch per piece off fresh `main`, PR with green CI, squash-merge. No direct pushes to `main`.
- At most 3 subagents at a time. Do not start semula's epic work until the owner says so.
- **Shell conflicts.** Cards that edit `frontend/` all regenerate the one file
  `src/indah/static/index.html`, which cannot be merged by hand. Run at most one frontend PR per merge
  window, and rebase and run `make frontend` before merging the next.
- **Hidden cost.** Every public name needs a Studio page (`tests/unit/test_studio_coverage.py`), a docs
  page in `website/docs/`, and a CHANGELOG entry; the e2e suite runs under `csp="strict"`. The card points
  mostly do not include this. Plan 20 percent on top, which is why releases are 24 to 25 points, not 28.
- Every bug found gets a failing test first.
- Release chores each time (`docs/RELEASING.md`): bump `pyproject.toml` and `__version__`, CHANGELOG
  section, `make cleanroom`, `make check`, tag, GitHub Release, owner approves the `pypi` environment.
  The "Status (2026-09)" block at the top of RELEASING.md is stale (Trusted Publishing works; 0.4.0 shipped
  that way); fix it in the first release PR.

## Owner checklist

| When | Decision or action |
|------|--------------------|
| Now | Approve this roadmap; then set a label or cycle per release on board IND |
| Now | Close IND-155 as folded; check IND-66 for a duplicate |
| Before 0.4.1 | Decide whether to cut 0.4.1; give access for V1 and V2 |
| Before 0.5.0 build | Accept the bridge ADR |
| Before 0.6.0 | Settle the Text scale and inline code and emphasis in the IND-166 ADR (the default look is decided) |
| Before 0.7.0 | Built-in or semula-owned for Marked, BarStrip, Steps; hosted Studio or not |
| Each release | Approve the `pypi` environment run |
