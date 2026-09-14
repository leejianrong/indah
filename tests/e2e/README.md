# End-to-end tests

The heavy layer: boots a real launched indah app and drives it through a
headless browser. Added with Slice 1 (see docs/SLICES.md). Marked `@pytest.mark.e2e`
so it stays out of the fast pre-push gate and runs in a dedicated CI job.

A separate Colab/RunPod smoke check (a real notebook run) guards proxy
compatibility and cannot be reproduced by a local test.
