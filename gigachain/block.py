import hashlib
import time
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Chain constants
# NOTE: SHA-256 is used as a prototype placeholder only.
#       The final hash function will be evaluated for CPU-friendliness
#       before any real network launch.
# ---------------------------------------------------------------------------

BLOCK_REWARD = 50

# Number of leading hex zeros required for a valid block hash.
# Fixed in Phase 2; dynamic adjustment comes in a later phase.
DIFFICULTY = 4

COINBASE_TX_ID = "0" * 64  # sentinel: marks a coinbase input


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Output:
    recipient: str   # address string
    amount: int


@dataclass
class Input:
    tx_id: str
    output_index: int
    # Phase 3: signature fields.
    # Both are empty string for coinbase inputs and for unsigned inputs.
    signature: str = ""       # DER signature hex
    public_key: str = ""      # compressed public key hex


@dataclass
class Transaction:
    inputs: list[Input]
    outputs: list[Output]
    data: str = ""          # hex-encoded inscription data; empty string = no inscription
    tx_id: str = field(default="", init=False)

    def __post_init__(self):
        self.tx_id = compute_tx_id(self)


@dataclass
class Block:
    index: int
    timestamp: int
    previous_hash: str
    transactions: list[Transaction]
    nonce: int = 0
    merkle_root: str = field(default="", init=False)
    hash: str = field(default="", init=False)

    def __post_init__(self):
        self.merkle_root = compute_merkle_root(self.transactions)
        self.hash = compute_block_hash(self)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def compute_tx_id(tx: Transaction) -> str:
    # Signatures are excluded: tx_id commits to inputs, outputs, and inscription data.
    # data="" for non-inscription transactions; the format is always deterministic.
    inputs_part = ",".join(f"{i.tx_id}:{i.output_index}" for i in tx.inputs)
    outputs_part = ",".join(f"{o.recipient}:{o.amount}" for o in tx.outputs)
    return _sha256(f"{inputs_part}|{outputs_part}|{tx.data}")


def compute_merkle_root(transactions: list[Transaction]) -> str:
    if not transactions:
        return "0" * 64
    hashes = [tx.tx_id for tx in transactions]
    while len(hashes) > 1:
        if len(hashes) % 2 == 1:
            hashes.append(hashes[-1])  # duplicate last if odd
        hashes = [_sha256(hashes[i] + hashes[i + 1]) for i in range(0, len(hashes), 2)]
    return hashes[0]


def compute_block_hash(block: Block) -> str:
    serialized = f"{block.index}:{block.timestamp}:{block.previous_hash}:{block.nonce}:{block.merkle_root}"
    return _sha256(serialized)


def meets_target(hash_hex: str, difficulty: int = DIFFICULTY) -> bool:
    """Return True if hash_hex starts with `difficulty` leading zero hex chars."""
    return hash_hex.startswith("0" * difficulty)


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------

def make_coinbase(miner_address: str, block_index: int) -> Transaction:
    """Coinbase transaction. Uses a sentinel input encoding block height
    to ensure unique tx_id per block. Coinbase inputs are unsigned."""
    return Transaction(
        inputs=[Input(tx_id=COINBASE_TX_ID, output_index=block_index)],
        outputs=[Output(recipient=miner_address, amount=BLOCK_REWARD)],
    )


def new_genesis(miner_address: str = "genesis") -> Block:
    coinbase = make_coinbase(miner_address, 0)
    return Block(
        index=0,
        timestamp=int(time.time()),
        previous_hash="0" * 64,
        transactions=[coinbase],
    )
