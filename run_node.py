#!/usr/bin/env python3
"""
run_node.py — minimal Gigachain node runner

Usage:
    python run_node.py --port PORT [--peers host:port ...]

Commands (typed at the prompt):
    mine            Mine a new block from the mempool
    tx ADDR AMOUNT  Submit a transaction to ADDR for AMOUNT (uses wallet balance)
    balance         Show wallet address and UTXO balance
    chain           Print chain length and tip hash
    peers           List configured peers
    sync            Sync chain from all peers
    quit            Stop the node
"""

import argparse
import sys

from gigachain import (
    Node, Wallet, mine_block, add_block, get_utxo_set,
    sign_transaction, BLOCK_REWARD,
)
from gigachain.block import Input, Output, Transaction


def parse_args():
    p = argparse.ArgumentParser(description="Run a Gigachain node")
    p.add_argument("--port", type=int, required=True, help="TCP port to listen on")
    p.add_argument(
        "--peers", nargs="*", default=[],
        metavar="host:port",
        help="Peer addresses to connect to on startup",
    )
    return p.parse_args()


def parse_peers(peer_strings: list[str]) -> list[tuple[str, int]]:
    peers = []
    for s in peer_strings:
        host, port = s.rsplit(":", 1)
        peers.append((host, int(port)))
    return peers


def get_balance(wallet: Wallet, chain) -> tuple[int, list]:
    """Return (total_balance, list_of_utxos) owned by wallet."""
    utxo_set = get_utxo_set(chain)
    owned = [
        (key, utxo) for key, utxo in utxo_set.items()
        if utxo.recipient == wallet.address
    ]
    total = sum(u.amount for _, u in owned)
    return total, owned


def do_mine(node: Node, wallet: Wallet, peers: list[tuple[str, int]]) -> None:
    txs = node.mempool.get_transactions()
    total_fees = sum(node.mempool.get_fee(tx.tx_id) for tx in txs)
    chain = node.get_chain()
    block = mine_block(chain[-1], txs, wallet.address, fees=total_fees)
    try:
        add_block(node.chain, block)
        node.mempool.remove([tx.tx_id for tx in block.transactions])
        node.broadcast_block(block, peers)
        print(f"Mined block {block.index} hash={block.hash[:12]}... reward={BLOCK_REWARD + total_fees} fees={total_fees}")
    except ValueError as e:
        print(f"Block rejected: {e}")


def do_tx(node: Node, wallet: Wallet, addr: str, amount: int) -> None:
    chain = node.get_chain()
    balance, owned_utxos = get_balance(wallet, chain)
    if balance < amount:
        print(f"Insufficient balance: have {balance}, need {amount}")
        return

    # Collect UTXOs until we have enough
    inputs = []
    collected = 0
    for (tx_id, out_idx), utxo in owned_utxos:
        inp = Input(tx_id=tx_id, output_index=out_idx)
        inputs.append(inp)
        collected += utxo.amount
        if collected >= amount:
            break

    outputs = [Output(recipient=addr, amount=amount)]
    change = collected - amount
    if change > 0:
        outputs.append(Output(recipient=wallet.address, amount=change))

    sig = sign_transaction(wallet, inputs, outputs)
    for inp in inputs:
        inp.signature = sig
        inp.public_key = wallet.public_key_hex()

    tx = Transaction(inputs=inputs, outputs=outputs)
    ok, err = node.add_transaction(tx)
    if ok:
        fee = collected - amount - change  # always 0 here; change returns remainder
        print(f"Transaction {tx.tx_id[:12]}... added to mempool (fee={collected - amount})")
    else:
        print(f"Transaction rejected: {err}")


def repl(node: Node, wallet: Wallet, peers: list[tuple[str, int]]) -> None:
    print(f"Node running on port {node.port}")
    print(f"Wallet address: {wallet.address}")
    print(f"Peers: {peers or '(none)'}")
    print("Commands: mine | tx ADDR AMOUNT | balance | chain | peers | sync | quit")

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        if cmd == "quit":
            break

        elif cmd == "mine":
            do_mine(node, wallet, peers)

        elif cmd == "tx" and len(parts) == 3:
            try:
                amount = int(parts[2])
            except ValueError:
                print("Usage: tx ADDR AMOUNT")
                continue
            do_tx(node, wallet, parts[1], amount)

        elif cmd == "balance":
            chain = node.get_chain()
            balance, _ = get_balance(wallet, chain)
            print(f"Address: {wallet.address}  Balance: {balance}")

        elif cmd == "chain":
            chain = node.get_chain()
            tip = chain[-1]
            print(f"Length: {len(chain)}  Tip: block {tip.index} hash={tip.hash[:16]}...")

        elif cmd == "peers":
            print(peers or "(none)")

        elif cmd == "sync":
            for host, port in peers:
                replaced = node.sync_from(host, port)
                print(f"  {host}:{port} → {'replaced chain' if replaced else 'no change'}")

        else:
            print("Unknown command. Try: mine | tx ADDR AMOUNT | balance | chain | peers | sync | quit")


def main():
    args = parse_args()
    peers = parse_peers(args.peers)

    wallet = Wallet.generate()
    node = Node(host="127.0.0.1", port=args.port)
    node.start()

    # Sync from first available peer on startup
    for host, port in peers:
        if node.sync_from(host, port):
            print(f"Synced chain from {host}:{port} (length {node.chain_length()})")
            break

    try:
        repl(node, wallet, peers)
    finally:
        node.stop()
        print("Node stopped.")


if __name__ == "__main__":
    main()
