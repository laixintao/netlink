#!/usr/bin/env python3
"""
netlink.py  –  PCIe / NIC / Bond / LLDP Topology
Python 3.10+, stdlib only.  Tip: pipe through  less -SR  for wide lines.
"""

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

def collect_iface(name: str) -> dict:
    d: dict = {"name": name}
    d["mac"]   = rf(f"/sys/class/net/{name}/address")
    d["state"] = rf(f"/sys/class/net/{name}/operstate")
    d["mtu"]   = rf(f"/sys/class/net/{name}/mtu")

    try:
        dev = os.readlink(f"/sys/class/net/{name}/device")
        d["pci"] = os.path.basename(dev)
    except OSError:
        d["pci"] = "N/A"

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

LEFT_W    = 112  # visible-character width of left panel (box borders land here)
SWITCH_COL = LEFT_W + 24  # column where switch boxes start (arrow extends this far)


def _fill_close(content: str, fill: str, close: str) -> str:
    """Pad content to (LEFT_W - 1) visible chars with fill, append dim(close)."""
    n = max(0, LEFT_W - _vlen(content) - 1)
    return content + dim(fill * n + close)


def _rclose(content: str, char: str) -> str:
    """Pad a content line to LEFT_W, placing dim(char) at the right edge."""
    n = max(0, LEFT_W - _vlen(content) - 1)
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
        self._anchors: list[tuple[int, dict]] = []

    def add(self, line: str = "") -> None:
        self._left.append(line)

    def add_lldp_anchor(self, prefix: str, lldp: dict) -> None:
        """Emit LLDP arrow line and record right-panel anchor."""
        idx = len(self._left)
        label = "└─ LLDP "
        vbase = _vlen(prefix) + len(label)
        ndash = max(2, SWITCH_COL - vbase - 1)       # extend to SWITCH_COL
        arrow = prefix + cyn(label + "─" * ndash + "►")
        self._left.append(arrow)
        self._anchors.append((idx, lldp))

    def render(self) -> str:
        if not self._anchors:
            return "\n".join(self._left)

        right: dict[int, str] = {}
        for anchor, lldp in self._anchors:
            for i, bl in enumerate(make_switch_box(lldp)):
                right[anchor + i] = bl

        total = max(len(self._left), max(k + 1 for k in right))
        out: list[str] = []
        for i in range(total):
            left = self._left[i] if i < len(self._left) else ""
            rbox = right.get(i)
            if rbox is not None:
                out.append(_ljust(left, SWITCH_COL) + " " + rbox)
            else:
                out.append(left)
        return "\n".join(out)


# ── renderers ─────────────────────────────────────────────────────────────────

def _render_iface_body(page: Page, iface: dict, p: str, rb: str = "") -> None:
    """
    p   –  continuation prefix, e.g. "║  │  " for a non-last bond slave.
    rb  –  right-border char ("║" inside bond, "│" inside standalone, "" = none).
           LLDP anchor lines never get rb: the arrow ► acts as the exit point.
    """
    def R(line: str) -> str:
        return _rclose(line, rb) if rb else line

    page.add(R(f"{p}{_kv('mac', iface['mac'])}   "
               f"{_kv('speed', iface['speed'])}   "
               f"{_kv('duplex', iface['duplex'])}   "
               f"{_kv('mtu', iface['mtu'])}"))

    page.add(R(f"{p}{cyn('├─ PCIe')} {'─' * 80}"))
    page.add(R(f"{p}{dim('│')}  {_kv('pci', iface['pci'])}   {_kv('numa', iface['numa'])}"))
    page.add(R(f"{p}{dim('│')}  {_kv('driver', iface['driver'])}"))
    # "│  model:  " overhead = 1+2+6+2 = 11 visible chars; +1 for right border
    # Use "..." (3 ASCII chars) not "…" — U+2026 is East-Asian-ambiguous-width
    # and renders as 2 columns on CJK-configured terminals.
    _max_model = LEFT_W - len(p) - 12
    _model = iface['model']
    if len(_model) > _max_model:
        _model = _model[:_max_model - 3] + "..."
    page.add(R(f"{p}{dim('│')}  {_kv('model', mgn(_model))}"))
    page.add(R(f"{p}{dim('│')}  {dim(iface['lnkcap'])}"))
    page.add(R(f"{p}{dim('│')}  {dim(iface['lnksta'])}"))

    lldp = iface["lldp"]
    if lldp["switch"] != "N/A":
        page.add_lldp_anchor(p, lldp)   # arrow replaces right border
    else:
        page.add(R(f"{p}{cyn('└─ LLDP')}  {dim('(no neighbor detected)')}"))


def render_slave(page: Page, iface: dict, bp: str, last: bool, rb: str = "") -> None:
    bar  = "└─" if last else "├─"
    cont = "   " if last else "│  "
    header = f"{dim(bp)}{cyn(bar)} {bcyn('NIC:')} {bwh(iface['name'])}   {_state(iface['state'])}"
    page.add(_rclose(header, rb) if rb else header)
    _render_iface_body(page, iface, bp + cont, rb=rb)


def render_bond(page: Page, bond: dict) -> None:
    RB = "║"
    header = f"{dim('╔══')} {bylw('BOND:')} {bwh(bond['name'])}   {_state(bond['status'])} "
    page.add(_fill_close(header, "═", "╗"))
    page.add(_rclose(f"{dim('║')}  {_kv('mode',   bond['mode'])}", RB))
    page.add(_rclose(f"{dim('║')}  {_kv('hash',   bond['hash'])}", RB))
    page.add(_rclose(f"{dim('║')}  {_kv('miimon', bond['miimon'])}    {_kv('ports', bond['ports'])}", RB))
    if bond["partner"] != "N/A":
        page.add(_rclose(f"{dim('║')}  {_kv('partner', bond['partner'])}", RB))
    page.add(_fill_close(dim("╠══ SLAVES "), "═", "╣"))

    for i, slave_name in enumerate(bond["slaves"]):
        iface = collect_iface(slave_name)
        page.add(_rclose(dim("║"), RB))
        render_slave(page, iface, "║  ", last=(i == len(bond["slaves"]) - 1), rb=RB)

    page.add(_fill_close(dim("╚"), "═", "╝"))


def render_standalone(page: Page, iface: dict) -> None:
    header = f"{dim('┌─')} {bcyn('NIC:')} {bwh(iface['name'])}   {_state(iface['state'])}"
    page.add(_fill_close(header, "─", "┐"))
    _render_iface_body(page, iface, "│  ", rb="│")
    page.add(_fill_close(dim("└"), "─", "┘"))


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
        for iface in standalone_ifaces:
            render_standalone(page, iface)
            page.add()

    print(page.render())


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if sys.platform != "linux":
        sys.exit(f"error: this tool reads /proc and /sys — Linux only (got {sys.platform})")

    global _USE_COLOR
    _USE_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ

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
