# ADR-0007: Build the documentation site with Zensical, aiming for FastAPI-grade polish

- Status: Accepted
- Date: 2026-09-14
- Deciders: Jian (owner)

## Context

indah is a developer-facing library whose adoption depends heavily on
documentation quality. FastAPI is the reference point for what good Python-library
docs feel like: a strong landing page, a guided tutorial that builds up concept by
concept with runnable examples, clean navigation, light/dark theming, and search.
We want that feel. We also want docs-as-code: authored in the repo, published on
merge, with a PR build-check so a broken docs build fails before merge.

## Decision

Author the documentation as a **Zensical** site living in the repo. Target the
look and feel of FastAPI's documentation: a landing page that sells the value
proposition, a progressive tutorial with copy-pasteable runnable examples,
clear top-level sections (Tutorial, Concepts, Components, API reference,
Deployment to Colab/Runpod), site search, and light/dark themes. Publish on merge
to `main` and add a PR check that fails on a broken docs build.

Scope note: the docs site is deferred as real work until there is an API worth
documenting (around Slice 4). This ADR records the tooling choice now so the
structure is planned for, not the build.

## Alternatives considered

| Option | Why not |
|--------|---------|
| MkDocs + Material (what FastAPI itself uses) | Excellent and the closest match; Zensical is the chosen successor line and is what the team's playbook standardizes on. Revisit if Zensical blocks a needed feature. |
| Sphinx | Powerful for API autodoc but heavier to reach a modern marketing-grade landing feel |
| Hand-rolled site / README only | No search, no versioning, does not scale past a few pages |

## Consequences

- Buys a modern, searchable, themeable docs site authored in the repo, with a feel
  users already associate with high-quality Python libraries.
- Costs a build step in CI and the discipline of keeping docs updated in the same
  PR as the code they describe (dev-playbook principle 16).
- Matching FastAPI's polish is a content effort, not just a tooling one: the
  tutorial and examples carry most of the perceived quality, so they must be
  runnable and kept current.
- Requires the docs build to be a PR gate so a broken build cannot merge.
