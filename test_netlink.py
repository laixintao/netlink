"""
pytest test suite for netlink.py rendering logic.
No external dependencies beyond pytest itself.

Run:
    pytest test_netlink.py -v
"""

import json
import re
import pytest
import netlink

# Disable colors for all tests — easier to assert on plain text
netlink._USE_COLOR = False

ANSI_RE = re.compile(r'\033\[[0-9;]*m')


def strip(s: str) -> str:
    return ANSI_RE.sub('', s)


# ── fixtures ──────────────────────────────────────────────────────────────────

LLDP_OK = {
    "switch":   "sw-rack01-leaf-01.example.net",
    "mgmt":     "192.0.2.1",
    "port":     "ifname 25GE1/0/43",
    "sw_model": "DemoSwitch DS6885-48Y8CQ",
}

LLDP_NONE = {"switch": "N/A", "mgmt": "N/A", "port": "N/A", "sw_model": "N/A"}


def make_iface(name="eno1", state="up", lldp=None, pci="0000:1a:00.0") -> dict:
    return {
        "name": name, "state": state,
        "mac": "de:ad:be:ef:00:01", "mtu": "1500",
        "speed": "10000Mb/s", "duplex": "Full",
        "pci": pci,
        "card_key": pci.rsplit(".", 1)[0] if "." in pci else pci,
        "numa": "0",
        "driver": "test_driver",
        "model": "Ethernet controller: Test NIC Model (rev 01)",
        "lnkcap": "LnkCap: Port #0, Speed 2.5GT/s, Width x1, ASPM L0s L1",
        "lnksta": "LnkSta: Speed 2.5GT/s, Width x1",
        "lldp": lldp if lldp is not None else LLDP_OK,
    }


def make_bond(slaves=("eno1", "eno2"), status="up") -> dict:
    return {
        "name": "bond0", "mode": "IEEE 802.3ad", "hash": "layer3+4",
        "status": status, "miimon": "100 ms", "ports": str(len(slaves)),
        "partner": "aa:bb:cc:dd:ee:11", "slaves": list(slaves),
    }


# ── IP addresses ─────────────────────────────────────────────────────────────

class TestAddresses:
    @pytest.mark.parametrize("collector,name", [
        (netlink.collect_iface, "eno1"),
        (netlink.collect_bond, "bond0"),
    ])
    def test_collects_all_local_addresses(self, monkeypatch, collector, name):
        data = [{"ifname": name, "addr_info": [
            {"family": "inet", "local": "192.0.2.10", "prefixlen": 24},
            {"family": "inet", "local": "198.51.100.10", "prefixlen": 0,
             "peer": "198.51.100.11"},
            {"family": "inet6", "local": "2001:db8::10", "prefixlen": 64},
            {"family": "inet6", "local": "fe80::1", "prefixlen": 64},
        ]}]

        def run(*cmd):
            assert cmd == ("ip", "-j", "address", "show", "dev", name)
            return json.dumps(data)

        monkeypatch.setattr(netlink, "has", lambda cmd: cmd == "ip")
        monkeypatch.setattr(netlink, "run", run)
        monkeypatch.setattr(netlink, "rf", lambda path, default="N/A": default)
        monkeypatch.setattr(netlink.os, "readlink", lambda path: "0000:1a:00.0")
        iface = collector(name)
        assert iface["ipv4"] == ["192.0.2.10/24", "198.51.100.10/0"]
        assert iface["ipv6"] == ["2001:db8::10/64", "fe80::1/64"]

    @pytest.mark.parametrize("output", ["", "not json", "[]", "null",
                                        '[{"addr_info": []}]'])
    def test_unavailable_addresses(self, monkeypatch, output):
        monkeypatch.setattr(netlink, "has", lambda cmd: True)
        monkeypatch.setattr(netlink, "run", lambda *cmd: output)
        assert netlink.collect_addresses("eno1") == {"ipv4": [], "ipv6": []}

    def test_missing_ip_command(self, monkeypatch):
        monkeypatch.setattr(netlink, "has", lambda cmd: False)
        monkeypatch.setattr(netlink, "run", lambda *cmd: pytest.fail("ip is unavailable"))
        assert netlink.collect_addresses("eno1") == {"ipv4": [], "ipv6": []}

    @pytest.mark.parametrize("color", [False, True])
    def test_topology_keeps_addresses_with_their_interfaces(self, monkeypatch, capsys, color):
        monkeypatch.setattr(netlink, "_USE_COLOR", color)
        monkeypatch.setattr(netlink, "collect_iface", lambda name: make_iface(name))
        bond = {**make_bond(), "ipv4": ["192.0.2.10/24"]}
        single = {**make_iface("eth0", pci="0000:05:00.0"),
                  "ipv4": ["198.51.100.10/24", "198.51.100.11/24"]}
        long_ipv6 = "2001:db8:1234:5678:abcd:ef01:2345:6789/128"
        card_a = {**make_iface("eth1", pci="0000:06:00.0"), "ipv6": [long_ipv6]}
        card_b = make_iface("eth2", pci="0000:06:00.1")

        netlink.render_topology([bond], [single, card_a, card_b])
        rendered = strip(capsys.readouterr().out)
        assert rendered.index("BOND: bond0") < rendered.index("192.0.2.10/24") < rendered.index("SLAVES")
        assert rendered.index("NIC: eth0") < rendered.index("198.51.100.10/24") < rendered.index("CARD:")
        assert rendered.index("NIC: eth0") < rendered.index("198.51.100.11/24") < rendered.index("CARD:")
        assert rendered.index("NIC: eth1") < rendered.index(long_ipv6) < rendered.index("NIC: eth2")
        assert "ipv4:  N/A" in rendered and "ipv6:  N/A" in rendered
        for line in rendered.splitlines():
            if "ipv4:" in line or "ipv6:" in line:
                assert line[netlink.LEFT_W - 1] in "│║"
            if "►" in line:
                assert line[netlink.SWITCH_COL - 1:netlink.SWITCH_COL + 2] == "► ┌"


# ── switch box ────────────────────────────────────────────────────────────────

class TestSwitchBox:
    def box_lines(self, lldp=None) -> list[str]:
        return [strip(l) for l in netlink.make_switch_box(lldp or LLDP_OK)]

    def test_has_six_lines(self):
        assert len(self.box_lines()) == 6  # top + 4 rows + bottom

    def test_all_lines_same_width(self):
        lines = self.box_lines()
        widths = [len(l) for l in lines]
        assert len(set(widths)) == 1, f"unequal widths: {widths}"

    def test_top_bottom_use_box_chars(self):
        lines = self.box_lines()
        assert lines[0].startswith("┌") and lines[0].endswith("┐")
        assert lines[-1].startswith("└") and lines[-1].endswith("┘")

    def test_content_rows_closed_on_both_sides(self):
        lines = self.box_lines()
        for row in lines[1:-1]:
            assert row.startswith("│"), f"missing left border: {row!r}"
            assert row.endswith("│"), f"missing right border: {row!r}"

    def test_switch_value_present(self):
        lines = self.box_lines()
        combined = "\n".join(lines)
        assert "sw-rack01-leaf-01.example.net" in combined
        assert "192.0.2.1" in combined
        assert "25GE1/0/43" in combined
        assert "DemoSwitch DS6885-48Y8CQ" in combined

    def test_long_switch_name_does_not_misalign(self):
        lldp = {
            "switch":   "A" * 60,
            "mgmt":     "10.0.0.1",
            "port":     "Eth1/1",
            "sw_model": "Cisco",
        }
        lines = [strip(l) for l in netlink.make_switch_box(lldp)]
        widths = [len(l) for l in lines]
        assert len(set(widths)) == 1, f"long name misaligns box: {widths}"


# ── visual-length helpers ─────────────────────────────────────────────────────

class TestHelpers:
    def test_vlen_plain(self):
        assert netlink._vlen("hello") == 5

    def test_vlen_strips_ansi(self):
        s = "\033[1;32mhello\033[0m"
        assert netlink._vlen(s) == 5

    def test_ljust_plain(self):
        result = netlink._ljust("hi", 10)
        assert len(result) == 10
        assert result == "hi        "

    def test_ljust_with_ansi(self):
        colored = "\033[32mhi\033[0m"   # visible width 2
        result = netlink._ljust(colored, 10)
        assert netlink._vlen(result) == 10


# ── _fill_close ───────────────────────────────────────────────────────────────

class TestFillClose:
    def test_output_visual_width_equals_LEFT_W(self):
        content = "╔══ BOND: bond0   ● up "
        result = strip(netlink._fill_close(content, "═", "╗"))
        assert len(result) == netlink.LEFT_W, f"got {len(result)}, want {netlink.LEFT_W}"

    def test_ends_with_close_char(self):
        result = strip(netlink._fill_close("╚", "═", "╝"))
        assert result.endswith("╝")

    def test_starts_with_content(self):
        result = strip(netlink._fill_close("┌─ NIC: eth0 ", "─", "┐"))
        assert result.startswith("┌─ NIC: eth0 ")


# ── Page two-column layout ────────────────────────────────────────────────────

class TestPage:
    def _make_page_with_lldp(self) -> netlink.Page:
        page = netlink.Page()
        page.add("line 0")
        page.add_lldp_anchor("", LLDP_OK)  # anchor at line 1
        page.add("line 2")
        return page

    def test_anchor_arrow_visual_width(self):
        page = self._make_page_with_lldp()
        arrow_line = strip(page._left[1])
        assert len(arrow_line) == netlink.SWITCH_COL, (
            f"arrow visual width {len(arrow_line)} ≠ SWITCH_COL {netlink.SWITCH_COL}"
        )

    def test_arrow_ends_with_arrowhead(self):
        page = self._make_page_with_lldp()
        assert strip(page._left[1]).endswith("►")

    def test_render_places_switch_box_on_anchor_line(self):
        page = self._make_page_with_lldp()
        rendered = strip(page.render())
        lines = rendered.splitlines()
        # line 1 is anchor → should contain switch box top (┌)
        assert "┌" in lines[1]

    def test_render_all_lines_left_padded_to_LEFT_W_when_box_present(self):
        page = self._make_page_with_lldp()
        rendered = page.render()
        for line in rendered.splitlines():
            # lines that contain a switch box character should have left panel at LEFT_W
            if "│" in strip(line)[netlink.LEFT_W:]:
                padded = strip(line)[:netlink.LEFT_W]
                assert len(padded) == netlink.LEFT_W

    def test_no_anchors_renders_plain(self):
        page = netlink.Page()
        page.add("hello")
        page.add("world")
        assert page.render() == "hello\nworld"


# ── render_standalone ─────────────────────────────────────────────────────────

class TestRenderStandalone:
    def _render(self, iface) -> list[str]:
        page = netlink.Page()
        netlink.render_standalone(page, iface)
        return [strip(l) for l in page._left]

    def test_top_line_starts_with_box_char(self):
        lines = self._render(make_iface())
        assert lines[0].startswith("┌")

    def test_top_line_ends_with_close_char(self):
        lines = self._render(make_iface())
        assert lines[0].endswith("┐")

    def test_top_line_visual_width(self):
        lines = self._render(make_iface())
        assert len(lines[0]) == netlink.LEFT_W

    def test_bottom_line_starts_and_ends(self):
        lines = self._render(make_iface(lldp=LLDP_NONE))
        bottom = lines[-1]
        assert bottom.startswith("└") and bottom.endswith("┘")

    def test_bottom_line_visual_width(self):
        lines = self._render(make_iface(lldp=LLDP_NONE))
        assert len(lines[-1]) == netlink.LEFT_W

    def test_nic_name_in_top_line(self):
        lines = self._render(make_iface(name="eth42"))
        assert "eth42" in lines[0]

    def test_down_state_shown(self):
        lines = self._render(make_iface(state="down"))
        combined = "\n".join(lines)
        assert "down" in combined

    def test_driver_present(self):
        combined = "\n".join(self._render(make_iface()))
        assert "test_driver" in combined

    def test_no_lldp_shows_message(self):
        combined = "\n".join(self._render(make_iface(lldp=LLDP_NONE)))
        assert "no neighbor" in combined


# ── render_bond (structural lines only) ──────────────────────────────────────

class TestRenderBond:
    def _render(self, bond, slaves) -> list[str]:
        page = netlink.Page()
        # patch collect_iface to return mock data
        original = netlink.collect_iface
        netlink.collect_iface = lambda name: make_iface(name=name)
        try:
            netlink.render_bond(page, bond)
        finally:
            netlink.collect_iface = original
        return [strip(l) for l in page._left]

    def test_top_line_starts_with_corner(self):
        lines = self._render(make_bond(), [make_iface("eno1"), make_iface("eno2")])
        assert lines[0].startswith("╔")

    def test_top_line_ends_with_corner(self):
        lines = self._render(make_bond(), [make_iface("eno1")])
        assert lines[0].endswith("╗")

    def test_top_line_visual_width(self):
        lines = self._render(make_bond(), [])
        assert len(lines[0]) == netlink.LEFT_W

    def test_bottom_line_closed(self):
        lines = self._render(make_bond(), [])
        bottom = lines[-1]
        assert bottom.startswith("╚") and bottom.endswith("╝")

    def test_slaves_separator_closed(self):
        lines = self._render(make_bond(), [])
        slaves_line = next(l for l in lines if "SLAVES" in l)
        assert slaves_line.endswith("╣")

    def test_bond_name_in_top_line(self):
        lines = self._render(make_bond(), [])
        assert "bond0" in lines[0]


# ── same-card grouping ────────────────────────────────────────────────────────

class TestSameCard:
    """NICs sharing the same PCIe card (same bus:device, different function)."""

    def _card_group_lines(self, ifaces: list) -> list[str]:
        page = netlink.Page()
        card_key = ifaces[0]["card_key"]
        netlink.render_card_group(page, card_key, ifaces)
        return [strip(l) for l in page._left]

    def test_card_group_header_contains_card_key(self):
        nic_a = make_iface("eth1", pci="0000:06:00.0")
        nic_b = make_iface("eth2", pci="0000:06:00.1")
        lines = self._card_group_lines([nic_a, nic_b])
        assert "CARD:" in lines[0] and "0000:06:00" in lines[0]

    def test_card_group_box_chars(self):
        nic_a = make_iface("eth1", pci="0000:06:00.0")
        nic_b = make_iface("eth2", pci="0000:06:00.1")
        lines = self._card_group_lines([nic_a, nic_b])
        assert lines[0].startswith("┌") and lines[0].endswith("┐")
        assert lines[-1].startswith("└") and lines[-1].endswith("┘")

    def test_card_group_contains_all_nic_names(self):
        nic_a = make_iface("eth1", pci="0000:06:00.0")
        nic_b = make_iface("eth2", pci="0000:06:00.1")
        combined = "\n".join(self._card_group_lines([nic_a, nic_b]))
        assert "eth1" in combined
        assert "eth2" in combined

    def test_card_group_all_lines_left_w(self):
        # Use no-LLDP NICs so no anchor lines (which extend to SWITCH_COL) appear
        nic_a = make_iface("eth1", pci="0000:06:00.0", lldp=LLDP_NONE)
        nic_b = make_iface("eth2", pci="0000:06:00.1", lldp=LLDP_NONE)
        for line in self._card_group_lines([nic_a, nic_b]):
            assert len(line) == netlink.LEFT_W, f"width {len(line)} != {netlink.LEFT_W}: {line!r}"

    def test_single_nic_uses_standalone_not_card(self):
        """A single-port card uses the NIC standalone box, not a CARD group."""
        page = netlink.Page()
        netlink.render_standalone(page, make_iface("eth1", pci="0000:06:00.0"))
        lines = [strip(l) for l in page._left]
        assert "NIC:" in lines[0]
        assert "CARD:" not in lines[0]

    def test_bond_slaves_same_card_annotation(self):
        """Bond slaves on the same physical card show 'same card' in PCIe header."""
        bond = make_bond(slaves=("eno1", "eno2"))
        page = netlink.Page()
        original = netlink.collect_iface
        slave_map = {
            "eno1": make_iface("eno1", pci="0000:1a:00.0"),
            "eno2": make_iface("eno2", pci="0000:1a:00.1"),
        }
        netlink.collect_iface = lambda n: slave_map[n]
        try:
            netlink.render_bond(page, bond)
        finally:
            netlink.collect_iface = original
        lines = [strip(l) for l in page._left]
        pcie_lines = [l for l in lines if "PCIe" in l and "same card" in l]
        assert len(pcie_lines) == 2, "both slaves should show same-card note"
        assert all("same card" in l for l in pcie_lines)
