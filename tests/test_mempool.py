import time
import socket
import pytest

from gigachain import (
    Block, Transaction, Input, Output,
    new_genesis, make_coinbase,
    add_block, get_utxo_set,
    mine_block, BLOCK_REWARD, COINBASE_TX_ID,
    Wallet, sign_transaction,
    Node, Mempool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fresh_chain_with_wallet():
    wallet = Wallet.generate()
    chain = [new_genesis(wallet.address)]
    return chain, wallet


def signed_tx(sender: Wallet, utxo_tx_id: str, utxo_out_idx: int,
              recipient: str, amount: int) -> Transaction:
    inp = Input(tx_id=utxo_tx_id, output_index=utxo_out_idx)
    out = Output(recipient=recipient, amount=amount)
    inp.signature = sign_transaction(sender, [inp], [out])
    inp.public_key = sender.public_key_hex()
    return Transaction(inputs=[inp], outputs=[out])


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def start_node(chain=None) -> Node:
    port = free_port()
    node = Node("127.0.0.1", port, chain=chain)
    node.start()
    time.sleep(0.05)
    return node


# ---------------------------------------------------------------------------
# Mempool: valid transactions accepted
# ---------------------------------------------------------------------------

def test_add_valid_tx():
    chain, alice = fresh_chain_with_wallet()
    utxos = get_utxo_set(chain)
    genesis_coinbase = chain[0].transactions[0]

    tx = signed_tx(alice, genesis_coinbase.tx_id, 0, "bob", BLOCK_REWARD)
    mp = Mempool()
    ok, err = mp.add(tx, utxos)
    assert ok, err
    assert mp.contains(tx.tx_id)
    assert mp.size() == 1


def test_mempool_returns_pending_transactions():
    chain, alice = fresh_chain_with_wallet()
    utxos = get_utxo_set(chain)
    genesis_coinbase = chain[0].transactions[0]

    tx = signed_tx(alice, genesis_coinbase.tx_id, 0, "bob", BLOCK_REWARD)
    mp = Mempool()
    mp.add(tx, utxos)

    pending = mp.get_transactions()
    assert len(pending) == 1
    assert pending[0].tx_id == tx.tx_id


# ---------------------------------------------------------------------------
# Mempool: rejection cases
# ---------------------------------------------------------------------------

def test_reject_coinbase():
    chain, _ = fresh_chain_with_wallet()
    utxos = get_utxo_set(chain)
    cb = make_coinbase("miner", 1)
    mp = Mempool()
    ok, err = mp.add(cb, utxos)
    assert not ok
    assert "coinbase" in err


def test_reject_duplicate():
    chain, alice = fresh_chain_with_wallet()
    utxos = get_utxo_set(chain)
    genesis_coinbase = chain[0].transactions[0]

    tx = signed_tx(alice, genesis_coinbase.tx_id, 0, "bob", BLOCK_REWARD)
    mp = Mempool()
    mp.add(tx, utxos)
    ok, err = mp.add(tx, utxos)
    assert not ok
    assert "duplicate" in err


def test_reject_nonexistent_utxo():
    chain, alice = fresh_chain_with_wallet()
    utxos = get_utxo_set(chain)

    tx = signed_tx(alice, "a" * 64, 0, "bob", 10)
    mp = Mempool()
    ok, err = mp.add(tx, utxos)
    assert not ok
    assert "not in UTXO set" in err


def test_reject_invalid_signature():
    chain, alice = fresh_chain_with_wallet()
    utxos = get_utxo_set(chain)
    genesis_coinbase = chain[0].transactions[0]

    inp = Input(tx_id=genesis_coinbase.tx_id, output_index=0)
    out = Output(recipient="bob", amount=BLOCK_REWARD)
    inp.signature = "00" * 71  # garbage
    inp.public_key = alice.public_key_hex()
    tx = Transaction(inputs=[inp], outputs=[out])

    mp = Mempool()
    ok, err = mp.add(tx, utxos)
    assert not ok
    assert "invalid signature" in err


def test_reject_wrong_owner():
    chain, alice = fresh_chain_with_wallet()
    eve = Wallet.generate()
    utxos = get_utxo_set(chain)
    genesis_coinbase = chain[0].transactions[0]

    # Eve tries to spend Alice's UTXO
    tx = signed_tx(eve, genesis_coinbase.tx_id, 0, "bob", BLOCK_REWARD)
    mp = Mempool()
    ok, err = mp.add(tx, utxos)
    assert not ok
    assert "does not match UTXO recipient" in err


def test_reject_double_spend_in_mempool():
    chain, alice = fresh_chain_with_wallet()
    utxos = get_utxo_set(chain)
    genesis_coinbase = chain[0].transactions[0]

    tx1 = signed_tx(alice, genesis_coinbase.tx_id, 0, "bob", BLOCK_REWARD)
    tx2 = signed_tx(alice, genesis_coinbase.tx_id, 0, "carol", BLOCK_REWARD)

    mp = Mempool()
    ok1, _ = mp.add(tx1, utxos)
    ok2, err2 = mp.add(tx2, utxos)
    assert ok1
    assert not ok2
    assert "already claimed" in err2


def test_reject_outputs_exceed_inputs():
    chain, alice = fresh_chain_with_wallet()
    utxos = get_utxo_set(chain)
    genesis_coinbase = chain[0].transactions[0]

    tx = signed_tx(alice, genesis_coinbase.tx_id, 0, "bob", BLOCK_REWARD + 1)
    mp = Mempool()
    ok, err = mp.add(tx, utxos)
    assert not ok
    assert "outputs exceed inputs" in err


# ---------------------------------------------------------------------------
# Mempool: remove after mining
# ---------------------------------------------------------------------------

def test_remove_clears_transaction():
    chain, alice = fresh_chain_with_wallet()
    utxos = get_utxo_set(chain)
    genesis_coinbase = chain[0].transactions[0]

    tx = signed_tx(alice, genesis_coinbase.tx_id, 0, "bob", BLOCK_REWARD)
    mp = Mempool()
    mp.add(tx, utxos)
    assert mp.size() == 1

    mp.remove([tx.tx_id])
    assert mp.size() == 0
    assert not mp.contains(tx.tx_id)


def test_mined_txs_removed_from_node_mempool():
    chain, alice = fresh_chain_with_wallet()
    genesis_coinbase = chain[0].transactions[0]

    node = Node("127.0.0.1", free_port(), chain=chain)
    tx = signed_tx(alice, genesis_coinbase.tx_id, 0, "bob", BLOCK_REWARD)
    ok, err = node.add_transaction(tx)
    assert ok, err
    assert node.mempool.size() == 1

    # Mine a block that includes the mempool tx
    block = mine_block(node.tip(), node.mempool.get_transactions(), alice.address)
    add_block(node.chain, block)
    node._clean_mempool_after_block(block)

    assert node.mempool.size() == 0


# ---------------------------------------------------------------------------
# Mempool: revalidate after chain replacement
# ---------------------------------------------------------------------------

def test_revalidate_drops_stale_txs():
    chain, alice = fresh_chain_with_wallet()
    genesis_coinbase = chain[0].transactions[0]
    utxos = get_utxo_set(chain)

    tx = signed_tx(alice, genesis_coinbase.tx_id, 0, "bob", BLOCK_REWARD)
    mp = Mempool()
    mp.add(tx, utxos)
    assert mp.size() == 1

    # Simulate chain replacement where the UTXO is now consumed
    # (empty UTXO set — nothing is spendable)
    mp.revalidate({})
    assert mp.size() == 0


# ---------------------------------------------------------------------------
# Network: broadcast and receive transaction
# ---------------------------------------------------------------------------

def test_broadcast_tx_received_by_peer():
    chain, alice = fresh_chain_with_wallet()
    genesis_coinbase = chain[0].transactions[0]

    # Both nodes share the same genesis chain
    node1 = start_node(chain=list(chain))
    node2 = start_node(chain=list(chain))

    try:
        tx = signed_tx(alice, genesis_coinbase.tx_id, 0, "bob", BLOCK_REWARD)

        # node1 adds to its own mempool and broadcasts
        ok, err = node1.add_transaction(tx)
        assert ok, err
        node1.broadcast_transaction(tx, [(node2.host, node2.port)])
        time.sleep(0.1)

        assert node2.mempool.contains(tx.tx_id)
    finally:
        node1.stop()
        node2.stop()


def test_invalid_tx_not_added_via_broadcast():
    chain, alice = fresh_chain_with_wallet()
    eve = Wallet.generate()
    genesis_coinbase = chain[0].transactions[0]

    node1 = start_node(chain=list(chain))
    node2 = start_node(chain=list(chain))

    try:
        # Eve tries to spend Alice's UTXO — invalid
        tx = signed_tx(eve, genesis_coinbase.tx_id, 0, "bob", BLOCK_REWARD)
        node1.broadcast_transaction(tx, [(node2.host, node2.port)])
        time.sleep(0.1)

        assert not node2.mempool.contains(tx.tx_id)
    finally:
        node1.stop()
        node2.stop()


def test_mempool_cleared_after_block_broadcast():
    chain, alice = fresh_chain_with_wallet()
    genesis_coinbase = chain[0].transactions[0]

    node1 = start_node(chain=list(chain))
    node2 = start_node(chain=list(chain))

    try:
        tx = signed_tx(alice, genesis_coinbase.tx_id, 0, "bob", BLOCK_REWARD)

        # Both nodes add the tx to their mempools
        node1.add_transaction(tx)
        node2.add_transaction(tx)
        assert node1.mempool.size() == 1
        assert node2.mempool.size() == 1

        # node1 mines the tx into a block and broadcasts
        block = mine_block(node1.tip(), [tx], alice.address)
        add_block(node1.chain, block)
        node1._clean_mempool_after_block(block)
        node1.broadcast_block(block, [(node2.host, node2.port)])
        time.sleep(0.15)

        assert node1.mempool.size() == 0
        assert node2.mempool.size() == 0
    finally:
        node1.stop()
        node2.stop()
