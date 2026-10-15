"""Heatmiser V3 RS-485 protocol helpers.

Pure Python (no Home Assistant imports) so it can be unit-tested on its own.

Frame layouts on the bus:

  master -> thermostat:  dest, len, src, func, start_lo, start_hi, count_lo, count_hi, [data...], crc_lo, crc_hi
                         dest 1..32, src 0x81..0xA0, func 0 = read, 1 = write.
                         A read uses start 0 and count 0xFFFF ("everything").
  thermostat -> master:  dest, len_lo, len_hi, src, func, start_lo, start_hi, count_lo, count_hi, [DCB...], crc_lo, crc_hi
                         dest is the master address (0x81..0xA0). A write is acknowledged with a 7-byte frame.

Multi-byte values inside the DCB (temperatures, holiday hours, hold minutes) are high byte first.
"""

from __future__ import annotations

import asyncio
import time

from .const import DCB_AIR, DCB_FLOOR, DCB_REMOTE_AIR, DCB_SENSOR

MASTER_MIN = 0x81
MASTER_MAX = 0xA0

SENSOR_NAMES = {0: "Built-in air", 1: "Remote air", 2: "Floor", 3: "Air + floor limit", 4: "Remote air + floor limit"}


def crc16(data: bytes) -> bytes:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF), returned low byte first as the bus expects."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return bytes((crc & 0xFF, crc >> 8))


def build_frame(addr: int, source: int, func: int, start: int, payload: list[int] | None = None) -> bytes:
    """Build a master -> thermostat frame including its CRC."""
    if func == 0:
        msg = [addr, 10, source, 0, start & 0xFF, start >> 8, 0xFF, 0xFF]
    else:
        payload = payload or []
        n = len(payload)
        msg = [addr, 10 + n, source, 1, start & 0xFF, start >> 8, n & 0xFF, n >> 8, *payload]
    raw = bytes(msg)
    return raw + crc16(raw)


class FrameParser:
    """Splits a byte stream into CRC-valid V3 frames, in both directions."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def feed(self, data: bytes) -> list[tuple[str, bytes]]:
        """Add bytes; return complete frames as ("request" | "reply", frame)."""
        self.buf += data
        b = self.buf
        out: list[tuple[str, bytes]] = []
        i = 0
        n = len(b)
        while i < n:
            c = b[i]
            if MASTER_MIN <= c <= MASTER_MAX:
                if n - i < 3:
                    break
                length = b[i + 1] | (b[i + 2] << 8)
                if 7 <= length <= 400:
                    if n - i < length:
                        break
                    fr = bytes(b[i : i + length])
                    if crc16(fr[:-2]) == fr[-2:]:
                        out.append(("reply", fr))
                        i += length
                        continue
            elif 1 <= c <= 32:
                if n - i < 3:
                    break
                length = b[i + 1]
                if 10 <= length <= 64 and MASTER_MIN <= b[i + 2] <= MASTER_MAX:
                    if n - i < length:
                        break
                    fr = bytes(b[i : i + length])
                    if crc16(fr[:-2]) == fr[-2:]:
                        out.append(("request", fr))
                        i += length
                        continue
            i += 1
        del b[:i]
        if len(b) > 2048:
            b.clear()
        return out


def reply_dcb(frame: bytes) -> tuple[int, bytes] | None:
    """For a read reply, return (thermostat address, DCB bytes); otherwise None."""
    if len(frame) >= 9 + 40 + 2 and frame[4] == 0:
        return frame[3], frame[9:-2]
    return None


def word(d: bytes, i: int) -> int:
    """Read a high-byte-first 16-bit value from the DCB."""
    return (d[i] << 8) | d[i + 1]


def current_temp(d: bytes) -> float | None:
    """Room temperature from whichever sensor the thermostat is set to use."""
    idx = {1: DCB_REMOTE_AIR, 2: DCB_FLOOR, 4: DCB_REMOTE_AIR}.get(d[DCB_SENSOR], DCB_AIR)
    raw = word(d, idx)
    return None if raw == 0xFFFF else raw / 10


def floor_temp(d: bytes) -> float | None:
    raw = word(d, DCB_FLOOR)
    return None if raw == 0xFFFF else raw / 10


def schedule(d: bytes, start: int) -> list[str]:
    """Four comfort levels (hour, minute, temperature) starting at `start`; unused slots have hour >= 24."""
    out = []
    for k in range(4):
        if start + 3 * k + 3 > len(d):
            break
        hh, mm, temp = d[start + 3 * k : start + 3 * k + 3]
        if hh < 24:
            out.append(f"{hh:02d}:{mm:02d} {temp}°C")
    return out


UNUSED_SLOT = [24, 0, 16]  # how the thermostats mark an unused program slot


def program_payload(periods: list[tuple[int, int, int]]) -> list[int]:
    """Build the 12-byte weekday/weekend program from 1-4 (hour, minute, temperature) periods.

    Heatmiser only accepts times on the hour or half hour and 5-35 degC; anything else can make
    the thermostat reset the whole program, so it is rejected here before anything is sent.
    """
    if not 1 <= len(periods) <= 4:
        raise ValueError("A program needs 1 to 4 periods")
    times = [(h, m) for h, m, _ in periods]
    if times != sorted(times) or len(set(times)) != len(times):
        raise ValueError("Period times must be in order, earliest first, with no duplicates")
    out: list[int] = []
    for hour, minute, temp in periods:
        if not 0 <= hour <= 23 or minute not in (0, 30):
            raise ValueError(f"{hour:02d}:{minute:02d} is not allowed; use HH:00 or HH:30")
        if not 5 <= temp <= 35:
            raise ValueError(f"{temp} degC is outside 5-35")
        out += [hour, minute, temp]
    while len(out) < 12:
        out += UNUSED_SLOT
    return out


async def discover(host: str, port: int, seconds: float = 20) -> list[int]:
    """Listen to the bus without transmitting and return the thermostat addresses heard."""
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 10)
    parser = FrameParser()
    found: set[int] = set()
    end = time.monotonic() + seconds
    try:
        while (left := end - time.monotonic()) > 0:
            try:
                data = await asyncio.wait_for(reader.read(4096), left)
            except asyncio.TimeoutError:  # same as TimeoutError on Python 3.11+
                break
            if not data:
                break
            for kind, frame in parser.feed(data):
                if kind == "reply" and (r := reply_dcb(frame)):
                    found.add(r[0])
    finally:
        writer.close()
    return sorted(found)
