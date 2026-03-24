"""
Tests for Phase 6: transaction fee system.

Covers:
- fee = sum(inputs) - sum(outputs)
- zero-fee transactions allowed
- negative-fee transactions rejected (mempool and chain)
- coinbase reward = BLOCK_REWARD + total fees in block
- wrong coinbase reward rejected by chain validation
- mempool sorts transactions by fee descending
- get_fee() returns stored fee
- fees cleared from mempool on remove and revalidate
"""

import pytest
from gigachain import (
    Block, Transaction, Input, Output,
    new_genesis, make_coinbase, add_block, validate_chain,
    mine_block, get_utxo_set, BLOCK_REWARD, COINBASE_TX_ID,
    Wallet, sign_transaction,
)
from gigachain.mempool import Mempool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def funded_wallet_and_chain():
    """Return (wallet, chain) with wallet owning the block-1 coinbase UTXO."""
    wallet = Wallet.generate()
    chain = [new_genesis("genesis_miner")]
    block1 = mine_block(chain[-1], [], wallet.address)
    add_block(chain, block1)
    return wallet, chain


def signed_tx(wallet, utxo_tx_id, utxo_out_idx, recipient, amount):
    inp = Input(tx_id=utxo_tx_id, output_index=utxo_out_idx)
    out = Output(recipient=recipient, amount=amount)
    sig = sign_transaction(wallet, [inp], [out])
    inp.signature = sig
    inp.public_key = wallet.public_key_hex()
    return Transaction(inputs=[inp], outputs=[out])


def signed_tx_multi_out(wallet, utxo_tx_id, utxo_out_idx, outputs: list[Output]):
    inp = Input(tx_id=utxo_tx_id, output_index=utxo_out_idx)
    sig = sign_transaction(wallet, [inp], outputs)
    inp.signature = sig
    inp.public_key = wallet.public_key_hex()
    return Transaction(inputs=[inp], outputs=outputs)


# ---------------------------------------------------------------------------
# Fee calculation
# ---------------------------------------------------------------------------

class TestFeeCalculation:
    def test_zero_fee_allowed_in_mempool(self):
        wallet, chain = funded_wallet_and_chain()
        coinbase_tx_id = chain[1].transactions[0].tx_id
        tx = signed_tx(wallet, coinbase_tx_id, 0, "recipient", BLOCK_REWARD)  # fee = 0
        utxo_set = get_utxo_set(chain)
        mempool = Mempool()
        ok, err = mempool.add(tx, utxo_set)
        assert ok, err
        assert mempool.get_fee(tx.tx_id) == 0

    def test_fee_stored_as_inputs_minus_outputs(self):
        wallet, chain = funded_wallet_and_chain()
        coinbase_tx_id = chain[1].transactions[0].tx_id
        tx = signed_tx(wallet, coinbase_tx_id, 0, "recipient", BLOCK_REWARD - 5)  # fee = 5
        utxo_set = get_utxo_set(chain)
        mempool = Mempool()
        mempool.add(tx, utxo_set)
        assert mempool.get_fee(tx.tx_id) == 5

    def test_outputs_exceed_inputs_rejected_by_mempool(self):
        """Negative fee rejected: outputs > inputs is not possible via mempool."""
        wallet, chain = funded_wallet_and_chain()
        coinbase_tx_id = chain[1].transactions[0].tx_id
        # Manually build a tx spending 50 but outputting 60
        inp = Input(tx_id=coinbase_tx_id, output_index=0)
        out = Output(recipient="recipient", amount=BLOCK_REWARD + 10)
        sig = sign_transaction(wallet, [inp], [out])
        inp.signature = sig
        inp.public_key = wallet.public_key_hex()
        tx = Transaction(inputs=[inp], outputs=[out])
        utxo_set = get_utxo_set(chain)
        mempool = Mempool()
        ok, err = mempool.add(tx, utxo_set)
        assert not ok
        assert "outputs exceed inputs" in err

    def test_get_fee_unknown_tx_returns_zero(self):
        mempool = Mempool()
        assert mempool.get_fee("0" * 64) == 0


# ---------------------------------------------------------------------------
# Coinbase reward includes fees
# ---------------------------------------------------------------------------

class TestCoinbaseReward:
    def test_coinbase_no_fees_equals_block_reward(self):
        wallet, chain = funded_wallet_and_chain()
        block = mine_block(chain[-1], [], "miner")
        add_block(chain, block)
        coinbase = block.transactions[0]
        assert coinbase.outputs[0].amount == BLOCK_REWARD

    def test_coinbase_with_fee(self):
        wallet, chain = funded_wallet_and_chain()
        coinbase_tx_id = chain[1].transactions[0].tx_id
        fee = 7
        tx = signed_tx(wallet, coinbase_tx_id, 0, "recipient", BLOCK_REWARD - fee)
        block = mine_block(chain[-1], [tx], "miner", fees=fee)
        add_block(chain, block)
        ok, err = validate_chain(chain)
        assert ok, err
        coinbase = block.transactions[0]
        assert coinbase.outputs[0].amount == BLOCK_REWARD + fee

    def test_coinbase_with_multiple_fee_txs(self):
        wallet, chain = funded_wallet_and_chain()
        coinbase_tx_id = chain[1].transactions[0].tx_id

        # Split coinbase into two outputs
        inp = Input(tx_id=coinbase_tx_id, output_index=0)
        out1 = Output(recipient=wallet.address, amount=30)
        out2 = Output(recipient=wallet.address, amount=20)  # fee = 0 (30+20=50)
        sig = sign_transaction(wallet, [inp], [out1, out2])
        inp.signature = sig
        inp.public_key = wallet.public_key_hex()
        split_tx = Transaction(inputs=[inp], outputs=[out1, out2])
        block2 = mine_block(chain[-1], [split_tx], "miner", fees=0)
        add_block(chain, block2)

        # Spend each output with a fee
        tx_a = signed_tx(wallet, split_tx.tx_id, 0, "recv", 28)  # fee = 2
        tx_b = signed_tx(wallet, split_tx.tx_id, 1, "recv", 17)  # fee = 3
        total_fees = 2 + 3
        block3 = mine_block(chain[-1], [tx_a, tx_b], "miner", fees=total_fees)
        add_block(chain, block3)

        ok, err = validate_chain(chain)
        assert ok, err
        assert block3.transactions[0].outputs[0].amount == BLOCK_REWARD + total_fees

    def test_coinbase_understated_rejected(self):
        """mine_block with fees=0 when tx has a fee → chain rejects block."""
        wallet, chain = funded_wallet_and_chain()
        coinbase_tx_id = chain[1].transactions[0].tx_id
        fee = 5
        tx = signed_tx(wallet, coinbase_tx_id, 0, "recipient", BLOCK_REWARD - fee)
        # Declare no fees → coinbase = BLOCK_REWARD, but chain expects BLOCK_REWARD + 5
        block = mine_block(chain[-1], [tx], "miner", fees=0)
        with pytest.raises(ValueError, match="coinbase pays"):
            add_block(chain, block)

    def test_coinbase_overstated_rejected(self):
        """mine_block with fees=10 when tx has no fee → chain rejects block."""
        wallet, chain = funded_wallet_and_chain()
        coinbase_tx_id = chain[1].transactions[0].tx_id
        tx = signed_tx(wallet, coinbase_tx_id, 0, "recipient", BLOCK_REWARD)  # fee = 0
        # Claim fees=10 → coinbase = BLOCK_REWARD + 10, but chain expects BLOCK_REWARD + 0
        block = mine_block(chain[-1], [tx], "miner", fees=10)
        with pytest.raises(ValueError, match="coinbase pays"):
            add_block(chain, block)


# ---------------------------------------------------------------------------
# Mining prioritization
# ---------------------------------------------------------------------------

class TestMiningPrioritization:
    def _three_fee_txs(self):
        """Return (wallet, chain, [tx_low, tx_mid, tx_high]) with fees 1, 5, 10."""
        wallet, chain = funded_wallet_and_chain()
        coinbase_tx_id = chain[1].transactions[0].tx_id

        # Split coinbase into three outputs: 15, 20, 15 (sum=50, fee=0)
        inp = Input(tx_id=coinbase_tx_id, output_index=0)
        outs = [
            Output(recipient=wallet.address, amount=15),
            Output(recipient=wallet.address, amount=20),
            Output(recipient=wallet.address, amount=15),
        ]
        sig = sign_transaction(wallet, [inp], outs)
        inp.signature = sig
        inp.public_key = wallet.public_key_hex()
        split_tx = Transaction(inputs=[inp], outputs=outs)
        block2 = mine_block(chain[-1], [split_tx], "miner", fees=0)
        add_block(chain, block2)

        # Three txs with fees 1, 5, 10
        tx_low  = signed_tx(wallet, split_tx.tx_id, 0, "recv", 14)  # fee=1
        tx_mid  = signed_tx(wallet, split_tx.tx_id, 1, "recv", 15)  # fee=5
        tx_high = signed_tx(wallet, split_tx.tx_id, 2, "recv",  5)  # fee=10

        return wallet, chain, split_tx, [tx_low, tx_mid, tx_high]

    def test_mempool_sorted_highest_fee_first(self):
        wallet, chain, split_tx, (tx_low, tx_mid, tx_high) = self._three_fee_txs()
        utxo_set = get_utxo_set(chain)
        mempool = Mempool()
        # Add in low→mid→high order; get_transactions should return high→mid→low
        mempool.add(tx_low,  utxo_set)
        mempool.add(tx_mid,  utxo_set)
        mempool.add(tx_high, utxo_set)
        txs = mempool.get_transactions()
        fees = [mempool.get_fee(tx.tx_id) for tx in txs]
        assert fees == sorted(fees, reverse=True), f"expected descending fees, got {fees}"
        assert fees[0] == 10
        assert fees[1] == 5
        assert fees[2] == 1

    def test_mempool_add_order_does_not_affect_sort(self):
        wallet, chain, split_tx, (tx_low, tx_mid, tx_high) = self._three_fee_txs()
        utxo_set = get_utxo_set(chain)
        mempool = Mempool()
        # Add in reverse order
        mempool.add(tx_high, utxo_set)
        mempool.add(tx_mid,  utxo_set)
        mempool.add(tx_low,  utxo_set)
        txs = mempool.get_transactions()
        assert txs[0].tx_id == tx_high.tx_id

    def test_get_fee_returns_correct_amount(self):
        wallet, chain, split_tx, (tx_low, tx_mid, tx_high) = self._three_fee_txs()
        utxo_set = get_utxo_set(chain)
        mempool = Mempool()
        mempool.add(tx_low,  utxo_set)
        mempool.add(tx_mid,  utxo_set)
        mempool.add(tx_high, utxo_set)
        assert mempool.get_fee(tx_low.tx_id)  == 1
        assert mempool.get_fee(tx_mid.tx_id)  == 5
        assert mempool.get_fee(tx_high.tx_id) == 10


# ---------------------------------------------------------------------------
# Fee cleanup in mempool
# ---------------------------------------------------------------------------

class TestMempoolFeeCleanup:
    def test_fee_cleared_on_remove(self):
        wallet, chain = funded_wallet_and_chain()
        coinbase_tx_id = chain[1].transactions[0].tx_id
        tx = signed_tx(wallet, coinbase_tx_id, 0, "recipient", BLOCK_REWARD - 3)
        utxo_set = get_utxo_set(chain)
        mempool = Mempool()
        mempool.add(tx, utxo_set)
        assert mempool.get_fee(tx.tx_id) == 3
        mempool.remove([tx.tx_id])
        assert mempool.get_fee(tx.tx_id) == 0  # gone → default 0

    def test_fee_cleared_on_revalidate(self):
        wallet, chain = funded_wallet_and_chain()
        coinbase_tx_id = chain[1].transactions[0].tx_id
        tx = signed_tx(wallet, coinbase_tx_id, 0, "recipient", BLOCK_REWARD - 3)
        utxo_set = get_utxo_set(chain)
        mempool = Mempool()
        mempool.add(tx, utxo_set)
        # Revalidate with empty UTXO set → tx becomes stale
        mempool.revalidate({})
        assert mempool.size() == 0
        assert mempool.get_fee(tx.tx_id) == 0
