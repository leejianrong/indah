# ADR-0006: Name the project "indah"

- Status: Accepted
- Date: 2026-09-14
- Deciders: Jian (owner)

## Context

The project needs a name usable as the PyPI distribution, the import package, a
future npm package for the prebuilt shell, and the repo. "indah" is Malay for
*beautiful / elegant*.

## Decision

Name the project **indah**. Verified available at time of writing:

- **PyPI** — `https://pypi.org/pypi/indah/json` returns 404 (name free).
- **npm** — `https://registry.npmjs.org/indah` returns 404 (name free).

Assessment: short, memorable, easy to type and pronounce for an English-speaking
audience, lowercase-clean for a package name, and thematically apt for a UI
library ("beautiful"). Low collision risk — it is not an existing tech term.

## Alternatives considered

| Option | Why not |
|--------|---------|
| A descriptive name (e.g. "pyui", "notebook-ui") | Generic, likely taken, forgettable |
| Keep working folder name only | Not a deliberate decision; risks a later rename |

## Consequences

- Buys a distinctive, available identity across PyPI, npm, and the repo.
- Costs some discoverability: "indah" does not self-describe as a UI framework, so
  the tagline and README must carry the "Python UI for cloud notebooks" framing.
- Requires reserving the name early (register a placeholder PyPI project) before
  someone else takes it, since availability is not a lock. Consider the `indah`
  GitHub org/repo and the npm name too, even though npm is only needed later
  (ADR-0005). Do a quick trademark sanity check before any public launch.
