"""N58 宏转录管线——.swp/.swb 宏解析器（2026-09-19 预建）。

SolidWorks 宏 → VBA 源码 → SW API 调用序列，为 N58「用户交 .swp 即开工」
做准备：解析层先行落地并用 2026-07 真实宏（RecordedExtrude.swp /
CreateConnector_Final.swp ↔ ForVBAEditor.txt）验证；四族（pattern/rib/
combine/AutoBalloon）内容一概不猜（FB-020），待 U9 交付后首跑。

用法：
    python tools/macro_transcribe.py <macro.swp|.swb|.txt|.bas> [--json] [--source]

格式层（纯 stdlib，零新依赖，不动 MCP 包/frozen 面）：
    .swp = OLE 复合文档 + MS-OVBA 压缩 VBA 项目（dir 流给模块表，
           模块流 = [性能缓存][压缩源码]，offset 由 dir 的 MODULEOFFSET 给出）
    .swb/.txt/.bas = 纯文本透传（utf-8→gbk→latin-1 容错解码）

契约（tests/test_macro_transcribe.py 锁定）：
    read_ole_streams(data) -> {限定名: bytes}   按目录尺寸截断，pad 不外漏
    decompress_ms_ovba(data) -> bytes           签名非法 raise ValueError
    parse_vba_dir(dir) -> [{name, stream, offset}]
    extract_api_calls(src) -> {declared, calls, noise}
    transcribe(path) -> {file, kind, modules, declared, calls, noise}
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF
NOSTREAM = 0xFFFFFFFF

NOISE_METHODS = {
    # 录制器/纯 UI 噪声（N58 转录目标是建模 API 序列）
    "SketchBoxSelect",
    "ActivateSelectedFeature",
    "DeSelectByID",
    "MsgBox",
    "InputBox",
}

_CHAIN_RE = re.compile(r"^([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)(?:\s+(.*))?$")
_PAREN_CHAIN_RE = re.compile(r"^([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\s*\((.*)\)\s*$")
_SET_RE = re.compile(r"^(?:Set\s+)?([A-Za-z_]\w*)\s*=\s*(.+)$", re.IGNORECASE)
_DIM_RE = re.compile(r"^(?:Dim|Public|Private|Static)\s+(.+)$", re.IGNORECASE)
_SKIP_KEYWORDS = {
    "option", "attribute", "on", "end", "else", "next", "dim",
    "public", "private", "const", "sub", "function", "exit", "stop",
}


def _u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def _u64(data: bytes, off: int) -> int:
    return struct.unpack_from("<Q", data, off)[0]


# ---------------------------------------------------------------------------
# Layer 1: OLE 复合文档读取（v3，含 miniFAT）
# ---------------------------------------------------------------------------

class _Compound:
    def __init__(self, data: bytes):
        if data[:8] != OLE_MAGIC:
            raise ValueError("not an OLE compound document (bad magic)")
        self.data = data
        self.sector_size = 1 << _u16(data, 30)
        self.mini_sector_size = 1 << _u16(data, 32)
        self._fat = self._read_fat()
        self.entries = self._read_directory()
        self._streams: dict[str, bytes] = {}
        for e in self.entries:
            if e["type"] == 2:
                self._streams[e["path"]] = self._read_stream(e)

    # -- header / FAT ------------------------------------------------------
    def _sector(self, idx: int) -> bytes:
        start = (idx + 1) * self.sector_size
        return self.data[start:start + self.sector_size]

    def _read_fat(self) -> list[int]:
        difat: list[int] = []
        for i in range(109):
            entry = _u32(self.data, 76 + 4 * i)
            if entry in (FREESECT, ENDOFCHAIN):
                break
            difat.append(entry)
        nxt = _u32(self.data, 68)
        guard = 0
        while nxt not in (FREESECT, ENDOFCHAIN) and guard < 1000:
            sec = self._sector(nxt)
            for i in range((self.sector_size - 4) // 4):
                v = _u32(sec, 4 * i)
                if v not in (FREESECT, ENDOFCHAIN):
                    difat.append(v)
            nxt = _u32(sec, self.sector_size - 4)
            guard += 1
        fat: list[int] = []
        for fs in difat:
            sec = self._sector(fs)
            fat.extend(_u32(sec, i) for i in range(0, self.sector_size, 4))
        return fat

    def _chain(self, start: int, table: list[int]) -> list[int]:
        out: list[int] = []
        cur = start
        guard = 0
        while cur not in (ENDOFCHAIN, FREESECT) and guard < 1_000_000:
            out.append(cur)
            if cur >= len(table):
                break
            cur = table[cur]
            guard += 1
        return out

    def _chain_bytes(self, start: int, table: list[int]) -> bytes:
        return b"".join(self._sector(i) for i in self._chain(start, table))

    # -- directory ---------------------------------------------------------
    def _read_directory(self) -> list[dict]:
        raw = self._chain_bytes(_u32(self.data, 48), self._fat)
        entries: list[dict] = []
        for off in range(0, len(raw) - 127, 128):
            blob = raw[off:off + 128]
            namelen = _u16(blob, 64)
            etype = blob[66]
            if etype == 0 or namelen < 2:
                entries.append({"type": 0, "path": ""})
                continue
            entries.append(
                {
                    "type": etype,
                    "name": blob[: namelen - 2].decode("utf-16-le", "replace"),
                    "left": _u32(blob, 68),
                    "right": _u32(blob, 72),
                    "child": _u32(blob, 76),
                    "start": _u32(blob, 116),
                    "size": _u64(blob, 120),
                }
            )
        # 根存储红黑树 → 限定路径；树不可达（合成夹具）退回平铺名
        visited: set[int] = set()

        def walk(idx: int, prefix: str) -> None:
            stack = [idx]
            while stack:
                i = stack.pop()
                if i == NOSTREAM or i >= len(entries) or i in visited:
                    continue
                visited.add(i)
                e = entries[i]
                if e["type"] == 0:
                    continue
                e["path"] = prefix + e["name"]
                stack.append(e["left"])
                stack.append(e["right"])
                if e["type"] in (1, 5) and e["child"] != NOSTREAM:
                    walk(e["child"], e["path"] + "\\")

        for e in entries:
            e.setdefault("path", e.get("name", ""))
        if entries and entries[0]["type"] == 5:
            entries[0]["path"] = ""
            if entries[0]["child"] != NOSTREAM:
                walk(entries[0]["child"], "")
        for e in entries:
            if e["type"] == 5:
                e["path"] = ""
            elif e["type"] != 0 and "path" not in e:
                e["path"] = e["name"]
        return entries

    # -- stream payload ----------------------------------------------------
    def _read_stream(self, e: dict) -> bytes:
        if e["size"] == 0:
            return b""
        cutoff = _u32(self.data, 56)
        if e["size"] >= cutoff:
            blob = self._chain_bytes(e["start"], self._fat)
            return blob[: e["size"]]
        root = next((x for x in self.entries if x["type"] == 5), None)
        if root is None or root["start"] in (NOSTREAM, ENDOFCHAIN):
            return b""
        mini_raw = self._chain_bytes(root["start"], self._fat)
        minifat_start = _u32(self.data, 60)
        if minifat_start in (FREESECT, ENDOFCHAIN):
            return b""
        mf_raw = self._chain_bytes(minifat_start, self._fat)
        table = [_u32(mf_raw, i) for i in range(0, len(mf_raw), 4)]
        msize = self.mini_sector_size
        blob = b"".join(
            mini_raw[ms * msize: ms * msize + msize]
            for ms in self._chain(e["start"], table)
        )
        return blob[: e["size"]]


def read_ole_streams(data: bytes) -> dict[str, bytes]:
    """读取复合文档全部流；键为存储限定名（如 VBA\\dir），按目录尺寸截断。"""
    return dict(_Compound(data)._streams)


# ---------------------------------------------------------------------------
# Layer 2: MS-OVBA 压缩容器解压（MS-OVBA 2.4.1）
# ---------------------------------------------------------------------------

def decompress_ms_ovba(data: bytes) -> bytes:
    if not data or data[0] != 0x01:
        raise ValueError("bad MS-OVBA container signature (expect 0x01)")
    out = bytearray()
    pos = 1
    total = len(data)
    while pos + 2 <= total:
        header = _u16(data, pos)
        pos += 2
        size = (header & 0x0FFF) + 3
        if (header >> 12) & 0x7 != 0b011:
            raise ValueError("bad chunk signature (expect 0b011)")
        compressed = bool((header >> 15) & 1)
        chunk_end = min(pos + size - 2, total)
        if not compressed:
            out += data[pos:pos + 4096]
            pos += 4096
            continue
        chunk_out_start = len(out)
        while pos < chunk_end:
            flags = data[pos]
            pos += 1
            for bit in range(8):
                if pos >= chunk_end:
                    break
                if not (flags >> bit) & 1:
                    out.append(data[pos])
                    pos += 1
                    continue
                if pos + 2 > chunk_end:
                    pos = chunk_end
                    break
                token = _u16(data, pos)
                pos += 2
                difference = len(out) - chunk_out_start
                bit_count = max(max(difference - 1, 0).bit_length(), 4)
                # spec 2.4.1.3.19.1: LengthMask = 0xFFFF >> BitCount，
                # OffsetMask = ~LengthMask；2.4.1.3.19.2: Offset 右移
                # (16 - BitCount) —— 16 位 CopyToken 高位归 offset 低位归
                # length，两字段宽度随 BitCount 此消彼长
                length_mask = 0xFFFF >> bit_count
                offset_mask = (~length_mask) & 0xFFFF
                length = (token & length_mask) + 3
                offset = ((token & offset_mask) >> (16 - bit_count)) + 1
                for _ in range(length):
                    if offset > len(out):
                        break
                    out.append(out[len(out) - offset])
    return bytes(out)


# ---------------------------------------------------------------------------
# Layer 3: VBA 项目 dir 流 → 模块表
# ---------------------------------------------------------------------------

def parse_vba_dir(dir_bytes: bytes) -> list[dict]:
    modules: list[dict] = []
    current: dict = {}
    pos = 0
    n = len(dir_bytes)
    while pos + 6 <= n:
        rid = _u16(dir_bytes, pos)
        size = _u32(dir_bytes, pos + 2)
        payload = dir_bytes[pos + 6: pos + 6 + size]
        if rid == 0x0009:
            # PROJECTVERSION 违反 [Id][Size][Data] 框架：Size=Reserved=4
            # 但实际载荷是 Reserved(4)+VersionMajor(4)+VersionMinor(4)
            pos += 6 + 4 + 8
            continue
        if rid == 0x0019 and size <= 200:  # MODULENAME
            current = {"name": payload.decode("latin-1", "replace")}
        elif rid == 0x001A and current:  # MODULESTREAMNAME：Size=串长，无内嵌前缀
            current["stream"] = payload.decode("latin-1", "replace")
        elif rid == 0x0031 and current and size >= 4:  # MODULEOFFSET
            current["offset"] = _u32(payload, 0)
        elif rid in (0x0021, 0x0022, 0x002B) and current:  # MODULETYPE / 终结
            if "name" in current:
                current.setdefault("stream", current["name"])
                current.setdefault("offset", 0)
                modules.append(current)
            current = {}
        pos += 6 + size
    if "name" in current:
        current.setdefault("stream", current["name"])
        current.setdefault("offset", 0)
        modules.append(current)
    return modules


# ---------------------------------------------------------------------------
# Layer 4: VBA 源码 → SW API 调用序列
# ---------------------------------------------------------------------------

def _strip_comment(line: str) -> str:
    out = []
    in_str = False
    for ch in line:
        if ch == '"':
            in_str = not in_str
            out.append(ch)
        elif ch == "'" and not in_str:
            break
        else:
            out.append(ch)
    return "".join(out)


def _split_args(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        return []
    args: list[str] = []
    depth = 0
    in_str = False
    cur: list[str] = []
    for ch in raw:
        if ch == '"':
            in_str = not in_str
            cur.append(ch)
        elif not in_str and ch == "(":
            depth += 1
            cur.append(ch)
        elif not in_str and ch == ")":
            depth -= 1
            cur.append(ch)
        elif not in_str and ch == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    args.append("".join(cur).strip())
    return args


def _join_continuations(source: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    buf = ""
    start = 0
    for i, raw in enumerate(source.splitlines(), 1):
        if buf:
            buf = buf + " " + raw.strip()
        else:
            start = i
            buf = raw.rstrip()
        if buf.endswith(" _"):
            buf = buf[:-2].rstrip()
            continue
        out.append((start, buf))
        buf = ""
    if buf:
        out.append((start, buf))
    return out


def extract_api_calls(source: str) -> dict:
    declared: dict[str, str] = {}
    calls: list[dict] = []
    noise: list[dict] = []

    def record(chain: str, method: str, args_raw: str, line: int, stmt: str) -> None:
        # VBA 属性赋值（obj.Prop = value）在 chain 正则里表现为带 "=" 前缀的
        # args——标为 property_put（N9 教训：方法/属性二义须显式区分）
        property_put = False
        if args_raw.lstrip().startswith("="):
            property_put = True
            args_raw = args_raw.lstrip()[1:].strip()
        entry = {
            "line": line,
            "chain": chain,
            "method": method,
            "args": _split_args(args_raw),
            "property_put": property_put,
            "raw": stmt,
        }
        if method in NOISE_METHODS:
            noise.append(entry)
        else:
            entry["seq"] = len(calls) + 1
            calls.append(entry)

    for line_no, raw_line in _join_continuations(source):
        stmt = _strip_comment(raw_line).strip()
        if not stmt:
            continue
        head_kw = stmt.split(None, 1)[0].lower()
        if head_kw in _SKIP_KEYWORDS:
            dim_m = _DIM_RE.match(stmt)
            if dim_m:
                for piece in dim_m.group(1).split(","):
                    m = re.match(r"\s*([A-Za-z_]\w*(?:\(\))?)\s+As\s+([\w.]+)", piece + " ")
                    if m:
                        declared[m.group(1).strip("()")] = m.group(2)
            continue
        if head_kw in ("msgbox", "inputbox"):
            canonical = "MsgBox" if head_kw == "msgbox" else "InputBox"
            rest = stmt.split(None, 1)[1] if " " in stmt else ""
            record("", canonical, rest, line_no, stmt)
            continue
        body = stmt
        if not body.lower().startswith(("if", "for", "do", "while", "select", "with", "call")):
            set_m = _SET_RE.match(body)
            if set_m:
                var, body = set_m.group(1), set_m.group(2).strip()
                declared.setdefault(var, "expr")
        paren_m = _PAREN_CHAIN_RE.match(body)
        chain_m = _CHAIN_RE.match(body)
        if paren_m:
            chain, args_raw = paren_m.group(1), paren_m.group(2)
        elif chain_m:
            chain, args_raw = chain_m.group(1), chain_m.group(2) or ""
        else:
            continue
        head_var = chain.split(".", 1)[0]
        if head_var not in declared and head_var.lower() not in ("swapp", "swmodel", "application"):
            continue
        receiver, method = chain.rsplit(".", 1)
        record(receiver, method, args_raw, line_no, stmt)
    return {"declared": declared, "calls": calls, "noise": noise}


# ---------------------------------------------------------------------------
# Layer 5: transcribe —— 单入口
# ---------------------------------------------------------------------------

def _decode_text(data: bytes) -> str:
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _looks_like_vba(text: str) -> bool:
    return "Sub " in text or "Attribute VB_Name" in text or "Dim " in text


def extract_swp_modules(streams: dict[str, bytes]) -> list[dict]:
    """dir 流驱动提取；dir 异常时对 VBA 存储下的流做压缩容器兜底扫描。
    MS-OVBA 保证模块源码以 "Attribute VB_Name" 开头，作为定位判据。"""
    modules: list[dict] = []
    covered: set[str] = set()
    dir_bytes: bytes | None = None
    for name in streams:
        if name.rsplit("\\", 1)[-1] == "dir" and "VBA" in name:
            try:
                dir_bytes = decompress_ms_ovba(streams[name])
                break
            except ValueError:
                continue
    if dir_bytes is not None:
        for mod in parse_vba_dir(dir_bytes):
            leaf = mod.get("stream") or mod["name"]
            candidates = [
                p for p in streams
                if p.rsplit("\\", 1)[-1] == leaf and "VBA" in p
            ]
            stream_name = candidates[0] if candidates else leaf
            raw = streams.get(stream_name)
            if raw is None:
                continue
            try:
                source = _decode_text(decompress_ms_ovba(raw[mod.get("offset", 0):]))
            except ValueError:
                continue
            if source.startswith("Attribute VB_Name"):
                modules.append({"name": mod["name"], "source": source})
                covered.add(stream_name)
    for name, raw in streams.items():
        if name in covered or "VBA" not in name or len(raw) < 8:
            continue
        for off in range(0, len(raw) - 4):
            if raw[off] != 0x01:
                continue
            try:
                text = _decode_text(decompress_ms_ovba(raw[off:]))
            except ValueError:
                continue
            if text.startswith("Attribute VB_Name"):
                modules.append({"name": name.rsplit("\\", 1)[-1], "source": text})
                covered.add(name)
                break
    return modules


def transcribe(path: str, include_source: bool = False) -> dict:
    p = Path(path)
    data = p.read_bytes()
    if data[:8] == OLE_MAGIC:
        kind = "swp"
        modules = extract_swp_modules(read_ole_streams(data))
    else:
        kind = "text"
        modules = [{"name": p.stem, "source": _decode_text(data)}]
    combined = "\n".join(m["source"] for m in modules)
    api = extract_api_calls(combined)
    return {
        "file": str(p),
        "kind": kind,
        "module_count": len(modules),
        "modules": [
            {
                "name": m["name"],
                "source_len": len(m["source"]),
                **({"source": m["source"]} if include_source else {}),
            }
            for m in modules
        ],
        "declared": api["declared"],
        "calls": api["calls"],
        "noise": api["noise"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="N58 macro transcription parser")
    parser.add_argument("path", help=".swp / .swb / .txt / .bas macro file")
    parser.add_argument("--json", action="store_true", help="full JSON output")
    parser.add_argument("--source", action="store_true", help="embed VBA source in JSON")
    args = parser.parse_args(argv)
    try:
        result = transcribe(args.path, include_source=args.source)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["module_count"] else 2
    if not result["modules"]:
        print("no VBA modules extracted")
        return 2
    print(f"file: {result['file']}  kind={result['kind']}  modules={result['module_count']}")
    for m in result["modules"]:
        print(f"  module {m['name']}: {m['source_len']} chars")
    print(f"declared vars: {len(result['declared'])}")
    print(f"calls ({len(result['calls'])}):")
    for c in result["calls"]:
        arg_line = ", ".join(c["args"])
        print(f"  #{c['seq']:>3} L{c['line']:<4} {c['chain']}.{c['method']}({arg_line})")
    print(f"noise ({len(result['noise'])}): "
          f"{sorted({c['method'] for c in result['noise']})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
