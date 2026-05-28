# -*- coding: utf-8 -*-
"""GB/T 20999-2017 报文编解码与解析。"""
from __future__ import annotations

import json
import re
import struct
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def _app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _resource_path(name: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundled = Path(sys._MEIPASS) / name
        if bundled.exists():
            return bundled
    external = _app_base_dir() / name
    if external.exists():
        return external
    return Path(__file__).resolve().parent.parent / name

FRAME_START = 0x7E
FRAME_END = 0x7D

FRAME_TYPE_NAMES = {
    0x10: "查询",
    0x20: "查询应答",
    0x21: "查询应答(异常)",
    0x30: "设置",
    0x40: "设置应答",
    0x60: "主动上报",
    0x70: "心跳查询",
    0x71: "心跳应答",
}

# 查询类应答（含带错状态否定应答 0x21）
QUERY_REPLY_TYPES = {0x20, 0x21}

# 应答 / 上报 分区
REPLY_TYPES = {0x20, 0x21, 0x40, 0x71}
REPORT_TYPES = {0x60}

CLASS_NAMES = {
    1: "设备信息",
    2: "基础信息",
    3: "灯组信息",
    4: "相位信息",
    5: "检测器信息",
    6: "相位阶段信息",
    7: "安全信息",
    8: "紧急优先",
    9: "方案信息",
    10: "过渡约束",
    11: "日计划",
    12: "调度表",
    13: "运行状态",
    14: "交通数据",
    15: "报警数据",
    16: "故障数据",
    17: "中心控制",
    18: "命令通道",
    128: "实时状态(扩展)",
    130: "可变车道(扩展)",
    131: "匝道运行状态(扩展)",
    134: "临时方案反馈(扩展)",
    136: "优先控制反馈(扩展)",
    137: "倒计时状态(扩展)",
    138: "倒计时9S(扩展)",
}

# GB/T 20999-2017 附录 A 值状态（查询/设置应答数据值内）
VALUE_STATUS: dict[int, tuple[str, str]] = {
    0x00: ("成功", "数据值正常，查询或设置已成功完成"),
    0x01: ("数据对象不存在", "数据类ID或对象ID无效，请核对参数编号是否在信号机中配置"),
    0x02: ("元素不存在", "元素编号无效，如方案号/灯组号/相位号不存在"),
    0x03: ("属性不存在", "属性ID无效，请确认该对象是否支持此属性"),
    0x04: ("属性不可读", "该属性不支持查询，仅可设置或不可访问"),
    0x05: ("属性不可写", "该属性只读，不可通过设置报文修改"),
    0x06: ("数据类型不匹配", "设置值长度或类型与协议定义不符"),
    0x07: ("数据值超出范围", "设置值超出允许范围，请检查数值或方案约束"),
    0x08: ("访问被拒绝", "当前运行状态下不允许访问，可稍后重试或检查控制模式"),
    0x09: ("设备忙", "信号机忙，请稍后重试"),
    0x0A: ("其他错误", "未分类错误，请对照信号机文档或抓包排查"),
    0x30: (
        "查询响应错误",
        "信号机以帧类型 0x21 返回否定应答，无法正确完成查询；"
        "常见于中心控制类参数、当前运行模式不允许或对象未配置",
    ),
}


def is_query_reply(frame_type: int) -> bool:
    return frame_type in QUERY_REPLY_TYPES


def describe_value_status(status: int | None) -> tuple[str, str, bool]:
    """返回 (简短描述, 排查提示, 是否成功)。"""
    if status is None:
        return "—", "", True
    if status == 0:
        return VALUE_STATUS[0][0], VALUE_STATUS[0][1], True
    name, hint = VALUE_STATUS.get(status, ("未知状态", "非标准值状态码，请查阅 GB/T 20999 附录 A"))
    return name, hint, False


def format_hex_wrapped(data: bytes, bytes_per_line: int = 16) -> str:
    """HEX 按行折行，便于窄窗口阅读。"""
    if not data:
        return ""
    parts = [f"{b:02X}" for b in data]
    lines = [
        " ".join(parts[i : i + bytes_per_line])
        for i in range(0, len(parts), bytes_per_line)
    ]
    return "\n".join(lines)


def parse_query_reply_data(frame_type: int, rest: bytes) -> tuple[int, bytes]:
    """解析查询应答 0x20 / 查询否定应答 0x21 的数据值区。"""
    if frame_type == 0x21:
        if not rest:
            return 0x30, b""
        if len(rest) == 1:
            return rest[0], b""
        if rest[0] in VALUE_STATUS or rest[0] >= 0x01:
            return rest[0], rest[1:]
        return rest[0], rest[1:]
    return parse_read_data_value(rest)


def parse_read_data_value(rest: bytes) -> tuple[int, bytes]:
    """解析查询应答(0x20)中地址后的「值状态 + 数据值」。

    规则（与需求样例及协议库样例一致）：
    - 仅 1 字节：视为紧凑数据值（无显式值状态），如路口号=0x01；
    - 2 字节及以上且首字节为 0x00：值状态成功 + 后续为数据值；
    - 2 字节及以上且首字节为 0x01~0x0A：值状态异常 + 后续为可选补充数据。
  """
    if not rest:
        return 0, b""
    if len(rest) == 1:
        return 0, rest
    if rest[0] == 0:
        return 0, rest[1:]
    if rest[0] in VALUE_STATUS and rest[0] != 0:
        return rest[0], rest[1:]
    return 0, rest


def crc16_gb20999(data: bytes) -> int:
    """GB/T 20999 CRC-16：生成多项式 0x1005，初值 0x0000，按字节高位在前移位。

    校验范围：帧头 0x7E 之后至 CRC 之前的全部字节（报文长度 + 协议头 + 数据区）。
    与 crc校验逻辑.txt / 需求描述样例一致。
    """
    polynomial = 0x1005
    crc = 0x0000
    for b in data:
        crc ^= (b << 8) & 0xFFFF
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ polynomial) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def parse_hex(text: str) -> bytes:
    text = re.sub(r"[^0-9a-fA-F]", "", text)
    if len(text) % 2:
        raise ValueError("十六进制长度必须为偶数")
    return bytes.fromhex(text)


def format_hex(data: bytes, sep: str = " ") -> str:
    return sep.join(f"{b:02X}" for b in data)


def format_hex_display(data: bytes, max_single_line: int = 64) -> str:
    """短报文单行，长报文自动折行。"""
    if len(data) <= max_single_line:
        return format_hex(data)
    return format_hex_wrapped(data)


@dataclass
class ProtocolConfig:
    version_major: int = 1
    version_minor: int = 0
    host_id: int = 7
    signal_id: int = 0x009A2109
    cross_id: int = 0
    seq: int = 1

    @property
    def version_bytes(self) -> bytes:
        return bytes([self.version_major & 0xFF, self.version_minor & 0xFF])

    @property
    def signal_id_bytes(self) -> bytes:
        return struct.pack(">I", self.signal_id & 0xFFFFFFFF)


@dataclass
class DataAddress:
    class_id: int
    object_id: int
    attr_id: int
    element_id: int = 0

    def to_bytes(self) -> bytes:
        return bytes([self.class_id, self.object_id, self.attr_id, self.element_id & 0xFF])

    @classmethod
    def from_bytes(cls, data: bytes) -> "DataAddress":
        if len(data) < 4:
            raise ValueError("地址至少 4 字节")
        return cls(data[0], data[1], data[2], data[3])

    def code_str(self) -> str:
        if self.element_id:
            return f"{self.class_id}.{self.object_id}.{self.attr_id}.{self.element_id}"
        return f"{self.class_id}.{self.object_id}.{self.attr_id}.0"


@dataclass
class DataValue:
    index: int
    address: DataAddress
    value: bytes = b""
    status: int | None = None

    @property
    def is_query_descriptor(self) -> bool:
        return not self.value and self.status is None


@dataclass
class Frame:
    config: ProtocolConfig
    frame_type: int
    data_values: list[DataValue] = field(default_factory=list)
    raw: bytes = b""

    @property
    def type_name(self) -> str:
        return FRAME_TYPE_NAMES.get(self.frame_type, f"未知(0x{self.frame_type:02X})")

    @property
    def zone(self) -> str:
        if self.frame_type in REPLY_TYPES:
            return "reply"
        if self.frame_type in REPORT_TYPES:
            return "report"
        return "other"


def build_frame(
    config: ProtocolConfig,
    frame_type: int,
    data_values: list[DataValue],
    crc_fn=crc16_gb20999,
) -> bytes:
    payload = bytearray()
    payload += config.version_bytes
    payload.append(config.host_id & 0xFF)
    payload += config.signal_id_bytes
    payload.append(config.cross_id & 0xFF)
    payload.append(config.seq & 0xFF)
    payload.append(frame_type & 0xFF)
    payload.append(len(data_values) & 0xFF)

    for dv in data_values:
        payload.append(dv.index & 0xFF)
        addr = dv.address.to_bytes()
        if frame_type == 0x10:
            payload.append(0x04)
            payload += addr
        else:
            body = addr + dv.value
            if dv.status is not None:
                body = bytes([dv.status & 0xFF]) + body
            payload.append(len(body) & 0xFF)
            payload += body

    length = len(payload) + 2
    body = struct.pack(">H", length) + payload
    crc = crc_fn(body)
    return bytes([FRAME_START]) + body + struct.pack(">H", crc) + bytes([FRAME_END])


def build_query_frame(config: ProtocolConfig, addresses: list[DataAddress]) -> bytes:
    values = [
        DataValue(index=i + 1, address=addr)
        for i, addr in enumerate(addresses)
    ]
    return build_frame(config, 0x10, values)


def build_heartbeat_query(config: ProtocolConfig) -> bytes:
    return build_frame(config, 0x70, [])


def build_heartbeat_response(config: ProtocolConfig) -> bytes:
    return build_frame(config, 0x71, [])


def _parse_int_list(text: str) -> list[int]:
    return [int(x) for x in re.split(r"[,，\s]+", text.strip()) if x.strip().isdigit()]


def encode_set_value_for_item(item: dict | None, text: str, width: int | None = None) -> bytes:
    """按参数类型编码设置值（含方案链类固定长度字段）。"""
    text = text.strip()
    if not text:
        return b""
    name = (item or {}).get("name") or ""
    if "阶段顺序" in name:
        nums = _parse_int_list(text)
        body = bytes(12) + bytes([n & 0xFF for n in nums])
        return body.ljust(16, b"\x00")[:16]
    if "时长链" in name or "阶段时长" in name:
        nums = _parse_int_list(text)
        body = bytearray(24)
        for n in nums:
            body.extend(struct.pack(">H", n & 0xFFFF))
        return bytes(body).ljust(32, b"\x00")[:32]
    if "出现" in name and "链" in name:
        nums = _parse_int_list(text)
        body = bytes(12) + bytes([n & 0xFF for n in nums])
        return body.ljust(16, b"\x00")[:16]
    if "周期" in name:
        return int(text).to_bytes(4, "big")
    if "相位差" in name:
        return int(text).to_bytes(2, "big")
    return encode_set_value(text, width)


def encode_set_value(text: str, hint: str | int | None = None) -> bytes:
    """将用户输入编码为设置值字节。"""
    text = text.strip()
    if not text:
        return b""
    compact = re.sub(r"[^0-9a-fA-F]", "", text)
    if len(compact) >= 2 and len(compact) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in compact):
        if " " in text or len(compact) > 2 or text.lower().startswith("0x"):
            return bytes.fromhex(compact)
    if compact.isdigit() and " " not in text.strip():
        num = int(compact)
        if isinstance(hint, int) and hint > 0:
            width = hint
        elif num <= 0xFF:
            width = 1
        elif num <= 0xFFFF:
            width = 2
        else:
            width = 4
        return num.to_bytes(width, "big")
    return text.encode("utf-8")


def guess_value_width(item: dict | None, sample_value: Any) -> int:
    if item and item.get("name"):
        n = item["name"]
        if "链" in n or "序列" in n or "时间" in n and "标准" not in n:
            return 0
    if sample_value is None or sample_value == "":
        return 1
    if isinstance(sample_value, int):
        if sample_value <= 0xFF:
            return 1
        if sample_value <= 0xFFFF:
            return 2
        return 4
    if isinstance(sample_value, str):
        if re.fullmatch(r"[0-9a-fA-F ]+", sample_value):
            hex_len = len(re.sub(r"\s+", "", sample_value))
            return hex_len // 2 if hex_len else 1
        return len(sample_value.encode("utf-8"))
    return 1


def build_set_frame(
    config: ProtocolConfig,
    entries: list[tuple[DataAddress, bytes]],
) -> bytes:
    values = [
        DataValue(index=i + 1, address=addr, value=val)
        for i, (addr, val) in enumerate(entries)
    ]
    return build_frame(config, 0x30, values)


def decode_value(data: bytes) -> str:
    if not data:
        return "(空)"
    if len(data) == 1:
        return str(data[0])
    if len(data) == 2:
        return str(int.from_bytes(data, "big"))
    if len(data) == 4:
        v = int.from_bytes(data, "big")
        if data[0] == 0 and data[1] == 0:
            return str(v)
        return str(v)
    try:
        text = data.decode("utf-8").strip("\x00")
        if text and all(c.isprintable() or c.isspace() for c in text):
            return text
    except UnicodeDecodeError:
        pass
    if len(data) == 7:
        y = int.from_bytes(data[0:2], "big")
        m, d, h, mi, s = data[2:7]
        return f"{y:04d}-{m:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"
    return format_hex(data)


def parse_frame(raw: bytes) -> Frame:
    if len(raw) < 8:
        raise ValueError("报文过短")
    if raw[0] != FRAME_START or raw[-1] != FRAME_END:
        raise ValueError("帧头/帧尾不正确")

    body = raw[1:-3]
    crc_recv = int.from_bytes(raw[-3:-1], "big")
    crc_calc = crc16_gb20999(body)
    if crc_recv != crc_calc:
        raise ValueError(
            f"CRC 校验失败: 接收 {crc_recv:04X} 计算 {crc_calc:04X} "
            f"(校验范围: 长度域至数据区末, 共 {len(body)} 字节)"
        )

    length = int.from_bytes(body[0:2], "big")
    offset = 2
    ver = body[offset : offset + 2]
    offset += 2
    host_id = body[offset]
    offset += 1
    signal_id = int.from_bytes(body[offset : offset + 4], "big")
    offset += 4
    cross_id = body[offset]
    offset += 1
    seq = body[offset]
    offset += 1
    frame_type = body[offset]
    offset += 1
    count = body[offset]
    offset += 1

    config = ProtocolConfig(
        version_major=ver[0],
        version_minor=ver[1],
        host_id=host_id,
        signal_id=signal_id,
        cross_id=cross_id,
        seq=seq,
    )
    values: list[DataValue] = []
    for _ in range(count):
        if offset >= len(body):
            break
        idx = body[offset]
        offset += 1
        dlen = body[offset]
        offset += 1
        chunk = body[offset : offset + dlen]
        offset += dlen
        if frame_type == 0x10 and dlen == 4:
            addr = DataAddress.from_bytes(chunk)
            values.append(DataValue(index=idx, address=addr))
        elif dlen >= 4:
            addr = DataAddress.from_bytes(chunk[:4])
            rest = chunk[4:]
            status = None
            value = rest
            if frame_type == 0x40:
                if rest:
                    status = rest[0]
                    value = rest[1:]
            elif frame_type in QUERY_REPLY_TYPES:
                status, value = parse_query_reply_data(frame_type, rest)
            elif frame_type == 0x30:
                value = rest
            else:
                if rest and len(rest) > 1 and frame_type not in (0x60, 0x71):
                    status = rest[0]
                    value = rest[1:]
            values.append(DataValue(index=idx, address=addr, value=value, status=status))
        else:
            values.append(
                DataValue(
                    index=idx,
                    address=DataAddress(0, 0, 0, 0),
                    value=chunk,
                )
            )

    return Frame(config=config, frame_type=frame_type, data_values=values, raw=raw)


def frame_to_text(frame: Frame, catalog_lookup: dict[str, dict] | None = None) -> str:
    lines = [
        f"帧类型: {frame.type_name} (0x{frame.frame_type:02X})",
        f"协议版本: {frame.config.version_major}.{frame.config.version_minor}",
        f"上位机ID: {frame.config.host_id}",
        f"信号机ID: 0x{frame.config.signal_id:08X}",
        f"路口ID: {frame.config.cross_id}",
        f"流水号: {frame.config.seq}",
        f"数据值数量: {len(frame.data_values)}",
        "-" * 50,
    ]
    for dv in frame.data_values:
        code = dv.address.code_str()
        cls_name = CLASS_NAMES.get(dv.address.class_id, f"类{dv.address.class_id}")
        name = ""
        if catalog_lookup and code in catalog_lookup:
            name = catalog_lookup[code].get("name", "")
        lines.append(f"[{dv.index}] {code} {cls_name} {name}")
        lines.append(
            f"    地址: 类={dv.address.class_id} 对象={dv.address.object_id} "
            f"属性={dv.address.attr_id} 元素={dv.address.element_id}"
        )
        if dv.status is not None:
            lines.append(f"    值状态: 0x{dv.status:02X}")
        if dv.value:
            lines.append(f"    值(HEX): {format_hex(dv.value)}")
            lines.append(f"    值(解析): {decode_value(dv.value)}")
    return "\n".join(lines)


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        path = _resource_path("protocol_catalog.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    lookup: dict[str, dict] = {}
    for item in data.get("items", []):
        lookup[item["code"]] = item
    data["lookup"] = lookup
    return data


def patch_element_in_sample(sample_hex: str, element_id: int) -> str:
    """在样例查询报文中替换元素 ID 并重新计算 CRC。"""
    raw = parse_hex(sample_hex)
    if len(raw) < 8 or raw[-1] != FRAME_END:
        return sample_hex
    # 单条查询：... 类 对象 属性 元素 | CRC(2) | 7D
    elem_pos = len(raw) - 4
    buf = bytearray(raw)
    buf[elem_pos] = element_id & 0xFF
    body = bytes(buf[1:-3])
    buf[-3:-1] = struct.pack(">H", crc16_gb20999(body))
    return format_hex(bytes(buf))
