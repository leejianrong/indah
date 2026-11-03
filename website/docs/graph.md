# How to draw a graph

This guide shows you how to draw a node-link graph, react to a click on a node, highlight a path through it, and keep a graph with thousands of nodes readable. It assumes you have read the [Quickstart](quickstart.md).

## Draw a graph

Save this as `team.py`. It is a complete app: five people, who works with whom, and a line of text that shows the person you click.

```python
import indah

people = [
    {"id": "ana", "group": "Design"},
    {"id": "ben", "group": "Design"},
    {"id": "cho", "group": "Platform"},
    {"id": "dev", "group": "Platform"},
    {"id": "eli", "group": "Data"},
]
works_with = [("ana", "ben"), ("ben", "cho"), ("cho", "dev"), ("dev", "eli"), ("ana", "eli")]

selected = indah.Signal(None)

app = indah.Column(
    children=[
        indah.Graph(people, works_with, selected=selected, height=360, label="Who works with whom"),
        indah.Text(lambda: f"Selected {selected.value}" if selected.value else "Click a person"),
    ]
)

if __name__ == "__main__":
    indah.launch(indah.create_app(session=indah.Session(app)))
```

Run it with `python team.py`. Drag the canvas to pan, scroll to zoom, and click a person: the text under the graph shows who you clicked, and a click on empty canvas clears it.

`group` picks a colour and adds a legend. Positions are worked out in your browser and start clustered by group, so the same graph always lays out the same way.

<indah-live page="media/graph"></indah-live>

## Select a node from Python

`selected` works both ways. Set it and the graph selects that node and centres on it:

```python
selected.set("dev")
```

`focus` centres on a node without selecting it. Give it an id, or a signal that holds one.

## Highlight a path

Give each edge an `id`, then name the nodes and edges to emphasise:

```python
edges = [{"source": "ana", "target": "ben", "id": "e1"}, ...]
path = {"nodes": ["ana", "ben", "cho"], "edges": ["e1", "e2"]}
indah.Graph(people, edges, highlight=path)
```

Highlighted nodes and edges are always drawn in full, and everything else is dimmed. `highlight` can be a signal, so you can show a different path as your user moves through a list. An id that is not in the graph raises `ValueError` when you build the graph, not later in the browser.

!!! tip
    Change `nodes` and `edges` together, inside `indah.batch(...)`, when both are signals. Set one at a time, and an edge can briefly name a node that is not there yet.

## Keep a big graph readable

A graph with thousands of labelled nodes is a hairball. `Graph` draws only the `focus_size` nodes nearest the middle of the canvas in full (default 300), with their labels and the edges between them. Every other node is a small dot, so you still see the shape of the whole graph. Pan, and the detail follows you. Click a dot and it is selected, centred and drawn in full, along with its nearest neighbours.

- Raise or lower `focus_size` (1 to 5,000) to trade detail for speed. It can be a signal, so a slider can drive it.
- A graph holds at most `max_nodes` nodes (default 10,000, up to 20,000) and three times as many edges. Past that, sample the graph before you hand it over.
- Above 8,000 nodes the nodes start clustered by group and are not relaxed further.

## Use the keyboard

Press Tab to focus the graph. Arrow keys pan, `+` and `-` zoom, and Escape clears the selection.

## Reference

| Argument | Meaning |
|----------|---------|
| `nodes` | ids, or dicts with `id` and optional `label`, `group`, `size`, `color`, `x`, `y` |
| `edges` | `(source, target)` pairs, or dicts with `source`, `target` and optional `id`, `label`, `color` |
| `selected` | a `Signal[str \| None]`, two-way |
| `focus` | a node id, signal or callable: centre on it |
| `focus_size` | nodes drawn in full (default 300, at most 5,000); may be a signal |
| `highlight` | `{"nodes": [...], "edges": [...]}`; may be a signal |
| `layout` | `"auto"` (default) or `"given"`, which needs `x` and `y` on every node |
| `height` | pixels, or `"fill"` |
| `legend` | show the group colours (default `True`) |
| `max_nodes` | most nodes allowed (default 10,000; ceiling 20,000) |
| `label` | the name a screen reader announces |

A duplicate id, an edge to a node that is not in the graph, or too many nodes raises `ValueError` when you build the `Graph`. The decision record is [ADR-0048](https://github.com/leejianrong/indah/blob/main/docs/adr/0048-graph-component.md).
