# Spec — Phase 1: Local Blockchain Prototype

Phase 1 is intentionally minimal. The goal is a working in-memory chain with correct hash linkage and basic UTXO-style transactions. No mining, no signatures, no networking.

---

## Block Structure

| Field | Type | Description |
|---|---|---|
| `index` | integer | Block height; genesis is 0 |
| `timestamp` | integer | Unix time in seconds |
| `previous_hash` | string (64 hex chars) | Hash of the prior block; all zeros for genesis |
| `nonce` | integer | Reserved for PoW (Phase 2); set to 0 in Phase 1 |
| `transactions` | list of Transaction | Ordered list of transactions in this block; coinbase is always first |
| `merkle_root` | string (64 hex chars) | Commitment to all transactions; see Merkle Root below |
| `hash` | string (64 hex chars) | Computed from block contents; never trusted as stored data |

### Hash Rule

The block hash is always **recomputed by the node** from the block's fields. A stored hash value is never accepted at face value — it must be verified.

```
hash = SHA256(serialize(index, timestamp, previous_hash, nonce, merkle_root))
```

SHA-256 is used here as a **prototype placeholder only**. The final chain hash function will be evaluated for CPU-friendliness before any real network launch.

### Serialization

Block fields are serialized as a UTF-8 string in this fixed field order:

```
"{index}:{timestamp}:{previous_hash}:{nonce}:{merkle_root}"
```

Rules:
- Fields are joined by `:` in the order listed above
- No extra whitespace
- Integer fields are decimal strings with no leading zeros (except `0` itself)

This format is deterministic and unambiguous. It can be replaced with binary encoding later without changing validation logic.

### Merkle Root

The merkle root commits to all transactions in the block:

1. Compute `tx_id` for each transaction (see Transaction Hash below)
2. If only one transaction, merkle root = that `tx_id`
3. Otherwise, hash pairs: `SHA256(left_tx_id + right_tx_id)` up a binary tree until one hash remains
4. If the count at any level is odd, duplicate the last hash before pairing

The merkle root is included in the block serialization and therefore covered by the block hash.

### Difficulty (Phase 1)

Difficulty is not enforced in Phase 1. The nonce is always 0 and no hash target is checked. Difficulty is defined and enforced starting in Phase 2.

---

## Transaction Structure

Gigachain uses a **UTXO model**. Transactions consume existing unspent outputs and produce new ones. Phase 1 omits signatures; the structure is designed so signatures slot in cleanly in Phase 3.

### Transaction

| Field | Type | Description |
|---|---|---|
| `tx_id` | string (64 hex chars) | Hash of this transaction's contents |
| `inputs` | list of Input | UTXOs being spent |
| `outputs` | list of Output | New UTXOs being created |

### Input

| Field | Type | Description |
|---|---|---|
| `tx_id` | string | The transaction that created the UTXO being spent |
| `output_index` | integer | Index into that transaction's output list |
| `signature` | — | **Omitted in Phase 1**; field reserved for Phase 3 |

### Output

| Field | Type | Description |
|---|---|---|
| `recipient` | string | Destination address (placeholder string in Phase 1) |
| `amount` | integer | Value in the smallest unit (no decimals) |

### Coinbase Transaction

The first transaction in any block is the coinbase. It has no inputs. Its single output pays the block reward to the miner address.

```
inputs:  []
outputs: [{ recipient: <miner_address>, amount: BLOCK_REWARD }]
```

`BLOCK_REWARD` is a constant defined at the chain level (set the value in Phase 2; placeholder for Phase 1).

### Transaction Hash

```
tx_id = SHA256(serialize(inputs, outputs))
```

Serialization for inputs: `"{tx_id}:{output_index}"` joined by `,`
Serialization for outputs: `"{recipient}:{amount}"` joined by `,`
Combined: `"{serialized_inputs}|{serialized_outputs}"`

**Ordering rule:** Inputs and outputs are serialized in the exact order they appear in the transaction. This order is canonical. Reordering inputs or outputs produces a different `tx_id` and is treated as a different transaction. Order must not be changed during validation.

---

## Chain Rules

1. **Genesis block** — `index` is 0, `previous_hash` is 64 zeros.
2. **Hash integrity** — each block's stored `hash` must equal the computed hash of its fields.
3. **Linkage** — each block's `previous_hash` must equal the `hash` of the block at `index - 1`.
4. **Index sequence** — each block's `index` must equal the previous block's `index + 1`.
5. **Timestamp** — each block's `timestamp` must be greater than or equal to the previous block's `timestamp`.

A chain is valid only if all rules pass for every block from genesis to tip.

---

## UTXO Rules (Phase 1 — simplified)

1. Every input must reference an output that exists in a prior block.
2. Every input must reference an output that has not already been spent.
3. For non-coinbase transactions: `sum(input amounts) >= sum(output amounts)`. Any difference is implicitly the fee (not collected in Phase 1, but the rule must hold).
4. No transaction may reference an output from a block at the same height or later.

Signatures are **not validated** in Phase 1. The input fields for signature are omitted entirely.

**UTXO set derivation:** The UTXO set is computed by scanning the chain from genesis to tip. For each block, add all outputs to the set. For each input in each transaction, remove the referenced output from the set. The result is the complete set of currently spendable outputs. There is no other authoritative source for the UTXO set.

---

## Mempool (Phase 1 — optional)

A mempool can be implemented as a simple list of unconfirmed transactions. Acceptance rules:

- Transaction inputs must reference UTXOs that exist and are unspent in the current chain.
- Transaction must not double-spend any other mempool transaction.
- Coinbase transactions are not accepted to the mempool; they are created by the miner.

---

## Operations

| Operation | Description |
|---|---|
| `new_genesis()` | Create and return the genesis block |
| `add_block(chain, block)` | Validate and append a block; reject if invalid |
| `validate_chain(chain)` | Check all rules from genesis to tip; return ok or first error |
| `get_block(chain, index)` | Return block at given index |
| `last_block(chain)` | Return the current chain tip |
| `compute_hash(block)` | Recompute and return the hash of a block from its fields |
| `compute_merkle_root(txs)` | Compute the merkle root from an ordered list of transactions |
| `get_utxo_set(chain)` | Return all unspent outputs from the current chain |

---

## Storage

In-memory list. No file persistence in Phase 1.

---

## Out of Scope for Phase 1

| Feature | Phase |
|---|---|
| Proof-of-work mining loop | Phase 2 |
| Real block rewards | Phase 2 |
| Key pairs and ECDSA signatures | Phase 3 |
| UTXO ownership enforcement | Phase 3 |
| Peer-to-peer networking | Phase 4 |
| Inscriptions | Phase 5 |
| Privacy features | Phase 6 |
