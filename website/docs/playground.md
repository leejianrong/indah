# Playground

Edit an indah app and run it, here, with no install and no server. Your code runs in a
Python runtime inside this browser tab and **is sent nowhere**: there is no server to
run it on.

Write a function called `build()` that returns an indah component (`indah` is already
imported). Press **Run** to see it; change the code and press **Run** again.

<indah-playground></indah-playground>

## What to expect

- **Download.** Nothing loads when you open this page. The first **Run** downloads the
  Python runtime and indah, about 9 MB compressed (once; your browser keeps it).
- **Time.** A run takes about 4 seconds to start once the download is cached, and 4 to 6
  seconds the first time, because every run starts a fresh Python. That is also what
  makes **Stop** reliable: stopping throws the whole runtime away.
- **Endless loops.** If your code does not return, the Playground stops it after 5
  seconds and says so. **Stop** does the same at any time. Nothing else on the page is
  affected, and the runtime restarts on the next run.
- **Errors.** A syntax error or an exception in your code is shown under the editor, as a
  traceback starting at your own lines.
- **Keyboard.** Tab indents inside the editor. Press Escape, then Tab, to leave it.
  Ctrl+Enter (Cmd+Enter on a Mac) runs.
- **No JavaScript.** The editor and the starting points are plain text you can read and
  copy; running needs JavaScript.

## What does not work here

The runtime is Python and indah only, with no server behind it. These do not work, or
work differently, in the Playground:

- Anything that needs a server: file **uploads and downloads**, `ctx.tail` and `Topic`
  (they need the app object), request headers and the client address, sessions, sign-in,
  `secure=True`, roles, rate limits and the Content-Security-Policy report.
- **Routing** with real URLs (`Router`, deep links): the page has no URL of its own.
- **Extra packages.** Only Python's standard library and indah are available, so
  `import numpy`, `pandas`, `matplotlib` and `PIL` fail; there is no `pip install`.
- **Threads and processes.** `asyncio` handlers, `asyncio.sleep`, `ctx.every` and
  `ctx.spawn` work; `threading` and `subprocess` do not.
- **Network.** Your code runs in a browser sandbox, so it can only do what a web page can.
- `indah.launch()` and `create_app()`: the Playground is the app. Write `build()` only.

To run any of these, use indah on your own machine ([Quickstart](quickstart.md)) or try
the [Studio](https://github.com/leejianrong/indah/blob/main/docs/STUDIO.md) with
`make demo`, which keeps a server-side playground for the same `build()` snippets.

Examples of components to try are on the [Components](components.md) page, where many
have their own **Run it** button.
