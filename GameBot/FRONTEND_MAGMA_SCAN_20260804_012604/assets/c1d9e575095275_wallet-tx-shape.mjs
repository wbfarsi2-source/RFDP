/**
 * Wallet-provider response-shape helpers for `signAndSendTransaction`.
 *
 * Phantom resolves `{ signature: <base58 string> }`, but other `window.solana`
 * providers differ: Brave Wallet has resolved bare strings, `{ publicKey,
 * signature }`, and byte-array signatures depending on version. The old
 * extractor (`sigResult?.signature?.toString?.()`) only understood the Phantom
 * shape, so a wallet could BROADCAST the payment yet the client treated it as
 * a failure and never told the server — the buyer was charged on-chain with
 * nothing delivered (a Brave user lost 32,210 $KINS on a $125 marketplace
 * listing this way on 2026-06-10). A byte-array signature was even worse:
 * `Uint8Array.toString()` produces `"12,34,…"`, which passed the old truthiness
 * check and then failed RPC with "Invalid signature parameter".
 *
 * Two defenses live here:
 *  1. {@link extractTxSignature} — recognize every known result shape and
 *     validate the output actually looks like a base58 signature.
 *  2. {@link findRecentSplPaymentSignature} — when the wallet's response is
 *     unusable (or it threw after broadcasting), scan the payer's token
 *     account on-chain for a transaction matching the exact quote amounts and
 *     recover the signature, so the server confirm step still runs.
 */

/**
 * Invoke a wallet's `signAndSendTransaction` with the argument shape that wallet
 * type actually expects — so the wallet's approval popup reliably opens.
 *
 * Two contracts exist:
 *  • Our **Wallet Standard shim** ({@link module:wallet-standard-shim}) takes the
 *    relay `Connection` as its 2nd arg, because a sign-only wallet is broadcast
 *    through it. It is tagged `isWalletStandardShim`.
 *  • **Raw injected providers** (Phantom, Brave, OKX, Solflare, Backpack, …)
 *    follow the Phantom API `signAndSendTransaction(transaction, options)` where
 *    arg 2 is a `SendOptions` object. Passing a `Connection` there is non-standard:
 *    Phantom/Brave ignore it, but **OKX silently refuses and never opens its
 *    popup** — the reported "OKX won't open on a transaction" bug. Give raw
 *    providers a real `SendOptions` instead.
 *
 * (The opt-in AppKit adapter takes a single `vtx` and ignores extra args, so
 * either call shape is safe for it.)
 *
 * @param {any} wallet provider from `getWalletProvider()`
 * @param {any} vtx v0 `VersionedTransaction`
 * @param {any} conn session relay `Connection` (only used by the shim)
 * @param {object} [sendOpts] SendOptions for raw providers
 * @returns {Promise<unknown>} the wallet's raw result (pass to {@link extractTxSignature})
 */
export function signAndSendViaWallet(wallet, vtx, conn, sendOpts = { skipPreflight: false }) {
  if (wallet && wallet.isWalletStandardShim) {
    return wallet.signAndSendTransaction(vtx, conn, sendOpts);
  }
  return wallet.signAndSendTransaction(vtx, sendOpts);
}

const BASE58_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';

/** Solana tx signatures are 64 bytes → 87-88 base58 chars; accept a safe range. */
const BASE58_SIG_RE = /^[1-9A-HJ-NP-Za-km-z]{64,90}$/;

/** @param {string} s */
export function looksLikeBase58Signature(s) {
  return typeof s === 'string' && BASE58_SIG_RE.test(s);
}

/**
 * Minimal base58 encoder (no dependency — the browser importmap only carries
 * three + @solana/*). Only used for 64-byte signatures, so O(n²) is fine.
 * @param {Uint8Array | number[]} bytes
 */
export function bs58EncodeBytes(bytes) {
  const input = bytes instanceof Uint8Array ? bytes : Uint8Array.from(bytes);
  if (!input.length) return '';
  const digits = [0];
  for (const byte of input) {
    let carry = byte;
    for (let i = 0; i < digits.length; i++) {
      carry += digits[i] << 8;
      digits[i] = carry % 58;
      carry = (carry / 58) | 0;
    }
    while (carry > 0) {
      digits.push(carry % 58);
      carry = (carry / 58) | 0;
    }
  }
  let out = '';
  for (const byte of input) {
    if (byte !== 0) break;
    out += BASE58_ALPHABET[0];
  }
  for (let i = digits.length - 1; i >= 0; i--) out += BASE58_ALPHABET[digits[i]];
  return out;
}

/** @param {unknown} v true for Uint8Array / plain byte arrays (wallets returning raw signature bytes). */
function isByteArrayLike(v) {
  if (v instanceof Uint8Array) return v.length >= 32;
  return (
    Array.isArray(v) &&
    v.length >= 32 &&
    v.length <= 128 &&
    v.every(n => typeof n === 'number' && n >= 0 && n <= 255)
  );
}

/**
 * Extract a base58 transaction signature from whatever a wallet's
 * `signAndSendTransaction` resolved with. Returns '' when nothing usable is
 * found — callers must treat that as "possibly broadcast" (see module doc),
 * not as a clean failure.
 * @param {unknown} sigResult
 * @returns {string}
 */
export function extractTxSignature(sigResult) {
  const seen = new Set();
  /** @param {unknown} v @param {number} depth */
  const walk = (v, depth) => {
    if (v == null || depth > 3) return '';
    if (typeof v === 'string') {
      const s = v.trim();
      return looksLikeBase58Signature(s) ? s : '';
    }
    if (isByteArrayLike(v)) {
      const s = bs58EncodeBytes(/** @type {Uint8Array | number[]} */ (v));
      return looksLikeBase58Signature(s) ? s : '';
    }
    if (typeof v !== 'object') return '';
    if (seen.has(v)) return '';
    seen.add(v);
    const o = /** @type {Record<string, unknown>} */ (v);
    /** Common field names across Phantom / Brave / Solflare / adapter wrappers. */
    for (const key of ['signature', 'txid', 'txId', 'txHash', 'hash', 'transactionSignature']) {
      const got = walk(o[key], depth + 1);
      if (got) return got;
    }
    if (Array.isArray(o.signatures) && o.signatures.length) {
      const got = walk(o.signatures[0], depth + 1);
      if (got) return got;
    }
    /** Last resort: some providers return objects whose toString() IS the base58 sig. */
    if (typeof o.toString === 'function') {
      try {
        const s = String(o.toString()).trim();
        if (looksLikeBase58Signature(s)) return s;
      } catch (_) {
        /* ignore */
      }
    }
    return '';
  };
  return walk(sigResult, 0);
}

/**
 * Recover the signature of a just-broadcast payment by scanning the payer's
 * token account for a transaction whose SPL instructions match the quote
 * exactly. Used when the wallet broadcast but its response gave us no usable
 * signature. Polls because broadcast → RPC visibility takes a few seconds.
 *
 * @param {import('@solana/web3.js').Connection} conn session-relay connection
 * @param {object} opts
 * @param {import('@solana/web3.js').PublicKey} opts.sourceAta payer's token account (the debit side of every expected instruction)
 * @param {string} opts.authorityB58 payer wallet — instruction authority must match
 * @param {Array<{ type: 'transferChecked', destination: string, amount: string } | { type: 'burnChecked', amount: string }>} opts.expects
 *   every entry must be present in the candidate tx for it to count as ours
 * @param {number} opts.sinceMs only consider txs landing at/after this wall-clock time (minus skew allowance)
 * @param {number} [opts.timeoutMs]
 * @param {number} [opts.pollMs]
 * @returns {Promise<string>} base58 signature, or '' if nothing matched in time
 */
export async function findRecentSplPaymentSignature(conn, opts) {
  const timeoutMs = opts.timeoutMs ?? 24_000;
  const pollMs = opts.pollMs ?? 4_000;
  /** blockTime is whole seconds and node clocks skew — accept a 2-minute look-back. */
  const earliestSec = Math.floor(opts.sinceMs / 1000) - 120;
  const deadline = Date.now() + timeoutMs;
  const sourceAtaB58 = opts.sourceAta.toBase58();
  const checked = new Set();

  /** @param {object} tx parsed transaction */
  const txMatchesQuote = tx => {
    const ixs = tx?.transaction?.message?.instructions || [];
    return opts.expects.every(exp =>
      ixs.some(ix => {
        const p = ix && ix.parsed;
        if (!p || ix.program !== 'spl-token') return false;
        const info = p.info || {};
        const authority = String(info.authority || info.multisigAuthority || '');
        if (authority !== opts.authorityB58) return false;
        const amount = String(info.tokenAmount?.amount ?? info.amount ?? '');
        if (amount !== String(exp.amount)) return false;
        if (exp.type === 'burnChecked') {
          return String(p.type).startsWith('burn') && String(info.account || '') === sourceAtaB58;
        }
        return (
          String(p.type).startsWith('transfer') &&
          String(info.source || '') === sourceAtaB58 &&
          String(info.destination || '') === String(exp.destination)
        );
      }),
    );
  };

  while (Date.now() < deadline) {
    try {
      const sigs = await conn.getSignaturesForAddress(opts.sourceAta, { limit: 8 }, 'confirmed');
      for (const s of sigs || []) {
        if (!s || s.err != null) continue;
        if (s.blockTime != null && s.blockTime < earliestSec) continue;
        if (checked.has(s.signature)) continue;
        checked.add(s.signature);
        const tx = await conn
          .getParsedTransaction(s.signature, { commitment: 'confirmed', maxSupportedTransactionVersion: 0 })
          .catch(() => null);
        if (tx && !tx.meta?.err && txMatchesQuote(tx)) return s.signature;
      }
    } catch (_) {
      /* relay hiccup — keep polling until the deadline */
    }
    await new Promise(r => setTimeout(r, pollMs));
  }
  return '';
}
