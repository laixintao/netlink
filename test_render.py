#!/usr/bin/env python3
"""
Render a fake topology with mock data so the display can be tested locally
without needing a Linux server.  Run:

    python3 test_render.py
    python3 test_render.py | less -SR      # wide-line scrolling with color
"""

import sys
import os

# Force color even when stdout is not a TTY (e.g. pipe to less)
# Remove this line if you want to test the no-color path.
os.environ.pop("NO_COLOR", None)

import netlink

netlink._USE_COLOR = True   # enable colors unconditionally for the demo


# ── mock data ─────────────────────────────────────────────────────────────────

BOND = {
    "name": "bond0",
    "mode": "IEEE 802.3ad Dynamic link aggregation",
    "hash": "layer3+4 (xor)",
    "status": "up",
    "miimon": "100 ms",
    "ports": "2",
    "partner": "c4:12:ec:2e:a8:f1",
    "slaves": [],  # not used directly; slaves are passed to render_slave
}

SLAVE1 = {
    "name": "eno1",
    "state": "up",
    "mac": "a6:ea:53:8b:77:dc",
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
        "switch":   "MY-CBJ4-SHOPEE-LAN-R034-P04-LEAF-01",
        "mgmt":     "172.30.32.17",
        "port":     "ifname 25GE1/0/43",
        "sw_model": "HUAWEI CE6885-48Y8CQ",
    },
}

SLAVE2 = {
    **SLAVE1,
    "name": "eno2",
    "pci":  "0000:1a:00.1",
    "state": "up",
    "lldp": {
        "switch":   "MY-CBJ4-SHOPEE-LAN-R034-P04-LEAF-02",
        "mgmt":     "172.30.32.18",
        "port":     "ifname 25GE1/0/44",
        "sw_model": "HUAWEI CE6885-48Y8CQ",
    },
}

STANDALONE = {
    "name": "eth0",
    "state": "down",
    "mac": "00:11:22:33:44:55",
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


# ── build page ────────────────────────────────────────────────────────────────

page = netlink.Page()
page.add()
page.add(netlink.bold("  PCIe / NIC / Bond / LLDP  Topology"))
page.add()

page.add(netlink.dim("─" * 20) + "  " + netlink.bold("BOND INTERFACES") + "  " + netlink.dim("─" * 20))
page.add()

# Bond header
page.add(
    f"{netlink.dim('╔══')} {netlink.bylw('BOND:')} {netlink.bwh(BOND['name'])}   "
    f"{netlink._state(BOND['status'])} " + netlink.dim("═" * 80)
)
page.add(f"{netlink.dim('║')}  {netlink._kv('mode',   BOND['mode'])}")
page.add(f"{netlink.dim('║')}  {netlink._kv('hash',   BOND['hash'])}")
page.add(f"{netlink.dim('║')}  {netlink._kv('miimon', BOND['miimon'])}    {netlink._kv('ports', BOND['ports'])}")
page.add(f"{netlink.dim('║')}  {netlink._kv('partner', BOND['partner'])}")
page.add(netlink.dim("╠══ SLAVES " + "═" * 90))

for i, slave in enumerate([SLAVE1, SLAVE2]):
    page.add(netlink.dim("║"))
    netlink.render_slave(page, slave, "║  ", last=(i == 1))

page.add(netlink.dim("╚" + "═" * 100))
page.add()

page.add(netlink.dim("─" * 20) + "  " + netlink.bold("STANDALONE NIC INTERFACES") + "  " + netlink.dim("─" * 20))
page.add()
netlink.render_standalone(page, STANDALONE)
page.add()

print(page.render())
