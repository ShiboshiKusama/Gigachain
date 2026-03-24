from .block import (
    Block, Transaction, Input, Output,
    compute_block_hash, compute_merkle_root,
    meets_target, COINBASE_TX_ID, DIFFICULTY,
)


# ---------------------------------------------------------------------------
# UTXO set
# ---------------------------------------------------------------------------

# A UTXO is identified by (tx_id, output_index).
# The set maps (tx_id, output_index) -> Output.

def get_utxo_set(chain: list[Block]) -> dict[tuple[str, int], Output]:
    utxos: dict[tuple[str, int], Output] = {}
    for block in chain:
        for tx in block.transactions:
            # Add all outputs
            for idx, output in enumerate(tx.outputs):
                utxos[(tx.tx_id, idx)] = output
            # Remove spent outputs; skip coinbase sentinel inputs
            for inp in tx.inputs:
                if inp.tx_id != COINBASE_TX_ID:
                    utxos.pop((inp.tx_id, inp.output_index), None)
    return utxos


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _is_coinbase(tx: Transaction) -> bool:
    """A coinbase transaction has exactly one input with the sentinel tx_id."""
    return len(tx.inputs) == 1 and tx.inputs[0].tx_id == COINBASE_TX_ID


def _validate_block(block: Block, previous: Block | None, utxos_before_block: dict) -> str | None:
    """Return an error string or None if valid."""

    # Genesis rules
    if previous is None:
        if block.index != 0:
            return f"block {block.index}: genesis must have index 0"
        if block.previous_hash != "0" * 64:
            return f"block {block.index}: genesis previous_hash must be 64 zeros"
    else:
        if block.index != previous.index + 1:
            return f"block {block.index}: expected index {previous.index + 1}"
        if block.previous_hash != previous.hash:
            return f"block {block.index}: previous_hash mismatch"
        if block.timestamp < previous.timestamp:
            return f"block {block.index}: timestamp must not decrease"

    # Hash integrity — always recompute, never trust stored value
    expected_hash = compute_block_hash(block)
    if block.hash != expected_hash:
        return f"block {block.index}: hash mismatch"

    # Difficulty target — enforced on all blocks except genesis
    if previous is not None and not meets_target(block.hash, DIFFICULTY):
        return f"block {block.index}: hash does not meet difficulty target ({DIFFICULTY} leading zeros)"

    # Merkle root integrity
    expected_merkle = compute_merkle_root(block.transactions)
    if block.merkle_root != expected_merkle:
        return f"block {block.index}: merkle_root mismatch"

    # Transactions: must have at least one; first must be coinbase
    if not block.transactions:
        return f"block {block.index}: must have at least one transaction (coinbase)"
    if not _is_coinbase(block.transactions[0]):
        return f"block {block.index}: first transaction must be a coinbase"

    # Coinbase input must encode this block's index
    coinbase_height = block.transactions[0].inputs[0].output_index
    if coinbase_height != block.index:
        return f"block {block.index}: coinbase input encodes wrong block height ({coinbase_height})"

    # Validate non-coinbase transactions against utxos_before_block
    spent_in_block: set[tuple[str, int]] = set()
    for tx in block.transactions[1:]:
        if _is_coinbase(tx):
            return f"block {block.index}: only first transaction may be coinbase"
        input_total = 0
        for inp in tx.inputs:
            key = (inp.tx_id, inp.output_index)
            if key not in utxos_before_block:
                return f"block {block.index} tx {tx.tx_id}: input {key} not in UTXO set"
            if key in spent_in_block:
                return f"block {block.index} tx {tx.tx_id}: double-spend of {key}"
            spent_in_block.add(key)
            input_total += utxos_before_block[key].amount
        output_total = sum(o.amount for o in tx.outputs)
        if input_total < output_total:
            return f"block {block.index} tx {tx.tx_id}: outputs exceed inputs"

    return None


# ---------------------------------------------------------------------------
# Chain validation
# ---------------------------------------------------------------------------

def validate_chain(chain: list[Block]) -> tuple[bool, str | None]:
    """Validate every block from genesis to tip. Returns (ok, error_or_None)."""
    utxos: dict[tuple[str, int], Output] = {}
    for i, block in enumerate(chain):
        previous = chain[i - 1] if i > 0 else None
        error = _validate_block(block, previous, utxos)
        if error:
            return False, error
        # Advance UTXO set past this block
        for tx in block.transactions:
            for idx, output in enumerate(tx.outputs):
                utxos[(tx.tx_id, idx)] = output
            for inp in tx.inputs:
                if inp.tx_id != COINBASE_TX_ID:
                    utxos.pop((inp.tx_id, inp.output_index), None)
    return True, None


# ---------------------------------------------------------------------------
# Chain operations
# ---------------------------------------------------------------------------

def add_block(chain: list[Block], block: Block) -> None:
    """Validate and append block. Raises ValueError if invalid."""
    utxos = get_utxo_set(chain)
    previous = chain[-1] if chain else None
    error = _validate_block(block, previous, utxos)
    if error:
        raise ValueError(error)
    chain.append(block)


def get_block(chain: list[Block], index: int) -> Block:
    if index < 0 or index >= len(chain):
        raise IndexError(f"no block at index {index}")
    return chain[index]


def last_block(chain: list[Block]) -> Block:
    if not chain:
        raise IndexError("chain is empty")
    return chain[-1]
