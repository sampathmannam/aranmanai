"""State-platform mock integrations.

v1: read + write to local JSON files shaped like the real CCTNS CAS v5.0,
eSakshya SID packet, and ICJS CNR schemas. Real adapter swap is a 1-line
change when DGP/SCRB/NIC grants access.

Pattern source: nyaya-ai's mock-tool-layer rule. The shape matches the
real contract so when the DGP sign-off lands, the swap is transparent.
"""
