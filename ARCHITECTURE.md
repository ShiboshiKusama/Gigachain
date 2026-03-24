# Architecture

Gigachain is a CPU-mineable proof-of-work blockchain.

## Components

- **Blockchain** — ordered chain of blocks, each containing a hash of the previous block
- **Block** — header (index, timestamp, previous hash, nonce) plus a list of transactions
- **Proof of Work** — miners increment a nonce until the block hash meets a difficulty target
- **Transaction** — a transfer of value from sender to recipient, signed by the sender
- **Mempool** — pending transactions waiting to be included in the next block
- **Peer Network** — nodes broadcast new blocks and transactions to connected peers

## Data Flow

```
User submits transaction
        |
        v
   Mempool (pending transactions)
        |
        v
   Miner picks transactions, builds block candidate
        |
        v
   Proof-of-Work loop (hash until difficulty met)
        |
        v
   Valid block appended to chain
        |
        v
   Block broadcast to peers
```

## Key Design Decisions

- **CPU mining** — no GPU/ASIC advantage; keeps participation open
- **Chain selection** — longest valid chain wins (most cumulative work)
- **Immutability** — altering any block invalidates all subsequent hashes
