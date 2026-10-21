"""Protobuf parsing, bit-for-bit serialization, and project metadata injection for Antigravity state.
Does not require external .proto definitions or compiler dependencies.
"""

import base64
import re
from typing import Any, Dict, Generator, List, Optional, Tuple


def varint_encode(n: int) -> bytes:
    """Encode an integer as a protobuf varint."""
    res = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            res.append(b | 0x80)
        else:
            res.append(b)
            break
    return bytes(res)


def varint_decode(data: bytes, offset: int = 0) -> Tuple[int, int]:
    """Decode a varint from data at offset. Returns (value, new_offset)."""
    val = 0
    shift = 0
    i = offset
    length = len(data)
    while True:
        if i >= length:
            raise IndexError("Unexpected EOF while reading varint")
        b = data[i]
        i += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return val, i


def parse_protobuf_stream(data: bytes) -> Generator[Tuple[int, int, Any], None, None]:
    """Parse raw protobuf wire bytes into a stream of (field_num, wire_type, value)."""
    i = 0
    length_data = len(data)
    while i < length_data:
        try:
            key, i = varint_decode(data, i)
        except IndexError:
            break
        field_num = key >> 3
        wire_type = key & 7

        if wire_type == 0:  # Varint
            val, i = varint_decode(data, i)
            yield (field_num, wire_type, val)
        elif wire_type == 2:  # Length-delimited
            length, i = varint_decode(data, i)
            val = data[i : i + length]
            i += length
            yield (field_num, wire_type, val)
        elif wire_type == 1:  # 64-bit
            val = data[i : i + 8]
            i += 8
            yield (field_num, wire_type, val)
        elif wire_type == 5:  # 32-bit
            val = data[i : i + 4]
            i += 4
            yield (field_num, wire_type, val)
        else:
            raise ValueError(f"Unsupported wire type {wire_type} at offset {i}")


def parse_protobuf_dict(data: bytes) -> Dict[int, List[Any]]:
    """Parse protobuf into a dictionary of field_number -> list of values."""
    res: Dict[int, List[Any]] = {}
    for fn, wt, val in parse_protobuf_stream(data):
        res.setdefault(fn, []).append((wt, val))
    return res


def extract_summary_metadata(raw_summary: bytes) -> Dict[str, Any]:
    """Extract metadata (title, steps, workspace, project_id) from a raw_summary blob."""
    res = {
        "title": "",
        "step_count": 0,
        "workspace_uri": "",
        "project_id": "",
        "last_user_step": 0,
    }
    if not raw_summary:
        return res

    try:
        fields = parse_protobuf_dict(raw_summary)

        # Field 1: Title / Preview
        if 1 in fields:
            val = fields[1][0][1]
            if isinstance(val, bytes):
                res["title"] = val.decode("utf-8", errors="ignore").strip()

        # Field 2: Step count
        if 2 in fields:
            res["step_count"] = int(fields[2][0][1])

        # Field 9 or 17: Workspace URI
        for fn in [9, 17]:
            if fn in fields:
                for wt, val in fields[fn]:
                    if isinstance(val, bytes):
                        m = re.search(rb"file:///[^\s\x00-\x1f\x7f-\xff\"']+", val)
                        if m:
                            try:
                                res["workspace_uri"] = m.group(0).decode("utf-8", errors="ignore")
                                break
                            except Exception:
                                pass
            if res["workspace_uri"]:
                break

        # Field 17 -> Field 18: Project ID
        if 17 in fields:
            for wt, val in fields[17]:
                if isinstance(val, bytes):
                    try:
                        m_fields = parse_protobuf_dict(val)
                        if 18 in m_fields:
                            res["project_id"] = m_fields[18][0][1].decode("ascii", errors="ignore")
                    except Exception:
                        pass

        # Field 16: Last user input step index
        if 16 in fields:
            res["last_user_step"] = int(fields[16][0][1])

    except Exception:
        pass

    return res


def inject_metadata_into_summary(
    raw_summary: bytes, project_id: str, workspace_uri: str = ""
) -> bytes:
    """Inject Field 18 (project_id) and Field 7 (workspace_uris) into
    Field 17 (trajectory_metadata) of CascadeTrajectorySummary.
    Ensures that Antigravity 2.0's 'Group by Project' associates the chat with this project.
    """
    if not raw_summary:
        # Create minimal summary if empty
        min_summary = bytearray()
        min_summary.extend(varint_encode((2 << 3) | 0))
        min_summary.extend(varint_encode(0))
        raw_summary = bytes(min_summary)

    fields = list(parse_protobuf_stream(raw_summary))
    new_raw = bytearray()
    has_17 = False

    for fn, wt, val in fields:
        if fn == 17 and wt == 2:
            has_17 = True
            subfields = list(parse_protobuf_stream(val))
            new_meta = bytearray()
            has_18 = False
            has_7 = False
            for s_fn, s_wt, s_val in subfields:
                if s_fn == 18:
                    has_18 = True
                    if project_id and project_id != "outside-of-project":
                        pid_bytes = project_id.encode("ascii")
                        new_meta.extend(varint_encode((18 << 3) | 2))
                        new_meta.extend(varint_encode(len(pid_bytes)))
                        new_meta.extend(pid_bytes)
                elif s_fn == 7:
                    has_7 = True
                    if workspace_uri:
                        ws_bytes = workspace_uri.encode("utf-8")
                        new_meta.extend(varint_encode((7 << 3) | 2))
                        new_meta.extend(varint_encode(len(ws_bytes)))
                        new_meta.extend(ws_bytes)
                    else:
                        new_meta.extend(varint_encode((7 << 3) | 2))
                        new_meta.extend(varint_encode(len(s_val)))
                        new_meta.extend(s_val)
                else:
                    new_meta.extend(varint_encode((s_fn << 3) | s_wt))
                    if s_wt == 0:
                        new_meta.extend(varint_encode(s_val))
                    elif s_wt == 2:
                        new_meta.extend(varint_encode(len(s_val)))
                        new_meta.extend(s_val)
                    elif s_wt in (1, 5):
                        new_meta.extend(s_val)

            if not has_18 and project_id and project_id != "outside-of-project":
                pid_bytes = project_id.encode("ascii")
                new_meta.extend(varint_encode((18 << 3) | 2))
                new_meta.extend(varint_encode(len(pid_bytes)))
                new_meta.extend(pid_bytes)

            if not has_7 and workspace_uri:
                ws_bytes = workspace_uri.encode("utf-8")
                new_meta.extend(varint_encode((7 << 3) | 2))
                new_meta.extend(varint_encode(len(ws_bytes)))
                new_meta.extend(ws_bytes)

            new_raw.extend(varint_encode((17 << 3) | 2))
            new_raw.extend(varint_encode(len(new_meta)))
            new_raw.extend(new_meta)
        else:
            new_raw.extend(varint_encode((fn << 3) | wt))
            if wt == 0:
                new_raw.extend(varint_encode(val))
            elif wt == 2:
                new_raw.extend(varint_encode(len(val)))
                new_raw.extend(val)
            elif wt in (1, 5):
                new_raw.extend(val)

    if not has_17:
        new_meta = bytearray()
        if project_id and project_id != "outside-of-project":
            pid_bytes = project_id.encode("ascii")
            new_meta.extend(varint_encode((18 << 3) | 2))
            new_meta.extend(varint_encode(len(pid_bytes)))
            new_meta.extend(pid_bytes)
        if workspace_uri:
            ws_bytes = workspace_uri.encode("utf-8")
            new_meta.extend(varint_encode((7 << 3) | 2))
            new_meta.extend(varint_encode(len(ws_bytes)))
            new_meta.extend(ws_bytes)

        if new_meta:
            new_raw.extend(varint_encode((17 << 3) | 2))
            new_raw.extend(varint_encode(len(new_meta)))
            new_raw.extend(new_meta)

    return bytes(new_raw)


def wrap_summary_for_vscdb(raw_summary: bytes) -> bytes:
    """Wrap raw_summary bytes for state.vscdb trajectorySummaries.
    In state.vscdb, subfield 2 is a protobuf message with Field 1 = base64(raw_summary).
    """
    b64_str = base64.b64encode(raw_summary).decode("ascii")
    b64_bytes = b64_str.encode("ascii")
    wrapped = bytearray()
    wrapped.extend(varint_encode((1 << 3) | 2))
    wrapped.extend(varint_encode(len(b64_bytes)))
    wrapped.extend(b64_bytes)
    return bytes(wrapped)


def unwrap_summary_from_vscdb(s2_bytes: bytes) -> bytes:
    """Extract raw_summary from state.vscdb trajectorySummaries subfield 2.
    If wrapped in a single-field base64 message, unwrap it.
    Otherwise return s2_bytes directly.
    """
    try:
        fields = parse_protobuf_dict(s2_bytes)
        # Wrapper message has ONLY field 1
        if len(fields) == 1 and 1 in fields and isinstance(fields[1][0][1], bytes):
            candidate = fields[1][0][1]
            if all(32 <= b <= 126 for b in candidate):
                dec = base64.b64decode(candidate)
                if len(dec) > 10 and (dec.startswith(b"\n") or dec.startswith(b"\x10")):
                    inner_fields = parse_protobuf_dict(dec)
                    if len(inner_fields) >= 2:
                        return dec
    except Exception:
        pass
    return s2_bytes


def parse_trajectory_summaries(data: bytes) -> List[Tuple[str, bytes]]:
    """Parse repeated trajectory entries from trajectorySummaries or agyhub_summaries_proto.pb.
    Returns list of (conversation_id, raw_summary_bytes).
    """
    entries = []
    for fn, wt, item_bytes in parse_protobuf_stream(data):
        if fn == 1 and wt == 2:
            cid = ""
            raw_summary = b""
            for s_fn, s_wt, s_val in parse_protobuf_stream(item_bytes):
                if s_fn == 1 and s_wt == 2:
                    cid = s_val.decode("ascii", errors="ignore").strip()
                elif s_fn == 2 and s_wt == 2:
                    raw_summary = unwrap_summary_from_vscdb(s_val)

            if cid:
                entries.append((cid, raw_summary))
    return entries


def encode_repeated_trajectory_entry(cid: str, summary_bytes: bytes) -> bytes:
    """Encode a single trajectory entry into protobuf repeated field 1 wire format."""
    item = bytearray()
    cid_bytes = cid.encode("ascii")

    # Subfield 1: CID
    item.extend(varint_encode((1 << 3) | 2))
    item.extend(varint_encode(len(cid_bytes)))
    item.extend(cid_bytes)

    # Subfield 2: summary bytes
    item.extend(varint_encode((2 << 3) | 2))
    item.extend(varint_encode(len(summary_bytes)))
    item.extend(summary_bytes)

    # Wrap in Field 1
    entry = bytearray()
    entry.extend(varint_encode((1 << 3) | 2))
    entry.extend(varint_encode(len(item)))
    entry.extend(item)
    return bytes(entry)


def merge_proto_summaries(
    existing_data: bytes,
    new_entries: Dict[str, bytes],
    wrap_for_vscdb: bool = False,
) -> bytes:
    """Merge new (cid -> raw_summary) entries into existing protobuf data,
    preserving order and overwriting existing cids if updated.
    If wrap_for_vscdb is True, wraps subfield 2 in Field 1 = base64(raw_summary).
    """
    entries = parse_trajectory_summaries(existing_data)
    entry_map = {cid: raw for cid, raw in entries}

    ordered_cids = [cid for cid, _ in entries]
    for cid in new_entries:
        if cid not in entry_map:
            ordered_cids.append(cid)

    entry_map.update(new_entries)

    output = bytearray()
    for cid in ordered_cids:
        raw = entry_map.get(cid, b"")
        sub2_data = wrap_summary_for_vscdb(raw) if wrap_for_vscdb else raw
        output.extend(encode_repeated_trajectory_entry(cid, sub2_data))

    return bytes(output)
