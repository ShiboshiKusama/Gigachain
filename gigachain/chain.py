from .block import Block, Transaction, Input, Output, compute_block_hash, compute_merkle_root


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
            # Remove spent outputs
            for inp in tx.inputs:
                utxos.pop((inp.tx_id, inp.output_index), None)
    return utxos


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

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

    # Merkle root integrity
    expected_merkle = compute_merkle_root(block.transactions)
    if block.merkle_root != expected_merkle:
        return f"block {block.index}: merkle_root mismatch"

    # Transactions: coinbase must be first
    if not block.transactions:
        return f"block {block.index}: must have at least one transaction (coinbase)"
    coinbase = block.transactions[0]
    if coinbase.inputs:
        return f"block {block.index}: first transaction must be coinbase (no inputs)"

    # Validate non-coinbase transactions against utxos_before_block
    spent_in_block: set[tuple[str, int]] = set()
    for tx in block.transactions[1:]:
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
