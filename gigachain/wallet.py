"""
Wallet — Phase 3

Key pair generation, address derivation, and transaction signing/verification.

Library: ecdsa (v0.19+)
  - Pure Python, no native dependencies, works in any environment
  - Provides SECP256K1 (same curve as Bitcoin)
  - Simple API for key generation, DER signing, and verification
  - Not recommended for high-security production use, but appropriate for
    this prototype phase. Switch to `cryptography` (PyCA) before mainnet.

What is signed
--------------
Each transaction is signed over the serialized tx content, EXCLUDING signatures:

    message = "{inp0_tx_id}:{inp0_out_idx},...|{out0_recipient}:{out0_amount},...|{data}"

This is the same string used as the preimage of compute_tx_id (before SHA-256).
`data` is the hex-encoded inscription string; empty string for non-inscription txs.
The message is deterministic and reproducible by any node from the transaction data.
The signature commits to all inputs, all outputs, and the inscription data.
All inputs in a transaction carry the same signature over this full content.
Signatures are never part of tx_id computation.
Coinbase transactions are unsigned.
"""

import hashlib
from ecdsa import SigningKey, VerifyingKey, SECP256k1
from ecdsa.util import sigencode_der, sigdecode_der


# ---------------------------------------------------------------------------
# Key pair and address
# ---------------------------------------------------------------------------

class Wallet:
    """Holds a SECP256K1 key pair and the derived address."""

    def __init__(self, signing_key: SigningKey):
        self._signing_key = signing_key
        self._verifying_key: VerifyingKey = signing_key.get_verifying_key()
        self.address: str = _derive_address(self._verifying_key)

    @staticmethod
    def generate() -> "Wallet":
        """Generate a new random key pair."""
        return Wallet(SigningKey.generate(curve=SECP256k1))

    def public_key_hex(self) -> str:
        """Compressed public key as hex (33 bytes)."""
        return _compress_public_key(self._verifying_key)

    def sign(self, message: str) -> str:
        """Sign a UTF-8 message. Returns DER-encoded signature as hex."""
        sig_bytes = self._signing_key.sign(
            message.encode("utf-8"),
            hashfunc=hashlib.sha256,
            sigencode=sigencode_der,
        )
        return sig_bytes.hex()


def _compress_public_key(vk: VerifyingKey) -> str:
    """Return the compressed public key as a 33-byte hex string."""
    x = vk.pubkey.point.x()
    y = vk.pubkey.point.y()
    prefix = "02" if y % 2 == 0 else "03"
    return prefix + format(x, "064x")


def _derive_address(vk: VerifyingKey) -> str:
    """
    Derive an address from a public key.

    address = SHA256(compressed_public_key_bytes)[:40]

    Simple and deterministic. Checksum / version bytes are a later-phase concern.
    """
    compressed_hex = _compress_public_key(vk)
    pub_bytes = bytes.fromhex(compressed_hex)
    return hashlib.sha256(pub_bytes).hexdigest()[:40]


def public_key_hex_to_address(pub_hex: str) -> str | None:
    """Derive address from a compressed public key hex string. Returns None on error."""
    try:
        pub_bytes = bytes.fromhex(pub_hex)
        # Decompress: strip prefix byte, recover the verifying key
        vk = VerifyingKey.from_string(
            _decompress_public_key(pub_bytes),
            curve=SECP256k1,
        )
        return _derive_address(vk)
    except Exception:
        return None


def _decompress_public_key(compressed: bytes) -> bytes:
    """Decompress a 33-byte compressed public key to 64-byte uncompressed (x, y)."""
    if len(compressed) != 33:
        raise ValueError("expected 33 bytes")
    prefix = compressed[0]
    x = int.from_bytes(compressed[1:], "big")
    p = SECP256k1.curve.p()
    y_sq = (pow(x, 3, p) + SECP256k1.curve.a() * x + SECP256k1.curve.b()) % p
    y = pow(y_sq, (p + 1) // 4, p)
    if (y % 2 == 0) != (prefix == 0x02):
        y = p - y
    return x.to_bytes(32, "big") + y.to_bytes(32, "big")


# ---------------------------------------------------------------------------
# Signing message
# ---------------------------------------------------------------------------

def _tx_signing_message(inputs: list, outputs: list, data: str = "") -> str:
    """
    Build the canonical message that is signed.

    Identical to the preimage used in compute_tx_id — excludes signature fields.
    Includes inscription data so signatures cover the full transaction content.
    All nodes reconstruct this string the same way for verification to work.
    """
    inputs_part = ",".join(f"{i.tx_id}:{i.output_index}" for i in inputs)
    outputs_part = ",".join(f"{o.recipient}:{o.amount}" for o in outputs)
    return f"{inputs_part}|{outputs_part}|{data}"


# ---------------------------------------------------------------------------
# Sign and verify
# ---------------------------------------------------------------------------

def sign_transaction(wallet: Wallet, inputs: list, outputs: list, data: str = "") -> str:
    """
    Sign a transaction's inputs, outputs, and inscription data (excluding signature fields).

    Returns DER signature as hex. The same signature is placed on every input
    in the transaction — all inputs share one signature over the full tx content.
    `data` defaults to "" for non-inscription transactions.
    """
    message = _tx_signing_message(inputs, outputs, data)
    return wallet.sign(message)


def verify_transaction_signature(
    signature_hex: str,
    public_key_hex: str,
    inputs: list,
    outputs: list,
    data: str = "",
) -> bool:
    """
    Verify a transaction signature.

    Reconstructs the signing message from inputs, outputs, and inscription data
    (same as sign_transaction), then checks the signature against the public key.
    Returns True if valid, False otherwise.
    """
    message = _tx_signing_message(inputs, outputs, data).encode("utf-8")
    try:
        pub_bytes = bytes.fromhex(public_key_hex)
        vk = VerifyingKey.from_string(
            _decompress_public_key(pub_bytes),
            curve=SECP256k1,
        )
        sig_bytes = bytes.fromhex(signature_hex)
        return vk.verify(
            sig_bytes,
            message,
            hashfunc=hashlib.sha256,
            sigdecode=sigdecode_der,
        )
    except Exception:
        return False
