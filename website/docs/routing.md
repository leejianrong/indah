# How to add several pages

This guide shows you how to give an app several pages with their own addresses, so a URL can be
bookmarked, reloaded and opened in a new tab. It assumes you have read the
[Quickstart](quickstart.md).

## Declare the routes

Save this as `pages.py`. It has an overview page and a page per project, with links between them.

```python
import indah

PROJECTS = ["alpha", "beta"]


def build(ctx: indah.Context) -> indah.Session:
    overview = indah.Text("# Overview\n\nPick a project.", markdown=True)

    # A page that is not showing is still built and runs, with no params:
    # use .get(), never ["project"]
    name = indah.computed(lambda: ctx.params.value.get("project", ""))
    project_page = indah.Column(
        children=[
            indah.Text(lambda: f"# Project {name.value}", markdown=True),
            indah.Button("Back to the overview", on_click=lambda: ctx.navigate("/")),
        ]
    )

    pages = indah.Router(
        ctx,
        routes={"/": overview, "/projects/{project}": project_page},
        not_found=indah.Text("No such page"),
    )
    nav = indah.Column(
        children=[
            indah.Link(ctx, "Overview", to="/"),
            *[indah.Link(ctx, p, to=f"/projects/{p}") for p in PROJECTS],
        ]
    )
    return indah.Session(indah.Sidebar(children=[nav, pages]))


app = indah.create_app(session_factory=build, title="pages", spa=True)

if __name__ == "__main__":
    indah.launch(app)
```

Run it with `uvicorn pages:app` and open `http://127.0.0.1:8000/`. This is what I saw driving it
in a browser:

| Action | Address bar | Page shows |
|--------|-------------|------------|
| Load `/` | `/` | Overview, "Pick a project." |
| Click the `beta` link | `/projects/beta` | Project beta |
| Click "Back to the overview" | `/` | Overview |
| Open `/projects/alpha` directly | `/projects/alpha` | Project alpha |
| Open `/nowhere` | `/nowhere` | No such page |

A deep link works because of `spa=True`, which serves the page for any path under the app.

## How it fits together

- **`routes`** maps a path pattern to a component. `{project}` captures a segment, and
  `{id:int}` converts it to an integer. The pages are components you have already built, not
  functions.
- **`ctx.params`** is a signal holding the captured values for the page that is showing. Read it
  inside a `computed` or a prop function so the page follows it.
- **`ctx.navigate("/x")`** goes to a page from code, for example after a save. It raises
  `ValueError` for a path that is not an in-app path, because that is a mistake in your code.
- **`Link`** is a real `<a href>`, so open-in-new-tab works. `match="prefix"` marks it active for
  every path under its own, which suits a section heading.
- **`NavItem(ctx, "Pending", to="/pending", badge=count)`** is a `Link` for a rail, with a live
  count that disappears when it is zero.

## If a link's address comes from data

A `Link` whose `to=` is a function of `ctx.params` is safe against a crafted address. If the function
returns something that is not an in-app path (a newline, a space, a backslash), the link points at
`/` and is never active, and the stream carries on.

## Things to know

- **Every page is built up front.** A page's reactive code runs even when its route is not showing,
  with no params. That is why the example uses `ctx.params.value.get("project", "")`: indexing
  with `["project"]` would raise on the hidden page. Keep expensive work behind a `computed`.
- **Do not put anything role-restricted in a page.** Hidden pages are in the page snapshot the
  browser receives. See [Roles, permissions and secrets](hosting-access.md).
- **One `Router` per session.** The address bar holds one path per tab, so a second `Router` raises
  `ValueError`. To switch content inside part of a page, use `Tabs`, or a `Signal` with a
  `computed`. Nested routers are not supported.
- After a server restart, an open tab reopens on the page it is on now.

## Related

- [Dashboard recipes](dashboards.md) for routing inside a larger service, with a sidebar and
  split panes.
- The Studio pages under Routing (`make demo`) show links, `NavItem` and `navigate` live.
