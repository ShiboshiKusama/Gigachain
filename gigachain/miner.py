import time
from .block import Block, Transaction, make_coinbase, compute_block_hash, meets_target, DIFFICULTY


def mine_block(
    previous: Block,
    transactions: list[Transaction],
    miner_address: str,
    fees: int = 0,
) -> Block:
    """
    Mine a new block on top of `previous`.

    Builds a block candidate with a coinbase transaction prepended,
    then increments nonce until the block hash meets the difficulty target.

    SHA-256 is used as a prototype hash function only.
    The final hash function will be chosen for CPU-friendliness before mainnet.
    """
    index = previous.index + 1
    timestamp = int(time.time())
    coinbase = make_coinbase(miner_address, index, fees)
    all_txs = [coinbase] + list(transactions)

    # Build the initial block candidate (merkle_root computed once here)
    block = Block(
        index=index,
        timestamp=timestamp,
        previous_hash=previous.hash,
        transactions=all_txs,
        nonce=0,
    )

    # Mining loop: increment nonce until hash meets target.
    # merkle_root is fixed; only nonce and hash change each iteration.
    while not meets_target(block.hash, DIFFICULTY):
        block.nonce += 1
        block.hash = compute_block_hash(block)

    return block
