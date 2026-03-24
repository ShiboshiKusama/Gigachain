import time
import pytest
from gigachain import (
    Block, Transaction, Input, Output,
    new_genesis, make_coinbase, compute_block_hash, compute_merkle_root,
    add_block, validate_chain, get_block, last_block, get_utxo_set,
    BLOCK_REWARD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_block(index, previous_hash, transactions, timestamp=None):
    return Block(
        index=index,
        timestamp=timestamp or int(time.time()),
        previous_hash=previous_hash,
        transactions=transactions,
    )


def fresh_chain():
    genesis = new_genesis("alice")
    return [genesis]


# ---------------------------------------------------------------------------
# Genesis
# ---------------------------------------------------------------------------

def test_genesis_structure():
    g = new_genesis("alice")
    assert g.index == 0
    assert g.previous_hash == "0" * 64
    assert len(g.transactions) == 1
    coinbase = g.transactions[0]
    assert coinbase.inputs == []
    assert coinbase.outputs[0].recipient == "alice"
    assert coinbase.outputs[0].amount == BLOCK_REWARD


def test_genesis_hash_is_valid():
    g = new_genesis("alice")
    assert g.hash == compute_block_hash(g)


def test_genesis_merkle_root():
    g = new_genesis("alice")
    assert g.merkle_root == compute_merkle_root(g.transactions)


# ---------------------------------------------------------------------------
# Chain validation
# ---------------------------------------------------------------------------

def test_valid_chain():
    chain = fresh_chain()
    ok, err = validate_chain(chain)
    assert ok, err


def test_tampered_block_hash_rejected():
    chain = fresh_chain()
    chain[0].hash = "a" * 64  # tamper
    ok, err = validate_chain(chain)
    assert not ok
    assert "hash mismatch" in err


def test_tampered_previous_hash_rejected():
    chain = fresh_chain()
    genesis = chain[0]
    block2 = make_block(1, "b" * 64, [make_coinbase("bob")])
    chain.append(block2)
    ok, err = validate_chain(chain)
    assert not ok
    assert "previous_hash mismatch" in err


def test_wrong_index_rejected():
    chain = fresh_chain()
    block = make_block(5, chain[-1].hash, [make_coinbase("bob")])
    chain.append(block)
    ok, err = validate_chain(chain)
    assert not ok
    assert "index" in err


def test_decreasing_timestamp_rejected():
    chain = fresh_chain()
    block = make_block(1, chain[-1].hash, [make_coinbase("bob")], timestamp=chain[-1].timestamp - 1)
    chain.append(block)
    ok, err = validate_chain(chain)
    assert not ok
    assert "timestamp" in err


# ---------------------------------------------------------------------------
# add_block
# ---------------------------------------------------------------------------

def test_add_valid_block():
    chain = fresh_chain()
    block = make_block(1, chain[-1].hash, [make_coinbase("bob")])
    add_block(chain, block)
    assert len(chain) == 2
    assert last_block(chain).index == 1


def test_add_invalid_block_raises():
    chain = fresh_chain()
    bad = make_block(1, "0" * 64, [make_coinbase("bob")])  # wrong previous_hash
    with pytest.raises(ValueError):
        add_block(chain, bad)


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
    # Use a distinct miner address to avoid coinbase tx_id collision with genesis.
    # (Two coinbase txs with identical inputs/outputs produce the same tx_id.
    # Block-height inclusion in coinbase is a Phase 2 concern.)
    block2 = make_block(1, chain[-1].hash, [make_coinbase("miner_b"), spend_tx])
    add_block(chain, block2)

    utxos = get_utxo_set(chain)
    # genesis coinbase is spent; block2 coinbase + spend output are unspent
    assert len(utxos) == 2
    recipients = {o.recipient for o in utxos.values()}
    assert "miner_b" in recipients
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
    block = make_block(1, chain[-1].hash, [make_coinbase("alice"), spend1, spend2])
    with pytest.raises(ValueError, match="double-spend"):
        add_block(chain, block)


def test_spend_nonexistent_utxo_rejected():
    chain = fresh_chain()
    bad_tx = Transaction(
        inputs=[Input(tx_id="a" * 64, output_index=0)],
        outputs=[Output(recipient="bob", amount=10)],
    )
    block = make_block(1, chain[-1].hash, [make_coinbase("alice"), bad_tx])
    with pytest.raises(ValueError, match="not in UTXO set"):
        add_block(chain, block)


def test_outputs_exceed_inputs_rejected():
    chain = fresh_chain()
    genesis_coinbase = chain[0].transactions[0]

    overspend = Transaction(
        inputs=[Input(tx_id=genesis_coinbase.tx_id, output_index=0)],
        outputs=[Output(recipient="bob", amount=BLOCK_REWARD + 1)],
    )
    block = make_block(1, chain[-1].hash, [make_coinbase("alice"), overspend])
    with pytest.raises(ValueError, match="outputs exceed inputs"):
        add_block(chain, block)


# ---------------------------------------------------------------------------
# Merkle root
# ---------------------------------------------------------------------------

def test_merkle_single_tx():
    tx = make_coinbase("alice")
    assert compute_merkle_root([tx]) == tx.tx_id


def test_merkle_two_txs():
    import hashlib
    tx1 = make_coinbase("alice")
    tx2 = make_coinbase("bob")
    expected = hashlib.sha256((tx1.tx_id + tx2.tx_id).encode()).hexdigest()
    assert compute_merkle_root([tx1, tx2]) == expected


def test_merkle_odd_count():
    # Three transactions: last one duplicated before pairing at level 2
    import hashlib
    tx1 = make_coinbase("alice")
    tx2 = make_coinbase("bob")
    tx3 = make_coinbase("carol")
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
