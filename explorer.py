#!/usr/bin/env python3
"""
Gigachain Block Explorer
Run: python explorer.py [--port 8080]

Seeds a small demo chain on startup for visual inspection.
No external dependencies beyond what gigachain already requires.
"""
import argparse
import html as _html
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from gigachain import (
    Wallet, new_genesis, mine_block, add_block, get_utxo_set,
    sign_transaction, BLOCK_REWARD, COINBASE_TX_ID,
)
from gigachain.block import Input, Output, Transaction
from gigachain.inscription import make_inscription_tx, Indexer

# ---------------------------------------------------------------------------
# Demo chain
# ---------------------------------------------------------------------------

def build_demo_chain():
    """Mine a few blocks with real transactions and one inscription."""
    alice = Wallet.generate()
    bob = Wallet.generate()
    miner = Wallet.generate()

    genesis = new_genesis(miner.address)
    chain = [genesis]

    # Block 1 — coinbase only
    b1 = mine_block(genesis, [], miner.address)
    add_block(chain, b1)

    # Block 2 — miner sends 10 to alice, keeps change
    utxos = get_utxo_set(chain)
    (m_tx_id, m_out_idx), m_utxo = next(
        (k, v) for k, v in utxos.items() if v.recipient == miner.address
    )
    inp_a = Input(tx_id=m_tx_id, output_index=m_out_idx)
    outs_a = [
        Output(recipient=alice.address, amount=10),
        Output(recipient=miner.address, amount=m_utxo.amount - 11),  # 1 coin fee
    ]
    sig_a = sign_transaction(miner, [inp_a], outs_a)
    inp_a.signature = sig_a
    inp_a.public_key = miner.public_key_hex()
    tx_a = Transaction(inputs=[inp_a], outputs=outs_a)

    b2 = mine_block(b1, [tx_a], miner.address, fees=1)
    add_block(chain, b2)

    # Block 3 — alice sends 5 to bob with an inscription
    utxos = get_utxo_set(chain)
    (a_tx_id, a_out_idx), a_utxo = next(
        (k, v) for k, v in utxos.items() if v.recipient == alice.address
    )
    inscription_data = b"Hello, Gigachain! First inscription on the chain."
    data_hex = inscription_data.hex()

    inp_b = Input(tx_id=a_tx_id, output_index=a_out_idx)
    outs_b = [
        Output(recipient=bob.address, amount=5),
        Output(recipient=alice.address, amount=a_utxo.amount - 6),  # 1 coin fee
    ]
    sig_b = sign_transaction(alice, [inp_b], outs_b, data_hex)
    inp_b.signature = sig_b
    inp_b.public_key = alice.public_key_hex()
    tx_b = make_inscription_tx([inp_b], outs_b, inscription_data)

    b3 = mine_block(b2, [tx_b], miner.address, fees=1)
    add_block(chain, b3)

    # Block 4 — bob sends 3 to miner
    utxos = get_utxo_set(chain)
    (b_tx_id, b_out_idx), b_utxo = next(
        (k, v) for k, v in utxos.items() if v.recipient == bob.address
    )
    inp_c = Input(tx_id=b_tx_id, output_index=b_out_idx)
    outs_c = [
        Output(recipient=miner.address, amount=3),
        Output(recipient=bob.address, amount=b_utxo.amount - 4),  # 1 coin fee
    ]
    sig_c = sign_transaction(bob, [inp_c], outs_c)
    inp_c.signature = sig_c
    inp_c.public_key = bob.public_key_hex()
    tx_c = Transaction(inputs=[inp_c], outputs=outs_c)

    b4 = mine_block(b3, [tx_c], miner.address, fees=1)
    add_block(chain, b4)

    indexer = Indexer()
    indexer.scan(chain)

    return chain, indexer, {
        "miner": miner.address,
        "alice": alice.address,
        "bob": bob.address,
    }


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font: 15px/1.6 system-ui, sans-serif; background: #f8f9fa; color: #212529; }
a { color: #0d6efd; text-decoration: none; }
a:hover { text-decoration: underline; }
header { background: #1a1a2e; color: #fff; padding: 12px 24px; display: flex; align-items: center; gap: 16px; }
header a { color: #a8d8ff; font-weight: 600; font-size: 1.1rem; }
header span { color: #8899aa; font-size: 0.9rem; }
main { max-width: 1100px; margin: 24px auto; padding: 0 16px; }
h1 { font-size: 1.3rem; margin-bottom: 16px; color: #1a1a2e; }
h2 { font-size: 1.1rem; margin: 24px 0 10px; color: #333; }
form.search { display: flex; gap: 8px; margin-bottom: 24px; }
form.search input { flex: 1; padding: 8px 12px; border: 1px solid #ced4da; border-radius: 4px; font-size: 14px; font-family: monospace; }
form.search button { padding: 8px 18px; background: #0d6efd; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
form.search button:hover { background: #0b5ed7; }
table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 6px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
th { background: #e9ecef; text-align: left; padding: 8px 12px; font-size: 13px; color: #495057; }
td { padding: 8px 12px; font-size: 13px; border-top: 1px solid #f0f0f0; vertical-align: top; }
tr:hover td { background: #f8f9fa; }
.mono { font-family: monospace; font-size: 12px; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.badge-coinbase { background: #d1ecf1; color: #0c5460; }
.badge-inscription { background: #d4edda; color: #155724; }
.badge-regular { background: #e2e3e5; color: #383d41; }
.card { background: #fff; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,.08); padding: 16px 20px; margin-bottom: 16px; }
.card dl { display: grid; grid-template-columns: 180px 1fr; gap: 6px 12px; }
.card dt { font-size: 12px; color: #6c757d; font-weight: 600; text-transform: uppercase; padding-top: 2px; }
.card dd { font-size: 13px; }
.inscription-box { background: #f0fff4; border: 1px solid #b2dfdb; border-radius: 4px; padding: 12px 16px; margin-top: 8px; }
.inscription-box pre { white-space: pre-wrap; word-break: break-all; font-size: 12px; margin-top: 6px; }
.balance-big { font-size: 2rem; font-weight: 700; color: #1a1a2e; }
.known { font-size: 11px; color: #6c757d; }
.error { color: #721c24; background: #f8d7da; padding: 16px; border-radius: 6px; }
.tip { font-size: 12px; color: #6c757d; margin-bottom: 16px; }
"""


def h(text) -> str:
    return _html.escape(str(text))


def page(title: str, body: str, search_val: str = "") -> str:
    sv = h(search_val)
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
  <a href="/">&#9642; Gigachain Explorer</a>
  <span>demo chain</span>
</header>
<main>
  <form class="search" action="/search" method="get">
    <input name="q" placeholder="Search by block height, tx_id, or address" value="{sv}">
    <button type="submit">Search</button>
  </form>
  {body}
</main>
</body>
</html>"""


def fmt_hash(h_str: str, length: int = 16) -> str:
    short = h_str[:length] + "…"
    return f'<span class="mono" title="{h(h_str)}">{h(short)}</span>'


def fmt_time(ts: int) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def tx_type_badge(tx: Transaction) -> str:
    if tx.inputs and tx.inputs[0].tx_id == COINBASE_TX_ID:
        return '<span class="badge badge-coinbase">coinbase</span>'
    if tx.data:
        return '<span class="badge badge-inscription">inscription</span>'
    return '<span class="badge badge-regular">transfer</span>'


def search_bar_hint() -> str:
    return ""


# ---------------------------------------------------------------------------
# Page renderers
# ---------------------------------------------------------------------------

def render_index(chain, known: dict) -> str:
    utxos = get_utxo_set(chain)
    tip = chain[-1]

    rows = ""
    for block in reversed(chain):
        miner_out = block.transactions[0].outputs[0] if block.transactions else None
        miner_addr = miner_out.recipient if miner_out else "?"
        label = next((name for name, addr in known.items() if addr == miner_addr), "")
        label_html = f' <span class="known">({h(label)})</span>' if label else ""
        rows += f"""
        <tr>
          <td><a href="/block/{block.index}">{block.index}</a></td>
          <td>{fmt_hash(block.hash)}</td>
          <td>{h(fmt_time(block.timestamp))}</td>
          <td>{len(block.transactions)}</td>
          <td><a href="/address/{h(miner_addr)}" class="mono">{h(miner_addr[:20])}…</a>{label_html}</td>
        </tr>"""

    body = f"""
    <h1>Latest Blocks</h1>
    <p class="tip">Chain height: {tip.index} &nbsp;|&nbsp; Total blocks: {len(chain)} &nbsp;|&nbsp; UTXOs: {len(utxos)}</p>
    <table>
      <thead><tr><th>Height</th><th>Hash</th><th>Time</th><th>Txs</th><th>Miner</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <h2>Demo Addresses</h2>
    <table>
      <thead><tr><th>Name</th><th>Address</th></tr></thead>
      <tbody>"""
    for name, addr in known.items():
        body += f'<tr><td>{h(name)}</td><td><a href="/address/{h(addr)}" class="mono">{h(addr)}</a></td></tr>'
    body += "</tbody></table>"
    return body


def render_block(block, chain, indexer, known: dict) -> str:
    idx = chain.index(block)
    prev_link = f'<a href="/block/{idx - 1}">{h(block.previous_hash[:20])}…</a>' if idx > 0 else h(block.previous_hash[:20]) + "…"

    rows = ""
    for tx in block.transactions:
        in_total = "—" if tx.inputs[0].tx_id == COINBASE_TX_ID else "?"
        out_total = sum(o.amount for o in tx.outputs)
        rows += f"""
        <tr>
          <td><a href="/tx/{h(tx.tx_id)}" class="mono">{h(tx.tx_id[:20])}…</a></td>
          <td>{tx_type_badge(tx)}</td>
          <td>{len(tx.inputs)}</td>
          <td>{len(tx.outputs)}</td>
          <td>{out_total}</td>
        </tr>"""

    body = f"""
    <h1>Block #{block.index}</h1>
    <div class="card">
      <dl>
        <dt>Height</dt><dd>{block.index}</dd>
        <dt>Hash</dt><dd class="mono">{h(block.hash)}</dd>
        <dt>Previous Hash</dt><dd class="mono">{prev_link}</dd>
        <dt>Merkle Root</dt><dd class="mono">{h(block.merkle_root[:32])}…</dd>
        <dt>Timestamp</dt><dd>{h(fmt_time(block.timestamp))}</dd>
        <dt>Nonce</dt><dd>{block.nonce:,}</dd>
        <dt>Transactions</dt><dd>{len(block.transactions)}</dd>
      </dl>
    </div>
    <h2>Transactions</h2>
    <table>
      <thead><tr><th>TX ID</th><th>Type</th><th>Inputs</th><th>Outputs</th><th>Total Out</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>"""
    return body


def render_tx(tx, block, indexer, known: dict) -> str:
    is_coinbase = tx.inputs[0].tx_id == COINBASE_TX_ID

    inp_rows = ""
    for inp in tx.inputs:
        if inp.tx_id == COINBASE_TX_ID:
            inp_rows += f"<tr><td colspan='3'><em>coinbase (block reward)</em></td></tr>"
        else:
            inp_rows += f"""<tr>
              <td><a href="/tx/{h(inp.tx_id)}" class="mono">{h(inp.tx_id[:20])}…</a></td>
              <td>{inp.output_index}</td>
              <td class="mono">{h(inp.public_key[:20]) if inp.public_key else '—'}…</td>
            </tr>"""

    out_rows = ""
    for i, out in enumerate(tx.outputs):
        label = next((name for name, addr in known.items() if addr == out.recipient), "")
        label_html = f' <span class="known">({h(label)})</span>' if label else ""
        out_rows += f"""<tr>
          <td>{i}</td>
          <td><a href="/address/{h(out.recipient)}" class="mono">{h(out.recipient)}</a>{label_html}</td>
          <td>{out.amount}</td>
        </tr>"""

    # Inscription section
    inscription_html = ""
    if tx.data:
        raw_bytes = bytes.fromhex(tx.data)
        try:
            decoded = raw_bytes.decode("utf-8")
            text_section = f"<p><strong>As text:</strong></p><pre>{h(decoded)}</pre>"
        except UnicodeDecodeError:
            text_section = "<p><em>Binary data (not UTF-8)</em></p>"
        inscription_html = f"""
        <h2>Inscription Data ({len(raw_bytes)} bytes)</h2>
        <div class="inscription-box">
          {text_section}
          <p style="margin-top:8px"><strong>Hex:</strong></p>
          <pre>{h(tx.data)}</pre>
        </div>"""

    block_link = f'<a href="/block/{block.index}">Block #{block.index}</a>'
    body = f"""
    <h1>Transaction</h1>
    <div class="card">
      <dl>
        <dt>TX ID</dt><dd class="mono">{h(tx.tx_id)}</dd>
        <dt>Block</dt><dd>{block_link}</dd>
        <dt>Type</dt><dd>{tx_type_badge(tx)}</dd>
        <dt>Inputs</dt><dd>{len(tx.inputs)}</dd>
        <dt>Outputs</dt><dd>{len(tx.outputs)}</dd>
      </dl>
    </div>
    <h2>Inputs</h2>
    <table>
      <thead><tr><th>Spending TX</th><th>Output Index</th><th>Public Key</th></tr></thead>
      <tbody>{inp_rows}</tbody>
    </table>
    <h2>Outputs</h2>
    <table>
      <thead><tr><th>#</th><th>Recipient</th><th>Amount</th></tr></thead>
      <tbody>{out_rows}</tbody>
    </table>
    {inscription_html}"""
    return body


def render_address(addr: str, chain, known: dict) -> str:
    utxos = get_utxo_set(chain)
    owned = {k: v for k, v in utxos.items() if v.recipient == addr}
    balance = sum(v.amount for v in owned.values())

    label = next((name for name, a in known.items() if a == addr), "")
    label_html = f' <span class="known">({h(label)})</span>' if label else ""

    utxo_rows = ""
    for (tx_id, out_idx), utxo in owned.items():
        utxo_rows += f"""<tr>
          <td><a href="/tx/{h(tx_id)}" class="mono">{h(tx_id[:20])}…</a></td>
          <td>{out_idx}</td>
          <td>{utxo.amount}</td>
        </tr>"""
    if not utxo_rows:
        utxo_rows = "<tr><td colspan='3'><em>No unspent outputs</em></td></tr>"

    # Find all txs involving this address
    tx_rows = ""
    seen = set()
    for block in chain:
        for tx in block.transactions:
            involved = any(o.recipient == addr for o in tx.outputs)
            if not involved and tx.inputs[0].tx_id != COINBASE_TX_ID:
                # Check if any input references a UTXO sent to this address (spending)
                for inp in tx.inputs:
                    prev = utxos.get((inp.tx_id, inp.output_index))
                    # Note: already spent, won't be in current utxo set; scan chain instead
            if involved and tx.tx_id not in seen:
                seen.add(tx.tx_id)
                out_total = sum(o.amount for o in tx.outputs if o.recipient == addr)
                tx_rows += f"""<tr>
                  <td><a href="/block/{block.index}">#{block.index}</a></td>
                  <td><a href="/tx/{h(tx.tx_id)}" class="mono">{h(tx.tx_id[:20])}…</a></td>
                  <td>{tx_type_badge(tx)}</td>
                  <td>+{out_total}</td>
                </tr>"""
    if not tx_rows:
        tx_rows = "<tr><td colspan='4'><em>No transactions found</em></td></tr>"

    body = f"""
    <h1>Address{label_html}</h1>
    <div class="card">
      <p class="mono" style="word-break:break-all;margin-bottom:12px">{h(addr)}</p>
      <p class="balance-big">{balance} <span style="font-size:1rem;color:#6c757d">coins</span></p>
    </div>
    <h2>Unspent Outputs ({len(owned)})</h2>
    <table>
      <thead><tr><th>TX ID</th><th>Index</th><th>Amount</th></tr></thead>
      <tbody>{utxo_rows}</tbody>
    </table>
    <h2>Received Transactions</h2>
    <table>
      <thead><tr><th>Block</th><th>TX ID</th><th>Type</th><th>Amount In</th></tr></thead>
      <tbody>{tx_rows}</tbody>
    </table>"""
    return body


def render_not_found(query: str) -> str:
    return f'<div class="error"><strong>Not found:</strong> {h(query)}</div>'


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

# Global state — set once before server starts
STATE: dict = {}


def find_tx(tx_id: str, chain):
    for block in chain:
        for tx in block.transactions:
            if tx.tx_id == tx_id:
                return tx, block
    return None, None


class ExplorerHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress default access log noise

    def send_html(self, content: str, status: int = 200):
        encoded = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def redirect(self, location: str):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        chain = STATE["chain"]
        indexer = STATE["indexer"]
        known = STATE["known"]

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        parts = [p for p in path.split("/") if p]

        # GET /
        if path == "/":
            body = render_index(chain, known)
            self.send_html(page("Home", body))

        # GET /block/<height>
        elif len(parts) == 2 and parts[0] == "block":
            try:
                height = int(parts[1])
                block = chain[height]
                body = render_block(block, chain, indexer, known)
                self.send_html(page(f"Block #{height}", body))
            except (ValueError, IndexError):
                body = render_not_found(parts[1])
                self.send_html(page("Not Found", body), status=404)

        # GET /tx/<tx_id>
        elif len(parts) == 2 and parts[0] == "tx":
            tx_id = parts[1]
            tx, block = find_tx(tx_id, chain)
            if tx:
                body = render_tx(tx, block, indexer, known)
                self.send_html(page(f"TX {tx_id[:12]}…", body))
            else:
                body = render_not_found(tx_id)
                self.send_html(page("Not Found", body), status=404)

        # GET /address/<addr>
        elif len(parts) == 2 and parts[0] == "address":
            addr = parts[1]
            body = render_address(addr, chain, known)
            self.send_html(page(f"Address {addr[:12]}…", body))

        # GET /search?q=...
        elif path == "/search":
            qs = parse_qs(parsed.query)
            q = qs.get("q", [""])[0].strip()
            if not q:
                self.redirect("/")
            elif q.isdigit():
                self.redirect(f"/block/{q}")
            elif len(q) == 64 and all(c in "0123456789abcdefABCDEF" for c in q):
                tx, _ = find_tx(q, chain)
                if tx:
                    self.redirect(f"/tx/{q}")
                else:
                    self.redirect(f"/address/{q}")
            else:
                self.redirect(f"/address/{q}")

        else:
            body = render_not_found(path)
            self.send_html(page("Not Found", body), status=404)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Gigachain Block Explorer")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port (default: 8080)")
    args = parser.parse_args()

    print("Building demo chain (mining a few blocks, please wait)…")
    t0 = time.time()
    chain, indexer, known = build_demo_chain()
    elapsed = time.time() - t0
    print(f"Demo chain ready: {len(chain)} blocks in {elapsed:.1f}s")
    print(f"  miner : {known['miner']}")
    print(f"  alice : {known['alice']}")
    print(f"  bob   : {known['bob']}")

    STATE["chain"] = chain
    STATE["indexer"] = indexer
    STATE["known"] = known

    server = HTTPServer(("127.0.0.1", args.port), ExplorerHandler)
    print(f"\nExplorer running at http://127.0.0.1:{args.port}/")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
