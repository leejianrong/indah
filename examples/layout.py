"""A multi-panel indah app built from indah's layout containers.

Shows the classic "inputs left, output right" split (Sidebar), a Row and a Grid of
cards, a Tabs section, and a collapsible Expander -- all arranging ordinary
children, with no wire-protocol change.

Run it with:  python examples/layout.py
It prints a URL (and embeds inline in a Colab/Runpod cell). No Node, at install or
at runtime.
"""

import indah

name = indah.Signal("Alice")
size = indah.Signal(3)
loud = indah.Signal(False)


def greeting() -> str:
    text = f"Hello, {name.value}!"
    if loud.value:
        text = text.upper()
    return text * int(size.value)


# Inputs on the left, live output on the right.
inputs_and_output = indah.Sidebar(
    children=[
        indah.Column(
            children=[
                indah.TextInput(name, label="Your name"),
                indah.Slider(size, min=1, max=5, step=1, label="Repeat"),
                indah.Checkbox(loud, label="Shout it"),
            ]
        ),
        indah.Column(children=[indah.Text(greeting)]),
    ]
)

# A tabbed section: one panel shown at a time.
sales = {"columns": ["month", "units"], "rows": [["Jan", 120], ["Feb", 138], ["Mar", 156]]}
sections = indah.Tabs(
    labels=["Overview", "Data", "About"],
    children=[
        indah.Row(
            children=[
                indah.Column(children=[indah.Text("Fast"), indah.Text("42ms")]),
                indah.Column(children=[indah.Text("Requests"), indah.Text("1.2k")]),
                indah.Column(children=[indah.Text("Errors"), indah.Text("0")]),
            ]
        ),
        indah.DataFrame(sales, label="Monthly sales"),
        indah.Column(
            children=[
                indah.Text(
                    "## Built with indah\n\n"
                    "These panels use the **layout containers** and render "
                    "*Markdown* in `Text` -- safely: raw HTML like "
                    "`<script>` stays literal text. See the "
                    "[docs](https://leejianrong.github.io/indah/).\n\n"
                    "- Row / Grid / Tabs / Sidebar / Expander\n"
                    "- Markdown + code\n"
                    "- Progress + spinner",
                    markdown=True,
                ),
                indah.Progress(0.65, label="Coverage"),
                indah.Spinner(label="Streaming..."),
            ]
        ),
    ],
)

app = indah.Column(
    children=[
        indah.Text("indah: layout containers"),
        inputs_and_output,
        sections,
        indah.Grid(
            columns=2,
            children=[
                indah.Column(children=[indah.Text("Card A")]),
                indah.Column(children=[indah.Text("Card B")]),
            ],
        ),
        indah.Expander(
            label="Advanced options",
            children=[indah.Text("Tucked away until you need it.")],
        ),
    ]
)

if __name__ == "__main__":
    indah.launch(indah.create_app(session=indah.Session(app)))
