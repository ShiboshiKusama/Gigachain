"""
Tests for Phase 5: inscription system.

Covers:
- make_inscription_tx: creates transactions with data field set
- tx_id includes data (same data → same tx_id; different data → different tx_id)
- Signatures cover data (changing data invalidates signature)
- Indexer.scan / get / all_tx_ids / count
- Inscription mined into a block and retrievable from chain
- Size limit enforcement at make_inscription_tx and chain validation
- Non-inscription transactions have empty data field
"""

import pytest
from gigachain import (
    Block, Transaction, Input, Output,
    new_genesis, make_coinbase, add_block,
    mine_block, get_utxo_set, validate_chain,
    BLOCK_REWARD, COINBASE_TX_ID,
    Wallet, sign_transaction, verify_transaction_signature,
    make_inscription_tx, Indexer, MAX_INSCRIPTION_SIZE,
    compute_tx_id,
)
from gigachain.block import compute_tx_id as _compute_tx_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fresh_chain():
    return [new_genesis("miner")]


def mine_and_append(chain, txs, miner_address="miner"):
    block = mine_block(chain[-1], txs, miner_address)
    add_block(chain, block)
    return block


def funded_wallet_and_chain():
    """Return (wallet, chain) where wallet has one UTXO from block 1 coinbase."""
    wallet = Wallet.generate()
    chain = [new_genesis("genesis_miner")]
    block1 = mine_block(chain[-1], [], wallet.address)
    add_block(chain, block1)
    return wallet, chain


def signed_inscription_tx(wallet, utxo_tx_id, utxo_out_idx, recipient, amount, data: bytes):
    inp = Input(tx_id=utxo_tx_id, output_index=utxo_out_idx)
    out = Output(recipient=recipient, amount=amount)
    tx = make_inscription_tx([inp], [out], data)
    sig = sign_transaction(wallet, tx.inputs, tx.outputs, tx.data)
    tx.inputs[0].signature = sig
    tx.inputs[0].public_key = wallet.public_key_hex()
    return tx


# ---------------------------------------------------------------------------
# make_inscription_tx
# ---------------------------------------------------------------------------

class TestMakeInscriptionTx:
    def test_data_stored_as_hex(self):
        inp = Input(tx_id="a" * 64, output_index=0)
        out = Output(recipient="alice", amount=10)
        data = b"hello"
        tx = make_inscription_tx([inp], [out], data)
        assert tx.data == data.hex()

    def test_empty_bytes_stored_as_empty_string(self):
        inp = Input(tx_id="a" * 64, output_index=0)
        out = Output(recipient="alice", amount=10)
        tx = make_inscription_tx([inp], [out], b"")
        assert tx.data == ""

    def test_at_size_limit_accepted(self):
        inp = Input(tx_id="a" * 64, output_index=0)
        out = Output(recipient="alice", amount=10)
        data = b"x" * MAX_INSCRIPTION_SIZE
        tx = make_inscription_tx([inp], [out], data)
        assert len(bytes.fromhex(tx.data)) == MAX_INSCRIPTION_SIZE

    def test_over_size_limit_raises(self):
        inp = Input(tx_id="a" * 64, output_index=0)
        out = Output(recipient="alice", amount=10)
        data = b"x" * (MAX_INSCRIPTION_SIZE + 1)
        with pytest.raises(ValueError, match="maximum is"):
            make_inscription_tx([inp], [out], data)

    def test_returns_transaction_type(self):
        inp = Input(tx_id="a" * 64, output_index=0)
        out = Output(recipient="alice", amount=10)
        tx = make_inscription_tx([inp], [out], b"abc")
        assert isinstance(tx, Transaction)

    def test_tx_id_computed_on_construction(self):
        inp = Input(tx_id="a" * 64, output_index=0)
        out = Output(recipient="alice", amount=10)
        tx = make_inscription_tx([inp], [out], b"test")
        assert tx.tx_id != ""


# ---------------------------------------------------------------------------
# tx_id determinism with data
# ---------------------------------------------------------------------------

class TestTxIdWithData:
    def test_same_data_same_tx_id(self):
        inp = Input(tx_id="a" * 64, output_index=0)
        out = Output(recipient="alice", amount=10)
        tx1 = make_inscription_tx([inp], [out], b"hello")
        tx2 = make_inscription_tx([inp], [out], b"hello")
        assert tx1.tx_id == tx2.tx_id

    def test_different_data_different_tx_id(self):
        inp = Input(tx_id="a" * 64, output_index=0)
        out = Output(recipient="alice", amount=10)
        tx1 = make_inscription_tx([inp], [out], b"hello")
        tx2 = make_inscription_tx([inp], [out], b"world")
        assert tx1.tx_id != tx2.tx_id

    def test_no_data_vs_data_different_tx_id(self):
        inp = Input(tx_id="a" * 64, output_index=0)
        out = Output(recipient="alice", amount=10)
        tx_plain = Transaction(inputs=[inp], outputs=[out])
        tx_inscribed = make_inscription_tx([inp], [out], b"x")
        assert tx_plain.tx_id != tx_inscribed.tx_id

    def test_tx_id_stable_across_recompute(self):
        inp = Input(tx_id="b" * 64, output_index=1)
        out = Output(recipient="bob", amount=5)
        tx = make_inscription_tx([inp], [out], b"stable")
        assert tx.tx_id == _compute_tx_id(tx)


# ---------------------------------------------------------------------------
# Signatures cover inscription data
# ---------------------------------------------------------------------------

class TestSignaturesWithData:
    def test_valid_signature_with_data(self):
        wallet = Wallet.generate()
        inp = Input(tx_id="a" * 64, output_index=0)
        out = Output(recipient=wallet.address, amount=10)
        tx = make_inscription_tx([inp], [out], b"signed data")
        sig = sign_transaction(wallet, tx.inputs, tx.outputs, tx.data)
        assert verify_transaction_signature(sig, wallet.public_key_hex(), tx.inputs, tx.outputs, tx.data)

    def test_signature_invalid_if_data_changed(self):
        wallet = Wallet.generate()
        inp = Input(tx_id="a" * 64, output_index=0)
        out = Output(recipient=wallet.address, amount=10)
        tx = make_inscription_tx([inp], [out], b"original")
        sig = sign_transaction(wallet, tx.inputs, tx.outputs, tx.data)
        # Verify against different data
        other_tx = make_inscription_tx([inp], [out], b"tampered")
        assert not verify_transaction_signature(sig, wallet.public_key_hex(), other_tx.inputs, other_tx.outputs, other_tx.data)

    def test_signature_invalid_without_data_when_signed_with_data(self):
        wallet = Wallet.generate()
        inp = Input(tx_id="a" * 64, output_index=0)
        out = Output(recipient=wallet.address, amount=10)
        tx = make_inscription_tx([inp], [out], b"has data")
        sig = sign_transaction(wallet, tx.inputs, tx.outputs, tx.data)
        # Verify without data (data="")
        assert not verify_transaction_signature(sig, wallet.public_key_hex(), tx.inputs, tx.outputs, "")


# ---------------------------------------------------------------------------
# Mining inscriptions into blocks
# ---------------------------------------------------------------------------

class TestInscriptionInBlock:
    def test_inscription_tx_mines_into_block(self):
        wallet, chain = funded_wallet_and_chain()
        coinbase_tx_id = chain[1].transactions[0].tx_id
        tx = signed_inscription_tx(wallet, coinbase_tx_id, 0, "recipient", BLOCK_REWARD, b"on-chain data")
        block = mine_block(chain[-1], [tx], "miner")
        add_block(chain, block)
        ok, err = validate_chain(chain)
        assert ok, err

    def test_inscription_data_preserved_in_block(self):
        wallet, chain = funded_wallet_and_chain()
        coinbase_tx_id = chain[1].transactions[0].tx_id
        payload = b"preserved"
        tx = signed_inscription_tx(wallet, coinbase_tx_id, 0, "recipient", BLOCK_REWARD, payload)
        block = mine_block(chain[-1], [tx], "miner")
        add_block(chain, block)
        # Find the inscription tx in the block (it's after the coinbase)
        mined_tx = block.transactions[1]
        assert mined_tx.data == payload.hex()

    def test_inscription_too_large_rejected_by_chain(self):
        """A transaction with oversized data is rejected at block validation."""
        wallet, chain = funded_wallet_and_chain()
        coinbase_tx_id = chain[1].transactions[0].tx_id
        # Build tx manually with oversized data (bypassing make_inscription_tx)
        inp = Input(tx_id=coinbase_tx_id, output_index=0)
        out = Output(recipient="recipient", amount=BLOCK_REWARD)
        oversized_data = ("ab" * (MAX_INSCRIPTION_SIZE + 1))  # hex string, too many bytes
        tx = Transaction(inputs=[inp], outputs=[out], data=oversized_data)
        sig = sign_transaction(wallet, tx.inputs, tx.outputs, tx.data)
        tx.inputs[0].signature = sig
        tx.inputs[0].public_key = wallet.public_key_hex()
        block = mine_block(chain[-1], [tx], "miner")
        with pytest.raises(ValueError, match="inscription data exceeds"):
            add_block(chain, block)

    def test_invalid_hex_data_rejected_by_chain(self):
        """A transaction with non-hex data is rejected at block validation."""
        wallet, chain = funded_wallet_and_chain()
        coinbase_tx_id = chain[1].transactions[0].tx_id
        inp = Input(tx_id=coinbase_tx_id, output_index=0)
        out = Output(recipient="recipient", amount=BLOCK_REWARD)
        # 'data' is not valid hex
        tx = Transaction(inputs=[inp], outputs=[out], data="not-valid-hex!")
        sig = sign_transaction(wallet, tx.inputs, tx.outputs, tx.data)
        tx.inputs[0].signature = sig
        tx.inputs[0].public_key = wallet.public_key_hex()
        block = mine_block(chain[-1], [tx], "miner")
        with pytest.raises(ValueError, match="inscription data is not valid hex"):
            add_block(chain, block)


# ---------------------------------------------------------------------------
# Indexer
# ---------------------------------------------------------------------------

class TestIndexer:
    def _chain_with_inscription(self, payload: bytes):
        wallet, chain = funded_wallet_and_chain()
        coinbase_tx_id = chain[1].transactions[0].tx_id
        tx = signed_inscription_tx(wallet, coinbase_tx_id, 0, "recipient", BLOCK_REWARD, payload)
        mine_and_append(chain, [tx])
        return chain, tx.tx_id

    def test_scan_finds_inscription(self):
        chain, tx_id = self._chain_with_inscription(b"find me")
        indexer = Indexer()
        indexer.scan(chain)
        assert indexer.get(tx_id) == b"find me"

    def test_get_unknown_tx_returns_none(self):
        chain, _ = self._chain_with_inscription(b"data")
        indexer = Indexer()
        indexer.scan(chain)
        assert indexer.get("0" * 64) is None

    def test_count_reflects_inscriptions(self):
        chain, _ = self._chain_with_inscription(b"one")
        indexer = Indexer()
        indexer.scan(chain)
        assert indexer.count() == 1

    def test_all_tx_ids_lists_inscribed_transactions(self):
        chain, tx_id = self._chain_with_inscription(b"list me")
        indexer = Indexer()
        indexer.scan(chain)
        assert tx_id in indexer.all_tx_ids()

    def test_non_inscription_txs_not_indexed(self):
        chain = [new_genesis("miner")]
        indexer = Indexer()
        indexer.scan(chain)
        # Only coinbase in genesis, no data
        assert indexer.count() == 0

    def test_scan_resets_previous_index(self):
        chain, tx_id = self._chain_with_inscription(b"first scan")
        indexer = Indexer()
        indexer.scan(chain)
        assert indexer.count() == 1
        # Scan a fresh single-block chain
        indexer.scan([new_genesis("miner")])
        assert indexer.count() == 0

    def test_multiple_inscriptions_indexed(self):
        wallet, chain = funded_wallet_and_chain()
        # Spend coinbase from block 1 to create two outputs
        coinbase_tx_id = chain[1].transactions[0].tx_id
        inp = Input(tx_id=coinbase_tx_id, output_index=0)
        out1 = Output(recipient=wallet.address, amount=25)
        out2 = Output(recipient=wallet.address, amount=25)
        sig = sign_transaction(wallet, [inp], [out1, out2])
        inp.signature = sig
        inp.public_key = wallet.public_key_hex()
        split_tx = Transaction(inputs=[inp], outputs=[out1, out2])
        block2 = mine_block(chain[-1], [split_tx], "miner")
        add_block(chain, block2)

        # Now inscribe two separate transactions spending the two outputs
        tx_a = signed_inscription_tx(wallet, split_tx.tx_id, 0, "recv", 25, b"inscription A")
        tx_b = signed_inscription_tx(wallet, split_tx.tx_id, 1, "recv", 25, b"inscription B")
        block3 = mine_block(chain[-1], [tx_a, tx_b], "miner")
        add_block(chain, block3)

        indexer = Indexer()
        indexer.scan(chain)
        assert indexer.count() == 2
        assert indexer.get(tx_a.tx_id) == b"inscription A"
        assert indexer.get(tx_b.tx_id) == b"inscription B"


# ---------------------------------------------------------------------------
# Non-inscription transactions unchanged
# ---------------------------------------------------------------------------

class TestNonInscriptionUnchanged:
    def test_plain_tx_data_is_empty(self):
        inp = Input(tx_id="a" * 64, output_index=0)
        out = Output(recipient="alice", amount=10)
        tx = Transaction(inputs=[inp], outputs=[out])
        assert tx.data == ""

    def test_coinbase_data_is_empty(self):
        from gigachain import make_coinbase
        cb = make_coinbase("miner", 0)
        assert cb.data == ""
