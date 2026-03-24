import time
import socket
import threading
import pytest

from gigachain import (
    Block, Transaction, Input, Output,
    new_genesis, make_coinbase,
    add_block, validate_chain,
    mine_block, BLOCK_REWARD,
    Wallet, sign_transaction,
    block_to_dict, block_from_dict,
    Node,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def free_port() -> int:
    """Ask the OS for an available port."""
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def start_node(chain=None) -> Node:
    """Create and start a node on a free port."""
    port = free_port()
    node = Node("127.0.0.1", port, chain=chain)
    node.start()
    time.sleep(0.05)  # let the listener thread start
    return node


def mine_n_blocks(chain: list[Block], n: int, miner: str = "miner") -> None:
    """Mine n blocks onto chain in place."""
    for _ in range(n):
        block = mine_block(chain[-1], [], miner)
        add_block(chain, block)


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

def test_block_round_trip():
    genesis = new_genesis("alice")
    data = block_to_dict(genesis)
    restored = block_from_dict(data)
    assert restored.index == genesis.index
    assert restored.hash == genesis.hash
    assert restored.merkle_root == genesis.merkle_root
    assert len(restored.transactions) == 1


def test_block_round_trip_mined():
    chain = [new_genesis("alice")]
    block = mine_block(chain[-1], [], "alice")
    data = block_to_dict(block)
    restored = block_from_dict(data)
    assert restored.hash == block.hash
    assert restored.nonce == block.nonce
    assert restored.previous_hash == block.previous_hash


# ---------------------------------------------------------------------------
# Chain sync — basic
# ---------------------------------------------------------------------------

def test_sync_adopts_longer_chain():
    # node1 has 3 extra mined blocks; node2 starts with only genesis
    chain1 = [new_genesis("miner")]
    mine_n_blocks(chain1, 3)

    node1 = start_node(chain=chain1)
    node2 = start_node()

    try:
        assert node2.chain_length() == 1
        replaced = node2.sync_from(node1.host, node1.port)
        assert replaced is True
        assert node2.chain_length() == 4
    finally:
        node1.stop()
        node2.stop()


def test_sync_does_not_replace_equal_length():
    chain1 = [new_genesis("miner_a")]
    chain2 = [new_genesis("miner_b")]

    node1 = start_node(chain=chain1)
    node2 = start_node(chain=chain2)

    try:
        replaced = node2.sync_from(node1.host, node1.port)
        assert replaced is False
        assert node2.chain_length() == 1
    finally:
        node1.stop()
        node2.stop()


def test_sync_does_not_replace_when_local_is_longer():
    short_chain = [new_genesis("short")]
    long_chain = [new_genesis("long")]
    mine_n_blocks(long_chain, 3)

    node_short = start_node(chain=short_chain)
    node_long = start_node(chain=long_chain)

    try:
        # long node tries to sync from short — should not replace
        replaced = node_long.sync_from(node_short.host, node_short.port)
        assert replaced is False
        assert node_long.chain_length() == 4
    finally:
        node_short.stop()
        node_long.stop()


# ---------------------------------------------------------------------------
# Chain sync — invalid peer chain rejected
# ---------------------------------------------------------------------------

def test_sync_rejects_tampered_chain():
    chain1 = [new_genesis("miner")]
    mine_n_blocks(chain1, 2)

    # Tamper with a field value so the chain fails validation on receipt.
    # Changing previous_hash breaks linkage; since it's a field (not computed),
    # it gets serialized and the receiver reconstructs a block with wrong linkage.
    chain1[1].previous_hash = "b" * 64

    node1 = start_node(chain=chain1)
    node2 = start_node()

    try:
        replaced = node2.sync_from(node1.host, node1.port)
        assert replaced is False
        assert node2.chain_length() == 1  # local chain unchanged
    finally:
        node1.stop()
        node2.stop()


def test_sync_rejects_chain_failing_difficulty():
    # Build a chain where one block doesn't meet difficulty
    chain1 = [new_genesis("miner")]
    # Add an unmined block (nonce=0 almost certainly fails difficulty)
    raw_block = Block(
        index=1,
        timestamp=chain1[-1].timestamp,
        previous_hash=chain1[-1].hash,
        transactions=[make_coinbase("miner", 1)],
        nonce=0,
    )
    chain1.append(raw_block)

    node1 = start_node(chain=chain1)
    node2 = start_node()

    try:
        replaced = node2.sync_from(node1.host, node1.port)
        # Either rejected (difficulty) or accepted (extremely unlikely nonce=0 hit)
        from gigachain import meets_target, DIFFICULTY
        if not meets_target(raw_block.hash, DIFFICULTY):
            assert replaced is False
    finally:
        node1.stop()
        node2.stop()


# ---------------------------------------------------------------------------
# Block broadcast
# ---------------------------------------------------------------------------

def test_broadcast_block_accepted():
    chain1 = [new_genesis("miner")]
    chain2 = [new_genesis("miner")]  # same genesis

    node1 = start_node(chain=chain1)
    node2 = start_node(chain=chain2)

    try:
        block = mine_block(node1.tip(), [], "miner")
        add_block(node1.chain, block)

        node1.broadcast_block(block, [(node2.host, node2.port)])
        time.sleep(0.1)  # let node2's handler thread process the message

        assert node2.chain_length() == 2
        assert node2.tip().hash == block.hash
    finally:
        node1.stop()
        node2.stop()


def test_broadcast_invalid_block_ignored():
    chain1 = [new_genesis("miner")]
    chain2 = [new_genesis("miner")]

    node1 = start_node(chain=chain1)
    node2 = start_node(chain=chain2)

    try:
        # Broadcast a block with wrong previous_hash — node2 should ignore it
        bad_block = Block(
            index=1,
            timestamp=chain1[-1].timestamp,
            previous_hash="f" * 64,  # wrong
            transactions=[make_coinbase("miner", 1)],
            nonce=99999,
        )
        node1.broadcast_block(bad_block, [(node2.host, node2.port)])
        time.sleep(0.1)

        assert node2.chain_length() == 1  # unchanged
    finally:
        node1.stop()
        node2.stop()


def test_broadcast_to_unreachable_peer_does_not_crash():
    chain = [new_genesis("miner")]
    node = start_node(chain=chain)

    try:
        block = mine_block(node.tip(), [], "miner")
        # Port 1 is almost certainly not listening
        node.broadcast_block(block, [("127.0.0.1", 1)])
        # No exception should propagate
    finally:
        node.stop()


# ---------------------------------------------------------------------------
# End-to-end: mine on node1, sync to node2
# ---------------------------------------------------------------------------

def test_end_to_end_sync_after_mining():
    genesis = new_genesis("miner")
    chain1 = [genesis]
    chain2 = [genesis]  # same genesis block object

    node1 = start_node(chain=chain1)
    node2 = start_node(chain=chain2)

    try:
        # Mine 3 blocks on node1
        mine_n_blocks(node1.chain, 3, miner="miner")

        assert node1.chain_length() == 4
        assert node2.chain_length() == 1

        replaced = node2.sync_from(node1.host, node1.port)
        assert replaced is True
        assert node2.chain_length() == 4

        ok, err = validate_chain(node2.get_chain())
        assert ok, err
    finally:
        node1.stop()
        node2.stop()


def test_new_block_triggers_sync_when_not_connecting():
    """
    If a broadcast block does not connect to the receiver's tip
    (e.g. receiver is behind by more than one block), the receiver
    should trigger a sync_from and end up with the full chain.
    """
    genesis = new_genesis("miner")
    chain1 = [genesis]
    chain2 = [genesis]

    node1 = start_node(chain=chain1)
    node2 = start_node(chain=chain2)

    try:
        # Mine 3 blocks on node1 without syncing node2
        mine_n_blocks(node1.chain, 3, miner="miner")

        # Broadcast only the latest block (block 3) to node2.
        # node2 is at block 0, so block 3 does not connect → sync triggered.
        tip = node1.tip()
        node1.broadcast_block(tip, [(node2.host, node2.port)])
        time.sleep(0.3)  # allow handler + sync to complete

        assert node2.chain_length() == 4
    finally:
        node1.stop()
        node2.stop()


def test_node_serves_chain_to_multiple_clients():
    chain = [new_genesis("miner")]
    mine_n_blocks(chain, 2)
    node = start_node(chain=chain)

    clients = [start_node() for _ in range(3)]
    try:
        for client in clients:
            replaced = client.sync_from(node.host, node.port)
            assert replaced is True
            assert client.chain_length() == 3
    finally:
        node.stop()
        for c in clients:
            c.stop()
