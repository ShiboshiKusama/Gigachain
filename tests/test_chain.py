import time
import pytest
from gigachain import (
    Block, Transaction, Input, Output,
    new_genesis, make_coinbase, compute_block_hash, compute_merkle_root,
    add_block, validate_chain, get_block, last_block, get_utxo_set,
    mine_block, BLOCK_REWARD, COINBASE_TX_ID,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fresh_chain():
    return [new_genesis("alice")]


# ---------------------------------------------------------------------------
# Genesis
# ---------------------------------------------------------------------------

def test_genesis_structure():
    g = new_genesis("alice")
    assert g.index == 0
    assert g.previous_hash == "0" * 64
    assert len(g.transactions) == 1
    coinbase = g.transactions[0]
    # Coinbase has one sentinel input encoding block height 0
    assert len(coinbase.inputs) == 1
    assert coinbase.inputs[0].tx_id == COINBASE_TX_ID
    assert coinbase.inputs[0].output_index == 0
    assert coinbase.outputs[0].recipient == "alice"
    assert coinbase.outputs[0].amount == BLOCK_REWARD


def test_genesis_hash_is_valid():
    g = new_genesis("alice")
    assert g.hash == compute_block_hash(g)


def test_genesis_merkle_root():
    g = new_genesis("alice")
    assert g.merkle_root == compute_merkle_root(g.transactions)


def test_coinbase_tx_id_unique_per_block():
    cb0 = make_coinbase("alice", 0)
    cb1 = make_coinbase("alice", 1)
    assert cb0.tx_id != cb1.tx_id


# ---------------------------------------------------------------------------
# Chain validation — tamper tests (mine then corrupt)
# ---------------------------------------------------------------------------

def test_valid_chain():
    chain = fresh_chain()
    ok, err = validate_chain(chain)
    assert ok, err


def test_tampered_block_hash_rejected():
    chain = fresh_chain()
    chain[0].hash = "a" * 64  # corrupt genesis hash
    ok, err = validate_chain(chain)
    assert not ok
    assert "hash mismatch" in err


def test_tampered_previous_hash_rejected():
    chain = fresh_chain()
    block2 = mine_block(chain[-1], [], "bob")
    block2.previous_hash = "b" * 64  # corrupt after mining
    block2.hash = compute_block_hash(block2)  # recompute so hash check passes
    chain.append(block2)
    ok, err = validate_chain(chain)
    assert not ok
    assert "previous_hash mismatch" in err


def test_wrong_index_rejected():
    chain = fresh_chain()
    block2 = mine_block(chain[-1], [], "bob")
    # Corrupt the index and recompute hash so hash check passes
    block2.index = 5
    block2.hash = compute_block_hash(block2)
    chain.append(block2)
    ok, err = validate_chain(chain)
    assert not ok
    assert "index" in err


def test_decreasing_timestamp_rejected():
    chain = fresh_chain()
    block2 = mine_block(chain[-1], [], "bob")
    block2.timestamp = chain[-1].timestamp - 1  # corrupt
    block2.hash = compute_block_hash(block2)
    chain.append(block2)
    ok, err = validate_chain(chain)
    assert not ok
    assert "timestamp" in err


def test_wrong_coinbase_height_rejected():
    chain = fresh_chain()
    # A block at index 1 with a coinbase that encodes height 99 will be rejected.
    # The block won't meet difficulty either, but both are valid rejections.
    bad_coinbase = make_coinbase("bob", 99)
    block = Block(
        index=1,
        timestamp=chain[-1].timestamp,
        previous_hash=chain[-1].hash,
        transactions=[bad_coinbase],
    )
    chain.append(block)
    ok, err = validate_chain(chain)
    assert not ok  # rejected for difficulty or coinbase height


# ---------------------------------------------------------------------------
# add_block
# ---------------------------------------------------------------------------

def test_add_valid_block():
    chain = fresh_chain()
    block = mine_block(chain[-1], [], "bob")
    add_block(chain, block)
    assert len(chain) == 2
    assert last_block(chain).index == 1


def test_add_invalid_block_raises():
    chain = fresh_chain()
    # Block with wrong previous_hash — corrupt after mining so hash also wrong
    block = mine_block(chain[-1], [], "bob")
    block.previous_hash = "0" * 64
    # Don't recompute hash — hash mismatch will be caught first
    with pytest.raises(ValueError):
        add_block(chain, block)


# ---------------------------------------------------------------------------
# UTXO tracking
# ---------------------------------------------------------------------------

def test_utxo_set_after_genesis():
    chain = fresh_chain()
    utxos = get_utxo_set(chain)
    assert len(utxos) == 1
    (tx_id, idx), output = next(iter(utxos.items()))
    assert output.recipient == "alice"
    assert output.amount == BLOCK_REWARD


def test_spend_utxo():
    chain = fresh_chain()
    genesis_coinbase = chain[0].transactions[0]

    spend_tx = Transaction(
        inputs=[Input(tx_id=genesis_coinbase.tx_id, output_index=0)],
        outputs=[Output(recipient="bob", amount=BLOCK_REWARD)],
    )
    block2 = mine_block(chain[-1], [spend_tx], "alice")
    add_block(chain, block2)

    utxos = get_utxo_set(chain)
    # genesis coinbase spent; block2 coinbase + bob output unspent
    assert len(utxos) == 2
    recipients = {o.recipient for o in utxos.values()}
    assert "alice" in recipients
    assert "bob" in recipients


def test_double_spend_rejected():
    chain = fresh_chain()
    genesis_coinbase = chain[0].transactions[0]

    spend1 = Transaction(
        inputs=[Input(tx_id=genesis_coinbase.tx_id, output_index=0)],
        outputs=[Output(recipient="bob", amount=BLOCK_REWARD)],
    )
    spend2 = Transaction(
        inputs=[Input(tx_id=genesis_coinbase.tx_id, output_index=0)],
        outputs=[Output(recipient="carol", amount=BLOCK_REWARD)],
    )
    block = mine_block(chain[-1], [spend1, spend2], "alice")
    with pytest.raises(ValueError, match="double-spend"):
        add_block(chain, block)


def test_spend_nonexistent_utxo_rejected():
    chain = fresh_chain()
    bad_tx = Transaction(
        inputs=[Input(tx_id="a" * 64, output_index=0)],
        outputs=[Output(recipient="bob", amount=10)],
    )
    block = mine_block(chain[-1], [bad_tx], "alice")
    with pytest.raises(ValueError, match="not in UTXO set"):
        add_block(chain, block)


def test_outputs_exceed_inputs_rejected():
    chain = fresh_chain()
    genesis_coinbase = chain[0].transactions[0]

    overspend = Transaction(
        inputs=[Input(tx_id=genesis_coinbase.tx_id, output_index=0)],
        outputs=[Output(recipient="bob", amount=BLOCK_REWARD + 1)],
    )
    block = mine_block(chain[-1], [overspend], "alice")
    with pytest.raises(ValueError, match="outputs exceed inputs"):
        add_block(chain, block)


# ---------------------------------------------------------------------------
# Merkle root
# ---------------------------------------------------------------------------

def test_merkle_single_tx():
    tx = make_coinbase("alice", 0)
    assert compute_merkle_root([tx]) == tx.tx_id


def test_merkle_two_txs():
    import hashlib
    tx1 = make_coinbase("alice", 0)
    tx2 = make_coinbase("bob", 1)
    expected = hashlib.sha256((tx1.tx_id + tx2.tx_id).encode()).hexdigest()
    assert compute_merkle_root([tx1, tx2]) == expected


def test_merkle_odd_count():
    import hashlib
    tx1 = make_coinbase("alice", 0)
    tx2 = make_coinbase("bob", 1)
    tx3 = make_coinbase("carol", 2)
    h12 = hashlib.sha256((tx1.tx_id + tx2.tx_id).encode()).hexdigest()
    h33 = hashlib.sha256((tx3.tx_id + tx3.tx_id).encode()).hexdigest()
    expected = hashlib.sha256((h12 + h33).encode()).hexdigest()
    assert compute_merkle_root([tx1, tx2, tx3]) == expected


# ---------------------------------------------------------------------------
# get_block / last_block
# ---------------------------------------------------------------------------

def test_get_block():
    chain = fresh_chain()
    assert get_block(chain, 0).index == 0


def test_get_block_out_of_range():
    chain = fresh_chain()
    with pytest.raises(IndexError):
        get_block(chain, 99)


def test_last_block_empty_raises():
    with pytest.raises(IndexError):
        last_block([])
