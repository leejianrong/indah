"""A small indah app using the V4 starter set plus one custom component.

Run it with:  python examples/starter_components.py
It prints a URL (and embeds inline in a Colab/Runpod cell). No Node, at install or
at runtime.
"""

import indah

# A custom component: a native colour picker the pre-built shell renders from this
# declarative spec, with no shell rebuild (ADR-0012).
indah.register_component(
    "colorpicker",
    render={
        "tag": "input",
        "attrs": {"type": "color"},
        "bind": {"value": "value"},
        "on": {"input": {"event": "input", "prop": "value"}},
    },
)

DATASETS = {
    "Squares": {"columns": ["n", "n^2"], "rows": [[n, n * n] for n in range(1, 6)]},
    "Primes": {"columns": ["i", "prime"], "rows": [[1, 2], [2, 3], [3, 5], [4, 7]]},
}

name = indah.Signal("Alice")
dataset = indah.Signal("Squares")
accent = indah.Signal("#5b5bd6")

app = indah.Card(
    title="Starter components",
    children=[
        indah.Text(lambda: f"Hello, {name.value}!"),
        indah.TextInput(name, label="Your name"),
        indah.Select(dataset, options=list(DATASETS), label="Dataset"),
        indah.DataFrame(lambda: DATASETS[dataset.value], label="Data"),
        indah.custom("colorpicker", value=accent),
        indah.Text(lambda: f"Accent colour: {accent.value}"),
    ],
)

if __name__ == "__main__":
    indah.launch(indah.create_app(session=indah.Session(app)))
