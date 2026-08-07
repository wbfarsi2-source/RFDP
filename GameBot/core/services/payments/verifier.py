from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from core.config import settings
from core.time_utils import ensure_utc
from core.runtime_settings import runtime_settings

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


@dataclass(slots=True)
class VerificationResult:
    status: str
    received_usdc: Decimal = Decimal("0")
    confirmations: int = 0
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


class CryptoPaymentVerifier:
    @staticmethod
    def normalize_tx_hash(network: str, value: str) -> str:
        text = str(value or "").strip()
        if network == "base_usdc":
            if not re.fullmatch(r"0x[a-fA-F0-9]{64}", text):
                raise ValueError("invalid_base_tx")
            return text.lower()
        if network == "solana_usdc":
            if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{70,100}", text):
                raise ValueError("invalid_solana_tx")
            return text
        raise ValueError("unsupported_network")

    async def verify(
        self,
        *,
        network: str,
        tx_hash: str,
        wallet: str,
        expected_usdc: Decimal,
        order_created_at: datetime,
    ) -> VerificationResult:
        if network == "base_usdc":
            return await self._verify_base(tx_hash, wallet, expected_usdc, order_created_at)
        if network == "solana_usdc":
            return await self._verify_solana(tx_hash, wallet, expected_usdc, order_created_at)
        return VerificationResult(status="failed", message="Unsupported network")

    async def _rpc(self, url: str, method: str, params: list[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        if data.get("error"):
            raise RuntimeError(str(data["error"]))
        return data.get("result")

    @staticmethod
    def _amount_matches(received: Decimal, expected: Decimal) -> bool:
        tolerance = runtime_settings.payment_tolerance_usdc()
        return abs(received - expected) <= tolerance

    @staticmethod
    def _time_allowed(transaction_time: datetime, order_created_at: datetime) -> bool:
        earliest = ensure_utc(order_created_at).timestamp() - runtime_settings.payment_max_preorder_age_seconds()
        return ensure_utc(transaction_time).timestamp() >= earliest

    async def _verify_base(
        self,
        tx_hash: str,
        wallet: str,
        expected: Decimal,
        order_created_at: datetime,
    ) -> VerificationResult:
        network = runtime_settings.payment_network("base_usdc")
        contract_value = str(network.get("token") or "")
        rpc_url = str(network.get("rpc_url") or settings.base_rpc_url)
        if not contract_value or not wallet:
            return VerificationResult(status="failed", message="Base payment configuration is incomplete")
        receipt = await self._rpc(rpc_url, "eth_getTransactionReceipt", [tx_hash])
        if receipt is None:
            return VerificationResult(status="pending", message="Transaction is not finalized yet")
        if int(str(receipt.get("status", "0x0")), 16) != 1:
            return VerificationResult(status="failed", message="Transaction failed")

        latest_hex = await self._rpc(rpc_url, "eth_blockNumber", [])
        latest = int(str(latest_hex), 16)
        block = int(str(receipt.get("blockNumber")), 16)
        confirmations = max(0, latest - block + 1)
        if confirmations < runtime_settings.payment_min_confirmations():
            return VerificationResult(status="pending", confirmations=confirmations, message="Waiting for confirmations")

        block_data = await self._rpc(rpc_url, "eth_getBlockByNumber", [hex(block), False])
        block_time = datetime.fromtimestamp(int(str(block_data.get("timestamp")), 16), tz=timezone.utc)
        if not self._time_allowed(block_time, order_created_at):
            return VerificationResult(status="failed", confirmations=confirmations, message="Transaction predates the order")

        contract = contract_value.lower()
        recipient = wallet.lower().replace("0x", "").rjust(64, "0")
        raw_amount = 0
        for log in receipt.get("logs") or []:
            if str(log.get("address") or "").lower() != contract:
                continue
            topics = [str(x).lower() for x in (log.get("topics") or [])]
            if len(topics) < 3 or topics[0] != TRANSFER_TOPIC:
                continue
            if topics[2].replace("0x", "").lower() != recipient:
                continue
            raw_amount += int(str(log.get("data") or "0x0"), 16)

        received = Decimal(raw_amount) / (Decimal(10) ** settings.usdc_decimals)
        if not self._amount_matches(received, expected):
            return VerificationResult(
                status="failed",
                received_usdc=received,
                confirmations=confirmations,
                message="Received amount does not match this order",
            )
        return VerificationResult(
            status="passed",
            received_usdc=received,
            confirmations=confirmations,
            message="Payment verified",
            detail={"block_number": block, "block_time": block_time.isoformat()},
        )

    async def _verify_solana(
        self,
        tx_hash: str,
        wallet: str,
        expected: Decimal,
        order_created_at: datetime,
    ) -> VerificationResult:
        network = runtime_settings.payment_network("solana_usdc")
        mint = str(network.get("token") or "")
        rpc_url = str(network.get("rpc_url") or settings.solana_rpc_url)
        if not mint or not wallet:
            return VerificationResult(status="failed", message="Solana payment configuration is incomplete")
        result = await self._rpc(
            rpc_url,
            "getTransaction",
            [tx_hash, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "commitment": "confirmed"}],
        )
        if result is None:
            return VerificationResult(status="pending", message="Transaction is not finalized yet")
        meta = result.get("meta") or {}
        if meta.get("err") is not None:
            return VerificationResult(status="failed", message="Transaction failed")
        block_time_raw = result.get("blockTime")
        if block_time_raw is None:
            return VerificationResult(status="pending", message="Transaction time is not available yet")
        block_time = datetime.fromtimestamp(int(block_time_raw), tz=timezone.utc)
        if not self._time_allowed(block_time, order_created_at):
            return VerificationResult(status="failed", message="Transaction predates the order")

        pre: dict[int, Decimal] = {}
        post: dict[int, Decimal] = {}
        for row in meta.get("preTokenBalances") or []:
            if row.get("mint") == mint and row.get("owner") == wallet:
                pre[int(row.get("accountIndex"))] = Decimal(str((row.get("uiTokenAmount") or {}).get("uiAmountString") or "0"))
        for row in meta.get("postTokenBalances") or []:
            if row.get("mint") == mint and row.get("owner") == wallet:
                post[int(row.get("accountIndex"))] = Decimal(str((row.get("uiTokenAmount") or {}).get("uiAmountString") or "0"))
        received = sum((post.get(index, Decimal("0")) - pre.get(index, Decimal("0"))) for index in set(pre) | set(post))
        received = max(Decimal("0"), received)
        if not self._amount_matches(received, expected):
            return VerificationResult(status="failed", received_usdc=received, message="Received amount does not match this order")
        return VerificationResult(
            status="passed",
            received_usdc=received,
            confirmations=1,
            message="Payment verified",
            detail={"block_time": block_time.isoformat()},
        )
