"""The pure logic of examples/markov_poet.py: tokens, the chain, generation, reproducibility."""

import importlib.util
import random
import sys
from pathlib import Path

import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "markov_poet.py"


@pytest.fixture(scope="module")
def mp():
    spec = importlib.util.spec_from_file_location("markov_poet_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_tokenize_keeps_words_and_marks_line_ends(mp):
    assert mp.tokenize("Hope is a thing\n\nwith feathers\n") == [
        "Hope",
        "is",
        "a",
        "thing",
        "\n",
        "with",
        "feathers",
        "\n",
    ]


@pytest.mark.unit
def test_chain_counts_successors_and_treats_the_text_as_a_ring(mp):
    chain = mp.build_chain(["a", "b", "a", "c"], 1)
    assert dict(chain.table[("a",)]) == {"b": 1, "c": 1}
    assert dict(chain.table[("c",)]) == {"a": 1}  # wraps round to the start
    assert chain.states == 3
    assert chain.starts == [("a",)]


@pytest.mark.unit
def test_every_state_has_a_successor_for_every_source_and_order(mp):
    for key in mp.SOURCES:
        for order in (1, 2, 3):
            chain = mp.get_chain(key, order)
            assert chain.starts
            assert all(choices for choices in chain.table.values())


@pytest.mark.unit
def test_higher_orders_have_more_states(mp):
    counts = [mp.get_chain("sonnets", n).states for n in (1, 2, 3)]
    assert counts[0] < counts[1] < counts[2]


@pytest.mark.unit
def test_chains_are_built_once_and_shared(mp):
    assert mp.get_chain("carroll", 2) is mp.get_chain("carroll", 2)


@pytest.mark.unit
def test_generate_produces_exactly_the_length_in_words(mp):
    chain = mp.get_chain("dickinson", 2)
    tokens = list(mp.generate(chain, length=25, rng=random.Random(1)))
    assert sum(t != mp.NEWLINE for t in tokens) == 25


@pytest.mark.unit
def test_length_is_capped(mp):
    chain = mp.get_chain("dickinson", 1)
    tokens = list(mp.generate(chain, length=10**6, rng=random.Random(1)))
    assert sum(t != mp.NEWLINE for t in tokens) == mp.MAX_WORDS


@pytest.mark.unit
def test_every_step_follows_the_source(mp):
    chain = mp.get_chain("sonnets", 2)
    tokens = list(mp.generate(chain, length=60, rng=random.Random(3)))
    for i in range(2, len(tokens)):
        state = tuple(tokens[i - 2 : i])
        assert tokens[i] in dict(chain.table[state])


@pytest.mark.unit
def test_the_same_seed_gives_the_same_poem_and_others_differ(mp):
    a = mp.write_poem("sonnets", order=1, length=50, seed=42)
    assert a == mp.write_poem("sonnets", order=1, length=50, seed=42)
    assert a != mp.write_poem("sonnets", order=1, length=50, seed=43)


@pytest.mark.unit
def test_seed_word_opens_the_poem_ignoring_case_and_punctuation(mp):
    poem = mp.write_poem("sonnets", order=2, length=12, seed_word="Love,", seed=5)
    assert poem.lower().startswith("love")


@pytest.mark.unit
def test_an_unknown_seed_word_is_reported_not_fatal(mp):
    chain = mp.get_chain("sonnets", 2)
    _, found = mp.opening_state(chain, "zzyzx", random.Random(0))
    assert not found
    assert mp.write_poem("sonnets", seed_word="zzyzx", length=10, seed=1)


@pytest.mark.unit
def test_low_temperature_prefers_the_common_continuation(mp):
    choices = [("rare", 1), ("common", 9)]
    rng = random.Random(0)
    cold = [mp._pick(choices, 0.2, rng) for _ in range(200)]
    hot = [mp._pick(choices, 2.0, rng) for _ in range(200)]
    assert cold.count("common") > hot.count("common")
    assert cold.count("rare") <= 2


@pytest.mark.unit
def test_pieces_join_into_clean_lines(mp):
    text = "".join(mp.pieces(iter(["a", "b", "\n", "c"])))
    assert text == "a b\nc"
