"""
Node — Phase 4

Minimal peer-to-peer node over plain TCP.

Transport
---------
Each connection carries exactly one message, then closes.
Message framing: 4-byte big-endian length prefix + UTF-8 JSON payload.

Message types
-------------
  GET_CHAIN               — request the node's full chain
  CHAIN   {blocks: [...]} — response carrying the full chain
  NEW_BLOCK {block: {...}} — broadcast a newly mined block

Chain selection rule
--------------------
A peer's chain replaces the local chain if and only if:
  1. validate_chain(peer_chain) passes all existing rules
  2. len(peer_chain) > len(local_chain)

Since difficulty is fixed, chain length equals cumulative work.
Peer data is never trusted without full validation.
"""

import json
import socket
import threading

from .block import Block, new_genesis
from .chain import add_block, validate_chain
from .serialization import block_to_dict, block_from_dict


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
    - Maintains a local chain
    - Serves chain requests from peers (TCP server)
    - Can sync its chain from a peer
    - Can broadcast new blocks to a list of peers
    """

    def __init__(self, host: str, port: int, chain: list[Block] | None = None):
        self.host = host
        self.port = port
        self.chain: list[Block] = chain if chain is not None else [new_genesis(host)]
        self._lock = threading.Lock()
        self._server_sock: socket.socket | None = None
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

        except Exception:
            pass
        finally:
            conn.close()

    def _handle_new_block(self, block: Block, sender: str | None) -> None:
        """
        Handle a broadcast NEW_BLOCK message.

        If the block connects cleanly to the current tip, append it.
        If it does not (wrong index or previous_hash), trigger a full sync
        from the sender — the peer may have a longer valid chain we haven't seen.
        """
        with self._lock:
            tip = self.chain[-1]
            connects = (
                block.index == tip.index + 1
                and block.previous_hash == tip.hash
            )

        if connects:
            with self._lock:
                try:
                    add_block(self.chain, block)
                except (ValueError, Exception):
                    pass  # invalid block — discard silently
        elif sender:
            # Block doesn't connect: request the full chain from this peer
            try:
                host, port = sender.split(":")
                self.sync_from(host, int(port))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Outbound operations
    # ------------------------------------------------------------------

    def sync_from(self, host: str, port: int) -> bool:
        """
        Request the full chain from a peer and replace local chain if:
        - the peer chain is fully valid
        - the peer chain is longer than the local chain

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

        with self._lock:
            if len(peer_chain) > len(self.chain):
                self.chain = peer_chain
                return True

        return False

    def broadcast_block(self, block: Block, peers: list[tuple[str, int]]) -> None:
        """
        Send a NEW_BLOCK message to each peer.

        Includes the sender address so the receiver can trigger a full sync
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
