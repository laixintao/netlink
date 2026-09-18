#!/usr/bin/env python3
"""
netlink.py  –  PCIe / NIC / Bond / LLDP Topology
Python 3.10+, stdlib only.  Tip: pipe through  less -SR  for wide lines.
"""

import argparse
import json
import os
import re as _re
import shutil
import subprocess
import sys
from pathlib import Path


# ── color support ─────────────────────────────────────────────────────────────

_ANSI_RE = _re.compile(r'\033\[[0-9;]*m')
_USE_COLOR = False  # set in main()


def _vlen(s: str) -> int:
    """String length ignoring ANSI escape sequences."""
    return len(_ANSI_RE.sub('', s))


def _ljust(s: str, w: int) -> str:
    """Left-justify based on visible (non-ANSI) width."""
    return s + " " * max(0, w - _vlen(s))


def _a(s: str, *codes: int) -> str:
    if not _USE_COLOR or not s:
        return s
    return f"\033[{';'.join(map(str, codes))}m{s}\033[0m"


def dim(s: str)  -> str: return _a(s, 2)
def bold(s: str) -> str: return _a(s, 1)
def grn(s: str)  -> str: return _a(s, 32)
def cyn(s: str)  -> str: return _a(s, 36)
def mgn(s: str)  -> str: return _a(s, 35)
def bgrn(s: str) -> str: return _a(s, 1, 32)
def bred(s: str) -> str: return _a(s, 1, 31)
def bylw(s: str) -> str: return _a(s, 1, 33)
def bcyn(s: str) -> str: return _a(s, 1, 36)
def bwh(s: str)  -> str: return _a(s, 1, 37)


def ip_bg(s: str) -> str:
    return s if s == "N/A" else _a(s, 30, 46)  # black on cyan


def mac_bg(s: str) -> str:
    return s if s == "N/A" else _a(s, 30, 43)  # black on yellow


def _state(s: str) -> str:
    return bgrn("● up") if s == "up" else bred(f"○ {s}")


def _kv(k: str, v: str) -> str:
    """Dimmed key + normal value."""
    return f"{dim(k + ':')}  {v}"


# ── helpers ───────────────────────────────────────────────────────────────────

def run(*cmd: str) -> str:
    try:
        r = subprocess.run(list(cmd), capture_output=True, text=True, timeout=10)
        return r.stdout
    except Exception:
        return ""


def rf(path: str, default: str = "N/A") -> str:
    try:
        return Path(path).read_text().strip()
    except Exception:
        return default


def has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


# ── data collection ───────────────────────────────────────────────────────────

def collect_addresses(name: str) -> dict:
    addresses: dict[str, list[str]] = {"ipv4": [], "ipv6": []}
    if not has("ip"):
        return addresses

    try:
        data = json.loads(run("ip", "-j", "address", "show", "dev", name))
        for iface in data:
            for addr in iface.get("addr_info", []):
                family = {"inet": "ipv4", "inet6": "ipv6"}.get(addr.get("family"))
                local, prefix = addr.get("local"), addr.get("prefixlen")
                if family and local and prefix is not None:
                    addresses[family].append(f"{local}/{prefix}")
    except (ValueError, TypeError, AttributeError):
        pass
    return addresses


def collect_iface(name: str) -> dict:
    d: dict = {"name": name}
    d.update(collect_addresses(name))
    d["mac"]   = rf(f"/sys/class/net/{name}/address")
    d["state"] = rf(f"/sys/class/net/{name}/operstate")
    d["mtu"]   = rf(f"/sys/class/net/{name}/mtu")

    try:
        dev = os.readlink(f"/sys/class/net/{name}/device")
        d["pci"] = os.path.basename(dev)
    except OSError:
        d["pci"] = "N/A"

    pci = d["pci"]
    d["card_key"] = pci.rsplit(".", 1)[0] if (pci != "N/A" and "." in pci) else pci

    d["driver"] = d["speed"] = d["duplex"] = "N/A"
    if has("ethtool"):
        for line in run("ethtool", "-i", name).splitlines():
            k, _, v = line.partition(":")
            match k.strip():
                case "driver": d["driver"] = v.strip()
        for line in run("ethtool", name).splitlines():
            k, _, v = line.strip().partition(":")
            match k.strip():
                case "Speed":  d["speed"]  = v.strip()
                case "Duplex": d["duplex"] = v.strip()

    d["model"] = d["numa"] = d["lnkcap"] = d["lnksta"] = "N/A"
    if d["pci"] != "N/A" and has("lspci"):
        raw = run("lspci", "-s", d["pci"]).strip()
        if raw:
            d["model"] = raw.split(" ", 1)[1] if " " in raw else raw
        d["numa"] = rf(f"/sys/bus/pci/devices/{d['pci']}/numa_node")
        for line in run("lspci", "-vv", "-s", d["pci"]).splitlines():
            s = line.strip()
            if s.startswith("LnkCap:") and d["lnkcap"] == "N/A":
                d["lnkcap"] = s
            elif s.startswith("LnkSta:") and d["lnksta"] == "N/A":
                d["lnksta"] = s

    d["lldp"] = {"switch": "N/A", "mgmt": "N/A", "port": "N/A", "sw_model": "N/A"}
    if has("lldpcli"):
        try:
            data = json.loads(run("lldpcli", "show", "nei", "-f", "json"))
            ifaces = data.get("lldp", {}).get("interface", [])
            if isinstance(ifaces, dict):
                ifaces = [ifaces]
            for entry in ifaces:
                if name not in entry:
                    continue
                n = entry[name]
                ch_items = list(n.get("chassis", {}).items())
                if ch_items:
                    sysname, c = ch_items[0]
                    d["lldp"]["switch"] = sysname
                    mgmt = c.get("mgmt-ip", "N/A")
                    if isinstance(mgmt, list):
                        mgmt = ", ".join(mgmt)
                    d["lldp"]["mgmt"] = mgmt or "N/A"
                    descr = (c.get("descr") or "").replace("\r", "")
                    ls = [l for l in descr.split("\n") if l.strip()]
                    d["lldp"]["sw_model"] = ls[-1] if ls else "N/A"
                pid = n.get("port", {}).get("id", {})
                d["lldp"]["port"] = f"{pid.get('type','?')} {pid.get('value','?')}"
                break
        except Exception:
            pass

    return d


def collect_bond(name: str) -> dict:
    b: dict = {
        "name": name, "mode": "N/A", "hash": "N/A", "status": "N/A",
        "miimon": "N/A", "ports": "N/A", "partner": "N/A", "slaves": [],
    }
    b.update(collect_addresses(name))
    seen_mii = False
    for line in rf(f"/proc/net/bonding/{name}", "").splitlines():
        k, _, v = line.partition(":")
        v = v.strip()
        match k.strip():
            case "Bonding Mode":                  b["mode"]    = v
            case "Transmit Hash Policy":          b["hash"]    = v
            case "MII Status" if not seen_mii:
                b["status"] = v; seen_mii = True
            case "MII Polling Interval (ms)":     b["miimon"]  = v + " ms"
            case "Number of ports":               b["ports"]   = v
            case "Partner Mac Address":           b["partner"] = v
            case "Slave Interface":               b["slaves"].append(v)
    return b


# ── layout engine ─────────────────────────────────────────────────────────────

LEFT_W = 112  # width limit for verbose PCIe descriptions
SWITCH_GAP = 2  # shortest connector outside the left box: ─►


def _fill_close(content: str, fill: str, close: str, width: int = LEFT_W) -> str:
    """Pad content to (width - 1) visible chars with fill, append dim(close)."""
    n = max(0, width - _vlen(content) - 1)
    return content + dim(fill * n + close)


def _rclose(content: str, char: str, width: int = LEFT_W) -> str:
    """Pad a content line to width, placing dim(char) at the right edge."""
    n = max(0, width - _vlen(content) - 1)
    return content + " " * n + dim(char)


def make_switch_box(lldp: dict) -> list[str]:
    rows = [
        ("switch", lldp["switch"]),
        ("mgmt",   lldp["mgmt"]),
        ("port",   lldp["port"]),
        ("model",  lldp["sw_model"]),
    ]
    kw = max(len(k) for k, _ in rows)
    vw = max(len(v) for _, v in rows)
    iw = kw + 2 + vw

    border = grn
    lines  = [border("┌" + "─" * (iw + 2) + "┐")]
    for k, v in rows:
        val  = bylw(v) if k == "switch" else v
        if k == "mgmt":
            val = ip_bg(v)
        elif k == "port" and v.startswith("mac "):
            val = "mac " + mac_bg(v[4:])
        # key column: "key:" padded to kw+1 chars (colon included), then one space
        # value column: val padded to vw chars
        # total cell visual width = kw + 2 + vw = iw  ✓
        cell = f"{dim(k + ':')}{' ' * (kw - len(k) + 1)}{val}{' ' * (vw - len(v))}"
        lines.append(f"{border('│')} {cell} {border('│')}")
    lines.append(border("└" + "─" * (iw + 2) + "┘"))
    return lines


class Page:
    def __init__(self) -> None:
        self._left: list[str] = []
        self._borders: dict[int, tuple[str, str]] = {}
        self._arrow_borders: dict[int, str] = {}
        self._anchors: list[tuple[int, dict]] = []

    @property
    def left_w(self) -> int:
        """Fit the longest content line, leaving one space before the border."""
        return max((_vlen(line) + 2 for line in self._left), default=0)

    @property
    def switch_col(self) -> int:
        return self.left_w + SWITCH_GAP

    def add(self, line: str = "", rb: str = "", fill: str = " ") -> None:
        if rb:
            self._borders[len(self._left)] = (rb, fill)
        self._left.append(line)

    def add_lldp_anchor(self, prefix: str, lldp: dict, rb: str = "") -> None:
        """Record the LLDP label; size its connector after all content is known."""
        idx = len(self._left)
        self._left.append(prefix + cyn("└─ LLDP "))
        self._arrow_borders[idx] = rb
        self._anchors.append((idx, lldp))

    def left_lines(self) -> list[str]:
        width = self.left_w
        lines = []
        for i, line in enumerate(self._left):
            if i in self._arrow_borders:
                rb = self._arrow_borders[i]
                if rb:
                    n = width - _vlen(line) - 1
                    line += cyn("─" * n + rb + "─" * (SWITCH_GAP - 1) + "►")
                else:
                    n = width + SWITCH_GAP - _vlen(line) - 1
                    line += cyn("─" * n + "►")
            elif i in self._borders:
                rb, fill = self._borders[i]
                if fill == " ":
                    line = _rclose(line, rb, width)
                else:
                    line = _fill_close(line, fill, rb, width)
            lines.append(line)
        return lines

    def render(self) -> str:
        left_lines = self.left_lines()
        if not self._anchors:
            return "\n".join(left_lines)

        right: dict[int, str] = {}
        for anchor, lldp in self._anchors:
            for i, bl in enumerate(make_switch_box(lldp)):
                right[anchor + i] = bl

        total = max(len(left_lines), max(k + 1 for k in right))
        switch_col = self.switch_col
        out: list[str] = []
        for i in range(total):
            left = left_lines[i] if i < len(left_lines) else ""
            rbox = right.get(i)
            if rbox is not None:
                out.append(_ljust(left, switch_col) + " " + rbox)
            else:
                out.append(left)
        return "\n".join(out)


# ── renderers ─────────────────────────────────────────────────────────────────

def _render_addresses(page: Page, iface: dict, p: str, rb: str = "") -> None:
    for family in ("ipv4", "ipv6"):
        for address in iface.get(family) or ["N/A"]:
            line = f"{p}{_kv(family, ip_bg(address))}"
            page.add(line, rb=rb)


def _render_iface_body(page: Page, iface: dict, p: str, rb: str = "",
                       card_peers: tuple[str, ...] = ()) -> None:
    """
    p          –  continuation prefix, e.g. "║  │  " for a non-last bond slave.
    rb         –  right-border char ("║" inside bond, "│" inside standalone, "" = none).
                  LLDP arrows pass through this border to reach the switch box.
    card_peers –  names of other NICs that share the same physical PCIe card.
    """
    def add(line: str) -> None:
        page.add(line, rb=rb)

    add(f"{p}{_kv('mac', mac_bg(iface['mac']))}   "
        f"{_kv('speed', iface['speed'])}   "
        f"{_kv('duplex', iface['duplex'])}   "
        f"{_kv('mtu', iface['mtu'])}")
    _render_addresses(page, iface, p, rb)

    if card_peers:
        note = f"same card: {', '.join(card_peers)}"
        add(f"{p}{cyn('├─ PCIe')} {bylw(note)}")
    else:
        add(f"{p}{cyn('├─ PCIe')}")
    add(f"{p}{dim('│')}  {_kv('pci', iface['pci'])}   {_kv('numa', iface['numa'])}")
    add(f"{p}{dim('│')}  {_kv('driver', iface['driver'])}")
    # lspci -vv uses \t as field separator (e.g. "LnkCap:\tPort #0...").
    # \t counts as 1 in len() but expands to multiple columns in the terminal,
    # causing _rclose to place the border too far right. Replace with a space.
    # Use "..." not "…" — U+2026 is East-Asian-ambiguous-width (renders 2 cols on CJK terminals).
    def _clean(s: str) -> str:
        return s.replace('\t', ' ')

    # "│  model:  " overhead = │(1) + 2sp + model:(6) + 2sp = 11; +1 border
    _max_model = LEFT_W - len(p) - 12
    _model = _clean(iface['model'])
    if len(_model) > _max_model:
        _model = _model[:_max_model - 3] + "..."
    add(f"{p}{dim('│')}  {_kv('model', mgn(_model))}")

    # "│  " overhead = │(1) + 2sp = 3; +1 border
    _max_lnk = LEFT_W - len(p) - 4
    _lnkcap = _clean(iface['lnkcap'])
    _lnksta = _clean(iface['lnksta'])
    if len(_lnkcap) > _max_lnk:
        _lnkcap = _lnkcap[:_max_lnk - 3] + "..."
    if len(_lnksta) > _max_lnk:
        _lnksta = _lnksta[:_max_lnk - 3] + "..."
    add(f"{p}{dim('│')}  {dim(_lnkcap)}")
    add(f"{p}{dim('│')}  {dim(_lnksta)}")

    lldp = iface["lldp"]
    if lldp["switch"] != "N/A":
        page.add_lldp_anchor(p, lldp, rb)
    else:
        add(f"{p}{cyn('└─ LLDP')}  {dim('(no neighbor detected)')}")


def render_slave(page: Page, iface: dict, bp: str, last: bool, rb: str = "",
                 card_peers: tuple[str, ...] = ()) -> None:
    bar  = "└─" if last else "├─"
    cont = "   " if last else "│  "
    header = f"{dim(bp)}{cyn(bar)} {bcyn('NIC:')} {bwh(iface['name'])}   {_state(iface['state'])}"
    page.add(header, rb=rb)
    _render_iface_body(page, iface, bp + cont, rb=rb, card_peers=card_peers)


def render_bond(page: Page, bond: dict) -> None:
    RB = "║"
    header = f"{dim('╔══')} {bylw('BOND:')} {bwh(bond['name'])}   {_state(bond['status'])} "
    page.add(header, rb="╗", fill="═")
    _render_addresses(page, bond, f"{dim('║')}  ", RB)
    page.add(f"{dim('║')}  {_kv('mode',   bond['mode'])}", rb=RB)
    page.add(f"{dim('║')}  {_kv('hash',   bond['hash'])}", rb=RB)
    page.add(f"{dim('║')}  {_kv('miimon', bond['miimon'])}    {_kv('ports', bond['ports'])}", rb=RB)
    if bond["partner"] != "N/A":
        page.add(f"{dim('║')}  {_kv('partner', mac_bg(bond['partner']))}", rb=RB)
    page.add(dim("╠══ SLAVES "), rb="╣", fill="═")

    # Collect all slave ifaces first so we can compute card-sharing groups.
    ifaces = [collect_iface(name) for name in bond["slaves"]]
    card_groups: dict[str, list[str]] = {}
    for iface in ifaces:
        ck = iface.get("card_key", "N/A")
        if ck and ck != "N/A":
            card_groups.setdefault(ck, []).append(iface["name"])

    for i, iface in enumerate(ifaces):
        ck = iface.get("card_key", "N/A")
        peers = tuple(n for n in card_groups.get(ck, []) if n != iface["name"])
        page.add(dim("║"), rb=RB)
        render_slave(page, iface, "║  ", last=(i == len(ifaces) - 1), rb=RB, card_peers=peers)

    page.add(dim("╚"), rb="╝", fill="═")


def render_standalone(page: Page, iface: dict) -> None:
    header = f"{dim('┌─')} {bcyn('NIC:')} {bwh(iface['name'])}   {_state(iface['state'])}"
    page.add(header, rb="┐", fill="─")
    _render_iface_body(page, iface, "│  ", rb="│")
    page.add(dim("└"), rb="┘", fill="─")


def render_card_group(page: Page, card_key: str, ifaces: list[dict]) -> None:
    """Render multiple NICs sharing a physical PCIe card inside a shared CARD box."""
    CB = "│"
    header = f"{dim('┌─')} {cyn('CARD:')} {bwh(card_key)} "
    page.add(header, rb="┐", fill="─")
    for i, iface in enumerate(ifaces):
        page.add(dim("│"), rb=CB)
        render_slave(page, iface, "│  ", last=(i == len(ifaces) - 1), rb=CB)
    page.add(dim("│"), rb=CB)
    page.add(dim("└"), rb="┘", fill="─")


# ── topology renderer ─────────────────────────────────────────────────────────

def render_topology(bonds: list[dict], standalone_ifaces: list[dict]) -> None:
    """Render and print a full topology page from pre-collected data dicts."""
    page = Page()
    page.add()
    page.add(bold("  PCIe / NIC / Bond / LLDP  Topology"))
    page.add()

    if bonds:
        for bond in bonds:
            render_bond(page, bond)
            page.add()

    if standalone_ifaces:
        # Group NICs by physical card (card_key), preserving first-appearance order.
        # NICs without a valid card_key (no PCI device) stay as individual boxes.
        seen_keys: dict[str, int] = {}
        groups: list[list[dict]] = []
        for iface in standalone_ifaces:
            ck = iface.get("card_key", "N/A")
            group_key = ck if (ck and ck != "N/A") else f"\x00{iface['name']}"
            if group_key not in seen_keys:
                seen_keys[group_key] = len(groups)
                groups.append([])
            groups[seen_keys[group_key]].append(iface)

        for group in groups:
            if len(group) > 1:
                render_card_group(page, group[0]["card_key"], group)
            else:
                render_standalone(page, group[0])
            page.add()

    print(page.render())


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="PCIe / NIC / Bond / LLDP Topology. Tip: pipe through  less -SR  for wide lines."
    )
    parser.add_argument("--color", action="store_true",
                        help="force color output even when stdout is not a TTY (e.g. when piping to less)")
    args = parser.parse_args()

    if sys.platform != "linux":
        sys.exit(f"error: this tool reads /proc and /sys — Linux only (got {sys.platform})")

    global _USE_COLOR
    _USE_COLOR = args.color or (sys.stdout.isatty() and "NO_COLOR" not in os.environ)

    bond_slaves: set[str] = set()
    bonds: list[dict] = []
    bond_dir = Path("/proc/net/bonding")

    if bond_dir.exists():
        for bname in sorted(f.name for f in bond_dir.iterdir() if f.is_file()):
            bond = collect_bond(bname)
            bond_slaves.update(bond["slaves"])
            bonds.append(bond)

    net_dir = Path("/sys/class/net")
    standalone_ifaces = [
        collect_iface(p.name)
        for p in sorted(net_dir.iterdir(), key=lambda p: p.name)
        if p.name not in ("lo",)
        and not (net_dir / p.name / "bonding").is_dir()
        and not (net_dir / p.name / "master").is_symlink()
        and (net_dir / p.name / "device").exists()
        and p.name not in bond_slaves
    ]

    render_topology(bonds, standalone_ifaces)


if __name__ == "__main__":
    main()
