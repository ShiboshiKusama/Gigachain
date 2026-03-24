"""
Node — Phase 4 / 4.5

Minimal peer-to-peer node over plain TCP.

Transport
---------
Each connection carries exactly one message, then closes.
Message framing: 4-byte big-endian length prefix + UTF-8 JSON payload.

Message types
-------------
  GET_CHAIN                  — request the node's full chain
  CHAIN        {blocks:[..]} — respond with full chain
  NEW_BLOCK    {block:{..}}  — broadcast a newly mined block
  NEW_TRANSACTION {tx:{..}}  — broadcast an unconfirmed transaction

Chain selection rule
--------------------
A peer's chain replaces the local chain if and only if:
  1. validate_chain(peer_chain) passes all existing rules
  2. len(peer_chain) > len(local_chain)

Since difficulty is fixed, chain length equals cumulative work.
Peer data is never trusted without full validation.

Mempool
-------
Each node maintains a local mempool. Received transactions are validated
before being added. After a block is accepted, its transactions are removed
from the mempool. After a chain replacement, the mempool is revalidated
against the new UTXO set.
"""

import json
import socket
import threading
from typing import Optional, List, Tuple

from .block import Block, Transaction, new_genesis
from .chain import add_block, validate_chain, get_utxo_set
from .mempool import Mempool
from .serialization import block_to_dict, block_from_dict, tx_to_dict, tx_from_dict


# ---------------------------------------------------------------------------
# Message framing
# ---------------------------------------------------------------------------

def _send_msg(sock: socket.socket, data: dict) -> None:
    payload = json.dumps(data).encode("utf-8")
    sock.sendall(len(payload).to_bytes(4, "big") + payload)


def _recv_msg(sock: socket.socket) -> dict:
    raw_len = _recv_exact(sock, 4)
    length = int.from_bytes(raw_len, "big")
    payload = _recv_exact(sock, length)
    return json.loads(payload.decode("utf-8"))


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed before all bytes received")
        buf += chunk
    return buf


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class Node:
    """
    A single Gigachain node.

    Responsibilities:
    - Maintains a local chain and mempool
    - Serves chain requests from peers (TCP server)
    - Syncs chain from peers
    - Broadcasts new blocks and transactions to peers
    """

    def __init__(self, host: str, port: int, chain: Optional[List[Block]] = None):
        self.host = host
        self.port = port
        self.chain: list[Block] = chain if chain is not None else [new_genesis(host)]
        self.mempool: Mempool = Mempool()
        self._lock = threading.Lock()
        self._server_sock: Optional[socket.socket] = None
        self._running = False

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the TCP listener in a background daemon thread."""
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(16)
        self._running = True
        t = threading.Thread(target=self._accept_loop, daemon=True)
        t.start()

    def stop(self) -> None:
        """Stop the TCP listener."""
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass

    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, _ = self._server_sock.accept()
                t = threading.Thread(target=self._handle_conn, args=(conn,), daemon=True)
                t.start()
            except OSError:
                break

    def _handle_conn(self, conn: socket.socket) -> None:
        try:
            msg = _recv_msg(conn)
            msg_type = msg.get("type")

            if msg_type == "GET_CHAIN":
                with self._lock:
                    chain_data = [block_to_dict(b) for b in self.chain]
                _send_msg(conn, {"type": "CHAIN", "blocks": chain_data})

            elif msg_type == "NEW_BLOCK":
                block = block_from_dict(msg["block"])
                peer_addr = msg.get("sender")
                self._handle_new_block(block, peer_addr)

            elif msg_type == "NEW_TRANSACTION":
                tx = tx_from_dict(msg["tx"])
                utxo_set = get_utxo_set(self.get_chain())
                self.mempool.add(tx, utxo_set)  # silently discard invalid

        except Exception:
            pass
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Block handling
    # ------------------------------------------------------------------

    def _handle_new_block(self, block: Block, sender: Optional[str]) -> None:
        """
        Handle a broadcast NEW_BLOCK message.

        If the block connects cleanly to the current tip, validate and append it,
        then clean the mempool. If it does not connect, trigger a full sync from
        the sender — the peer may have a longer chain we haven't seen.
        """
        with self._lock:
            tip = self.chain[-1]
            connects = (
                block.index == tip.index + 1
                and block.previous_hash == tip.hash
            )

        if connects:
            accepted = False
            with self._lock:
                try:
                    add_block(self.chain, block)
                    accepted = True
                except (ValueError, Exception):
                    pass  # invalid block — discard silently
            if accepted:
                self._clean_mempool_after_block(block)
        elif sender:
            try:
                host, port = sender.split(":")
                self.sync_from(host, int(port))
            except Exception:
                pass

    def _clean_mempool_after_block(self, block: Block) -> None:
        """Remove transactions confirmed in `block` from the mempool."""
        tx_ids = [tx.tx_id for tx in block.transactions]
        self.mempool.remove(tx_ids)

    # ------------------------------------------------------------------
    # Outbound: chain sync
    # ------------------------------------------------------------------

    def sync_from(self, host: str, port: int) -> bool:
        """
        Request the full chain from a peer and replace local chain if:
        - the peer chain is fully valid
        - the peer chain is strictly longer than the local chain

        On replacement, the mempool is revalidated against the new UTXO set.
        Returns True if the local chain was replaced.
        """
        try:
            conn = socket.create_connection((host, port), timeout=5)
            _send_msg(conn, {"type": "GET_CHAIN"})
            resp = _recv_msg(conn)
            conn.close()
        except Exception:
            return False

        if resp.get("type") != "CHAIN":
            return False

        try:
            peer_chain = [block_from_dict(b) for b in resp["blocks"]]
        except Exception:
            return False

        ok, _ = validate_chain(peer_chain)
        if not ok:
            return False

        replaced = False
        with self._lock:
            if len(peer_chain) > len(self.chain):
                self.chain = peer_chain
                replaced = True

        if replaced:
            # Revalidate mempool: drop txs whose UTXOs are now consumed
            new_utxo_set = get_utxo_set(self.get_chain())
            self.mempool.revalidate(new_utxo_set)

        return replaced

    # ------------------------------------------------------------------
    # Outbound: broadcast
    # ------------------------------------------------------------------

    def broadcast_block(self, block: Block, peers: list[tuple[str, int]]) -> None:
        """
        Send a NEW_BLOCK message to each peer.

        Includes sender address so the receiver can trigger a full sync
        if the block does not connect to its current tip.
        Failures are silently ignored — broadcast is best-effort.
        """
        block_data = block_to_dict(block)
        sender_addr = f"{self.host}:{self.port}"
        for host, port in peers:
            try:
                conn = socket.create_connection((host, port), timeout=5)
                _send_msg(conn, {
                    "type": "NEW_BLOCK",
                    "block": block_data,
                    "sender": sender_addr,
                })
                conn.close()
            except Exception:
                pass

    def broadcast_transaction(self, tx: Transaction, peers: list[tuple[str, int]]) -> None:
        """
        Send a NEW_TRANSACTION message to each peer.
        Failures are silently ignored — broadcast is best-effort.
        """
        tx_data = tx_to_dict(tx)
        for host, port in peers:
            try:
                conn = socket.create_connection((host, port), timeout=5)
                _send_msg(conn, {"type": "NEW_TRANSACTION", "tx": tx_data})
                conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Mempool interface
    # ------------------------------------------------------------------

    def add_transaction(self, tx: Transaction) -> Tuple[bool, Optional[str]]:
        """
        Validate and add a transaction to the local mempool.
        Returns (True, None) on success or (False, reason) on rejection.
        """
        utxo_set = get_utxo_set(self.get_chain())
        return self.mempool.add(tx, utxo_set)

    # ------------------------------------------------------------------
    # Chain accessors (thread-safe)
    # ------------------------------------------------------------------

    def chain_length(self) -> int:
        with self._lock:
            return len(self.chain)

    def get_chain(self) -> list[Block]:
        with self._lock:
            return list(self.chain)

    def tip(self) -> Block:
        with self._lock:
            return self.chain[-1]
