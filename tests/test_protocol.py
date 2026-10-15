"""Protocol tests using frames captured from a real Heatmiser V3 bus (Touchpad + PRT-E thermostats)."""

import asyncio
import pathlib
import sys
import types
import unittest

# Import the protocol module without Home Assistant installed
PKG = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "heatmiser_bus"
pkg = types.ModuleType("heatmiser_bus")
pkg.__path__ = [str(PKG)]
sys.modules.setdefault("heatmiser_bus", pkg)

from heatmiser_bus import const, protocol  # noqa: E402

# Touchpad (0x81) asking thermostat 3 for everything
READ_REQ = bytes.fromhex("030a81000000ffff8a86")
# HA (0x82) setting thermostat 19's set temperature (address 18) to 23, and its acknowledgement
WRITE_REQ = bytes.fromhex("130b82011200010017e22b")
WRITE_ACK = bytes.fromhex("82070013017360")
# Thermostat 5 replying to the Touchpad with its 64-byte DCB (5/2 day program)
READ_REPLY = bytes.fromhex(
    "814b00050000004000004000130300010000000005000000140011171c0101000100000000ffffffff00e6"
    "000004161803090017091e17101e171700170900171600171800101800105b5a"
)


class TestCrc(unittest.TestCase):
    def test_known_frames(self):
        for frame in (READ_REQ, WRITE_REQ, WRITE_ACK, READ_REPLY):
            self.assertEqual(protocol.crc16(frame[:-2]), frame[-2:], frame.hex())


class TestBuild(unittest.TestCase):
    def test_read(self):
        self.assertEqual(protocol.build_frame(3, 0x81, 0, 0), READ_REQ)

    def test_write(self):
        self.assertEqual(protocol.build_frame(19, 0x82, 1, const.REG_SET_TEMP, [23]), WRITE_REQ)


class TestParser(unittest.TestCase):
    def test_stream_in_odd_chunks_with_noise(self):
        stream = b"\x00\xff\x13" + READ_REQ + READ_REPLY + b"\x55" + WRITE_REQ + WRITE_ACK
        parser = protocol.FrameParser()
        frames = []
        for i in range(0, len(stream), 7):
            frames += parser.feed(stream[i : i + 7])
        self.assertEqual(
            frames,
            [("request", READ_REQ), ("reply", READ_REPLY), ("request", WRITE_REQ), ("reply", WRITE_ACK)],
        )

    def test_corrupt_frame_skipped(self):
        bad = bytearray(READ_REPLY)
        bad[40] ^= 0xFF
        frames = protocol.FrameParser().feed(bytes(bad) + READ_REQ)
        self.assertEqual(frames, [("request", READ_REQ)])


class TestDecode(unittest.TestCase):
    def setUp(self):
        addr, self.d = protocol.reply_dcb(READ_REPLY)
        self.assertEqual(addr, 5)
        self.assertEqual(len(self.d), 64)

    def test_fields(self):
        d = self.d
        self.assertEqual(d[const.DCB_MODEL], 3)  # PRT-E
        self.assertEqual(d[const.DCB_SET_TEMP], 23)
        self.assertEqual(d[const.DCB_FROST_TEMP], 17)
        self.assertEqual(d[const.DCB_RUN_MODE], 1)  # frost
        self.assertEqual(d[const.DCB_HEATING], 0)
        self.assertEqual(protocol.current_temp(d), 23.0)
        self.assertIsNone(protocol.floor_temp(d))
        self.assertEqual(tuple(d[const.DCB_DOW : const.DCB_DOW + 4]), (4, 22, 24, 3))  # Thu 22:24:03

    def test_schedule(self):
        self.assertEqual(
            protocol.schedule(self.d, const.DCB_WEEKDAY), ["09:00 23°C", "09:30 23°C", "16:30 23°C", "23:00 23°C"]
        )
        self.assertEqual(protocol.schedule(self.d, const.DCB_WEEKEND), ["09:00 23°C", "22:00 23°C"])

    def test_write_ack_is_not_a_dcb(self):
        self.assertIsNone(protocol.reply_dcb(WRITE_ACK))


class TestDiscover(unittest.TestCase):
    def test_discover_lists_repliers_only(self):
        async def run():
            async def handler(reader, writer):
                writer.write(READ_REQ + READ_REPLY + WRITE_REQ + WRITE_ACK)
                await writer.drain()
                await asyncio.sleep(0.3)
                writer.close()

            server = await asyncio.start_server(handler, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            async with server:
                return await protocol.discover("127.0.0.1", port, seconds=2)

        self.assertEqual(asyncio.run(run()), [5])


if __name__ == "__main__":
    unittest.main()
