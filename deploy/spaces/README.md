# Hosting the indah demos on Hugging Face Spaces

The persistent "try-it-now" gallery (ADR-0023): one **Docker Space** per demo,
running the example's indah ASGI `app` under uvicorn. Free tier, persistent URL, and
it plants indah on the same turf as the Gradio/Streamlit demos. The free-tier Space
sleeps on idle (a cold start on the first hit) and caps resources - fine for demos.

The Colab one-click badges (the other tier) are the free, zero-host baseline and live
with the demos / gallery; this directory is only the persistent HF Spaces path.

## What's here

- `demos.tsv` - the manifest: one line per demo (slug, example file, title, emoji,
  any extra pip deps).
- `build_space.sh` - assembles a ready-to-push Space folder into `build/<slug>/`
  (Dockerfile + `requirements.txt` + `app.py` + a `README.md` with the HF
  frontmatter). It does **not** push - that needs your HF credentials.
- `build/` - generated output (git-ignored).

## Build

```bash
cd deploy/spaces
./build_space.sh              # all demos
./build_space.sh poster       # or just one, by slug
```

Each `build/<slug>/` is a complete Docker Space.

## Push (owner step - needs a Hugging Face **write** token)

No secrets live in this repo (AGENTS.md). The push needs a token with **write**
access (a read token gets `403 Forbidden` on Space creation). Create one at
<https://huggingface.co/settings/tokens> (role *write*, or a fine-grained token with
"Write access to Spaces"), then log in and deploy:

```bash
hf auth login                              # paste your WRITE token
# (or: export HF_TOKEN=hf_...write-token...)

./build_space.sh                           # assemble build/<slug>/
uv run python deploy_hf.py                 # create + upload every Space
uv run python deploy_hf.py poster          # ...or just one, by slug
```

`deploy_hf.py` creates `<you>/indah-<slug>` as a Docker Space (idempotent) and
uploads the folder; HF builds the Dockerfile and serves each demo at
`https://<you>-indah-<slug>.hf.space`. Add those URLs to the gallery
(`website/docs/gallery.md`) next to each demo's "Open in Colab" badge.

Manual alternative (per demo), if you prefer git over the script:

```bash
cd build/poster
git init && git add . && git commit -m "indah poster demo"
git remote add space https://huggingface.co/spaces/<you>/indah-poster
git push space HEAD:main
```

## Notes

- The image installs indah from `git+https://github.com/leejianrong/indah@main`
  until indah is published to PyPI; then switch `INDAH_REQ` in `build_space.sh` to a
  pinned release for reproducible Space builds.
- Each example exposes a module-level `app` (an indah ASGI app), so the Dockerfile's
  `uvicorn app:app` is identical across demos.
- `chatbot` deploys the **mock** chatbot (no model weights/GPU), so it runs on the
  free tier; the real-model path is `python examples/chatbot.py` locally.
