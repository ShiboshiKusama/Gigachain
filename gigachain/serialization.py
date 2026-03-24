"""
Serialization — Phase 4

Converts Block/Transaction/Input/Output to and from plain dicts for JSON transport.

Rules:
- Computed fields (hash, merkle_root, tx_id) are NOT serialized — they are
  recomputed on deserialization by the dataclass __post_init__ methods.
  This means the receiver always verifies structure independently.
- All field values are already JSON-compatible (str, int).
- Signatures and public keys are hex strings and round-trip cleanly.
"""

from .block import Block, Transaction, Input, Output


def input_to_dict(inp: Input) -> dict:
    return {
        "tx_id": inp.tx_id,
        "output_index": inp.output_index,
        "signature": inp.signature,
        "public_key": inp.public_key,
    }


def input_from_dict(data: dict) -> Input:
    return Input(
        tx_id=data["tx_id"],
        output_index=data["output_index"],
        signature=data.get("signature", ""),
        public_key=data.get("public_key", ""),
    )


def output_to_dict(out: Output) -> dict:
    return {"recipient": out.recipient, "amount": out.amount}


def output_from_dict(data: dict) -> Output:
    return Output(recipient=data["recipient"], amount=data["amount"])


def tx_to_dict(tx: Transaction) -> dict:
    return {
        "inputs": [input_to_dict(i) for i in tx.inputs],
        "outputs": [output_to_dict(o) for o in tx.outputs],
    }


def tx_from_dict(data: dict) -> Transaction:
    return Transaction(
        inputs=[input_from_dict(i) for i in data["inputs"]],
        outputs=[output_from_dict(o) for o in data["outputs"]],
    )


def block_to_dict(block: Block) -> dict:
    # hash, merkle_root are excluded — recomputed on receipt
    return {
        "index": block.index,
        "timestamp": block.timestamp,
        "previous_hash": block.previous_hash,
        "nonce": block.nonce,
        "transactions": [tx_to_dict(tx) for tx in block.transactions],
    }


def block_from_dict(data: dict) -> Block:
    return Block(
        index=data["index"],
        timestamp=data["timestamp"],
        previous_hash=data["previous_hash"],
        nonce=data["nonce"],
        transactions=[tx_from_dict(t) for t in data["transactions"]],
    )
