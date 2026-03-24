# Roadmap

## Phase 1: Local Single-Node Blockchain Prototype

**Objective:** Build and validate the core data structures locally. No mining, no networking, no signatures.

**Deliverables:**
- Block struct with index, timestamp, previous hash, nonce, and transaction list
- Simplified UTXO transaction structure (no signatures yet)
- SHA-256 block hashing (prototype only; not the final hash function)
- Chain validation: verify hash linkage from genesis
- In-memory chain storage
- Basic chain operations: add block, validate chain, get block, chain tip

**Risks:**
- Locking in design decisions (e.g., account model vs UTXO) too early — mitigated by using UTXO from the start

**Definition of Done:**
- Can build a chain of blocks in memory
- `validate_chain` correctly accepts valid chains and rejects tampered ones
- No networking or mining required to pass

---

## Phase 2: CPU-Friendly Proof-of-Work Prototype

**Objective:** Add a working mining loop with adjustable difficulty and block rewards.

**Deliverables:**
- PoW loop: increment nonce until block hash meets difficulty target
- Adjustable difficulty (target leading zeros or target threshold)
- Coinbase transaction to reward the miner
- Block reward constant defined
- SHA-256 used as a stand-in; final hash function to be evaluated before any real network

**Risks:**
- SHA-256 is GPU/ASIC-friendly — must not be treated as the final choice
- Difficulty adjustment not needed yet, but design should allow it later

**Definition of Done:**
- Miner can produce valid blocks that satisfy the difficulty target
- Chain validation still passes after mining
- Hash function is clearly marked as a prototype placeholder

---

## Phase 3: Wallet and Signed Transactions

**Objective:** Add real key pairs, transaction signing, and UTXO validation.

**Deliverables:**
- ECDSA key pair generation
- Address derivation from public key
- Transaction signing (inputs signed by the UTXO owner)
- Signature verification on transaction inputs
- UTXO set tracking: mark outputs as spent when consumed
- Reject transactions that double-spend or reference missing UTXOs

**Risks:**
- UTXO tracking logic is where most bugs will appear
- Serialization format for signing must be deterministic and stable

**Definition of Done:**
- Valid signed transactions are accepted
- Invalid signatures and double-spends are rejected
- UTXO set stays consistent after each block

---

## Phase 4: Peer-to-Peer Networking

**Objective:** Connect nodes so they can share blocks and transactions.

**Deliverables:**
- Node discovery and peer connections
- Block propagation: broadcast new blocks to peers
- Transaction propagation: broadcast mempool transactions
- Chain sync: a new node can download and validate the full chain
- Longest valid chain selection

**Risks:**
- Network partitions and chain forks require careful handling
- Peer misbehavior (invalid blocks, spam) needs basic protection

**Definition of Done:**
- Two nodes can sync to the same chain tip
- A new node joining the network can fully validate and catch up

---

## Phase 5: Inscriptions

**Objective:** Allow arbitrary data to be committed on-chain in a defined way.

**Deliverables:**
- Inscription data format (likely through a transaction data extension field or commit/reveal pattern)
- Protocol rules for what is a valid inscription
- Indexer to read and serve inscriptions from chain data
- Basic inscription standard documented

**Risks:**
- Block size and spam: need limits or fees to prevent abuse
- Commit/reveal adds protocol complexity; keep it minimal at first

**Definition of Done:**
- An inscription can be created, confirmed, and retrieved from chain history
- Indexer correctly reads inscription data without breaking chain validation

---

## Phase 6: Privacy Research

**Objective:** Investigate Monero-inspired privacy techniques and evaluate what fits Gigachain.

**Deliverables:**
- Research report on ring signatures, stealth addresses, and confidential transactions
- Prototype of at least one technique integrated into a test chain
- Assessment of trade-offs: performance, complexity, auditability

**Risks:**
- Privacy features add significant protocol complexity
- Some techniques conflict with UTXO transparency or inscription indexing
- This is research; nothing from this phase ships to mainnet without full review

**Definition of Done:**
- At least one privacy technique is prototyped and documented
- Trade-offs clearly written up with a recommendation for or against inclusion
