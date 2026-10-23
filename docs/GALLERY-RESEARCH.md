# Gallery research: how other projects list and accept apps

- Status: research note for IND-182, 2026-10-23. Nothing here is built.
- Question: the gallery (`indah-demos.fly.dev`, `deploy/fly/`) should grow from the owner's 13 demos into a
  place that shows apps people really built with indah. How do Streamlit and others list and accept apps,
  and what is the smallest first version for indah?
- Method: primary pages and docs, fetched 2026-10-23, linked next to each claim. Anything I could not
  confirm from a primary source is marked **unverified**. I did not guess how review works.

## Where indah is today

- 13 demos, one list in `deploy/fly/gallery_app.py` (`MANIFEST`: slug, title, emoji, module; `BLURBS`;
  screenshots in `deploy/fly/thumbnails/`). All are the owner's.
- All 13 run **in one Python process** on one 1 GB Fly machine, each mounted under `/<slug>` with rate limits
  and security headers (ADR-0024). Adding someone else's app to that process would run their code with the
  gallery's privileges, so "accept an app" must not mean "run it here".
- No community path exists, and the owner has said none is wanted yet.

## Streamlit

**Listing: apparently curated or automatic, with no public submission.**
- The [gallery page](https://streamlit.io/gallery) has categories (Favorites, Trending, LLMs, Data
  visualization and others) and says "Try out these apps, browse their source code, then fork them and make
  them your own". It has no submission instructions and no submission link.
- A Streamlit staff member (tonykip) wrote on 2024-03-28 that "There isn't a submission process for the
  Streamlit app gallery because it is dynamically generated", pulling the most popular public apps, and
  suggested sharing on social media, a video demo and sample data
  ([forum thread](https://discuss.streamlit.io/t/how-do-we-get-our-app-featured/65753)). On 2024-03-29 the
  same person acknowledged complaints that gallery apps were often down and said the team was working on it.
- An older staff reply (Caroline, 2023-02-27) invited people to DM staff a link to an app they thought a
  good fit ([forum thread](https://discuss.streamlit.io/t/what-does-it-take-for-my-app-to-be-featured-in-streamlit-apps-gallery/38293)).
  No criteria or timeline are stated. Both threads are staff statements on a forum, not documentation, and
  may be out of date: **I could not find a current official statement**.

**Hosting: the author's own app on Community Cloud.**
- Apps are deployed by the author from their own GitHub repository in a workspace ("Create app", then
  "Deploy"); you can also fork or clone an app from the gallery
  ([deploy docs](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app)). The page does
  not say whether the repository must be public: **unverified**.
- Inactive apps: "All apps without traffic for 12 hours go to sleep", and a viewer can wake one. Listed
  limits (as of February 2024, "may change at any time"): CPU 0.078 to 2 cores, memory 690 MB to 2.7 GB,
  storage up to 50 GB ([manage your app](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)).
  I found no stated policy for abandoned or broken apps beyond sleeping.

**Metadata:** none documented for apps. The gallery's source is a public repo,
[streamlit/gallery](https://github.com/streamlit/gallery) ("Public-Facing gallery for our website. PRs
welcome!"), with a `components/registry` path. I could not confirm how that registry is used; a blog post
that reportedly describes a pull-request route for the separate *components* gallery returned 403, so that
route is **unverified**.

**Safety and quality:** I found no documented review or safety process for the gallery. Streamlit's model
is that the author hosts the app, so a bad app is the author's server, not Streamlit's.

## Hugging Face Spaces (and Gradio)

**Listing: open hosting, editorial highlighting.**
- Anyone with an account can create a Space (Gradio, Docker or static); a Space is a git repository that
  rebuilds on every push ([Spaces overview](https://huggingface.co/docs/hub/spaces-overview)). Creating a
  Gradio or Docker Space needs a paid plan, with a small free exception; static Spaces are free.
- Highlighting is separate and editorial: "Spaces of the Week are a curated weekly selection of standout
  Spaces chosen by the Hugging Face team", and a star marks author-owned Spaces on model, dataset and paper
  pages ([featured Spaces](https://huggingface.co/docs/hub/en/spaces-featured)). The page gives no criteria
  and no nomination route. A nomination form exists in a 2024 commit but I could not confirm it is live:
  **unverified**.

**Metadata:** a YAML block at the top of the repo's `README.md`: `title`, `emoji`, `colorFrom`, `colorTo`,
`sdk`, `app_file`, `short_description`, `tags`, `thumbnail`, `pinned`, `models`, `datasets`,
`disable_embedding` and more ([configuration reference](https://huggingface.co/docs/hub/spaces-config-reference)).
One file per app gives the card, the search tags and the run instructions.

**Hosting model:** HF runs the code, on default hardware of 2 vCPU and 16 GB. Visibility is public,
protected or private. Free hardware sleeps when unused and an owner can pause a Space; anyone can duplicate
a public one ([Spaces overview](https://huggingface.co/docs/hub/spaces-overview)).

**Safety:** a content policy covers unlawful material, spam and "Content designed to disrupt, damage, or
gain unauthorized access to systems or devices". Moderation is report-driven (a Report button or
safety@huggingface.co), reviewed case by case, with actions from asking for changes to disabling access and
suspending accounts, plus a DMCA route ([content guidelines](https://huggingface.co/content-guidelines)).
A secrets scanner warns owners of hard-coded secrets. HF can do this because it sandboxes each Space on its
own infrastructure at its own cost.

## Two more points of comparison

**Vercel templates.** A form with stated requirements: a working demo deployed on Vercel, a Deploy button
in the README, a polished design, App Router for Next.js; the form asks for a publisher name and contact
email, and says only "Your template will be submitted for review" with no timeline, criteria or removal
policy ([submission page](https://vercel.com/templates/submit)). Community threads report long silences
after submitting ([example](https://community.vercel.com/t/no-response-after-submitting-projects-to-the-vercel-templates-marketplace/32250));
those are users' accounts, not Vercel policy. Lesson: a form with no feedback loop frustrates submitters.

**Reflex templates.** A public repo, [reflex-dev/templates](https://github.com/reflex-dev/templates). Its
README is aimed at maintainers: a template needs a `preview.png` or `preview.webp`, is published through a
release, and maintainers add its entry to `templates.json`. It describes no general outside submission
process. A docs page on open-source templates could not be fetched (404), so a claim elsewhere that outside
apps are submitted through this repo is **unverified**. Lesson: a catalog as one reviewed data file in a
repo is cheap, and the preview image is a hard requirement.

## What to copy, what to avoid

Copy:
- **A small metadata file per app** (HF's README YAML): title, blurb, tags, thumbnail, source link. It
  drives the card and filtering with no extra tooling.
- **Preview image required** (Reflex).
- **A catalog that is a reviewed file in git** (Reflex, `streamlit/gallery`): changes are pull requests, so
  review, history and rollback are free.
- **A report and takedown contact** (HF) before any outside content is listed.
- **A "last seen working" signal.** Streamlit staff acknowledged that gallery apps were often down.

Avoid:
- **Running other people's code on indah's machine.** HF and Streamlit can, because they built per-app
  sandboxes and charge or limit resources. The indah gallery is one process (ADR-0024); ADR-0041 already
  rejected a hosted playground for the same reason.
- **Popularity-driven automatic listing** (Streamlit): indah has no usage data and few apps.
- **A submission form with no status or deadline** (Vercel reports).
- **Promising hosting or uptime for apps indah does not host.**

## Recommended smallest first version: a catalog, not hosting

1. **The gallery keeps two kinds of entry.** *Hosted*: the owner's own demos, as today. *Listed*: an app that
   someone else hosts (their Fly, Hugging Face Space, Colab notebook or any URL), shown as a card that links
   out. For a listed app indah runs nothing.
2. **One data file** (for example `gallery/apps.toml`) replaces the in-code `MANIFEST` and `BLURBS`. One
   entry per app: `slug`, `title`, `blurb`, `author`, `kind` (hosted or listed), `url`, `source_url`,
   `thumbnail`, `tags`, `indah_version`, `added`. A unit test validates it (unique slugs, thumbnail exists,
   no raw HTML, https only, blurb length).
3. **Review by pull request, by the owner.** No form. A short `CONTRIBUTING`-style page says what a good
   entry is. This is a later step; the owner has asked for no community contributions yet, so first the file
   and the owner's own listed apps.
4. **A scheduled link check** (not at deploy time) that marks a listed app as not responding after a few
   failures and hides it after more, which answers the Streamlit "often down" complaint.
5. **A report contact and a takedown rule** on the page before any outside entry is accepted.
6. **Listing is not endorsement of safety**, so links open with `rel="noopener noreferrer"`, an external
   app is never embedded in an iframe on the indah origin by default, and the landing page's CSP is unchanged.

Not in this version: uploads, accounts, hosting other people's apps, ratings, popularity ranking, a
marketplace or payments. If hosting others' apps ever becomes the goal, that needs its own ADR on isolation
(a container or microVM per app, resource caps, egress rules, review), and is a different cost model.

Risks: link rot and dead listings (the checker), reputational risk from a listed site changing later (the
report contact and a manual removal), and an empty gallery (the owner populates it first, which matches the
intent that the owner dogfoods and grows it with agent help).

## Follow-up cards (filed on board IND)

- Gallery catalog file and schema, replacing `MANIFEST` and `BLURBS`, with a validation test (3).
- Scheduled link and thumbnail check for listed apps (2).
- Gallery policy page: what makes a good entry, report and takedown contact, listing is not endorsement (1).
- Plan the next batch of gallery apps the owner will build (fun, wacky, useful), as cards with a theme and
  a feature each (2).

## Not verified

- Streamlit: current official criteria and review time for the gallery, whether a Community Cloud repo must
  be public, the components registry pull request route, any abandoned-app policy.
- Hugging Face: the criteria and nomination route for Spaces of the Week, whether the nomination form is live.
- Reflex: whether outside contributors can add templates through the repo.
- Vercel: review times and criteria; only submitter reports were found.
