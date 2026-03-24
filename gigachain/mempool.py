"""
Mempool — Phase 4.5

Holds valid unconfirmed transactions waiting to be mined into a block.

Acceptance rules:
  1. Not a coinbase transaction
  2. Not already in the mempool (duplicate)
  3. All inputs exist in the current UTXO set
  4. No input is already claimed by another mempool transaction
  5. Signature and public key present on every input
  6. Public key derives to the UTXO's recipient address
  7. Signature valid over the transaction content
  8. sum(input amounts) >= sum(output amounts)

The mempool does not persist. It is rebuilt from broadcast transactions
between restarts. After a block is accepted, mined transactions are removed.
After a chain replacement, all transactions are revalidated against the new
UTXO set and any that are no longer valid are dropped.
"""

import threading

from .block import Transaction, COINBASE_TX_ID
from .wallet import verify_transaction_signature, public_key_hex_to_address


def _is_coinbase(tx: Transaction) -> bool:
    return len(tx.inputs) == 1 and tx.inputs[0].tx_id == COINBASE_TX_ID


class Mempool:
    def __init__(self):
        self._txs: dict[str, Transaction] = {}          # tx_id -> Transaction
        self._claimed: set[tuple[str, int]] = set()     # UTXOs spoken for by mempool txs
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Add
    # ------------------------------------------------------------------

    def add(self, tx: Transaction, utxo_set: dict) -> tuple[bool, str | None]:
        """
        Validate and add a transaction.

        utxo_set is the current confirmed UTXO set (from get_utxo_set(chain)).
        Returns (True, None) on success or (False, reason) on rejection.
        """
        with self._lock:
            if _is_coinbase(tx):
                return False, "coinbase transactions are not accepted into the mempool"

            if tx.tx_id in self._txs:
                return False, "duplicate transaction"

            input_total = 0
            for inp in tx.inputs:
                key = (inp.tx_id, inp.output_index)

                if key not in utxo_set:
                    return False, f"input {key} not in UTXO set"

                if key in self._claimed:
                    return False, f"input {key} already claimed by another mempool transaction"

                if not inp.signature or not inp.public_key:
                    return False, f"input {key} is missing signature or public key"

                derived = public_key_hex_to_address(inp.public_key)
                if derived is None:
                    return False, f"input {key} has invalid public key"

                if derived != utxo_set[key].recipient:
                    return False, f"input {key} public key does not match UTXO recipient"

                if not verify_transaction_signature(
                    inp.signature, inp.public_key, tx.inputs, tx.outputs
                ):
                    return False, f"input {key} has invalid signature"

                input_total += utxo_set[key].amount

            output_total = sum(o.amount for o in tx.outputs)
            if input_total < output_total:
                return False, "outputs exceed inputs"

            # Accept
            self._txs[tx.tx_id] = tx
            for inp in tx.inputs:
                self._claimed.add((inp.tx_id, inp.output_index))

            return True, None

    # ------------------------------------------------------------------
    # Remove
    # ------------------------------------------------------------------

    def remove(self, tx_ids: list[str]) -> None:
        """Remove transactions by tx_id. Called after a block is accepted."""
        with self._lock:
            for tx_id in tx_ids:
                tx = self._txs.pop(tx_id, None)
                if tx:
                    for inp in tx.inputs:
                        self._claimed.discard((inp.tx_id, inp.output_index))

    def revalidate(self, utxo_set: dict) -> None:
        """
        Drop any mempool transactions whose inputs are no longer in the UTXO set.
        Called after a chain replacement so stale transactions don't linger.
        """
        with self._lock:
            stale = [
                tx_id for tx_id, tx in self._txs.items()
                if any((i.tx_id, i.output_index) not in utxo_set for i in tx.inputs)
            ]
            for tx_id in stale:
                tx = self._txs.pop(tx_id)
                for inp in tx.inputs:
                    self._claimed.discard((inp.tx_id, inp.output_index))

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_transactions(self) -> list[Transaction]:
        """Return a snapshot of all pending transactions."""
        with self._lock:
            return list(self._txs.values())

    def contains(self, tx_id: str) -> bool:
        with self._lock:
            return tx_id in self._txs

    def size(self) -> int:
        with self._lock:
            return len(self._txs)
