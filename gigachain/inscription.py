"""
Inscription — Phase 5

Allows transactions to carry arbitrary data embedded as a hex string.
Data is included in tx_id computation. Signatures cover data too.
Inscriptions have no effect on UTXO rules, balance rules, or signature ownership.

Storage model: a `data` field on Transaction (hex string, empty = no inscription).
Indexer: scans a chain and returns all inscriptions keyed by tx_id.
"""

from .block import Block, Transaction, Input, Output

# Maximum raw byte size for inscription data per transaction.
# Keeps block size bounded without additional rules in Phase 5.
MAX_INSCRIPTION_SIZE = 520  # bytes


def make_inscription_tx(
    inputs: list[Input],
    outputs: list[Output],
    data: bytes,
) -> Transaction:
    """
    Build a Transaction carrying inscription data.

    `data` is arbitrary bytes, encoded as hex for storage and transport.
    Raises ValueError if data exceeds MAX_INSCRIPTION_SIZE.
    Signatures must be added to inputs separately (same as any transaction).
    """
    if len(data) > MAX_INSCRIPTION_SIZE:
        raise ValueError(
            f"inscription data is {len(data)} bytes; maximum is {MAX_INSCRIPTION_SIZE}"
        )
    return Transaction(inputs=inputs, outputs=outputs, data=data.hex())


class Indexer:
    """
    Scans a chain and indexes all transactions that carry inscription data.

    Usage:
        indexer = Indexer()
        indexer.scan(chain)
        data_hex = indexer.get(tx_id)
    """

    def __init__(self):
        self._index: dict[str, str] = {}  # tx_id -> hex data

    def scan(self, chain: list[Block]) -> None:
        """Rebuild the index from the full chain."""
        self._index = {}
        for block in chain:
            for tx in block.transactions:
                if tx.data:
                    self._index[tx.tx_id] = tx.data

    def get(self, tx_id: str) -> bytes | None:
        """
        Return the raw bytes for an inscription, or None if not found.
        """
        hex_data = self._index.get(tx_id)
        if hex_data is None:
            return None
        return bytes.fromhex(hex_data)

    def all_tx_ids(self) -> list[str]:
        """Return tx_ids of all transactions carrying inscriptions."""
        return list(self._index.keys())

    def count(self) -> int:
        return len(self._index)
