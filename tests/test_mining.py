import pytest
from gigachain import (
    Block, Transaction, Input, Output,
    new_genesis, make_coinbase, compute_block_hash, meets_target,
    add_block, validate_chain, get_utxo_set, last_block,
    mine_block, BLOCK_REWARD, DIFFICULTY, COINBASE_TX_ID,
    Wallet, sign_transaction,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fresh_chain():
    return [new_genesis("miner")]


# ---------------------------------------------------------------------------
# meets_target
# ---------------------------------------------------------------------------

def test_meets_target_pass():
    assert meets_target("0000abcd", 4)


def test_meets_target_fail():
    assert not meets_target("000fabcd", 4)


def test_meets_target_custom_difficulty():
    assert meets_target("00abcd", 2)
    assert not meets_target("0fabcd", 2)


# ---------------------------------------------------------------------------
# mine_block structure
# ---------------------------------------------------------------------------

def test_mined_block_meets_target():
    chain = fresh_chain()
    block = mine_block(chain[-1], [], "miner")
    assert meets_target(block.hash, DIFFICULTY)


def test_mined_block_hash_is_correct():
    chain = fresh_chain()
    block = mine_block(chain[-1], [], "miner")
    assert block.hash == compute_block_hash(block)


def test_mined_block_index():
    chain = fresh_chain()
    block = mine_block(chain[-1], [], "miner")
    assert block.index == 1


def test_mined_block_previous_hash():
    chain = fresh_chain()
    block = mine_block(chain[-1], [], "miner")
    assert block.previous_hash == chain[-1].hash


def test_mined_block_coinbase_is_first():
    chain = fresh_chain()
    block = mine_block(chain[-1], [], "miner")
    coinbase = block.transactions[0]
    assert coinbase.inputs[0].tx_id == COINBASE_TX_ID
    assert coinbase.outputs[0].amount == BLOCK_REWARD
    assert coinbase.outputs[0].recipient == "miner"


def test_mined_block_coinbase_encodes_height():
    chain = fresh_chain()
    block = mine_block(chain[-1], [], "miner")
    coinbase = block.transactions[0]
    assert coinbase.inputs[0].output_index == block.index


def test_mined_block_includes_transactions():
    chain = fresh_chain()
    genesis_coinbase = chain[0].transactions[0]
    spend_tx = Transaction(
        inputs=[Input(tx_id=genesis_coinbase.tx_id, output_index=0)],
        outputs=[Output(recipient="bob", amount=BLOCK_REWARD)],
    )
    block = mine_block(chain[-1], [spend_tx], "miner")
    assert len(block.transactions) == 2  # coinbase + spend_tx
    assert block.transactions[1].tx_id == spend_tx.tx_id


# ---------------------------------------------------------------------------
# Mined blocks pass chain validation
# ---------------------------------------------------------------------------

def test_mined_block_passes_validation():
    chain = fresh_chain()
    block = mine_block(chain[-1], [], "miner")
    add_block(chain, block)
    ok, err = validate_chain(chain)
    assert ok, err


def test_three_mined_blocks_valid_chain():
    chain = fresh_chain()
    for _ in range(3):
        block = mine_block(chain[-1], [], "miner")
        add_block(chain, block)
    assert len(chain) == 4
    ok, err = validate_chain(chain)
    assert ok, err


def test_unmined_block_fails_validation():
    chain = fresh_chain()
    # Build a block without mining (nonce=0 almost certainly won't meet target)
    block = Block(
        index=1,
        timestamp=chain[-1].timestamp,
        previous_hash=chain[-1].hash,
        transactions=[make_coinbase("miner", 1)],
        nonce=0,
    )
    # Only add to chain directly to bypass add_block validation
    chain.append(block)
    ok, err = validate_chain(chain)
    # Genesis is exempt; block 1 must meet difficulty
    if not meets_target(block.hash, DIFFICULTY):
        assert not ok
        assert "difficulty" in err


# ---------------------------------------------------------------------------
# UTXO after mining
# ---------------------------------------------------------------------------

def test_utxo_grows_with_each_mined_block():
    chain = fresh_chain()
    for i in range(3):
        block = mine_block(chain[-1], [], f"miner_{i}")
        add_block(chain, block)
    # 4 blocks total (genesis + 3), each with one coinbase output, none spent
    utxos = get_utxo_set(chain)
    assert len(utxos) == 4


def test_spend_mined_coinbase():
    alice = Wallet.generate()
    chain = [new_genesis(alice.address)]
    block1 = mine_block(chain[-1], [], alice.address)
    add_block(chain, block1)

    # Spend alice's block1 coinbase (signed by alice)
    alice_coinbase = block1.transactions[0]
    inp = Input(tx_id=alice_coinbase.tx_id, output_index=0)
    out = Output(recipient="bob", amount=BLOCK_REWARD)
    inp.signature = sign_transaction(alice, [inp], [out])
    inp.public_key = alice.public_key_hex()
    spend_tx = Transaction(inputs=[inp], outputs=[out])

    block2 = mine_block(chain[-1], [spend_tx], "miner")
    add_block(chain, block2)

    utxos = get_utxo_set(chain)
    recipients = {o.recipient for o in utxos.values()}
    # genesis coinbase + block1 coinbase both spent by now? No:
    # genesis coinbase (alice.address) unspent, block1 coinbase spent, block2 coinbase + bob unspent
    assert "bob" in recipients
    assert "miner" in recipients
