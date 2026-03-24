# Architecture

Gigachain is a proof-of-work blockchain designed for normal computer mining. No specialized hardware should be required as a long-term goal.

## Transaction Model

Gigachain uses a **UTXO model** (Unspent Transaction Output), similar to Bitcoin. Coins exist as discrete outputs, not account balances. Each transaction consumes one or more UTXOs as inputs and creates new UTXOs as outputs. This model cleanly supports future features like signatures, privacy, and scripting.

Phase 1 uses a simplified UTXO structure without signatures. Signatures are added in Phase 3.

## Components

- **Block** — header (index, timestamp, previous hash, nonce, merkle root) plus a list of transactions
- **Blockchain** — ordered chain of blocks linked by hash; each block commits to the one before it
- **UTXO Set** — the set of all unspent outputs; determines valid spends
- **Mempool** — unconfirmed transactions waiting to be mined into a block
- **Proof of Work** — miners search for a nonce such that the block hash meets a difficulty target
- **Peer Network** — nodes share blocks and transactions (Phase 4+)

## Hashing

SHA-256 is used only as a **learning prototype** in early phases. The final chain hash function must be CPU-friendly and resistant to ASIC and GPU optimization. The hash function choice will be evaluated before any real network launch.

## Mining Difficulty

Difficulty defines how hard it is to produce a valid block hash. A block is valid when its hash has at least N leading zero bits (or equivalently, N leading hex zeros).

- **Phase 1** — difficulty is not enforced (nonce is always 0; no mining loop)
- **Phase 2** — difficulty is a fixed constant; the miner increments the nonce until the hash meets the target
- **Later phases** — dynamic difficulty adjustment based on average block time

## Merkle Root

The merkle root is a single hash that commits to all transactions in the block. It is built by hashing pairs of transaction hashes up a binary tree until one root hash remains. If the transaction count is odd, the last hash is duplicated before pairing.

This allows a node to verify that a specific transaction is in a block without downloading all transactions.

## Coinbase Transaction

Every block must include a coinbase transaction as its first transaction. The coinbase:

- Has no inputs
- Creates new coins as the block reward (a fixed constant per block)
- Pays the reward to the miner's address
- Is the only transaction permitted to create coins from nothing

## Data Flow

```
User creates transaction
        |
        v
   Mempool (pending UTXOs)
        |
        v
   Miner selects transactions, builds block candidate
        |
        v
   Proof-of-Work loop (increment nonce until target met)
        |
        v
   Valid block appended to local chain
        |
        v
   Block broadcast to peers  [Phase 4+]
```

## Key Design Decisions

| Decision | Choice |
|---|---|
| Transaction model | UTXO |
| Mining | CPU-friendly PoW; final hash function TBD |
| Chain selection | Longest valid chain (most cumulative work) |
| Signatures | ECDSA, added in Phase 3 |
| Inscriptions | Future feature via transaction data extension or commit/reveal |
| Privacy | Future research phase, Monero-inspired (ring signatures, stealth addresses) |

## Phase Boundaries

- **Phase 1** — local only, no networking, no signatures, no real mining; validates chain structure
- **Phase 2** — adds PoW loop and block rewards; SHA-256 acceptable as a temporary stand-in
- **Phase 3** — adds key pairs, ECDSA signing, and real UTXO validation
- **Phase 4** — adds peer-to-peer networking and chain sync
- **Phase 5** — adds inscription protocol
- **Phase 6** — privacy research and prototyping

## What Is Intentionally Deferred

- Signature validation (Phase 3)
- Real CPU-optimized hash function (evaluated before mainnet)
- Networking (Phase 4)
- Inscriptions (Phase 5)
- Privacy (Phase 6)
