"""Heatmiser V3 RS-485 bus over a transparent RS485-to-TCP converter.

Reading is passive: the Touchpad already polls every thermostat, so we just
decode its traffic. Writes are slipped into the quiet gap after a thermostat
answers the Touchpad, and retried if not acknowledged. If the Touchpad goes
silent, HA polls the thermostats itself (slowly) so readings keep flowing.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DCB_DOW,
    DCB_RUN_MODE,
    DCB_WEEKDAY,
    DCB_WEEKEND,
    DOMAIN,
    HA_MASTER,
    REG_RUN_MODE,
    REG_TIME,
    REG_WEEKDAY,
    REG_WEEKEND,
    SIGNAL_STATUS,
    SIGNAL_UPDATE,
    STALE_AFTER,
    TOUCHPAD_MASTER,
)

from .protocol import FrameParser, build_frame, reply_dcb

_LOGGER = logging.getLogger(__name__)

class HeatmiserBus:
    """Connection to the bus and the latest data for each thermostat."""

    def __init__(self, hass: HomeAssistant, host: str, port: int, names: dict[int, str]) -> None:
        self.hass = hass
        self.host = host
        self.port = port
        self.names = names
        self.addresses = sorted(names)
        self.master = HA_MASTER
        self.dcb: dict[int, bytes] = {}
        self.seen: dict[int, float] = {}
        self._avail: dict[int, bool] = {}
        self.connected = False
        self.touchpad_seen = 0.0
        self.last_rx = 0.0
        self.stats = {"frames": 0, "writes": 0, "write_retries": 0, "write_failures": 0, "own_polls": 0, "other_master_writes": 0}
        self._parser = FrameParser()
        self._writer: asyncio.StreamWriter | None = None
        self._gap_waiters: list[asyncio.Future] = []
        self._ack: tuple[int, asyncio.Future] | None = None
        self._read_reply: tuple[int, asyncio.Future] | None = None
        self._lock = asyncio.Lock()
        self._tasks: list[asyncio.Task] = []
        self._stopping = False
        self._store = Store(hass, 1, f"{DOMAIN}.away")
        self.away_saved: dict[str, int] | None = None

    # ------------------------------------------------------------------ life cycle
    async def async_start(self) -> None:
        data = await self._store.async_load()
        self.away_saved = (data or {}).get("saved") or None
        self._tasks.append(self.hass.async_create_background_task(self._run(), f"{DOMAIN} reader"))
        self._tasks.append(self.hass.async_create_background_task(self._housekeeping(), f"{DOMAIN} housekeeping"))

    async def async_stop(self) -> None:
        self._stopping = True
        for task in self._tasks:
            task.cancel()
        if self._writer:
            self._writer.close()

    async def async_wait_first_data(self, timeout: float) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end and len(self.dcb) < len(self.addresses):
            await asyncio.sleep(0.5)

    def _status(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_STATUS)

    async def _run(self) -> None:
        backoff = 2
        while not self._stopping:
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), 10)
                self._writer = writer
                self.connected = True
                self.touchpad_seen = time.monotonic()  # grace period before we consider polling ourselves
                backoff = 2
                _LOGGER.info("Connected to Heatmiser bus at %s:%s", self.host, self.port)
                self._status()
                while True:
                    data = await asyncio.wait_for(reader.read(4096), 90)
                    if not data:
                        raise ConnectionError("connection closed by converter")
                    self.last_rx = time.monotonic()
                    for kind, frame in self._parser.feed(data):
                        self.stats["frames"] += 1
                        if kind == "reply":
                            self._on_reply(frame)
                        elif frame[3] == 1 and frame[2] != self.master:
                            # Another master (normally the Touchpad) changed a thermostat
                            self.stats["other_master_writes"] += 1
                            _LOGGER.info(
                                "Master 0x%02X wrote thermostat %s address %s: %s",
                                frame[2], frame[0], frame[4] | (frame[5] << 8), frame[8:-2].hex(" "),
                            )
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                if not self._stopping:
                    _LOGGER.warning("Heatmiser bus connection problem: %s (retrying in %ss)", err, backoff)
            finally:
                if self._writer:
                    self._writer.close()
                self._writer = None
                if self.connected:
                    self.connected = False
                    self._status()
                    for addr in self.addresses:
                        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(addr))
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    # ------------------------------------------------------------------ receive
    def _on_reply(self, fr: bytes) -> None:
        dest, src, func = fr[0], fr[3], fr[4]
        now = time.monotonic()
        if dest == TOUCHPAD_MASTER:
            self.touchpad_seen = now
            waiters, self._gap_waiters = self._gap_waiters, []
            for fut in waiters:
                if not fut.done():
                    fut.set_result(None)
        if (dcb := reply_dcb(fr)) is not None:
            self._store_dcb(src, dcb[1], now)
            if dest == self.master and self._read_reply and self._read_reply[0] == src:
                if not self._read_reply[1].done():
                    self._read_reply[1].set_result(None)
        elif func == 1 and dest == self.master and self._ack and self._ack[0] == src:
            if not self._ack[1].done():
                self._ack[1].set_result(None)

    def _store_dcb(self, addr: int, data: bytes, now: float) -> None:
        if addr not in self.addresses:
            return
        old = self.dcb.get(addr)
        self.dcb[addr] = data
        self.seen[addr] = now
        became_available = not self._avail.get(addr)
        self._avail[addr] = True
        # Ignore the clock bytes (36-39) so we don't push a state update every poll
        if became_available or old is None or old[:DCB_DOW] != data[:DCB_DOW] or old[DCB_DOW + 4 :] != data[DCB_DOW + 4 :]:
            async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(addr))

    def available(self, addr: int) -> bool:
        return self.connected and bool(self._avail.get(addr))

    # ------------------------------------------------------------------ transmit
    async def _wait_slot(self) -> None:
        """Wait for a moment when the bus is quiet."""
        loop = asyncio.get_running_loop()
        if time.monotonic() - self.touchpad_seen < 15:
            fut = loop.create_future()
            self._gap_waiters.append(fut)
            try:
                await asyncio.wait_for(fut, 4)
                return
            except TimeoutError:
                pass
        while time.monotonic() - self.last_rx < 0.3:
            await asyncio.sleep(0.05)

    async def _send(self, frame: bytes) -> None:
        if not self._writer:
            raise HomeAssistantError("Heatmiser bus is not connected")
        self._writer.write(frame)
        await self._writer.drain()

    async def async_write(self, addr: int, reg: int, payload: list[int]) -> None:
        """Write bytes to a thermostat and wait for its acknowledgement."""
        if not self.connected:
            raise HomeAssistantError("Heatmiser bus is not connected")
        frame = build_frame(addr, self.master, 1, reg, payload)
        loop = asyncio.get_running_loop()
        async with self._lock:
            for attempt in range(1, 7):
                await self._wait_slot()
                fut = loop.create_future()
                self._ack = (addr, fut)
                try:
                    await self._send(frame)
                    await asyncio.wait_for(fut, 1.0)
                except TimeoutError:
                    self.stats["write_retries"] += 1
                    _LOGGER.debug("No ack from thermostat %s (attempt %s)", addr, attempt)
                    await asyncio.sleep(0.2 + random.random() * 0.5)
                    continue
                finally:
                    self._ack = None
                self.stats["writes"] += 1
                self._apply_local(addr, reg, payload)
                return
        self.stats["write_failures"] += 1
        raise HomeAssistantError(f"Heatmiser thermostat {addr} did not confirm the change")

    async def async_read(self, addr: int) -> None:
        """Ask a thermostat for its data (used only when the Touchpad is silent)."""
        frame = build_frame(addr, self.master, 0, 0, None)
        loop = asyncio.get_running_loop()
        async with self._lock:
            await self._wait_slot()
            fut = loop.create_future()
            self._read_reply = (addr, fut)
            try:
                await self._send(frame)
                await asyncio.wait_for(fut, 1.5)
                self.stats["own_polls"] += 1
            except TimeoutError:
                pass
            finally:
                self._read_reply = None

    def _apply_local(self, addr: int, reg: int, payload: list[int]) -> None:
        data = self.dcb.get(addr)
        # Program writes go to different addresses than where they are read back
        reg = {REG_WEEKDAY: DCB_WEEKDAY, REG_WEEKEND: DCB_WEEKEND}.get(reg, reg if reg < DCB_DOW else -1)
        if data is None or reg < 0 or reg + len(payload) > len(data):
            return
        new = bytearray(data)
        new[reg : reg + len(payload)] = bytes(payload)
        self.dcb[addr] = bytes(new)
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(addr))

    # ------------------------------------------------------------------ housekeeping
    async def _housekeeping(self) -> None:
        idx = 0
        while True:
            await asyncio.sleep(1.5)
            now = time.monotonic()
            for addr in self.addresses:
                if self._avail.get(addr) and now - self.seen.get(addr, 0) > STALE_AFTER:
                    self._avail[addr] = False
                    async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(addr))
            if self.connected and now - self.touchpad_seen > 30 and self.addresses:
                addr = self.addresses[idx % len(self.addresses)]
                idx += 1
                try:
                    await self.async_read(addr)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Own poll of %s failed: %s", addr, err)

    # ------------------------------------------------------------------ features
    def clock_drift(self, addr: int) -> float | None:
        """Seconds the thermostat clock is ahead (+) or behind (-) local time."""
        data = self.dcb.get(addr)
        if data is None:
            return None
        dow, hh, mm, ss = data[DCB_DOW : DCB_DOW + 4]
        if not 1 <= dow <= 7:
            return None
        then = dt_util.now().timestamp() - (time.monotonic() - self.seen[addr])
        local = dt_util.as_local(dt_util.utc_from_timestamp(then))
        week = 7 * 86400
        stat = ((dow - 1) * 86400 + hh * 3600 + mm * 60 + ss) % week
        real = (local.weekday() * 86400 + local.hour * 3600 + local.minute * 60 + local.second) % week
        diff = (stat - real) % week
        return diff - week if diff > week / 2 else diff

    async def async_sync_clocks(self, force: bool = False) -> list[int]:
        """Set thermostat clocks that have drifted (or all, if forced)."""
        changed: list[int] = []
        failed: list[int] = []
        for addr in self.addresses:
            drift = self.clock_drift(addr)
            if not force and drift is not None and abs(drift) < 90:
                continue
            now = dt_util.now()
            try:
                await self.async_write(addr, REG_TIME, [now.isoweekday(), now.hour, now.minute, now.second])
                changed.append(addr)
            except HomeAssistantError:
                failed.append(addr)
            await asyncio.sleep(0.3)
        if changed or failed:
            _LOGGER.info("Heatmiser clock sync: set %s, failed %s", changed, failed)
        if failed:
            raise HomeAssistantError(f"Clock sync failed for thermostats {failed}")
        return changed

    async def async_set_away(self, on: bool) -> None:
        """Whole-house away: every room to Frost, then restore each room's previous mode."""
        failed: list[int] = []
        if on:
            if self.away_saved:
                return
            saved = {str(a): self.dcb[a][DCB_RUN_MODE] for a in self.addresses if a in self.dcb}
            self.away_saved = saved
            await self._store.async_save({"saved": saved})
            self._status()
            for addr_s, mode in saved.items():
                if mode == 0:
                    try:
                        await self.async_write(int(addr_s), REG_RUN_MODE, [1])
                    except HomeAssistantError:
                        failed.append(int(addr_s))
        else:
            saved = self.away_saved or {}
            for addr_s, mode in saved.items():
                if mode == 0:
                    try:
                        await self.async_write(int(addr_s), REG_RUN_MODE, [0])
                    except HomeAssistantError:
                        failed.append(int(addr_s))
            if not failed:
                self.away_saved = None
                await self._store.async_save({"saved": None})
        self._status()
        if failed:
            raise HomeAssistantError(f"Heatmiser thermostats {failed} did not confirm the change; try again")
