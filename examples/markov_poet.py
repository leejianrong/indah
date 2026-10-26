"""Markov poet: a word-level Markov chain that writes new verse, streamed word by word.

Pick a small public-domain source, a chain order and a length, and press Generate. The poet
learns, for every run of ``order`` words in the source, which words follow it, then walks
that table one word at a time and streams each word into a `StreamText` as it is chosen.
Line breaks are tokens too, so the output keeps the shape of verse.

Controls:

- **Order** (1 to 3): how many words of context each step looks at. Order 1 wanders; order 3
  mostly quotes the source, because most three-word runs only ever occur once.
- **Randomness** (a temperature): each candidate's weight is ``count ** (1 / temperature)``.
  Low values favour the most common continuation, high values flatten the odds. It matters
  most at order 1, where states have many successors.
- **Seed word**: start from a word of your choice, if the source has it.
- **Fixed random seed**: the same settings then give the same poem every time.

Everything is pure Python and model-free. The chain for a source and order is built once and
shared (three small sources and three orders is at most nine tiny tables), and each session
only holds its own signals, so it stays cheap on a shared host.

Sources, all in the public domain (the authors died long ago and the works were published
in the 19th century): Shakespeare's sonnets (1609), Emily Dickinson's *Poems* (1890), and
the verses in Lewis Carroll's *Alice's Adventures in Wonderland* (1865) and *Through the
Looking-Glass* (1871). The excerpts are typed in below, so this file is self-contained.

Run it with:  python examples/markov_poet.py   (prints a URL; embeds inline in a cell).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Iterator
from dataclasses import dataclass

import indah

NEWLINE = "\n"
MAX_WORDS = 200  # hard cap on one poem, whatever the slider or a caller asks for
FIXED_SEED = 42
WORD_DELAY = 0.04  # seconds between words, so the streaming is visible
_PUNCTUATION = " ,.;:!?\"'()-_"

SHAKESPEARE = """\
Shall I compare thee to a summer's day?
Thou art more lovely and more temperate:
Rough winds do shake the darling buds of May,
And summer's lease hath all too short a date;
Sometime too hot the eye of heaven shines,
And often is his gold complexion dimm'd;
And every fair from fair sometime declines,
By chance or nature's changing course untrimm'd;
But thy eternal summer shall not fade,
Nor lose possession of that fair thou ow'st;
Nor shall death brag thou wander'st in his shade,
When in eternal lines to time thou grow'st:
So long as men can breathe or eyes can see,
So long lives this, and this gives life to thee.

When, in disgrace with fortune and men's eyes,
I all alone beweep my outcast state,
And trouble deaf heaven with my bootless cries,
And look upon myself and curse my fate,
Wishing me like to one more rich in hope,
Featured like him, like him with friends possess'd,
Desiring this man's art and that man's scope,
With what I most enjoy contented least;
Yet in these thoughts myself almost despising,
Haply I think on thee, and then my state,
Like to the lark at break of day arising
From sullen earth, sings hymns at heaven's gate;
For thy sweet love remember'd such wealth brings
That then I scorn to change my state with kings.

That time of year thou mayst in me behold
When yellow leaves, or none, or few, do hang
Upon those boughs which shake against the cold,
Bare ruin'd choirs, where late the sweet birds sang.
In me thou see'st the twilight of such day
As after sunset fadeth in the west,
Which by and by black night doth take away,
Death's second self, that seals up all in rest.
In me thou see'st the glowing of such fire
That on the ashes of his youth doth lie,
As the death-bed whereon it must expire,
Consum'd with that which it was nourish'd by.
This thou perceiv'st, which makes thy love more strong,
To love that well which thou must leave ere long.

Like as the waves make towards the pebbled shore,
So do our minutes hasten to their end;
Each changing place with that which goes before,
In sequent toil all forwards do contend.
Nativity, once in the main of light,
Crawls to maturity, wherewith being crown'd,
Crooked eclipses 'gainst his glory fight,
And time that gave doth now his gift confound.
Time doth transfix the flourish set on youth
And delves the parallels in beauty's brow,
Feeds on the rarities of nature's truth,
And nothing stands but for his scythe to mow:
And yet to times in hope my verse shall stand,
Praising thy worth, despite his cruel hand.

Let me not to the marriage of true minds
Admit impediments. Love is not love
Which alters when it alteration finds,
Or bends with the remover to remove:
O no! it is an ever-fixed mark
That looks on tempests and is never shaken;
It is the star to every wandering bark,
Whose worth's unknown, although his height be taken.
Love's not Time's fool, though rosy lips and cheeks
Within his bending sickle's compass come;
Love alters not with his brief hours and weeks,
But bears it out even to the edge of doom.
If this be error and upon me proved,
I never writ, nor no man ever loved.

My mistress' eyes are nothing like the sun;
Coral is far more red than her lips' red;
If snow be white, why then her breasts are dun;
If hairs be wires, black wires grow on her head.
I have seen roses damask'd, red and white,
But no such roses see I in her cheeks;
And in some perfumes is there more delight
Than in the breath that from my mistress reeks.
I love to hear her speak, yet well I know
That music hath a far more pleasing sound;
I grant I never saw a goddess go;
My mistress, when she walks, treads on the ground:
And yet, by heaven, I think my love as rare
As any she belied with false compare.
"""

DICKINSON = """\
Hope is the thing with feathers
That perches in the soul,
And sings the tune without the words,
And never stops at all,

And sweetest in the gale is heard;
And sore must be the storm
That could abash the little bird
That kept so many warm.

I've heard it in the chillest land,
And on the strangest sea;
Yet, never, in extremity,
It asked a crumb of me.

I'm Nobody! Who are you?
Are you Nobody too?
Then there's a pair of us - don't tell!
They'd banish us, you know.

How dreary to be Somebody!
How public, like a frog
To tell your name the livelong day
To an admiring bog!

There is no Frigate like a Book
To take us Lands away
Nor any Coursers like a Page
Of prancing Poetry -
This Traverse may the poorest take
Without oppress of Toll -
How frugal is the Chariot
That bears the Human Soul.

I taste a liquor never brewed,
From tankards scooped in pearl;
Not all the vats upon the Rhine
Yield such an alcohol!

Inebriate of air am I,
And debauchee of dew,
Reeling, through endless summer days,
From inns of molten blue.

Because I could not stop for Death,
He kindly stopped for me;
The carriage held but just ourselves
And Immortality.

We slowly drove, he knew no haste,
And I had put away
My labor, and my leisure too,
For his civility.

We passed the school where children strove
At recess in the ring;
We passed the fields of gazing grain,
We passed the setting sun.

I'll tell you how the sun rose,
A ribbon at a time.
The steeples swam in amethyst,
The news like squirrels ran.

The hills untied their bonnets,
The bobolinks begun.
Then I said softly to myself,
That must have been the sun!

The soul selects her own society,
Then shuts the door;
On her divine majority
Obtrude no more.

Unmoved, she notes the chariot's pausing
At her low gate;
Unmoved, an emperor is kneeling
Upon her mat.
"""

CARROLL = """\
'Twas brillig, and the slithy toves
Did gyre and gimble in the wabe:
All mimsy were the borogoves,
And the mome raths outgrabe.

"Beware the Jabberwock, my son!
The jaws that bite, the claws that catch!
Beware the Jubjub bird, and shun
The frumious Bandersnatch!"

He took his vorpal sword in hand:
Long time the manxome foe he sought -
So rested he by the Tumtum tree,
And stood awhile in thought.

And, as in uffish thought he stood,
The Jabberwock, with eyes of flame,
Came whiffling through the tulgey wood,
And burbled as it came!

One, two! One, two! And through and through
The vorpal blade went snicker-snack!
He left it dead, and with its head
He went galumphing back.

"And hast thou slain the Jabberwock?
Come to my arms, my beamish boy!
O frabjous day! Callooh! Callay!"
He chortled in his joy.

'Twas brillig, and the slithy toves
Did gyre and gimble in the wabe:
All mimsy were the borogoves,
And the mome raths outgrabe.

How doth the little crocodile
Improve his shining tail,
And pour the waters of the Nile
On every golden scale!

How cheerfully he seems to grin,
How neatly spreads his claws,
And welcomes little fishes in,
With gently smiling jaws!

"You are old, Father William," the young man said,
"And your hair has become very white;
And yet you incessantly stand on your head -
Do you think, at your age, it is right?"

"In my youth," Father William replied to his son,
"I feared it might injure the brain;
But, now that I'm perfectly sure I have none,
Why, I do it again and again."

Twinkle, twinkle, little bat!
How I wonder what you're at!
Up above the world you fly,
Like a tea-tray in the sky.

Speak roughly to your little boy,
And beat him when he sneezes:
He only does it to annoy,
Because he knows it teases.
"""


@dataclass(frozen=True)
class Corpus:
    key: str
    label: str
    credit: str
    text: str


SOURCES: dict[str, Corpus] = {
    s.key: s
    for s in (
        Corpus(
            "sonnets",
            "Shakespeare sonnets",
            "William Shakespeare, Sonnets (1609): numbers 18, 29, 73, 60, 116 and 130. "
            "Public domain.",
            SHAKESPEARE,
        ),
        Corpus(
            "dickinson",
            "Dickinson poems",
            "Emily Dickinson, Poems (1890 and 1891): a selection. Public domain.",
            DICKINSON,
        ),
        Corpus(
            "carroll",
            "Carroll verse",
            "Lewis Carroll, Alice's Adventures in Wonderland (1865) and Through the Looking-Glass "
            "(1871): Jabberwocky and four verses from Alice. Public domain.",
            CARROLL,
        ),
    )
}
DEFAULT_SOURCE = "sonnets"


def tokenize(text: str) -> list[str]:
    """Words as written (case and punctuation kept), with one NEWLINE token per non-blank line."""
    tokens: list[str] = []
    for line in text.splitlines():
        words = line.split()
        if words:
            tokens.extend(words)
            tokens.append(NEWLINE)
    return tokens


def _normalise(word: str) -> str:
    return word.strip(_PUNCTUATION).lower()


@dataclass(frozen=True)
class Chain:
    """A Markov chain over tokens: ``table`` maps each ``order``-token state to its successors
    as ``(token, count)`` pairs. The token list is treated as a ring, so no state is a dead end."""

    order: int
    table: dict[tuple[str, ...], list[tuple[str, int]]]
    starts: list[tuple[str, ...]]  # states that open a line, in source order
    by_first_word: dict[str, list[tuple[str, ...]]]

    @property
    def states(self) -> int:
        return len(self.table)


def build_chain(tokens: list[str], order: int) -> Chain:
    if order < 1:
        raise ValueError("order must be at least 1")
    n = len(tokens)
    if n <= order:
        raise ValueError("not enough text for that order")
    ring = tokens + tokens[:order]
    counts: dict[tuple[str, ...], dict[str, int]] = {}
    starts: list[tuple[str, ...]] = []
    for i in range(n):
        state = tuple(ring[i : i + order])
        nxt = ring[i + order]
        bucket = counts.setdefault(state, {})
        bucket[nxt] = bucket.get(nxt, 0) + 1
        if (i == 0 or ring[i - 1] == NEWLINE) and state[0] != NEWLINE and state not in starts:
            starts.append(state)
    by_first: dict[str, list[tuple[str, ...]]] = {}
    for state in counts:
        if state[0] != NEWLINE:
            by_first.setdefault(_normalise(state[0]), []).append(state)
    table = {state: list(bucket.items()) for state, bucket in counts.items()}
    return Chain(order=order, table=table, starts=starts, by_first_word=by_first)


_chains: dict[tuple[str, int], Chain] = {}


def get_chain(source_key: str, order: int) -> Chain:
    """The chain for a source and order, built once and shared by every session."""
    key = (source_key, min(max(int(order), 1), 3))
    if key not in _chains:
        _chains[key] = build_chain(tokenize(SOURCES[key[0]].text), key[1])
    return _chains[key]


def _pick(choices: list[tuple[str, int]], temperature: float, rng: random.Random) -> str:
    """One successor, weighted by ``count ** (1 / temperature)``."""
    if len(choices) == 1:
        return choices[0][0]
    power = 1.0 / max(temperature, 0.05)
    weights = [count**power for _, count in choices]
    return rng.choices([word for word, _ in choices], weights=weights)[0]


def opening_state(chain: Chain, seed_word: str, rng: random.Random) -> tuple[tuple[str, ...], bool]:
    """The state to start from, and whether the seed word was found (empty counts as found)."""
    wanted = _normalise(seed_word)
    if wanted:
        matches = chain.by_first_word.get(wanted)
        if matches:
            return rng.choice(matches), True
    return rng.choice(chain.starts), not wanted


def generate(
    chain: Chain,
    *,
    length: int,
    seed_word: str = "",
    temperature: float = 1.0,
    rng: random.Random | None = None,
) -> Iterator[str]:
    """Yield tokens until ``length`` words (NEWLINE tokens do not count) have been produced."""
    rng = rng or random.Random()
    length = min(max(int(length), 1), MAX_WORDS)
    state, _ = opening_state(chain, seed_word, rng)
    words = 0
    for token in state:
        if token != NEWLINE:
            words += 1
        yield token
        if words >= length:
            return
    while words < length:
        token = _pick(chain.table[state], temperature, rng)
        state = (*state[1:], token)
        if token != NEWLINE:
            words += 1
        yield token


def pieces(tokens: Iterator[str]) -> Iterator[str]:
    """Text fragments for a stream: a word gets a leading space unless it opens a line."""
    at_line_start = True
    for token in tokens:
        if token == NEWLINE:
            at_line_start = True
            yield NEWLINE
        else:
            yield token if at_line_start else " " + token
            at_line_start = False


def write_poem(
    source_key: str,
    *,
    order: int = 2,
    length: int = 40,
    seed_word: str = "",
    temperature: float = 1.0,
    seed: int | None = None,
) -> str:
    """A whole poem as a string (what the app streams, in one go); ``seed`` fixes the output."""
    chain = get_chain(source_key, order)
    rng = random.Random(seed)
    return "".join(
        pieces(
            generate(chain, length=length, seed_word=seed_word, temperature=temperature, rng=rng)
        )
    ).strip()


def build() -> indah.Session:
    source = indah.Signal(DEFAULT_SOURCE)
    order = indah.Signal(2)
    length = indah.Signal(40)
    temperature = indah.Signal(1.0)
    seed_word = indah.Signal("")
    fixed = indah.Signal(False)
    running = indah.Signal(False)
    status = indah.Signal("")

    poem = indah.StreamText(label="Poem")
    # Open on a finished poem (the same one every time) so the page is not blank.
    poem.feed(write_poem(DEFAULT_SOURCE, order=2, length=40, seed=7))

    async def on_generate() -> None:
        if running.value:
            return
        running.set(True)
        try:
            chain = get_chain(source.value, int(order.value))
            rng = random.Random(FIXED_SEED if fixed.value else None)
            word = seed_word.value[:40]
            _, found = opening_state(chain, word, random.Random(0))
            status.set(
                "" if found else f"'{word.strip()}' is not in this source, so the poet chose."
            )
            poem.reset()
            for piece in pieces(
                generate(
                    chain,
                    length=int(length.value),
                    seed_word=word,
                    temperature=float(temperature.value),
                    rng=rng,
                )
            ):
                poem.feed(piece)
                await asyncio.sleep(WORD_DELAY)
        finally:
            running.set(False)

    def note() -> str:
        chain = get_chain(source.value, int(order.value))
        tokens = len(tokenize(SOURCES[source.value].text))
        return f"Chain of order {chain.order}: {chain.states} states from {tokens} tokens."

    options = [(c.key, c.label) for c in SOURCES.values()]
    controls = indah.Card(
        title="Poet",
        children=[
            indah.Select(source, options=options, label="Source"),
            indah.Slider(order, min=1, max=3, step=1, label="Chain order"),
            indah.Slider(length, min=10, max=120, step=10, label="Length (words)"),
            indah.Slider(temperature, min=0.2, max=2.0, step=0.1, label="Randomness"),
            indah.TextInput(seed_word, placeholder="optional, e.g. love", label="Start with"),
            indah.Switch(fixed, label="Fixed random seed"),
            indah.Button("Generate", on_click=on_generate),
            indah.Spinner(active=running, label="writing..."),
        ],
    )
    workspace = indah.Column(
        children=[
            indah.Card(children=[poem]),
            indah.Text(note),
            indah.Text(lambda: status.value),
            indah.Text(lambda: SOURCES[source.value].credit),
        ]
    )
    intro = indah.Text(
        "# Markov poet\n\n"
        "A word-level Markov chain learns which words follow which in a small public-domain "
        "source, then writes new verse one word at a time. Higher orders copy the source more "
        "closely; the randomness control matters most at order 1.",
        markdown=True,
    )
    return indah.Session(
        indah.Column(children=[intro, indah.Sidebar(children=[controls, workspace])])
    )


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)
