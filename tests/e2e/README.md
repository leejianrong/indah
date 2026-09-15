# End-to-end tests

The heavy layer: boots a real launched indah app (`launch()` in a background
thread) and drives it end to end. Marked `@pytest.mark.e2e` so it stays out of the
fast pre-push gate and runs in dedicated CI jobs.

Two layers:

- **`test_live_server.py`** drives the server over HTTP/SSE with `httpx` - no
  browser. It proves the Python core and the wire protocol agree (streaming
  arrives incrementally, the UI stays live mid-stream, a custom component
  round-trips). Runs on just `--extra dev`.
- **`test_browser.py`** renders the pre-built Svelte shell in a real headless
  Chromium (Playwright) and asserts the DOM patches through the SSE round-trip:
  the init tree renders, a slider and a select patch the live DOM, and the
  registered colorpicker round-trips a value. This is the only place the shell is
  exercised in a real DOM. It needs the browser layer installed:

  ```bash
  uv sync --extra dev --extra e2e
  uv run playwright install chromium
  uv run pytest -m e2e -q            # or: make test-e2e
  ```

  If the `e2e` extra isn't installed, the browser test skips cleanly (via
  `importorskip`) and the httpx layer still runs.

A separate Colab/RunPod smoke check (`examples/smoke_test_rc.ipynb`, a real
notebook run) guards proxy compatibility and cannot be reproduced by a local test.
