# Gigachain Architecture

## 1. Chain Model: UTXO

**Decision: UTXO-based.**

Reasons:
- Natural fit for PoW (each block produces a coinbase UTXO, spendable later)
- Enables Ordinals-style inscription tracking (inscriptions attach to specific outputs)
- Prepares for Monero-style ring signatures, which operate over discrete output sets
- Parallel transaction validation is simpler on UTXO than account model
- Well-understood attack surface (Bitcoin, Dogecoin, Monero all use UTXO)

Tradeoff: UTXO state is harder to query than account balances. A UTXO index is required for wallet software. This is a known, solved problem.

---

## 2. Mining Algorithm: GigaHash (RandomX-inspired)

**Decision: A custom CPU-oriented PoW algorithm, GigaHash, inspired by RandomX.**

### Comparison

| Algorithm | ASIC Resistant | GPU Resistant | Memory Hard | Implementation Complexity |
|-----------|---------------|---------------|-------------|---------------------------|
| SHA-256   | No            | No            | No          | Low                       |
| Scrypt    | Partially     | Partially     | Yes         | Medium                    |
| RandomX   | Yes           | Yes           | Yes         | High                      |
| GigaHash  | Yes (goal)    | Yes (goal)    | Yes         | High (Phase 2)            |

**SHA-256**: Dominated by ASICs. Excludes CPU miners entirely. Rejected.

**Scrypt**: Litecoin and Dogecoin use it. Scrypt ASICs (Antminer L series) now exist. Memory hardness has been partially overcome. Not future-proof.

**RandomX**: Monero's algorithm. Generates random programs executed on a virtual CPU. Requires ~2 GB dataset in RAM. Genuinely resists ASICs and GPUs because the cost of building hardware that executes random code efficiently approaches the cost of a general-purpose CPU. Best known option for CPU-friendly mining.

**GigaHash**: For Phase 1, we use SHA3-256 (Keccak) as a temporary placeholder — it is simple, well-audited, and has no ASIC ecosystem yet. In Phase 2, we replace it with a production CPU-hard algorithm. We will either adopt RandomX directly (it is MIT-licensed) or design a derivative. This decision will be made in Phase 2 with benchmarking.

**Phase 1 hashing: SHA3-256 (temporary, clearly labeled)**
**Phase 2 target: RandomX or GigaHash derivative**

---

## 3. Block Structure

```
BlockHeader {
    version:        u32       // protocol version
    prev_hash:      [u8; 32]  // hash of previous block header
    merkle_root:    [u8; 32]  // merkle root of transactions
    timestamp:      u64       // unix seconds
    difficulty:     u32       // compact nBits format (Bitcoin-compatible)
    nonce:          u64       // proof-of-work nonce
    // reserved: [u8; 32] for future extension (e.g. privacy commitments)
}

Block {
    header:         BlockHeader
    transactions:   Vec<Transaction>  // first tx is always coinbase
}
```

Block hash = SHA3-256(SHA3-256(encoded_header)) — double hash, Bitcoin-style, for length-extension resistance.

Max block size: 4 MB (generous for testnet; will be tuned before mainnet).

---

## 4. Transaction Model

```
Transaction {
    version:    u16               // tx version (allows future types)
    inputs:     Vec<TxInput>
    outputs:    Vec<TxOutput>
    lock_time:  u64               // earliest block/time this tx is valid
    extra:      Option<TxExtra>   // reserved for inscriptions, privacy fields
}

TxInput {
    prev_txid:  [u8; 32]
    prev_vout:  u32
    script_sig: Vec<u8>          // unlocking script
    sequence:   u32
}

TxOutput {
    value:      u64              // amount in gigons (smallest unit, 1 GIGA = 100_000_000 gigons)
    script_pub: Vec<u8>         // locking script
}

TxExtra {
    type_tag:   u8               // 0x00 = none, 0x01 = inscription, 0x02 = reserved
    data:       Vec<u8>
}
```

Fee = sum(inputs) - sum(outputs). No explicit fee field.

Script system: Phase 1 uses a minimal, non-Turing-complete script. Only P2PK and P2PKH patterns are supported. Full scripting is a later phase.

---

## 5. Inscriptions (Design Only — Phase 4)

Inscriptions are native on-chain artifacts: images, text, or arbitrary data permanently attached to a specific UTXO.

**Design approach: Commit/Reveal over TxExtra**

1. **Commit transaction**: Sender broadcasts a tx with a hash commitment in `TxExtra` (`type_tag = 0x01`, data = hash of artifact). This is cheap and small.
2. **Reveal transaction**: A subsequent tx spends the commit output and includes the full artifact bytes in `TxExtra`. The node validates that SHA3-256(artifact) matches the committed hash.
3. The artifact is permanently associated with the output created by the reveal transaction. An inscription indexer tracks these by output.

**Why commit/reveal**: Prevents miners from front-running inscriptions. The commit anchors ownership before the data is public.

**Why TxExtra instead of OP_RETURN**: OP_RETURN is a Bitcoin limitation workaround. We have a clean chain; we can give artifacts a first-class transaction field with proper size accounting.

**Why not witness-style**: Segregated witness adds significant protocol complexity. We are not inheriting Bitcoin's technical debt. TxExtra achieves the same data-carrying goal with a cleaner model.

Artifact size limit: TBD in Phase 4. Likely capped at 400 KB per reveal, with fee scaling.

---

## 6. Privacy Roadmap (Phase 5+, Research Only)

Monero achieves privacy through three layered mechanisms:

### Stealth Addresses
Every payment goes to a one-time address derived from the recipient's public key. An outside observer cannot link two payments to the same recipient. The recipient scans the blockchain with a private view key to find their outputs.

### Ring Signatures
When spending an output, the sender signs with a "ring" of other outputs as decoys. A verifier knows one of the ring members spent, but cannot determine which. Hides the sender.

### RingCT (Ring Confidential Transactions)
Amounts are hidden using Pedersen commitments (homomorphic encryption). The network can verify that inputs equal outputs (no inflation) without knowing the actual values.

### What Gigachain Could Add Later

| Feature | Difficulty | Phase |
|---------|-----------|-------|
| Stealth addresses | Medium — key derivation scheme | 5 |
| Ring signatures | High — requires MLSAG or CLSAG construction | 5 |
| RingCT | Very High — bulletproofs for range proofs | 6+ |
| View keys | Medium — depends on stealth addresses | 5 |

**Phase 1 scope**: None. The `version` field in Transaction and the `reserved` field in BlockHeader are intentional extension points for future privacy fields.

**Honest assessment**: Implementing RingCT correctly requires serious cryptographic expertise and an extensive audit. It should not be attempted until Phases 1–4 are stable and the team has grown.

---

## 7. Consensus and Economics

- **Block time**: 2 minutes. Faster than Bitcoin (better UX), slower than Ethereum (lower orphan rate on early p2p network).
- **Difficulty adjustment**: LWMA (Linearly Weighted Moving Average). Adjusts every block using a weighted window of the last 60 blocks. More responsive than Bitcoin's 2016-block retarget. Resistant to timestamp manipulation attacks that exploit simple EMA. Used by Zcash and others.
- **Block subsidy**: 50 GIGA at genesis. Halves every 210,000 blocks (~2 years at 2-minute blocks).
- **Max supply**: ~21 million GIGA (mirrors Bitcoin's model; well-understood scarcity).
- **Tail emission**: 0.01 GIGA per block permanently after the final halving. Ensures miners are always incentivized even when transaction volume is low. Monero uses a similar model. This is a deliberate departure from Bitcoin's zero-emission endpoint.
- **Units**: 1 GIGA = 100,000,000 gigons (smallest unit). All internal arithmetic in gigons.

---

## 8. Node Architecture

```
gigachain/
├── core/        # Block and transaction validation, UTXO set, chain state, consensus rules
├── miner/       # PoW loop, block template construction, GigaHash implementation
├── wallet/      # Key management, UTXO tracking, transaction construction and signing
├── p2p/         # Peer discovery, block and transaction propagation, sync protocol
├── rpc/         # JSON-RPC API for wallet and external tooling
├── inscriptions/ # (Phase 4) Artifact indexer, commit/reveal tracker
├── privacy/     # (Phase 5) Stealth address, ring signature, RingCT stubs
└── tests/       # Integration tests
```

**core** is the consensus-critical module. Everything else depends on it; it depends on nothing else in this repo. This separation is non-negotiable.

---

## 9. Implementation Language: Rust

**Decision: Rust.**

| Language | Memory Safety | Performance | Crypto Ecosystem | Blockchain Precedent |
|----------|--------------|-------------|------------------|---------------------|
| Rust     | Yes (compile-time) | Near C++ | Excellent | Solana, Polkadot, Zcash librustzcash |
| Go       | GC           | Good        | Adequate         | Ethereum (Geth), Cosmos |
| C++      | No           | Best        | Good             | Bitcoin Core, Monero |
| Python   | GC           | Poor        | Good             | Prototyping only |

**Why not C++**: Bitcoin Core and Monero are C++. Memory safety bugs in consensus code are catastrophic. Rust eliminates entire classes of vulnerabilities at compile time with no runtime cost.

**Why not Go**: Go's GC introduces latency unpredictability in hot paths. The crypto library ecosystem is thinner. Ring signature and bulletproof implementations are more mature in Rust.

**Why Rust**: Memory safety without a garbage collector. `tokio` for async networking. `rocksdb` bindings for chain state storage. `secp256k1` and `curve25519-dalek` for cryptography. Strong type system catches protocol bugs early. The language is harder to learn but the investment pays off for a long-lived protocol implementation.

Key crates: `sha3`, `secp256k1`, `rocksdb`, `tokio`, `serde`, `bincode`, `clap`.
