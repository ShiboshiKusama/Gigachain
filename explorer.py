#!/usr/bin/env python3
"""
Gigachain Block Explorer

Two modes:

  Demo (default) — seeds a local chain, no node needed:
    python explorer.py

  Live — connects to a running Gigachain node:
    python explorer.py --node 127.0.0.1:9000

Options:
  --port PORT        HTTP port for the explorer (default: 8080)
  --node HOST:PORT   Fetch chain from this node on every request

No dependencies beyond what gigachain already uses.
"""
import argparse
import html as _html
import json
import socket
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from gigachain import (
    Wallet, new_genesis, mine_block, add_block, get_utxo_set,
    sign_transaction, BLOCK_REWARD, COINBASE_TX_ID,
)
from gigachain.block import Block, Input, Output, Transaction
from gigachain.inscription import make_inscription_tx, Indexer
from gigachain.serialization import block_from_dict


# ---------------------------------------------------------------------------
# Live node client — uses the existing GET_CHAIN TCP protocol
# ---------------------------------------------------------------------------

def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed")
        buf += chunk
    return buf


def fetch_chain_from_node(host: str, port: int) -> list[Block]:
    """Pull the full chain from a running node via its TCP GET_CHAIN message."""
    conn = socket.create_connection((host, port), timeout=5)
    try:
        payload = json.dumps({"type": "GET_CHAIN"}).encode("utf-8")
        conn.sendall(len(payload).to_bytes(4, "big") + payload)
        length = int.from_bytes(_recv_exact(conn, 4), "big")
        resp = json.loads(_recv_exact(conn, length).decode("utf-8"))
    finally:
        conn.close()
    if resp.get("type") != "CHAIN":
        raise ValueError(f"unexpected response type: {resp.get('type')}")
    return [block_from_dict(b) for b in resp["blocks"]]


# ---------------------------------------------------------------------------
# Demo chain — used when no --node is given
# ---------------------------------------------------------------------------

def build_demo_chain():
    alice = Wallet.generate()
    bob   = Wallet.generate()
    miner = Wallet.generate()

    genesis = new_genesis(miner.address)
    chain = [genesis]

    # Block 1 — coinbase only
    b1 = mine_block(genesis, [], miner.address)
    add_block(chain, b1)

    # Block 2 — miner → alice 10, fee 1
    utxos = get_utxo_set(chain)
    (m_tid, m_oi), m_utxo = next((k, v) for k, v in utxos.items() if v.recipient == miner.address)
    inp1 = Input(tx_id=m_tid, output_index=m_oi)
    outs1 = [Output(recipient=alice.address, amount=10),
             Output(recipient=miner.address, amount=m_utxo.amount - 11)]
    sig1 = sign_transaction(miner, [inp1], outs1)
    inp1.signature, inp1.public_key = sig1, miner.public_key_hex()
    tx1 = Transaction(inputs=[inp1], outputs=outs1)
    b2 = mine_block(b1, [tx1], miner.address, fees=1)
    add_block(chain, b2)

    # Block 3 — alice → bob 5 with inscription, fee 1
    utxos = get_utxo_set(chain)
    (a_tid, a_oi), a_utxo = next((k, v) for k, v in utxos.items() if v.recipient == alice.address)
    idata = b"Hello, Gigachain! First inscription on the chain."
    inp2 = Input(tx_id=a_tid, output_index=a_oi)
    outs2 = [Output(recipient=bob.address,   amount=5),
             Output(recipient=alice.address, amount=a_utxo.amount - 6)]
    sig2 = sign_transaction(alice, [inp2], outs2, idata.hex())
    inp2.signature, inp2.public_key = sig2, alice.public_key_hex()
    tx2 = make_inscription_tx([inp2], outs2, idata)
    b3 = mine_block(b2, [tx2], miner.address, fees=1)
    add_block(chain, b3)

    # Block 4 — bob → miner 3, fee 1
    utxos = get_utxo_set(chain)
    (b_tid, b_oi), b_utxo = next((k, v) for k, v in utxos.items() if v.recipient == bob.address)
    inp3 = Input(tx_id=b_tid, output_index=b_oi)
    outs3 = [Output(recipient=miner.address, amount=3),
             Output(recipient=bob.address,   amount=b_utxo.amount - 4)]
    sig3 = sign_transaction(bob, [inp3], outs3)
    inp3.signature, inp3.public_key = sig3, bob.public_key_hex()
    tx3 = Transaction(inputs=[inp3], outputs=outs3)
    b4 = mine_block(b3, [tx3], miner.address, fees=1)
    add_block(chain, b4)

    return chain, {"miner": miner.address, "alice": alice.address, "bob": bob.address}


# ---------------------------------------------------------------------------
# Chain helpers
# ---------------------------------------------------------------------------

def build_tx_index(chain: list) -> dict:
    return {tx.tx_id: tx for block in chain for tx in block.transactions}


def compute_fee(tx: Transaction, tx_index: dict) -> int:
    if tx.inputs[0].tx_id == COINBASE_TX_ID:
        return 0
    in_total = sum(
        tx_index[inp.tx_id].outputs[inp.output_index].amount
        for inp in tx.inputs
        if inp.tx_id in tx_index and inp.output_index < len(tx_index[inp.tx_id].outputs)
    )
    return max(0, in_total - sum(o.amount for o in tx.outputs))


def find_tx(tx_id: str, chain: list):
    for block in chain:
        for tx in block.transactions:
            if tx.tx_id == tx_id:
                return tx, block
    return None, None


def txs_for_address(addr: str, chain: list, tx_index: dict) -> list:
    """Return (block, tx, received, sent) for every tx touching this address."""
    results, seen = [], set()
    for block in chain:
        for tx in block.transactions:
            is_cb = tx.inputs[0].tx_id == COINBASE_TX_ID
            received = sum(o.amount for o in tx.outputs if o.recipient == addr)
            sent = 0
            if not is_cb:
                for inp in tx.inputs:
                    prev = tx_index.get(inp.tx_id)
                    if prev and inp.output_index < len(prev.outputs):
                        if prev.outputs[inp.output_index].recipient == addr:
                            sent += prev.outputs[inp.output_index].amount
            if (received or sent) and tx.tx_id not in seen:
                seen.add(tx.tx_id)
                results.append((block, tx, received, sent))
    return results


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font: 15px/1.6 system-ui, sans-serif; background: #f5f6f8; color: #1e2025; }
a { color: #2563eb; text-decoration: none; }
a:hover { text-decoration: underline; }

header { background: #111827; color: #fff; padding: 10px 24px;
         display: flex; align-items: center; gap: 20px; }
header .logo { color: #60a5fa; font-weight: 700; font-size: 1.05rem; }
header .mode { color: #6b7280; font-size: 0.85rem; }

main { max-width: 1080px; margin: 28px auto; padding: 0 16px; }

h1 { font-size: 1.2rem; margin-bottom: 14px; color: #111827; }
h2 { font-size: 0.95rem; margin: 20px 0 8px; color: #374151; font-weight: 600;
     text-transform: uppercase; letter-spacing: .04em; }

form.search { display: flex; gap: 8px; margin-bottom: 22px; }
form.search input  { flex: 1; padding: 8px 12px; border: 1px solid #d1d5db; border-radius: 5px;
                     font-size: 13px; font-family: monospace; background: #fff; }
form.search button { padding: 8px 16px; background: #2563eb; color: #fff;
                     border: none; border-radius: 5px; cursor: pointer; font-size: 13px; }
form.search button:hover { background: #1d4ed8; }

table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 7px;
        overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.07); font-size: 13px; }
th { background: #f3f4f6; text-align: left; padding: 7px 12px; color: #6b7280;
     font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
td { padding: 8px 12px; border-top: 1px solid #f0f0f0; vertical-align: top; }
tr:hover td { background: #f9fafb; }

.mono  { font-family: monospace; font-size: 12px; }
.dim   { color: #9ca3af; }
.small { font-size: 11px; color: #9ca3af; }

.badge { display: inline-block; padding: 1px 7px; border-radius: 9px; font-size: 11px; font-weight: 600; }
.cb    { background: #dbeafe; color: #1e40af; }
.ins   { background: #d1fae5; color: #065f46; }
.xfer  { background: #e5e7eb; color: #374151; }

.card { background: #fff; border-radius: 7px; box-shadow: 0 1px 3px rgba(0,0,0,.07);
        padding: 16px 20px; margin-bottom: 14px; }
.card dl { display: grid; grid-template-columns: 160px 1fr; row-gap: 5px; column-gap: 12px; }
.card dt { font-size: 11px; color: #6b7280; font-weight: 600; text-transform: uppercase; padding-top: 3px; }
.card dd { font-size: 13px; word-break: break-all; }

.bal   { font-size: 1.8rem; font-weight: 700; color: #111827; }
.ibox  { background: #f0fdf4; border: 1px solid #86efac; border-radius: 5px;
         padding: 12px 14px; margin-top: 6px; }
.ibox pre { white-space: pre-wrap; word-break: break-all; font-size: 12px;
            font-family: monospace; color: #374151; margin-top: 4px; }
.stat  { font-size: 12px; color: #6b7280; margin-bottom: 14px; }
.stat b { color: #111827; }
.err   { color: #991b1b; background: #fee2e2; padding: 14px 16px; border-radius: 6px; }
.warn  { color: #92400e; background: #fef3c7; padding: 14px 16px; border-radius: 6px; }
.in    { color: #15803d; }
.out   { color: #b91c1c; }
"""


def h(v) -> str:
    return _html.escape(str(v))


def page(title: str, body: str, mode_label: str = "demo", q: str = "") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{h(title)} — Gigachain Explorer</title>
  <style>{CSS}</style>
</head>
<body>
<header>
  <a class="logo" href="/">&#9670; Gigachain Explorer</a>
  <span class="mode">{h(mode_label)}</span>
</header>
<main>
  <form class="search" action="/search" method="get">
    <input name="q" placeholder="Block height, tx_id, or address…" value="{h(q)}">
    <button>Search</button>
  </form>
  {body}
</main>
</body>
</html>"""


def abbrev(s: str, n: int = 16) -> str:
    return f'<span class="mono" title="{h(s)}">{h(s[:n])}…</span>'


def fmt_time(unix: int) -> str:
    return datetime.fromtimestamp(unix, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def badge(tx: Transaction) -> str:
    if tx.inputs[0].tx_id == COINBASE_TX_ID:
        return '<span class="badge cb">coinbase</span>'
    if tx.data:
        return '<span class="badge ins">inscription</span>'
    return '<span class="badge xfer">transfer</span>'


def known_label(addr: str, known: dict) -> str:
    name = known.get(addr, "")
    return f' <span class="small">({h(name)})</span>' if name else ""


# ---------------------------------------------------------------------------
# Page renderers
# ---------------------------------------------------------------------------

def render_index(chain: list, known: dict) -> str:
    tip   = chain[-1]
    utxos = get_utxo_set(chain)

    rows = ""
    for block in reversed(chain):
        miner_addr = block.transactions[0].outputs[0].recipient if block.transactions else "?"
        rows += f"""<tr>
          <td><a href="/block/{block.index}">{block.index}</a></td>
          <td>{abbrev(block.hash)}</td>
          <td>{abbrev(block.previous_hash)}</td>
          <td class="dim">{h(fmt_time(block.timestamp))}</td>
          <td>{len(block.transactions)}</td>
          <td>
            <a href="/address/{h(miner_addr)}" class="mono">{h(miner_addr[:20])}…</a>
            {known_label(miner_addr, known)}
          </td>
        </tr>"""

    known_rows = "".join(
        f'<tr><td>{h(n)}</td>'
        f'<td><a href="/address/{h(a)}" class="mono">{h(a)}</a></td></tr>'
        for n, a in known.items()
    ) if known else "<tr><td colspan='2' class='dim'>—</td></tr>"

    return f"""
    <h1>Latest Blocks</h1>
    <p class="stat">
      Tip <b>{tip.index}</b> &nbsp;·&nbsp;
      <b>{len(chain)}</b> blocks &nbsp;·&nbsp;
      <b>{len(utxos)}</b> UTXOs
    </p>
    <table>
      <thead><tr>
        <th>Height</th><th>Hash</th><th>Prev Hash</th>
        <th>Time (UTC)</th><th>Txs</th><th>Miner</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>

    <h2>Known Addresses</h2>
    <table>
      <thead><tr><th>Label</th><th>Address</th></tr></thead>
      <tbody>{known_rows}</tbody>
    </table>"""


def render_block(block: Block, chain: list, tx_index: dict, known: dict) -> str:
    prev_link = (
        f'<a href="/block/{block.index - 1}" class="mono">{h(block.previous_hash[:22])}…</a>'
        if block.index > 0 else
        f'<span class="mono dim">{h(block.previous_hash[:22])}…</span>'
    )

    rows = ""
    for tx in block.transactions:
        fee = compute_fee(tx, tx_index)
        out_total = sum(o.amount for o in tx.outputs)
        rows += f"""<tr>
          <td><a href="/tx/{h(tx.tx_id)}" class="mono">{h(tx.tx_id[:22])}…</a></td>
          <td>{badge(tx)}</td>
          <td>{len(tx.inputs)}</td>
          <td>{len(tx.outputs)}</td>
          <td>{out_total}</td>
          <td>{fee or "—"}</td>
        </tr>"""

    return f"""
    <h1>Block #{block.index}</h1>
    <div class="card">
      <dl>
        <dt>Height</dt>       <dd>{block.index}</dd>
        <dt>Hash</dt>         <dd class="mono">{h(block.hash)}</dd>
        <dt>Previous Hash</dt><dd class="mono">{prev_link}</dd>
        <dt>Merkle Root</dt>  <dd class="mono">{h(block.merkle_root[:32])}…</dd>
        <dt>Timestamp</dt>    <dd>{h(fmt_time(block.timestamp))}</dd>
        <dt>Nonce</dt>        <dd>{block.nonce:,}</dd>
        <dt>Transactions</dt> <dd>{len(block.transactions)}</dd>
      </dl>
    </div>
    <h2>Transactions</h2>
    <table>
      <thead><tr>
        <th>TX ID</th><th>Type</th><th>Inputs</th><th>Outputs</th><th>Total Out</th><th>Fee</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def render_tx(tx: Transaction, block: Block, tx_index: dict, known: dict) -> str:
    is_cb     = tx.inputs[0].tx_id == COINBASE_TX_ID
    fee       = compute_fee(tx, tx_index)
    out_total = sum(o.amount for o in tx.outputs)

    inp_rows = ""
    for inp in tx.inputs:
        if inp.tx_id == COINBASE_TX_ID:
            inp_rows += "<tr><td colspan='4'><em class='dim'>coinbase — block reward</em></td></tr>"
        else:
            prev      = tx_index.get(inp.tx_id)
            amount    = prev.outputs[inp.output_index].amount if prev else "?"
            from_addr = prev.outputs[inp.output_index].recipient if prev else "?"
            inp_rows += f"""<tr>
              <td><a href="/tx/{h(inp.tx_id)}" class="mono">{h(inp.tx_id[:18])}…</a></td>
              <td>{inp.output_index}</td>
              <td>
                <a href="/address/{h(from_addr)}" class="mono">{h(str(from_addr)[:20])}…</a>
                {known_label(str(from_addr), known)}
              </td>
              <td>{amount}</td>
            </tr>"""

    out_rows = ""
    for i, out in enumerate(tx.outputs):
        out_rows += f"""<tr>
          <td>{i}</td>
          <td>
            <a href="/address/{h(out.recipient)}" class="mono">{h(out.recipient)}</a>
            {known_label(out.recipient, known)}
          </td>
          <td>{out.amount}</td>
        </tr>"""

    ins_html = ""
    if tx.data:
        raw = bytes.fromhex(tx.data)
        try:
            text_block = f"<p><b>Text:</b></p><pre>{h(raw.decode('utf-8'))}</pre>"
        except UnicodeDecodeError:
            text_block = "<p class='dim'>Binary data — not valid UTF-8</p>"
        ins_html = f"""
        <h2>Inscription ({len(raw)} bytes)</h2>
        <div class="ibox">
          {text_block}
          <p style="margin-top:8px"><b>Hex:</b></p>
          <pre>{h(tx.data)}</pre>
        </div>"""

    return f"""
    <h1>Transaction</h1>
    <div class="card">
      <dl>
        <dt>TX ID</dt>    <dd class="mono">{h(tx.tx_id)}</dd>
        <dt>Block</dt>    <dd><a href="/block/{block.index}">#{block.index}</a></dd>
        <dt>Type</dt>     <dd>{badge(tx)}</dd>
        <dt>Total Out</dt><dd>{out_total}</dd>
        <dt>Fee</dt>      <dd>{fee if not is_cb else "—"}</dd>
      </dl>
    </div>
    <h2>Inputs</h2>
    <table>
      <thead><tr><th>Prev TX</th><th>Output #</th><th>From</th><th>Amount</th></tr></thead>
      <tbody>{inp_rows}</tbody>
    </table>
    <h2>Outputs</h2>
    <table>
      <thead><tr><th>#</th><th>Recipient</th><th>Amount</th></tr></thead>
      <tbody>{out_rows}</tbody>
    </table>
    {ins_html}"""


def render_address(addr: str, chain: list, tx_index: dict, known: dict) -> str:
    utxos   = get_utxo_set(chain)
    owned   = {k: v for k, v in utxos.items() if v.recipient == addr}
    balance = sum(v.amount for v in owned.values())

    utxo_rows = "".join(
        f'<tr>'
        f'<td><a href="/tx/{h(tid)}" class="mono">{h(tid[:20])}…</a></td>'
        f'<td>{oi}</td>'
        f'<td>{utxo.amount}</td>'
        f'</tr>'
        for (tid, oi), utxo in owned.items()
    ) or "<tr><td colspan='3' class='dim'>No unspent outputs</td></tr>"

    tx_rows = ""
    for block, tx, received, sent in txs_for_address(addr, chain, tx_index):
        parts = []
        if received: parts.append(f'<span class="in">+{received}</span>')
        if sent:     parts.append(f'<span class="out">−{sent}</span>')
        tx_rows += f"""<tr>
          <td><a href="/block/{block.index}">#{block.index}</a></td>
          <td><a href="/tx/{h(tx.tx_id)}" class="mono">{h(tx.tx_id[:20])}…</a></td>
          <td>{badge(tx)}</td>
          <td>{"  ".join(parts)}</td>
        </tr>"""
    if not tx_rows:
        tx_rows = "<tr><td colspan='4' class='dim'>No transactions</td></tr>"

    label = known.get(addr, "")
    heading = f"Address — {h(label)}" if label else "Address"

    return f"""
    <h1>{heading}</h1>
    <div class="card">
      <p class="mono" style="margin-bottom:10px">{h(addr)}</p>
      <p class="bal">{balance} <span style="font-size:1rem;color:#6b7280">coins</span></p>
    </div>
    <h2>Unspent Outputs ({len(owned)})</h2>
    <table>
      <thead><tr><th>TX ID</th><th>Index</th><th>Amount</th></tr></thead>
      <tbody>{utxo_rows}</tbody>
    </table>
    <h2>Transaction History</h2>
    <table>
      <thead><tr><th>Block</th><th>TX ID</th><th>Type</th><th>Amount</th></tr></thead>
      <tbody>{tx_rows}</tbody>
    </table>"""


def render_error(msg: str, detail: str = "") -> str:
    detail_html = f"<p style='margin-top:8px;font-size:12px;font-family:monospace'>{h(detail)}</p>" if detail else ""
    return f'<div class="err"><b>Error:</b> {h(msg)}{detail_html}</div>'


def render_not_found(q: str) -> str:
    return f'<div class="err"><b>Not found:</b> {h(q)}</div>'


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

STATE: dict = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_html(self, content: str, status: int = 200):
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, loc: str):
        self.send_response(302)
        self.send_header("Location", loc)
        self.end_headers()

    def get_chain(self):
        """Return current chain — fetched live if in node mode, static in demo mode."""
        node = STATE.get("node")
        if node:
            host, port = node
            return fetch_chain_from_node(host, port)
        return STATE["chain"]

    def do_GET(self):
        known      = STATE["known"]
        mode_label = STATE["mode_label"]

        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/") or "/"
        parts  = [p for p in path.split("/") if p]

        # Fetch fresh chain on every request
        try:
            chain = self.get_chain()
        except Exception as exc:
            body = render_error("Could not reach node", str(exc))
            self.send_html(page("Error", body, mode_label), 503)
            return

        tx_index = build_tx_index(chain)

        # Routes
        if path == "/":
            self.send_html(page("Home", render_index(chain, known), mode_label))

        elif len(parts) == 2 and parts[0] == "block":
            try:
                block = chain[int(parts[1])]
                self.send_html(page(f"Block #{block.index}",
                                    render_block(block, chain, tx_index, known), mode_label))
            except (ValueError, IndexError):
                self.send_html(page("Not Found", render_not_found(parts[1]), mode_label), 404)

        elif len(parts) == 2 and parts[0] == "tx":
            tx, block = find_tx(parts[1], chain)
            if tx:
                self.send_html(page(f"TX {parts[1][:12]}…",
                                    render_tx(tx, block, tx_index, known), mode_label))
            else:
                self.send_html(page("Not Found", render_not_found(parts[1]), mode_label), 404)

        elif len(parts) == 2 and parts[0] == "address":
            self.send_html(page(f"Address {parts[1][:12]}…",
                                render_address(parts[1], chain, tx_index, known), mode_label))

        elif path == "/search":
            q = parse_qs(parsed.query).get("q", [""])[0].strip()
            if not q:
                self.redirect("/")
            elif q.isdigit():
                self.redirect(f"/block/{q}")
            elif len(q) == 64 and all(c in "0123456789abcdefABCDEF" for c in q):
                tx, _ = find_tx(q, chain)
                self.redirect(f"/tx/{q}" if tx else f"/address/{q}")
            else:
                self.redirect(f"/address/{q}")

        else:
            self.send_html(page("Not Found", render_not_found(path), mode_label), 404)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Gigachain Block Explorer")
    ap.add_argument("--port", type=int, default=8080, help="Explorer HTTP port (default: 8080)")
    ap.add_argument("--node", metavar="HOST:PORT",
                    help="Connect to a running Gigachain node (e.g. 127.0.0.1:9000)")
    args = ap.parse_args()

    if args.node:
        # Live node mode
        host, port_str = args.node.rsplit(":", 1)
        node_port = int(port_str)
        print(f"Live mode — connecting to node at {host}:{node_port}")
        try:
            chain = fetch_chain_from_node(host, node_port)
            print(f"Connected. Chain length: {len(chain)} blocks.")
        except Exception as e:
            print(f"Warning: initial fetch failed ({e}). Will retry on each request.")
        STATE["node"]       = (host, node_port)
        STATE["chain"]      = None
        STATE["known"]      = {}
        STATE["mode_label"] = f"live · {host}:{node_port}"
    else:
        # Demo mode
        print("Demo mode — building local chain (mining a few blocks)…")
        t0 = time.time()
        chain, known = build_demo_chain()
        print(f"Ready: {len(chain)} blocks in {time.time() - t0:.1f}s")
        for name, addr in known.items():
            print(f"  {name:6s}  {addr}")
        STATE["node"]       = None
        STATE["chain"]      = chain
        STATE["known"]      = known
        STATE["mode_label"] = "demo"

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"\nExplorer →  http://127.0.0.1:{args.port}/\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
