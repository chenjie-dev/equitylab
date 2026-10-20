"""qdb HTTP 客户端：读写同一契约；写调用纪律仍是 collector 唯一回源。"""

from __future__ import annotations

from .client import Client, PRICE_SCALE, scale, unscale

__all__ = ["Client", "PRICE_SCALE", "scale", "unscale"]
