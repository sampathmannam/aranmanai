"""Mock state-platform integrations.

These adapters read/write local JSON shaped like the real CCTNS / eSakshya
/ ICJS contracts. When the user gets DGP/SCRB sign-off, swap in the real
HTTP clients behind the same interface.

v1 design principle: every integration is an adapter with a sync/async
pair of methods. Tests use these mocks. Production swaps in real
implementations that hit the actual state APIs.
"""
from aranmanai.integrations.mock_cctns import MockCctnsAdapter
from aranmanai.integrations.mock_esakshya import MockEsakshyaAdapter
from aranmanai.integrations.mock_icjs import MockIcjsAdapter

__all__ = ["MockCctnsAdapter", "MockEsakshyaAdapter", "MockIcjsAdapter"]
