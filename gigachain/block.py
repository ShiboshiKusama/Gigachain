import hashlib
import time
from dataclasses import dataclass, field


BLOCK_REWARD = 50  # placeholder; real value set in Phase 2


@dataclass
class Output:
    recipient: str
    amount: int


@dataclass
class Input:
    tx_id: str
    output_index: int
    # signature: reserved for Phase 3


@dataclass
class Transaction:
    inputs: list[Input]
    outputs: list[Output]
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
    inputs_part = ",".join(f"{i.tx_id}:{i.output_index}" for i in tx.inputs)
    outputs_part = ",".join(f"{o.recipient}:{o.amount}" for o in tx.outputs)
    return _sha256(f"{inputs_part}|{outputs_part}")


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


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------

def make_coinbase(recipient: str) -> Transaction:
    return Transaction(inputs=[], outputs=[Output(recipient=recipient, amount=BLOCK_REWARD)])


def new_genesis(miner_address: str = "genesis") -> Block:
    coinbase = make_coinbase(miner_address)
    return Block(
        index=0,
        timestamp=int(time.time()),
        previous_hash="0" * 64,
        transactions=[coinbase],
    )
