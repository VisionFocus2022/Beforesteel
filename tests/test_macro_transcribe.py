"""N58 macro-transcription pipeline tests: OLE container reading, MS-OVBA
decompression, VBA project dir parsing, and SW API call extraction.

The parser lives in tools/macro_transcribe.py (stdlib only, deliberately
outside the MCP package so the frozen build surface is untouched); it is
loaded via importlib. Real-machine integration cases skip when the July
2026 recorded macros are not present (they live outside the repo)."""

from __future__ import annotations

import importlib.util
import struct
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "macro_transcribe.py"

VBA_DIR = Path(r"E:\SolidWorks 2026\SolidWorksMCP\VBA")
RECORDED_EXTRUDE = VBA_DIR / "RecordedExtrude.swp"
CONNECTOR_FINAL = VBA_DIR / "CreateConnector_Final.swp"
CONNECTOR_DEBUG = VBA_DIR / "CreateConnector_Debug.swp"
RECORD_STYLE_SWB = VBA_DIR / "CreateConnector_RecordStyle.swb"


def _load_tool():
    spec = importlib.util.spec_from_file_location("macro_transcribe", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mt = _load_tool()

SECTOR = 512
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF
FATSECT = 0xFFFFFFFD
NOSTREAM = 0xFFFFFFFF


def _dir_entry(name: str, etype: int, color: int, left: int, right: int, child: int,
               start: int, size: int) -> bytes:
    raw_name = name.encode("utf-16-le") + b"\x00\x00"
    if len(raw_name) > 64:
        raise ValueError("name too long")
    entry = bytearray(128)
    entry[0:len(raw_name)] = raw_name
    struct.pack_into("<H", entry, 64, len(raw_name))
    entry[66] = etype
    entry[67] = color
    struct.pack_into("<I", entry, 68, left & 0xFFFFFFFF)
    struct.pack_into("<I", entry, 72, right & 0xFFFFFFFF)
    struct.pack_into("<I", entry, 76, child & 0xFFFFFFFF)
    struct.pack_into("<I", entry, 116, start)
    struct.pack_into("<Q", entry, 120, size)
    return bytes(entry)


def build_minimal_ole(streams: dict[str, bytes]) -> bytes:
    """Hand-rolled OLE v3 writer: one FAT sector, one directory sector,
    one miniFAT sector, small streams (<4096) in a 64-byte mini stream."""
    names = list(streams)
    small = {n: b for n, b in streams.items() if len(b) < 4096}
    big = {n: b for n, b in streams.items() if len(b) >= 4096}

    sectors: list[bytes] = []
    fat: list[int] = []

    def set_fat(idx: int, value: int) -> None:
        while len(fat) <= idx:
            fat.append(FREESECT)
        fat[idx] = value

    fat_sector_idx = len(sectors)
    sectors.append(b"")          # placeholder, filled at the end
    dir_sector_idx = len(sectors)
    sectors.append(b"")

    set_fat(0, FATSECT)
    set_fat(dir_sector_idx, ENDOFCHAIN)

    def alloc_chain(payload: bytes) -> tuple[int, list[int]]:
        n = max((len(payload) + SECTOR - 1) // SECTOR, 1)
        idxs = [len(sectors) + i for i in range(n)]
        padded = payload + b"\x00" * (n * SECTOR - len(payload))
        for pos_i, sec in enumerate(idxs):
            sectors.append(padded[pos_i * SECTOR:(pos_i + 1) * SECTOR])
            set_fat(sec, ENDOFCHAIN if pos_i == n - 1 else idxs[pos_i + 1])
        return idxs[0], idxs

    big_starts = {n: alloc_chain(b)[0] for n, b in big.items()}

    # mini stream: 64-byte minisectors, chained per small stream
    mini_bytes = bytearray()
    minifat: list[int] = []
    small_starts: dict[str, int] = {}
    for name, payload in small.items():
        nm = (len(payload) + 63) // 64 or 1
        start_mini = len(minifat)
        small_starts[name] = start_mini
        mini_bytes += payload + b"\x00" * (nm * 64 - len(payload))
        for i in range(nm):
            minifat.append(start_mini + i + 1 if i < nm - 1 else ENDOFCHAIN)
    mini_start, _ = alloc_chain(bytes(mini_bytes)) if mini_bytes else (ENDOFCHAIN, [])
    minifat_sector_idx = len(sectors)
    minifat_padded = struct.pack(f"<{len(minifat)}I", *minifat) if minifat else b""
    minifat_padded += b"\xff" * (SECTOR - len(minifat_padded))
    sectors.append(minifat_padded)
    if minifat:
        set_fat(minifat_sector_idx, ENDOFCHAIN)

    entries = [_dir_entry("Root Entry", 5, 1, NOSTREAM, NOSTREAM, 1,
                          mini_start if mini_bytes else ENDOFCHAIN, len(mini_bytes))]
    for i, name in enumerate(names):
        payload = streams[name]
        if name in small:
            start = small_starts[name]
        else:
            start = big_starts[name]
        entries.append(_dir_entry(name, 2, 1, NOSTREAM, NOSTREAM, NOSTREAM,
                                  start, len(payload)))
    directory = b"".join(entries)
    directory += b"\x00" * (SECTOR - len(directory))
    sectors[dir_sector_idx] = directory

    header = bytearray(SECTOR)
    header[0:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    struct.pack_into("<H", header, 24, 0x003E)
    struct.pack_into("<H", header, 26, 0x0003)
    struct.pack_into("<H", header, 28, 0xFFFE)
    struct.pack_into("<H", header, 30, 9)          # sector shift -> 512
    struct.pack_into("<H", header, 32, 6)          # mini shift -> 64
    struct.pack_into("<I", header, 40, 0)          # dir sector count (v3: 0)
    struct.pack_into("<I", header, 44, 1)          # FAT sector count
    struct.pack_into("<I", header, 48, dir_sector_idx)
    struct.pack_into("<I", header, 52, 0)          # transaction signature
    struct.pack_into("<I", header, 56, 4096)       # mini stream cutoff
    struct.pack_into("<I", header, 60, minifat_sector_idx if minifat else ENDOFCHAIN)
    struct.pack_into("<I", header, 64, 1 if minifat else 0)
    struct.pack_into("<I", header, 68, ENDOFCHAIN)  # no DIFAT chain
    struct.pack_into("<I", header, 72, 0)
    for i in range(109):
        struct.pack_into("<I", header, 76 + 4 * i, fat_sector_idx if i == 0 else FREESECT)

    fat_bytes = struct.pack(f"<{len(fat)}I", *fat)
    fat_bytes += b"\xff" * (SECTOR - len(fat_bytes))
    sectors[fat_sector_idx] = fat_bytes
    return bytes(header) + b"".join(sectors)


def build_container(literal: bytes, copy_token: int | None = None) -> bytes:
    """Hand-built MS-OVBA compressed container: signature byte, one chunk
    of literals plus (optionally) one copy token computed by hand from the
    spec (independent of the implementation under test). One flag byte
    precedes each group of 8 token slots, bits consumed LSB-first."""

    slots: list[tuple[bool, bytes]] = [(False, bytes([b])) for b in literal]
    if copy_token is not None:
        slots.append((True, struct.pack("<H", copy_token)))
    tokens = bytearray()
    for i in range(0, len(slots), 8):
        group = slots[i:i + 8]
        flag = 0
        for bit, (is_copy, _) in enumerate(group):
            if is_copy:
                flag |= 1 << bit
        tokens.append(flag)
        for _, payload in group:
            tokens += payload
    chunk_len = 2 + len(tokens)
    header = 0xB000 | (chunk_len - 3)
    return b"\x01" + struct.pack("<H", header) + bytes(tokens)


SAMPLE_VBA = """\
Dim swApp As SldWorks.SldWorks
Dim swModel As SldWorks.ModelDoc2
Dim boolstatus As Boolean

Sub main()
    Set swApp = Application.SldWorks
    Set swModel = swApp.NewDocument("E:\\t\\gb_part.prtdot", 0, 0, 0)
    swModel.SetUnits swMM, swMM, swMM, swMM, swMM, swMM
    boolstatus = swModel.Extension.SelectByID2("\u4e0a\u89c6\u57fa\u51c6\u9762", "PLANE", _
        0, 0, 0, False, 0, Nothing, 0)
    swModel.SketchManager.InsertSketch True
    Set feat = swModel.FeatureManager.FeatureExtrusion2(True, False, False, _
        0, 0, 0.014, 0.0001, False, False, False, False, 0.017, 0.017, False, _
        False, False, False, True, True, True, 0, 0, False)
    swModel.SketchBoxSelect
    swApp.ActivateSelectedFeature
    MsgBox "done", vbInformation
End Sub
"""


class TestMsOvbaDecompress(unittest.TestCase):
    def test_literals_only(self):
        blob = build_container(b"Hi")
        self.assertEqual(mt.decompress_ms_ovba(blob), b"Hi")

    def test_copy_token_roundtrip(self):
        # chunk-so-far = "ABCD" -> difference 4 -> BitCount 4.
        # LengthMask = 0xFFFF >> 4 = 0xFFF: token 0x3001 -> length 4;
        # offset = (0x3000 >> 12) + 1 = 4.
        blob = build_container(b"ABCD", copy_token=0x3001)
        self.assertEqual(mt.decompress_ms_ovba(blob), b"ABCDABCD")

    def test_copy_token_exercises_length_middle_bits(self):
        # 256 literals -> difference 256 -> BitCount 8, LengthMask = 0xFF.
        # Token 0xFF34: offset = (0xFF00 >> 8) + 1 = 256; length = 0x34 + 3
        # = 55 —— length 字段的 bits 4-7 非零，回归 12 位 LengthMask 截断。
        literal = bytes(range(256))
        blob = build_container(literal, copy_token=0xFF34)
        self.assertEqual(mt.decompress_ms_ovba(blob), literal + literal[:55])

    def test_bad_signature_rejected(self):
        with self.assertRaises(ValueError):
            mt.decompress_ms_ovba(b"\x02\x00\xb0\x07x")


class TestOleReading(unittest.TestCase):
    def test_ministream_and_directory(self):
        streams = {"VBA/dir": b"\x01data", "Module1": b"X" * 100}
        blob = build_minimal_ole(streams)
        parsed = mt.read_ole_streams(blob)
        # the reader must truncate to the directory-declared size
        self.assertEqual(parsed["VBA/dir"], b"\x01data")
        self.assertEqual(parsed["Module1"], b"X" * 100)

    def test_regular_stream_over_4096(self):
        blob = build_minimal_ole({"Big": b"Z" * 5000})
        parsed = mt.read_ole_streams(blob)
        self.assertEqual(len(parsed["Big"]), 5000)
        self.assertEqual(parsed["Big"], b"Z" * 5000)


class TestDirParsing(unittest.TestCase):
    def test_module_records(self):
        def rec(rid: int, payload: bytes) -> bytes:
            return struct.pack("<HI", rid, len(payload)) + payload
        dir_bytes = (
            rec(0x0019, b"SwMacro") +
            rec(0x001A, b"SwMacro") +
            rec(0x0031, struct.pack("<I", 512)) +
            rec(0x0021, struct.pack("<I", 0))
        )
        modules = mt.parse_vba_dir(dir_bytes)
        self.assertEqual(len(modules), 1)
        self.assertEqual(modules[0]["name"], "SwMacro")
        self.assertEqual(modules[0]["offset"], 512)


class TestApiExtraction(unittest.TestCase):
    def setUp(self):
        self.result = mt.extract_api_calls(SAMPLE_VBA)

    def test_declared_variables_tracked(self):
        self.assertIn("swApp", self.result["declared"])
        self.assertIn("swModel", self.result["declared"])
        self.assertIn("feat", self.result["declared"])

    def test_modeling_calls_extracted_with_chains(self):
        calls = {(c["chain"], c["method"]): c for c in self.result["calls"]}
        self.assertIn(("swModel", "SetUnits"), calls)
        self.assertIn(("swModel.Extension", "SelectByID2"), calls)
        self.assertIn(("swModel.SketchManager", "InsertSketch"), calls)
        self.assertIn(("swModel.FeatureManager", "FeatureExtrusion2"), calls)
        self.assertIn(("swApp", "NewDocument"), calls)

    def test_select_args_parse_nine_fields_with_continuation_join(self):
        call = next(c for c in self.result["calls"]
                    if c["method"] == "SelectByID2")
        self.assertEqual(len(call["args"]), 9)
        self.assertEqual(call["args"][1], '"PLANE"')

    def test_extrusion_arg_count(self):
        call = next(c for c in self.result["calls"]
                    if c["method"] == "FeatureExtrusion2")
        self.assertEqual(len(call["args"]), 23)

    def test_recorder_noise_tagged(self):
        noise = {c["method"] for c in self.result["noise"]}
        self.assertIn("SketchBoxSelect", noise)
        self.assertIn("ActivateSelectedFeature", noise)
        self.assertNotIn("FeatureExtrusion2", noise)

    def test_msgbox_is_noise_not_call(self):
        noise = {c["method"] for c in self.result["noise"]}
        self.assertIn("MsgBox", noise)

    def test_line_numbers_monotonic(self):
        lines = [c["line"] for c in self.result["calls"]]
        self.assertEqual(lines, sorted(lines))


@unittest.skipUnless(RECORDED_EXTRUDE.exists(), "July 2026 recorded macros not on this host")
class TestRealRecordedMacro(unittest.TestCase):
    def test_recorded_extrude_transcribes(self):
        result = mt.transcribe(str(RECORDED_EXTRUDE), include_source=True)
        self.assertEqual(result["kind"], "swp")
        self.assertTrue(result["modules"])
        sources = "\n".join(m["source"] for m in result["modules"])
        self.assertIn("FeatureExtrusion2", sources)
        methods = {c["method"] for c in result["calls"]}
        self.assertIn("FeatureExtrusion2", methods)
        self.assertIn("SelectByID2", methods)
        noise = {c["method"] for c in result["noise"]}
        self.assertTrue(noise & {"SketchBoxSelect", "ActivateSelectedFeature", "DeSelectByID"})

    def test_connector_debug_full_code_oracle(self):
        # 全码 .swp 对照：Debug 版 7121 字符含建模调用；Final.swp 本体只存
        # 存根（参考 oletools 同样只得 304+124 模块），如实定谳为「无码」。
        result = mt.transcribe(str(CONNECTOR_DEBUG), include_source=True)
        sources = "\n".join(m["source"] for m in result["modules"])
        self.assertIn("FeatureExtrusion2", sources)
        self.assertIn("SelectByID2", sources)
        methods = {c["method"] for c in result["calls"]}
        self.assertIn("FeatureExtrusion2", methods)

    def test_connector_final_is_stub_only(self):
        result = mt.transcribe(str(CONNECTOR_FINAL))
        self.assertEqual(result["module_count"], 2)
        methods = {c["method"] for c in result["calls"]}
        # 存根唯一调用是 Set swApp = Application.SldWorks 的 getter
        self.assertTrue(methods <= {"SldWorks"}, methods)
        self.assertNotIn("SelectByID2", methods)

    def test_swb_text_passthrough(self):
        result = mt.transcribe(str(RECORD_STYLE_SWB))
        self.assertEqual(result["kind"], "text")
        methods = {c["method"] for c in result["calls"]}
        self.assertIn("SelectByID2", methods)


if __name__ == "__main__":
    unittest.main()
