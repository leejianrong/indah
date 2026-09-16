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

## Push (owner step - needs a Hugging Face account/token)

No secrets live in this repo (AGENTS.md). Do this once per demo, signed in as the
indah HF org/user:

```bash
# 1) Create the Space (Docker SDK) once, via the HF UI or the CLI:
pip install huggingface_hub
huggingface-cli login                      # paste your HF token
huggingface-cli repo create indah-poster --repo-type space --space_sdk docker

# 2) Push the built folder to it:
cd deploy/spaces/build/poster
git init && git add . && git commit -m "indah poster demo"
git remote add space https://huggingface.co/spaces/<your-user>/indah-poster
git push space HEAD:main
```

The Space builds the Dockerfile and serves the demo at
`https://<your-user>-indah-poster.hf.space`. Add that URL to the gallery
(`website/docs/gallery.md`) next to the demo's "Open in Colab" badge.

## Notes

- The image installs indah from `git+https://github.com/leejianrong/indah@main`
  until indah is published to PyPI; then switch `INDAH_REQ` in `build_space.sh` to a
  pinned release for reproducible Space builds.
- Each example exposes a module-level `app` (an indah ASGI app), so the Dockerfile's
  `uvicorn app:app` is identical across demos.
- `chatbot` deploys the **mock** chatbot (no model weights/GPU), so it runs on the
  free tier; the real-model path is `python examples/chatbot.py` locally.
