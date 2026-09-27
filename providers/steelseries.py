"""SteelSeries wireless headsets (Arctis Nova 7 and Nova 5 families), directly
over USB/HID, without SteelSeries GG. Works alongside GG.

Protocol (model list and reply layouts as documented by Sapd/HeadsetControl):
  * output report 00 b0 on interface 3 (usage page 0xFFC0) of the dongle
  * Nova 7 reply:  b0 <link> <battery> <status> ...
      link 03 = headset connected, 02 = not connected (Linux driver; seen on a 22A1:
      while the headset is off or still switching on, the dongle repeats the last
      battery value, and only the link byte shows it)
      battery 0..100, or 0..4 on the original firmware
      status 00 = headset off / out of range, 01 / 02 = charging, 03 = on battery
  * Nova 5 / Nova 3P reply:  b0 <status> <?> <battery 0..100> <charging> ...
      status 02 = headset off / out of range, charging 01 = charging
  * Arctis 7+ reply:  b0 <status> <battery 0..4> <charging> ...
      status 01 = headset off, charging 01 = charging
  * GameBuds reply:  b0 <?> <?> <left status> <right status> <left %> <right %> ...
      status 03 = bud out of the case; a bud in the case reports 0 %, so it is ignored
  * other reports can arrive on the same interface; the b0 reply is picked out, and the
   parsers insist on it, so anything else the dongle sends yields no reading at all
   (without that check a stray report reads as a level: `01 00 63 02` as 99%)

Mouse battery (Rival 3 Wireless and family), from yurtemre7/steel-mouse:
  * same interface 3 and the same ffc0 collection, but a different exchange:
    a 64-byte request 00 aa 01 ... and a reply that echoes the command: aa <level> ...
  * a report on that interface which does not carry the aa echo is skipped, as
    steel-mouse does (they used to read as a fixed 85% / 100%)
  * steel-mouse accepts a reply with the aa echo present, while its decoder and unit
    tests read the level with no echo at all. The offsets here follow the echo, so
    they are not confirmed on hardware: a level above 100 is refused rather than
    shown, and the raw reply is logged, so a probe settles the layout
  * SteelSeries GG reads the same collection, so both can run side by side

Older Arctis headsets (Arctis 1, 7, 9, Pro Wireless) use other requests on other
interfaces: see CLASSIC_MODELS further down.

The Arctis Nova Pro Omni (base station 1038:2290) has a protocol of its own, with the
level of the spare battery charging in the base station next to the headset's: see
OMNI_MODELS further down.

New models go into MODELS (headsets on the b0 exchange), MOUSE_MODELS (mice),
CLASSIC_MODELS (older headsets) or OMNI_MODELS: product id -> (name, parser ...).
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Tuple

import hid

from . import hidlist
from .base import DeviceStatus, Provider, hexdump, log

STEELSERIES_VID = 0x1038
INTERFACE = 3
VENDOR_USAGE_PAGE = 0xFFC0       # the configuration collection, whatever interface it is on
REQUEST = [0x00, 0xB0]
TIMEOUT = 1.0

Reading = Tuple[Optional[int], bool, bool]   # level, charging, online


def parse_nova7(r) -> Reading:
    # the link byte must say "connected": the battery byte keeps its old value while
    # the headset is off, so without this check an old level shows as a live one
    if len(r) < 4 or r[0] != 0xB0 or r[1] != 0x03 or r[3] == 0x00:
        return None, False, False
    return min(r[2], 100), r[3] in (0x01, 0x02), True


def parse_nova7_discrete(r) -> Reading:
    level, chg, online = parse_nova7(r)
    return (None if level is None else min(level, 4) * 25), chg, online


def parse_nova5(r) -> Reading:
    if len(r) < 5 or r[0] != 0xB0 or r[1] == 0x02:
        return None, False, False
    return min(r[3], 100), r[4] == 0x01, True


def parse_arctis7_plus(r) -> Reading:
    """Arctis 7+: b0 <status> <level 0..4> <charging>. Status 01 = headset off."""
    if len(r) < 4 or r[0] != 0xB0 or r[1] == 0x01:
        return None, False, False
    return min(r[2], 4) * 25, r[3] == 0x01, True


def parse_gamebuds(r) -> Reading:
    """Arctis GameBuds: the lower level of the buds that are out of the case."""
    if len(r) < 7 or r[0] != 0xB0:
        return None, False, False
    levels = [r[5 + i] for i in (0, 1) if r[3 + i] == 0x03]
    if not levels:                        # both buds are in the case (or off)
        return None, False, False
    return min(min(levels), 100), False, True


# tested on hardware: 22A1. The others follow HeadsetControl's device list.
MODELS = {
    0x22A1: ("Arctis Nova 7", parse_nova7),
    0x2202: ("Arctis Nova 7", parse_nova7_discrete),
    0x227E: ("Arctis Nova 7 Gen 2", parse_nova7),
    0x2206: ("Arctis Nova 7x", parse_nova7_discrete),
    0x2258: ("Arctis Nova 7x", parse_nova7),
    0x229E: ("Arctis Nova 7x", parse_nova7),
    0x22AD: ("Arctis Nova 7x", parse_nova7),
    0x22A4: ("Arctis Nova 7X", parse_nova7_discrete),
    0x22A5: ("Arctis Nova 7X", parse_nova7),
    0x223A: ("Arctis Nova 7 Diablo IV", parse_nova7_discrete),
    0x22A9: ("Arctis Nova 7 Diablo IV", parse_nova7),
    0x227A: ("Arctis Nova 7 WoW Edition", parse_nova7_discrete),
    0x2232: ("Arctis Nova 5", parse_nova5),
    0x2253: ("Arctis Nova 5X", parse_nova5),
    0x220A: ("Arctis Nova 7P", parse_nova7_discrete),
    0x22A7: ("Arctis Nova 7P", parse_nova7),
    0x2298: ("Arctis Nova 7P", parse_nova7),
    0x2269: ("Arctis Nova 3P Wireless", parse_nova5),
    0x226D: ("Arctis Nova 3X Wireless", parse_nova5),
    0x220E: ("Arctis 7+", parse_arctis7_plus),
    0x2212: ("Arctis 7+ PS5", parse_arctis7_plus),
    0x2216: ("Arctis 7+ Xbox", parse_arctis7_plus),
    0x2236: ("Arctis 7+ Destiny", parse_arctis7_plus),
    0x230A: ("Arctis GameBuds", parse_gamebuds),
}


MOUSE_REQUEST = [0x00, 0xAA, 0x01]
MOUSE_ECHO = 0xAA
MOUSE_WRITE_ATTEMPTS = 3
MOUSE_READ_ATTEMPTS = 6
MOUSE_READ_TIMEOUT_MS = 100


def parse_rival3(r) -> Reading:
    """Rival 3 Wireless: either aa <level> <?> <charging> ... or <level> <?> <charging>.

    The two references disagree and neither has been confirmed on hardware here:

      * yurtemre7/steel-mouse reads a reply that echoes the aa command - level in byte 1,
        charging in byte 3 - although its own decoder and tests expect no echo at all
      * flozz/rivalcfg sends the same request and then reads 3 bytes with hidapi exactly as
        this provider does, taking the level in byte 0 and charging in byte 2; the same
        layout is in its Rival 3 Wireless Gen 2 and Rival 650 profiles

    Both are accepted, so the mouse works whichever is right:

      * a leading report id byte of 0x00 is skipped
      * if the next byte is the aa echo, the level and the charging flag follow it
      * otherwise the reply is read the rivalcfg way - level first - but only when the
        charging byte is 0 or 1, so a stray report on the collection cannot pass as a level
      * a level above 100 is refused in both shapes

    The diagnostics print the raw reply, so which shape the mouse actually sends is visible
    in a probe.
    """
    if not r:
        return None, False, False
    m = 1 if r[0] == 0x00 and len(r) > 1 else 0
    if len(r) >= m + 4 and r[m] == MOUSE_ECHO:
        level = r[m + 1]
        if not 0 <= level <= 100:
            return None, False, False
        return level, r[m + 3] != 0, True
    if len(r) >= m + 3:
        level, charging = r[m], r[m + 2]
        if 0 <= level <= 100 and charging in (0, 1):
            return level, charging == 1, True
    return None, False, False


# Rival 3 Wireless / Rival 650 exchange, as listed by steel-mouse. None of these has
# been on hardware here; the reply layout is the open question in issue #5.
MOUSE_MODELS = {
    0x1830: ("SteelSeries Rival 3 Wireless", parse_rival3),
    0x1872: ("SteelSeries Rival 3 Wireless Gen 2", parse_rival3),
}


# ---------------------------------------------------------------- older Arctis headsets
# These headsets use other requests on other interfaces. Model list, requests and
# layouts come from HeadsetControl. The echo checks and the Arctis 7 connection query
# come from the Linux driver (drivers/hid/hid-steelseries-arctis.c).
#
# An exchange gets a function `ask(request, accept)`. ask() writes the request and
# returns the first reply for which accept(reply) is true, or None. So a report that
# is not the answer is never read as a level.

Ask = Callable[[List[int], Callable[[List[int]], bool]], Optional[List[int]]]


def _echo(a: int, b: int) -> Callable[[List[int]], bool]:
    """Accept a reply that starts with the two request bytes."""
    return lambda r: len(r) >= 4 and r[0] == a and r[1] == b


def exchange_arctis1(ask: Ask) -> Reading:
    """06 12 -> 06 12 <status> <level>. Status 01 = headset off. No charging flag."""
    r = ask([0x06, 0x12], _echo(0x06, 0x12))
    if r is None or r[2] == 0x01:
        return None, False, False
    return min(r[3], 100), False, True


def exchange_arctis7_2018(ask: Ask) -> Reading:
    """06 14 -> 06 14 <link>, link 03 = connected; then 06 18 -> 06 18 <level>."""
    r = ask([0x06, 0x14], _echo(0x06, 0x14))
    if r is None or r[2] != 0x03:
        return None, False, False
    r = ask([0x06, 0x18], _echo(0x06, 0x18))
    if r is None:
        return None, False, False
    return min(r[2], 100), False, True       # "sometimes overreports": capped (Linux)


def exchange_arctis7(ask: Ask) -> Reading:
    """06 18 -> 06 18 <level>. No connection query is documented for these models;
    the level reads 0 while the headset is off (Linux), so 0 means no reading."""
    r = ask([0x06, 0x18], _echo(0x06, 0x18))
    if r is None or r[2] == 0:
        return None, False, False
    return min(r[2], 100), False, True


def exchange_arctis9(ask: Ask) -> Reading:
    """00 20 -> aa 01 <?> <raw level> <charging>. Any other reply = headset off
    (Linux: 55 = no status, 03 = old status). Raw level 0x64..0x9A -> 0..100 %."""
    r = ask([0x00, 0x20], lambda r: len(r) >= 5 and r[0] in (0xAA, 0x55))
    if r is None or r[0] != 0xAA or r[1] != 0x01:
        return None, False, False
    raw = min(max(r[3], 0x64), 0x9A)
    return (raw - 0x64) * 100 // (0x9A - 0x64), r[4] == 0x01, True


def exchange_pro_wireless(ask: Ask) -> Reading:
    """41 aa -> <state>, state 02 = headset off, 04 = on; then 40 aa -> <level 0..4>.
    The replies do not echo the request, so only the documented values are accepted."""
    r = ask([0x41, 0xAA] + [0x00] * 29, lambda r: len(r) >= 1 and r[0] in (0x02, 0x04))
    if r is None or r[0] == 0x02:
        return None, False, False
    r = ask([0x40, 0xAA] + [0x00] * 29, lambda r: len(r) >= 1 and r[0] <= 4)
    if r is None:
        return None, False, False
    return r[0] * 25, False, True


# product id -> (name, interface, usage page or None, exchange). Only the vendor
# collections (usage page 0xFF00 and above) of that interface ever get a request.
# The Arctis Pro GameDAC (1280) is left out: it is a wired headset with no battery.
CLASSIC_MODELS: Dict[int, Tuple[str, int, Optional[int], Callable[[Ask], Reading]]] = {
    0x12B3: ("Arctis 1 Wireless", 3, 0xFF43, exchange_arctis1),
    0x12B6: ("Arctis 1 Wireless Xbox", 3, 0xFF43, exchange_arctis1),
    0x12D7: ("Arctis 7X", 3, 0xFF43, exchange_arctis1),
    0x12D5: ("Arctis 7P", 3, 0xFF43, exchange_arctis1),
    0x12AD: ("Arctis 7", 5, None, exchange_arctis7_2018),
    0x1260: ("Arctis 7", 5, None, exchange_arctis7),
    0x1252: ("Arctis Pro Wireless 2019", 5, None, exchange_arctis7),
    0x12C2: ("Arctis 9", 0, None, exchange_arctis9),
    0x1290: ("Arctis Pro Wireless", 0, None, exchange_pro_wireless),
}


# ---------------------------------------------------------------- Arctis Nova Pro Omni
# Layout from loteran/Arctis-Sound-Manager (nova_pro_omni.yaml), which checked it
# against a USBPcap capture of SteelSeries GG and GG's own device specification:
#   * interface 3 of the base station; it has no interrupt OUT endpoint, so the
#     request goes out as an output report with report id 01 (the base station
#     ignores a request under another report id)
#   * request 01 b0, reply 01 b0 ... with
#       byte 6  headset battery, 0..100
#       byte 7  spare battery in the base station's charging slot, 0..100
#       byte 14 radio link: 01 not paired, 02 searching, 04 paired but off, 08 connected
#       byte 15 charging: 02 charging, 04 plugged in but not charging, 08 on battery
#   * the base station also pushes events prefixed 07 on the same endpoint; they are
#     skipped
# The base station has a USB-1 / USB-2 / XBOX switch and only answers on USB-1. In the
# other positions it enumerates with another product id and stays silent.
OMNI_INTERFACE = 3
OMNI_REQUEST = [0x01, 0xB0]
OMNI_LINK_CONNECTED = 0x08
OMNI_CHARGING = 0x02

OmniReading = Tuple[Optional[int], bool, bool, Optional[int]]   # + spare battery level

OMNI_MODELS = {
    0x2290: "Arctis Nova Pro Omni",
}
OMNI_SILENT = {
    0x2292: "USB-2",
    0x2293: "XBOX",
}


def is_omni_status(r) -> bool:
    return len(r) >= 16 and r[0] == 0x01 and r[1] == 0xB0


def parse_nova_pro_omni(r) -> OmniReading:
    """01 b0 reply -> (headset level, charging, online, spare battery level)."""
    if not is_omni_status(r) or r[14] != OMNI_LINK_CONNECTED or r[6] > 100:
        return None, False, False, None
    spare = r[7] if r[7] <= 100 else None
    return r[6], r[15] == OMNI_CHARGING, True, spare


class SteelSeriesProvider(Provider):
    name = "steelseries"

    def __init__(self):
        self._diag: List[str] = []
        self._classic_path: Dict[int, bytes] = {}   # pid -> the collection that answered

    def _pick(self, infos: List[dict]) -> Optional[dict]:
        """The configuration collection of one device, picked by usage page.

        Not by interface number: the Rival 650 exposes it on interface 0 (rivalcfg's profile
        says endpoint 0, and rivalcfg issue #202 is about needing the usage page to find it
        dependably - "the luck of the draw" without it), so filtering on interface 3 skips
        that mouse altogether. When the page appears more than once, the collection on
        interface 3 wins, which is where the Nova headsets and the Rival 3 have it, so their
        path is unchanged.
        """
        mine = [d for d in infos
                if (d.get("usage_page"), d.get("usage")) == (VENDOR_USAGE_PAGE, 0x0001)]
        if not mine:
            offered = ", ".join(f"{d.get('usage_page', 0):04x}:{d.get('usage', 0):04x}"
                                for d in infos)
            self._diag.append(f"  no usage {VENDOR_USAGE_PAGE:04x}:0001 collection "
                              f"(found: {offered})")
            return None
        for d in mine:
            if d.get("interface_number") == INTERFACE:
                return d
        return mine[0]

    def _read(self, path: bytes) -> Optional[List[int]]:
        dev = hid.device()
        try:
            dev.open_path(path)
        except (OSError, IOError) as e:
            self._diag.append(f"  open: {e}")
            return None
        try:
            dev.write(REQUEST)
            first = None
            end = time.time() + TIMEOUT
            while time.time() < end:
                r = dev.read(64, 100)
                if not r:
                    continue
                if r[0] == 0xB0:
                    self._diag.append(f"  reply: {hexdump(r, 8)}")
                    return list(r)
                first = first or list(r)
            if first:                         # no b0 report: take what came, as HeadsetControl does
                self._diag.append(f"  reply (not b0): {hexdump(first, 8)}")
            else:
                self._diag.append("  no reply")
            return first
        except (OSError, IOError, ValueError) as e:
            self._diag.append(f"  error: {e}")
            return None
        finally:
            try:
                dev.close()
            except Exception:
                pass

    def _read_mouse(self, path: bytes, parse=None) -> Optional[List[int]]:
        """00 aa 01 out, then the first report the model's parser accepts.

        A report carrying the aa echo is taken straight away. Otherwise the parser judges
        it, so a layout that does not echo the command still works - which is what
        flozz/rivalcfg describes for the Rival 3 - while the interface's other traffic is
        refused. Up to three rounds are tried, as steel-mouse does.
        """
        dev = hid.device()
        try:
            dev.open_path(path)
        except (OSError, IOError) as e:
            self._diag.append(f"  open: {e}")
            return None
        try:
            for _ in range(MOUSE_WRITE_ATTEMPTS):
                try:
                    dev.write(MOUSE_REQUEST + [0x00] * 61)   # 64 bytes, as steel-mouse sends
                except (OSError, IOError, ValueError) as e:
                    self._diag.append(f"  write: {e}")
                    continue
                for _ in range(MOUSE_READ_ATTEMPTS):
                    r = list(dev.read(64, MOUSE_READ_TIMEOUT_MS) or [])
                    if not r:
                        continue
                    if r[0] == MOUSE_ECHO or (r[0] == 0x00 and len(r) > 1 and r[1] == MOUSE_ECHO):
                        self._diag.append(f"  reply (aa echo): {hexdump(r, 8)}")
                        return r
                    if parse is not None and parse(r)[2]:
                        self._diag.append(f"  reply (no aa echo, read the way rivalcfg "
                                          f"does): {hexdump(r, 8)}")
                        return r
                    self._diag.append(f"  reply (no aa echo): {hexdump(r, 8)}")
                    break
            self._diag.append("  no reply with the aa echo")
            return None
        except (OSError, IOError, ValueError) as e:
            self._diag.append(f"  error: {e}")
            return None
        finally:
            try:
                dev.close()
            except Exception:
                pass

    def poll(self) -> List[DeviceStatus]:
        self._diag = []
        try:
            infos = hidlist.enumerate(STEELSERIES_VID)
        except Exception as e:  # pragma: no cover
            log.warning("hid.enumerate(steelseries): %s", e)
            return []
        out = []
        for pid in sorted({d["product_id"] for d in infos}):
            if pid not in MOUSE_MODELS and pid not in MODELS:
                continue
            mine = [d for d in infos if d["product_id"] == pid]
            d = self._pick(mine)
            if d is None:
                continue
            if pid in MOUSE_MODELS:
                name, parse = MOUSE_MODELS[pid]
                self._diag.append(f"[SteelSeries] pid={pid:04x} '{name}' (mouse)")
                level, chg, online = parse(self._read_mouse(d["path"], parse) or [])
                if online and level is not None:
                    out.append(DeviceStatus(f"steelseries:{pid:04x}", name, level, chg, True,
                                            "steelseries", kind="mouse"))
                continue
            if pid not in MODELS or d.get("usage_page") != 0xFFC0:
                continue
            name, parse = MODELS[pid]
            self._diag.append(f"[SteelSeries] pid={pid:04x} '{name}'")
            level, chg, online = parse(self._read(d["path"]) or [])
            if online and level is not None:
                out.append(DeviceStatus(f"steelseries:{pid:04x}", name, level, chg, True,
                                        "steelseries", kind="headset"))
        out += self._poll_classic(infos)
        out += self._poll_omni(infos)
        return out

    def _run_exchange(self, path: bytes, exchange: Callable[[Ask], Reading]):
        """Open one collection and run an exchange on it.
        -> (reading, answered): answered is True if any request got an accepted reply."""
        dev = hid.device()
        try:
            dev.open_path(path)
        except (OSError, IOError) as e:
            self._diag.append(f"  open: {e}")
            return (None, False, False), False
        answered = []

        def ask(request, accept):
            dev.write(request)
            end = time.time() + TIMEOUT
            while time.time() < end:
                r = list(dev.read(64, 100) or [])
                if r and accept(r):
                    self._diag.append(f"  {hexdump(request, 2)} -> {hexdump(r, 8)}")
                    answered.append(True)
                    return r
            self._diag.append(f"  {hexdump(request, 2)} -> no reply")
            return None

        try:
            return exchange(ask), bool(answered)
        except (OSError, IOError, ValueError) as e:
            self._diag.append(f"  error: {e}")
            return (None, False, False), bool(answered)
        finally:
            try:
                dev.close()
            except Exception:
                pass

    def _poll_classic(self, infos: List[dict]) -> List[DeviceStatus]:
        out = []
        for pid, (name, iface, page, exchange) in CLASSIC_MODELS.items():
            paths = [d["path"] for d in infos
                     if d["product_id"] == pid and d.get("interface_number") == iface
                     and (d.get("usage_page") == page if page
                          else (d.get("usage_page") or 0) >= 0xFF00)]
            if not paths:
                continue
            self._diag.append(f"[SteelSeries] pid={pid:04x} '{name}'")
            # once a collection has answered, ask only that one
            known = self._classic_path.get(pid)
            for path in ([known] if known in paths else paths):
                (level, chg, online), answered = self._run_exchange(path, exchange)
                if answered:
                    self._classic_path[pid] = path
                    if online and level is not None:
                        out.append(DeviceStatus(f"steelseries:{pid:04x}", name, level, chg, True,
                                                "steelseries", kind="headset"))
                    else:
                        self._diag.append("  the headset is off or out of range")
                    break
        return out

    def _poll_omni(self, infos: List[dict]) -> List[DeviceStatus]:
        out = []
        pids = {d["product_id"] for d in infos}
        for pid, position in OMNI_SILENT.items():
            if pid in pids:
                self._diag.append(f"[SteelSeries] pid={pid:04x} Arctis Nova Pro Omni with the "
                                  f"base station switch on {position}: it only answers on "
                                  f"USB-1, so the battery cannot be read")
        for pid, name in OMNI_MODELS.items():
            # vendor collections only, 0xFFC0 first
            paths = [d["path"] for d in sorted(
                (d for d in infos if d["product_id"] == pid
                 and d.get("interface_number") == OMNI_INTERFACE
                 and (d.get("usage_page") or 0) >= 0xFF00),
                key=lambda d: d.get("usage_page") != VENDOR_USAGE_PAGE)]
            if not paths:
                if pid in pids:
                    self._diag.append(f"[SteelSeries] pid={pid:04x} '{name}': no vendor "
                                      f"collection on interface {OMNI_INTERFACE}")
                continue
            self._diag.append(f"[SteelSeries] pid={pid:04x} '{name}'")
            known = self._classic_path.get(pid)
            for path in ([known] if known in paths else paths):
                reply: List[List[int]] = []

                def exchange(ask):
                    r = ask(OMNI_REQUEST, is_omni_status)
                    if r is not None:
                        reply.append(r)
                    return None, False, False

                _, answered = self._run_exchange(path, exchange)
                if not answered:
                    continue
                self._classic_path[pid] = path
                level, chg, online, spare = parse_nova_pro_omni(reply[0])
                if online and level is not None:
                    extra = f"spare battery {spare}%" if spare is not None else ""
                    out.append(DeviceStatus(f"steelseries:{pid:04x}", name, level, chg, True,
                                            "steelseries", kind="headset", extra=extra))
                    self._diag.append(f"  headset {level}%{' (charging)' if chg else ''}, "
                                      f"spare battery {spare}%")
                else:
                    self._diag.append("  the headset is off or out of range")
                break
        return out

    def diagnostics(self) -> List[str]:
        return list(self._diag)
