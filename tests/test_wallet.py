import pytest
from gigachain import (
    Block, Transaction, Input, Output,
    new_genesis, make_coinbase, compute_tx_id,
    add_block, validate_chain, get_utxo_set,
    mine_block, BLOCK_REWARD, COINBASE_TX_ID,
    Wallet, sign_transaction, verify_transaction_signature, public_key_hex_to_address,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fresh_chain():
    wallet = Wallet.generate()
    return [new_genesis(wallet.address)], wallet


def make_signed_tx(sender_wallet, utxo_tx_id, utxo_out_idx, recipient_address, amount):
    """Build a signed transaction spending one UTXO."""
    inp = Input(tx_id=utxo_tx_id, output_index=utxo_out_idx)
    out = Output(recipient=recipient_address, amount=amount)
    sig = sign_transaction(sender_wallet, [inp], [out])
    inp.signature = sig
    inp.public_key = sender_wallet.public_key_hex()
    return Transaction(inputs=[inp], outputs=[out])


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------

def test_wallet_generates_keys():
    w = Wallet.generate()
    assert w.address
    assert w.public_key_hex()
    assert len(w.address) == 40  # 20 hex bytes


def test_two_wallets_have_different_addresses():
    w1 = Wallet.generate()
    w2 = Wallet.generate()
    assert w1.address != w2.address
    assert w1.public_key_hex() != w2.public_key_hex()


def test_address_is_deterministic():
    w = Wallet.generate()
    assert public_key_hex_to_address(w.public_key_hex()) == w.address


def test_invalid_public_key_returns_none():
    assert public_key_hex_to_address("notahex") is None
    assert public_key_hex_to_address("deadbeef") is None


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------

def test_sign_transaction_produces_signature():
    w = Wallet.generate()
    inp = Input(tx_id="a" * 64, output_index=0)
    out = Output(recipient="bob", amount=10)
    sig = sign_transaction(w, [inp], [out])
    assert isinstance(sig, str)
    assert len(sig) > 0


def test_signature_is_deterministic_for_same_key():
    # ECDSA with a deterministic nonce (RFC 6979) is not guaranteed by the
    # cryptography library, but the same content verifies consistently.
    w = Wallet.generate()
    inp = Input(tx_id="a" * 64, output_index=0)
    out = Output(recipient="bob", amount=10)
    sig1 = sign_transaction(w, [inp], [out])
    sig2 = sign_transaction(w, [inp], [out])
    # Both must verify correctly (may differ due to random k in ECDSA)
    assert verify_transaction_signature(sig1, w.public_key_hex(), [inp], [out])
    assert verify_transaction_signature(sig2, w.public_key_hex(), [inp], [out])


def test_signature_varies_by_content():
    w = Wallet.generate()
    inp1 = Input(tx_id="a" * 64, output_index=0)
    inp2 = Input(tx_id="b" * 64, output_index=0)
    out = Output(recipient="bob", amount=10)
    sig1 = sign_transaction(w, [inp1], [out])
    sig2 = sign_transaction(w, [inp2], [out])
    # Different inputs → different messages → different signatures
    assert not verify_transaction_signature(sig1, w.public_key_hex(), [inp2], [out])
    assert not verify_transaction_signature(sig2, w.public_key_hex(), [inp1], [out])


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def test_valid_signature_verifies():
    w = Wallet.generate()
    inp = Input(tx_id="c" * 64, output_index=1)
    out = Output(recipient="alice", amount=25)
    sig = sign_transaction(w, [inp], [out])
    assert verify_transaction_signature(sig, w.public_key_hex(), [inp], [out])


def test_wrong_key_fails_verification():
    w1 = Wallet.generate()
    w2 = Wallet.generate()
    inp = Input(tx_id="d" * 64, output_index=0)
    out = Output(recipient="alice", amount=10)
    sig = sign_transaction(w1, [inp], [out])
    assert not verify_transaction_signature(sig, w2.public_key_hex(), [inp], [out])


def test_tampered_output_fails_verification():
    w = Wallet.generate()
    inp = Input(tx_id="e" * 64, output_index=0)
    out = Output(recipient="alice", amount=10)
    sig = sign_transaction(w, [inp], [out])
    tampered_out = Output(recipient="eve", amount=10)
    assert not verify_transaction_signature(sig, w.public_key_hex(), [inp], [tampered_out])


def test_tampered_amount_fails_verification():
    w = Wallet.generate()
    inp = Input(tx_id="f" * 64, output_index=0)
    out = Output(recipient="alice", amount=10)
    sig = sign_transaction(w, [inp], [out])
    tampered_out = Output(recipient="alice", amount=9999)
    assert not verify_transaction_signature(sig, w.public_key_hex(), [inp], [tampered_out])


def test_signatures_excluded_from_tx_id():
    # tx_id must not change when signature fields are set
    inp = Input(tx_id="a" * 64, output_index=0)
    out = Output(recipient="bob", amount=10)
    tx_before = Transaction(inputs=[inp], outputs=[out])
    tx_id_before = tx_before.tx_id

    inp.signature = "deadsig"
    inp.public_key = "deadkey"
    tx_after = Transaction(inputs=[inp], outputs=[out])
    assert tx_after.tx_id == tx_id_before


# ---------------------------------------------------------------------------
# End-to-end: signed transactions in mined blocks
# ---------------------------------------------------------------------------

def test_signed_tx_accepted_in_chain():
    alice = Wallet.generate()
    bob = Wallet.generate()

    chain = [new_genesis(alice.address)]
    genesis_coinbase = chain[0].transactions[0]

    tx = make_signed_tx(alice, genesis_coinbase.tx_id, 0, bob.address, BLOCK_REWARD)
    block = mine_block(chain[-1], [tx], alice.address)
    add_block(chain, block)

    ok, err = validate_chain(chain)
    assert ok, err


def test_unsigned_tx_rejected():
    alice = Wallet.generate()
    bob = Wallet.generate()

    chain = [new_genesis(alice.address)]
    genesis_coinbase = chain[0].transactions[0]

    # No signature on input
    tx = Transaction(
        inputs=[Input(tx_id=genesis_coinbase.tx_id, output_index=0)],
        outputs=[Output(recipient=bob.address, amount=BLOCK_REWARD)],
    )
    block = mine_block(chain[-1], [tx], alice.address)
    with pytest.raises(ValueError, match="missing signature"):
        add_block(chain, block)


def test_wrong_key_tx_rejected():
    alice = Wallet.generate()
    bob = Wallet.generate()
    eve = Wallet.generate()

    chain = [new_genesis(alice.address)]
    genesis_coinbase = chain[0].transactions[0]

    # Eve signs a tx spending Alice's UTXO
    tx = make_signed_tx(eve, genesis_coinbase.tx_id, 0, bob.address, BLOCK_REWARD)
    block = mine_block(chain[-1], [tx], alice.address)
    with pytest.raises(ValueError, match="does not match UTXO recipient"):
        add_block(chain, block)


def test_invalid_signature_rejected():
    alice = Wallet.generate()
    bob = Wallet.generate()

    chain = [new_genesis(alice.address)]
    genesis_coinbase = chain[0].transactions[0]

    inp = Input(tx_id=genesis_coinbase.tx_id, output_index=0)
    out = Output(recipient=bob.address, amount=BLOCK_REWARD)
    inp.signature = "00" * 71   # garbage signature
    inp.public_key = alice.public_key_hex()
    tx = Transaction(inputs=[inp], outputs=[out])
    block = mine_block(chain[-1], [tx], alice.address)
    with pytest.raises(ValueError, match="invalid signature"):
        add_block(chain, block)


def test_multi_block_signed_chain_valid():
    alice = Wallet.generate()
    bob = Wallet.generate()
    carol = Wallet.generate()

    chain = [new_genesis(alice.address)]

    # Block 1: alice spends genesis coinbase → bob
    genesis_coinbase = chain[0].transactions[0]
    tx1 = make_signed_tx(alice, genesis_coinbase.tx_id, 0, bob.address, BLOCK_REWARD)
    block1 = mine_block(chain[-1], [tx1], alice.address)
    add_block(chain, block1)

    # Block 2: bob spends his received UTXO → carol
    tx2 = make_signed_tx(bob, tx1.tx_id, 0, carol.address, BLOCK_REWARD)
    block2 = mine_block(chain[-1], [tx2], alice.address)
    add_block(chain, block2)

    ok, err = validate_chain(chain)
    assert ok, err

    utxos = get_utxo_set(chain)
    recipients = {o.recipient for o in utxos.values()}
    assert carol.address in recipients


def test_coinbase_remains_unsigned():
    # Coinbase inputs carry no signature — validation must not require one
    chain = [new_genesis("miner")]
    block = mine_block(chain[-1], [], "miner")
    add_block(chain, block)
    ok, err = validate_chain(chain)
    assert ok, err
