"""Signed session tokens (ADR-0033, IND-114): sign/verify, binding and rotation."""

import pytest

from indah.auth import Principal, TokenSigner

KEY = "a-long-random-secret-value-0123456789"
ALICE = Principal(id="alice")


@pytest.mark.unit
def test_a_minted_token_verifies_for_its_principal_and_yields_the_sid():
    signer = TokenSigner(KEY)
    token = signer.mint(ALICE)
    sid = signer.verify(token, ALICE)
    assert sid and token.startswith(sid + ".")
    assert signer.mint(ALICE, sid) == token  # deterministic for a sid: resume returns the same


@pytest.mark.unit
def test_sids_are_random_and_long_enough():
    signer = TokenSigner(KEY)
    sids = {signer.verify(signer.mint(ALICE), ALICE) for _ in range(50)}
    assert len(sids) == 50 and all(len(s) >= 22 for s in sids)  # 16 bytes, base64url


@pytest.mark.unit
def test_a_token_is_bound_to_the_principal_and_workspace():
    signer = TokenSigner(KEY)
    token = signer.mint(Principal(id="alice", workspace="w1"))
    assert signer.verify(token, Principal(id="alice", workspace="w1"))
    assert signer.verify(token, Principal(id="mallory", workspace="w1")) is None
    assert signer.verify(token, Principal(id="alice", workspace="w2")) is None
    assert signer.verify(token, Principal(id="alice")) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    [None, 5, "", ".", "abc", "a.b.c", "x" * 300, "short.sig", "../../etc/passwd.x", b"bytes"],
)
def test_malformed_tokens_never_verify(bad):
    assert TokenSigner(KEY).verify(bad, ALICE) is None


@pytest.mark.unit
def test_tampering_with_the_sid_or_signature_fails():
    signer = TokenSigner(KEY)
    sid, _, sig = signer.mint(ALICE).partition(".")
    assert signer.verify(f"{sid[:-1]}{'A' if sid[-1] != 'A' else 'B'}.{sig}", ALICE) is None
    assert signer.verify(f"{sid}.{sig[:-1]}{'A' if sig[-1] != 'A' else 'B'}", ALICE) is None
    assert signer.verify(f"{sid}.", ALICE) is None


@pytest.mark.unit
def test_a_different_secret_does_not_verify():
    token = TokenSigner(KEY).mint(ALICE)
    assert TokenSigner("another-long-random-secret-value-xyz").verify(token, ALICE) is None


@pytest.mark.unit
def test_rotation_new_secret_signs_old_secret_still_verifies():
    old, new = "old-secret-value-0123456789abcdef", "new-secret-value-0123456789abcdef"
    old_token = TokenSigner(old).mint(ALICE)
    rotating = TokenSigner([new, old])
    assert rotating.verify(old_token, ALICE)  # still accepted during rotation
    fresh = rotating.mint(ALICE)
    assert TokenSigner(new).verify(fresh, ALICE)  # signed with the first
    assert TokenSigner(old).verify(fresh, ALICE) is None
    assert TokenSigner(new).verify(old_token, ALICE) is None  # old dropped: refused


@pytest.mark.unit
@pytest.mark.parametrize("secret", ["", "short", [], ["ok-secret-value-0123456789", "tiny"], b"x"])
def test_weak_or_missing_secrets_are_refused(secret):
    with pytest.raises(ValueError, match="secret"):
        TokenSigner(secret)
