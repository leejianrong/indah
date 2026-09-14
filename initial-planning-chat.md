# Initial Planning Chat — A Cloud-Optimized Python UI Framework

> Working notes from an exploratory conversation about building a Python UI
> library to compete with Gradio and Streamlit, specifically for ephemeral
> cloud environments (Google Colab, RunPod).

## Contents

- [1. Criticisms of Gradio and Streamlit](#1-criticisms-of-gradio-and-streamlit)
- [2. Is there value in building your own library?](#2-is-there-value-in-building-your-own-library)
- [3. Blueprint for a cloud-optimized framework](#3-blueprint-for-a-cloud-optimized-framework)
- [4. FastUI — the closest existing prior art](#4-fastui--the-closest-existing-prior-art)

---

## 1. Criticisms of Gradio and Streamlit

Both tools are excellent for rapid prototyping, but they hit a distinct
architectural wall when a project moves from "demo" to "production."

### Streamlit

- **The global state & rerun bottleneck.** Streamlit's greatest feature is also
  its biggest flaw. Every button click or slider move reruns the entire Python
  script top to bottom. Caching (`@st.cache_data`) helps, but apps with large ML
  models, heavy database queries, or complex multi-step state quickly become
  sluggish or consume massive server memory.
- **Layout rigidness.** Streamlit forces an opinionated visual structure.
  Hyper-custom UI, pixel-perfect layouts, or advanced responsive grids require
  injecting raw HTML/CSS via hacks or writing complex JavaScript components.
- **Concurrency limitations.** Backend and frontend run as a single unified
  execution thread per user session, so scaling to hundreds of concurrent public
  users without crashing or slowing down is notoriously difficult.

### Gradio

- **Strictly rigid component layouts.** Gradio is a block-based system
  (`gr.Blocks`). It excels at inputs-left / outputs-right, but is restrictive for
  a standard application interface (multi-page apps, persistent side navigation, a
  custom dashboard).
- **Difficult custom state management.** Multi-step workflows or complex
  conditional logic require wrapping functions in `gr.State` and chaining
  component triggers. The code gets confusing and hard to debug compared to
  traditional event-driven architecture.
- **Heavily tied to Hugging Face.** Gradio is optimized for the Hugging Face
  ecosystem. For general data science, classic CRUD business apps, or non-AI
  workflows, the framework can feel out of place.

---

## 2. Is there value in building your own library?

Three domains of potential value: **market**, **architectural**, and
**personal/educational**.

### 2.1 Competitive market value

The bar for entering this market is high. Existing tools already target the exact
flaws above:

- **Reflex** — compiles Python to a Next.js/Tailwind frontend.
- **FastUI** (by the Pydantic team) — drives UI purely from backend JSON schemas.

To offer genuine market value, the library would need to solve a major unsolved
pain point, such as:

- A true reactive execution graph (like Shiny for Python) but with the modern
  aesthetic and component ecosystem of React/Tailwind.
- An incredibly lightweight UI layer with zero runtime compilation overhead
  (unlike Reflex, which requires Node.js initialization).

### 2.2 Architectural value

The most architecturally viable approach is to **separate the rendering layer
from the execution loop** — a Server-Driven UI pattern. Rather than inventing a
new layout engine, the Python library outputs structured JSON (or handles
real-time WebSockets) to a lightweight, pre-compiled web frontend (React, Vue, or
Svelte). Python manages state changes and pushes minimal JSON updates, bypassing
Streamlit's full-script reruns without a slow compilation step like Reflex.

### 2.3 Personal & educational value

Building a custom UI framework forces deep mastery of:

- Asynchronous Python (`asyncio`) and high-performance web servers (FastAPI,
  Starlette).
- State synchronization over WebSockets.
- Bridging data structures between Python (Pandas, Pydantic) and the browser.

### Verdict

- **Build your own if:** you want a profound architectural challenge, have a
  highly specific niche workflow existing frameworks can't satisfy, or want a
  lightweight open-source project to showcase engineering skills.
- **Don't build your own if:** the goal is simply to ship a business product or
  get an AI startup to market quickly. In that case, building core infrastructure
  from scratch is a massive distraction — use Reflex (full-stack) or Dash
  (performance) instead.

---

## 3. Blueprint for a cloud-optimized framework

The explicit target is hosted cloud notebooks / notebook-based containers like
**Google Colab** and **RunPod**. This is a real architectural gap: Streamlit
handles networking beautifully but fails on performance; Reflex handles
production architecture but is a logistical nightmare to initialize inside a
transient cloud container.

Three core architectural pillars:

### 3.1 Single-port, standard HTTP/WebSocket architecture

- **Problem.** Reflex splits into a Next.js port and a FastAPI port, so proxying
  through Colab (`npx localtunnel`) or RunPod's HTTP proxy breaks down.
- **Solution.** Combine frontend serving and backend logic into a single ASGI app
  (Uvicorn/FastAPI or Starlette) on one port. Python serves static frontend
  assets over standard HTTP and opens a single WebSocket on that same port for
  real-time UI state sync.

### 3.2 Pre-compiled, server-driven UI (no Node.js/Bun dependency)

- **Problem.** Reflex takes minutes to compile because it triggers a local
  JavaScript build (`npm run build`) inside the container on every launch.
- **Solution.** Never compile frontend code inside the cloud container. Build a
  single, highly flexible, pre-compiled frontend shell (React, Vue, or Svelte)
  and distribute it as static assets inside the Python wheel. When the user writes
  Python, the backend sends declarative UI layouts as JSON schemas over the
  WebSocket, and the pre-compiled frontend renders components dynamically.

### 3.3 Granular state updates (no full-script reruns)

- **Problem.** Streamlit re-executes the entire `.py` file from line 1 on every
  click, killing execution efficiency.
- **Solution.** Implement an event-driven / reactive model using standard Python
  classes. When a user moves a slider, only the specific bound function or
  variable executes on the backend, returning a minimal JSON patch to update only
  that UI element.

### Verdict

Yes — worth making, **if scoped tightly to this hybrid developer workflow.**
There is an active audience of AI developers, researchers, and hobbyists who want
the deployment simplicity of Streamlit (zero config, single port, fast startup)
but need the async performance of an actual full-stack app so heavy
PyTorch/Transformers pipelines don't freeze or break the UI.

The closest existing project attempting this "Server-Driven UI via JSON" approach
is **FastUI** — but it lacks out-of-the-box interactive components optimized for
heavy AI/ML pipelines.

---

## 4. FastUI — the closest existing prior art

[FastUI](https://docs.pydantic.dev/fastui/) is an open-source framework created by
Samuel Colvin (creator of Pydantic). It was built to let Python developers build
rich, modern web frontends without writing JavaScript or setting up a frontend
build chain.

> **Status:** The [official FastUI repo](https://github.com/pydantic/FastUI) was
> archived and marked inactive in June 2026. The Pydantic team shifted focus to
> their core validation library and their observability platform, Logfire. Despite
> being archived, FastUI's Server-Driven UI pattern is a solid engineering
> blueprint for a custom cloud-oriented library.

### 4.1 Architecture

Instead of a heavy compilation step or full-script reruns, FastUI separates layout
definitions from the browser using four components:

1. **The `fastui` PyPI package** — Python classes mapping to standard web UI
   components (`c.Button`, `c.Table`, `c.Markdown`). Every component is a Pydantic
   model.
2. **The pre-built frontend engine** (`@pydantic/fastui-prebuilt`) — a
   pre-compiled React single-page app, served over a CDN or bundled in the Python
   package.
3. **Pure JSON exchange** — the pre-built React frontend loads instantly, sends an
   HTTP request to your Python server, and the backend responds with structured
   JSON generated by your Pydantic UI models.
4. **Dynamic rendering** — the React frontend parses the JSON and maps the layout
   into real Bootstrap or Tailwind components on screen.

### 4.2 What the code looks like

Because it relies on a standard web request lifecycle, you define UIs inside a
routing framework like FastAPI:

```python
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastui import FastUI, AnyComponent, prebuilt_html, components as c

app = FastAPI()

# 1. The main entry point serves the pre-compiled frontend shell
@app.get("/{path:path}")
def html_landing() -> HTMLResponse:
    return HTMLResponse(prebuilt_html(title="FastUI Demo"))

# 2. The API endpoint that dictates what the frontend actually draws
@app.get("/api/", response_model=FastUI, response_model_exclude_none=True)
def main_page() -> list[AnyComponent]:
    return [
        c.Page(
            components=[
                c.Heading(text="Welcome to FastUI", level=1),
                c.Paragraph(text="This UI was generated completely from a backend JSON payload."),
                c.Button(text="Click Me", on_click=c.GoToEvent(url="/api/clicked")),
            ]
        )
    ]
```

### 4.3 Why it fits the "Colab / RunPod" dream

**Brilliantly executed:**

- **Single port, zero Node.js.** The React shell is pre-compiled, so `pip install`
  is all you need. It runs on a single port (e.g. Uvicorn on 8000), making it
  compatible with RunPod and Colab network-proxy rules.
- **Granular updates.** Clicking a button triggers a normal API call
  (`GoToEvent`). The server handles logic and returns a small JSON fragment to
  change screen state, avoiding Streamlit's global re-execution.
- **Built-in Server-Sent Events (SSE).** Native hooks for streaming tokens — good
  for real-time text generation from a local-GPU LLM.

**The gaps you could fill:**

- **Lack of native rich media / AI components.** FastUI was optimized for data
  tables, admin dashboards, and simple forms. It has no built-in audio-recorder
  canvas, image-to-image masking brush, or 3D mesh viewers.
- **No integrated cloud-tunneling utilities.** It relies on the developer to spin
  up ngrok or manually configure proxy routes for outside access.
- **Project inactivity.** The repo is read-only; it won't adapt to newer web
  paradigms or Pydantic versions without community forks.

### 4.4 Takeaway

To build a framework optimized for AI notebooks, you don't need to reinvent the
wheel. Steal FastUI's core philosophy — **Pydantic UI schemas sent over a single
port to a pre-compiled JS wrapper** — and specialize it by bundling components
designed for deep-learning workflows.

---

## Open questions to carry into planning

- Which frontend framework for the pre-compiled shell — React, Vue, or
  **Svelte** / HTML+Tailwind with vanilla JS?
- What is the first component workflow to prototype — an image-generation viewer, a
  live-streaming text container for LLMs, or something else?
- Which architectural trick beats Streamlit's reruns — a reactive execution graph,
  event-driven binding, or JSON-patch diffing?
- **Escape hatch:** should the framework support transitioning from
  Python-only UI to a "proper" hand-written frontend (JS/HTML/Svelte) as an app
  matures? Still an open design question.
