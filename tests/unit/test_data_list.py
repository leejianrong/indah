import pytest

from indah.components import Chat, Gallery, List
from indah.reactive import Signal

# -- List --------------------------------------------------------------------


@pytest.mark.unit
def test_list_of_scalars_serialises_and_has_no_template():
    items = Signal(["a", "b", "c"])
    lst = List(items, empty="nothing here")
    lst.id = "n0"
    node = lst.to_json()
    assert node["type"] == "list"
    assert node["props"] == {"empty": "nothing here", "items": ["a", "b", "c"]}


@pytest.mark.unit
def test_list_reacts_to_signal_set():
    items = Signal([1, 2])
    lst = List(items)
    assert lst.reactive_props()["items"]() == [1, 2]
    items.set([1, 2, 3])
    assert lst.reactive_props()["items"]() == [1, 2, 3]


@pytest.mark.unit
def test_list_empty_source_is_empty_list():
    assert List(Signal(None)).reactive_props()["items"]() == []


@pytest.mark.unit
def test_list_dict_items_are_json_safe():
    lst = List(Signal([{"role": "user", "n": 1}]))
    assert lst.reactive_props()["items"]() == [{"role": "user", "n": 1}]


@pytest.mark.unit
def test_list_item_template_is_validated_and_wired():
    lst = List(
        Signal([{"msg": "hello"}]),
        item={"tag": "div", "class": "log-line", "text": "msg"},
    )
    lst.id = "n0"
    template = lst.to_json()["props"]["template"]
    assert template["tag"] == "div"
    assert template["text"] == "msg"


@pytest.mark.unit
def test_list_rejects_a_disallowed_template_tag():
    with pytest.raises(ValueError):
        List(Signal([]), item={"tag": "script", "text": "msg"})


# -- Chat --------------------------------------------------------------------


@pytest.mark.unit
def test_chat_normalises_messages_and_defaults_pending_empty():
    msgs = Signal([{"role": "user", "content": "hi"}, ("assistant", "hello")])
    chat = Chat(msgs, label="Conversation")
    chat.id = "n0"
    props = chat.to_json()["props"]
    assert props["label"] == "Conversation"
    assert props["messages"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    assert props["pending"] == ""


@pytest.mark.unit
def test_chat_pending_is_reactive():
    pending = Signal("")
    chat = Chat(Signal([]), pending=pending)
    assert chat.reactive_props()["pending"]() == ""
    pending.set("streaming...")
    assert chat.reactive_props()["pending"]() == "streaming..."


@pytest.mark.unit
def test_chat_skips_malformed_messages():
    chat = Chat(Signal([{"role": "user", "content": "ok"}, 42, ["only-one"]]))
    assert chat.reactive_props()["messages"]() == [{"role": "user", "content": "ok"}]


@pytest.mark.unit
def test_chat_message_defaults_role_to_assistant():
    chat = Chat(Signal([{"content": "no role"}]))
    assert chat.reactive_props()["messages"]() == [{"role": "assistant", "content": "no role"}]


# -- Gallery -----------------------------------------------------------------


@pytest.mark.unit
def test_gallery_normalises_string_and_dict_images():
    images = Signal(["https://x/1.png", {"src": "https://x/2.png", "caption": "two"}])
    g = Gallery(images, columns=2, label="Outputs")
    g.id = "n0"
    props = g.to_json()["props"]
    assert props["columns"] == 2
    assert props["label"] == "Outputs"
    assert props["images"] == [
        {"src": "https://x/1.png", "alt": "", "caption": ""},
        {"src": "https://x/2.png", "alt": "", "caption": "two"},
    ]


@pytest.mark.unit
def test_gallery_encodes_bytes_as_data_uri():
    g = Gallery(Signal([b"\x89PNG\r\n"]))
    src = g.reactive_props()["images"]()[0]["src"]
    assert src.startswith("data:image/png;base64,")


@pytest.mark.unit
def test_gallery_reacts_to_signal():
    images = Signal([])
    g = Gallery(images)
    assert g.reactive_props()["images"]() == []
    images.set(["a.png"])
    assert g.reactive_props()["images"]() == [{"src": "a.png", "alt": "", "caption": ""}]
