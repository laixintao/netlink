#!/usr/bin/env python3
"""
Render a fake topology with mock data so the display can be tested locally
without needing a Linux server.  Run:

    python3 test_render.py
    python3 test_render.py | less -SR      # wide-line scrolling with color
"""

import os
os.environ.pop("NO_COLOR", None)

import netlink

netlink._USE_COLOR = True   # enable colors even when piped


# ── mock NIC data ─────────────────────────────────────────────────────────────

SLAVE1 = {
    "name": "eno1",
    "state": "up",
    "mac": "de:ad:be:ef:00:01",
    "mtu": "1500",
    "speed": "10000Mb/s",
    "duplex": "Full",
    "pci": "0000:1a:00.0",
    "numa": "0",
    "driver": "i40e",
    "model": "Ethernet controller: Intel Corporation Ethernet Connection X722 for 10GbE SFP+ (rev 09)",
    "lnkcap": "LnkCap: Port #0, Speed 2.5GT/s, Width x1, ASPM L0s L1, Exit Latency L0s <64ns, L1 <1us",
    "lnksta": "LnkSta: Speed 2.5GT/s, Width x1",
    "lldp": {
        "switch":   "sw-rack01-leaf-01.example.net",
        "mgmt":     "192.0.2.1",
        "port":     "ifname 25GE1/0/43",
        "sw_model": "DemoSwitch DS6885-48Y8CQ",
    },
}

SLAVE2 = {
    **SLAVE1,
    "name": "eno2",
    "pci":  "0000:1a:00.1",
    "mac":  "de:ad:be:ef:00:02",
    "lldp": {
        "switch":   "sw-rack01-leaf-02.example.net",
        "mgmt":     "192.0.2.2",
        "port":     "ifname 25GE1/0/44",
        "sw_model": "DemoSwitch DS6885-48Y8CQ",
    },
}

STANDALONE_DOWN = {
    "name": "eth0",
    "state": "down",
    "mac": "aa:bb:cc:dd:ee:ff",
    "mtu": "9000",
    "speed": "Unknown!",
    "duplex": "Unknown!",
    "pci": "0000:05:00.0",
    "numa": "1",
    "driver": "mlx5_core",
    "model": "Mellanox Technologies MT27710 Family [ConnectX-4 Lx] (rev 00)",
    "lnkcap": "LnkCap: Speed 8GT/s, Width x8, ASPM L1, Exit Latency L0s unlimited, L1 <4us",
    "lnksta": "LnkSta: Speed 8GT/s, Width x8 (ok)",
    "lldp": {"switch": "N/A", "mgmt": "N/A", "port": "N/A", "sw_model": "N/A"},
}

STANDALONE_UP = {
    "name": "eth1",
    "state": "up",
    "mac": "aa:bb:cc:dd:ee:00",
    "mtu": "1500",
    "speed": "25000Mb/s",
    "duplex": "Full",
    "pci": "0000:06:00.0",
    "numa": "0",
    "driver": "mlx5_core",
    "model": "Mellanox Technologies MT27710 Family [ConnectX-4 Lx] (rev 00)",
    "lnkcap": "LnkCap: Speed 8GT/s, Width x8, ASPM L1, Exit Latency L0s unlimited, L1 <4us",
    "lnksta": "LnkSta: Speed 8GT/s, Width x8 (ok)",
    "lldp": {
        "switch":   "sw-rack01-leaf-03.example.net",
        "mgmt":     "192.0.2.3",
        "port":     "ifname 25GE1/0/45",
        "sw_model": "DemoSwitch DS6885-48Y8CQ",
    },
}

BOND = {
    "name": "bond0",
    "mode": "IEEE 802.3ad Dynamic link aggregation",
    "hash": "layer3+4 (xor)",
    "status": "up",
    "miimon": "100 ms",
    "ports": "2",
    "partner": "aa:bb:cc:dd:ee:11",
    "slaves": ["eno1", "eno2"],
}


# ── patch collect_iface and run render ────────────────────────────────────────

_MOCK_IFACES = {iface["name"]: iface for iface in [SLAVE1, SLAVE2, STANDALONE_DOWN, STANDALONE_UP]}
netlink.collect_iface = lambda name: _MOCK_IFACES[name]

netlink.render_topology([BOND], [STANDALONE_DOWN, STANDALONE_UP])
