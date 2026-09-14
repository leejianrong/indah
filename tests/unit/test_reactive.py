import pytest

from indah.reactive import Signal, batch, computed, effect


@pytest.mark.unit
def test_effect_runs_once_immediately():
    s = Signal(1)
    seen = []
    effect(lambda: seen.append(s.value))
    assert seen == [1]


@pytest.mark.unit
def test_effect_reruns_on_change():
    s = Signal(1)
    seen = []
    effect(lambda: seen.append(s.value))
    s.set(2)
    s.set(3)
    assert seen == [1, 2, 3]


@pytest.mark.unit
def test_setting_same_value_does_not_rerun():
    s = Signal(1)
    seen = []
    effect(lambda: seen.append(s.value))
    s.set(1)
    assert seen == [1]


@pytest.mark.unit
def test_effect_tracks_only_signals_it_reads():
    a = Signal(1)
    b = Signal(10)
    seen = []
    effect(lambda: seen.append(a.value))  # never reads b
    b.set(20)
    assert seen == [1]  # unaffected by b


@pytest.mark.unit
def test_computed_derives_and_updates():
    a = Signal(2)
    b = Signal(3)
    total = computed(lambda: a.value + b.value)
    assert total.value == 5
    a.set(10)
    assert total.value == 13


@pytest.mark.unit
def test_computed_only_notifies_when_result_changes():
    n = Signal(2)
    parity = computed(lambda: n.value % 2)  # 0 for even
    seen = []
    effect(lambda: seen.append(parity.value))
    assert seen == [0]
    n.set(4)  # still even -> parity unchanged -> effect must NOT rerun
    assert seen == [0]
    n.set(5)  # now odd -> parity changes -> effect reruns
    assert seen == [0, 1]


@pytest.mark.unit
def test_chain_signal_to_computed_to_effect_sees_fresh_value():
    a = Signal(1)
    b = Signal(1)
    total = computed(lambda: a.value + b.value)
    seen = []
    effect(lambda: seen.append(total.value))
    a.set(5)
    assert seen[-1] == 6  # not a stale intermediate


@pytest.mark.unit
def test_batch_coalesces_into_single_rerun():
    a = Signal(1)
    b = Signal(1)
    runs = []
    effect(lambda: runs.append((a.value, b.value)))
    batch(lambda: (a.set(2), b.set(3)))
    assert runs == [(1, 1), (2, 3)]  # one rerun after the batch, not two
