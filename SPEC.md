# Spec — Phase 1: Local Blockchain

## Block

```
{
  index:        integer
  timestamp:    unix seconds
  previous_hash: hex string (64 chars)
  nonce:        integer
  transactions: list of Transaction
  hash:         SHA-256(index + timestamp + previous_hash + nonce + transactions)
}
```

## Transaction

```
{
  sender:    string (address or "coinbase")
  recipient: string (address)
  amount:    integer (smallest unit)
}
```

## Chain Rules

- Block 0 is the genesis block; `previous_hash` is 64 zeros.
- Each block's `hash` must match `SHA-256` of its fields.
- Each block's `previous_hash` must equal the hash of the prior block.
- A chain is valid only if every block passes both checks.

## Operations

| Operation       | Description                          |
|-----------------|--------------------------------------|
| `add_block`     | Append a valid block to the chain    |
| `validate_chain`| Check all blocks from genesis        |
| `get_block`     | Retrieve block by index              |
| `last_block`    | Return the current chain tip         |

## Storage

- In-memory list for Phase 1.
- No persistence required.

## Out of Scope

Mining, wallets, networking, signatures — all later phases.
