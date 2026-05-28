# -*- coding: utf-8 -*-
"""查询/设置结果解析与格式说明展示。"""
from __future__ import annotations

from dataclasses import dataclass

from .protocol import (
    CLASS_NAMES,
    DataValue,
    Frame,
    decode_value,
    describe_value_status,
    format_hex,
    format_hex_display,

)


@dataclass
class ResultRow:
    index: int
    code: str
    name: str
    category: str
    class_name: str
    element_id: int
    value_hex: str
    value_text: str
    explanation: str = ""
    status_hex: str | None = None
    status_text: str | None = None
    error_hint: str | None = None
    ok: bool | None = None


def _resolve_catalog_item(code: str, lookup: dict[str, dict] | None) -> dict | None:
    if not lookup:
        return None
    if code in lookup:
        return lookup[code]
    parts = code.split(".")
    if len(parts) == 4:
        for alt in (f"{parts[0]}.{parts[1]}.{parts[2]}.0", code):
            if alt in lookup:
                return lookup[alt]
    return None


def _value_format_hint(param_name: str) -> str:
    n = param_name or ""
    rules: list[tuple[tuple[str, ...], str]] = [
        (("周期",), "无符号整数，单位：秒（通常 4 字节）"),
        (("时长链", "阶段时长"), "阶段时长序列，每阶段 2 字节大端，单位：秒"),
        (("阶段顺序",), "阶段编号顺序，多字节按序排列"),
        (("出现方式", "出现链"), "各阶段出现方式，每字节一种模式（如 0x10）"),
        (("协调阶段",), "无符号整数，表示协调阶段号"),
        (("相位差",), "无符号整数，单位：秒"),
        (("路口", "路口号"), "无符号整数，方案关联的路口编号"),
        (("方案",), "方案相关参数，元素编号即方案号"),
        (("灯组",), "灯组相关参数，元素编号即灯组号"),
        (("相位",), "相位相关参数，元素编号即相位号"),
        (("检测器",), "检测器相关参数，元素编号即检测器号"),
        (("厂商", "版本", "编号", "名称"), "字符串（UTF-8 或 ASCII）"),
        (("日期", "时间"), "日期时间：7 字节（年2+月日时分秒）或协议规定格式"),
        (("链", "序列"), "多字节序列，按序解析各项"),
    ]
    for keys, hint in rules:
        if any(k in n for k in keys):
            return hint
    return "按 GB/T 20999 数据值编码，见协议对象属性定义"


def explain_query_value(
    code: str,
    param_name: str,
    element_id: int,
    value: bytes,
    catalog_item: dict | None,
    *,
    ok: bool,
    status: int | None,
    error_hint: str,
) -> str:
    if not ok:
        parts = [f"查询失败：{describe_value_status(status)[0]}"]
        if error_hint:
            parts.append(f"排查建议：{error_hint}")
        if status is not None:
            parts.append(f"值状态码 0x{status:02X}")
        return "；".join(parts)

    if not value:
        return "查询成功，但应答中无数据值（可能为空属性或仅返回状态）"

    decoded = decode_value(value)
    fmt = _value_format_hint(param_name)
    parts: list[str] = []

    if catalog_item and catalog_item.get("note"):
        parts.append(catalog_item["note"])

    if element_id:
        parts.append(f"元素编号 {element_id} 用于定位具体对象（如方案/灯组/相位号）")

    parts.append(f"数据格式：{fmt}")

    n = param_name or ""
    if "周期" in n:
        parts.append(f"当前周期 = {decoded} 秒")
    elif "路口" in n:
        parts.append(f"当前路口号 = {decoded}")
    elif "协调阶段" in n:
        parts.append(f"当前协调阶段 = {decoded}")
    elif "相位差" in n:
        parts.append(f"当前相位差 = {decoded} 秒")
    elif len(value) > 4 and "链" in n:
        parts.append(f"序列内容：{decoded}")
    elif len(value) == 7 and ("日期" in n or "时间" in n):
        parts.append(f"日期时间：{decoded}")
    else:
        parts.append(f"解析结果：{decoded}")

    if catalog_item and catalog_item.get("sample_value") not in (None, ""):
        parts.append(f"参考样例值：{catalog_item['sample_value']}")

    return "；".join(parts)


def _lookup_name(code: str, lookup: dict[str, dict] | None) -> tuple[str, str, dict | None]:
    item = _resolve_catalog_item(code, lookup)
    if item:
        return item.get("name", ""), item.get("category", ""), item
    return "", "", None


def query_rows_from_frame(frame: Frame, lookup: dict[str, dict] | None = None) -> list[ResultRow]:
    rows: list[ResultRow] = []
    for dv in frame.data_values:
        code = dv.address.code_str()
        name, category, item = _lookup_name(code, lookup)
        cls_name = CLASS_NAMES.get(dv.address.class_id, f"类{dv.address.class_id}")
        pname = name or "(未命名)"
        dv_status_for_explain: int | None = None
        if dv.status is not None:
            status_label, hint, ok = describe_value_status(dv.status)
        elif frame.frame_type == 0x21:
            status_label, hint, ok = describe_value_status(0x30)
            dv_status_for_explain = 0x30
        else:
            status_label, hint, ok = describe_value_status(0)
            dv_status_for_explain = None
        explanation = explain_query_value(
            code,
            pname,
            dv.address.element_id,
            dv.value,
            item,
            ok=ok,
            status=dv.status if dv.status is not None else dv_status_for_explain,
            error_hint=hint if not ok else "",
        )
        st_hex = (
            f"0x{dv.status:02X}"
            if dv.status is not None
            else (f"0x{dv_status_for_explain:02X}" if dv_status_for_explain is not None else ("0x00" if ok else "—"))
        )
        rows.append(
            ResultRow(
                index=dv.index,
                code=code,
                name=pname,
                category=category or cls_name,
                class_name=cls_name,
                element_id=dv.address.element_id,
                value_hex=format_hex(dv.value) if dv.value else (st_hex if not ok else ""),
                value_text=decode_value(dv.value) if dv.value else ("—" if ok else ""),
                explanation=explanation,
                status_hex=st_hex,
                status_text=status_label,
                error_hint=hint if not ok else None,
                ok=ok,
            )
        )
    return rows


def summarize_query_ack(rows: list[ResultRow]) -> tuple[str, str]:
    """返回 (摘要文字, 颜色键 ok|partial|fail)。"""
    if not rows:
        return "应答无数据值", "partial"
    ok_count = sum(1 for r in rows if r.ok is True)
    fail_count = sum(1 for r in rows if r.ok is False)
    if fail_count == 0:
        return f"全部查询成功 ({ok_count}/{len(rows)})", "ok"
    if ok_count == 0:
        return f"全部查询失败 ({fail_count}/{len(rows)})", "fail"
    return f"部分成功：成功 {ok_count}，失败 {fail_count}，共 {len(rows)} 项", "partial"


def query_explanation_report(
    frame: Frame,
    lookup: dict[str, dict] | None,
    *,
    pending_seq: int | None = None,
    sent_at: str | None = None,
) -> str:
    rows = query_rows_from_frame(frame, lookup)
    summary, _ = summarize_query_ack(rows)
    ft_note = ""
    if frame.frame_type == 0x21:
        ft_note = "（否定应答，含错误值状态，仍属查询回复）"
    lines: list[str] = [
        "════════ 查询应答格式解析说明 ════════",
        f"帧类型：{frame.type_name} (0x{frame.frame_type:02X}){ft_note}",
        f"总体结果：{summary}",
        f"应答时间：{sent_at or '—'}",
        f"流水号：{frame.config.seq}"
        + (
            f"（与本次查询发送一致）"
            if pending_seq is not None and frame.config.seq == pending_seq
            else ""
        ),
        f"信号机 ID：0x{frame.config.signal_id:08X}  路口 ID：{frame.config.cross_id}",
        f"共返回 {len(frame.data_values)} 项数据值",
        "",
        "字段说明：",
        "  · 查询结果 — 根据值状态(附录A)判断该项是否成功；",
        "  · 值状态码 — 0x00 成功，0x01~0x0A 为各类异常；",
        "  · 格式说明 — 成功时为数据含义，失败时为排查建议。",
        "────────────────────────────────────────",
    ]
    for r in rows:
        lines.append(f"\n【数据值 {r.index}】{r.code}  {r.name}")
        lines.append(f"  查询结果：{'✓ 成功' if r.ok else '✗ 失败'}")
        lines.append(f"  值状态：{r.status_text} ({r.status_hex})")
        if not r.ok and r.error_hint:
            lines.append(f"  排查建议：{r.error_hint}")
        lines.append(f"  数据类：{r.category}（{r.class_name}）")
        lines.append(f"  元素编号：{r.element_id}")
        if r.value_hex:
            lines.append(f"  原始 HEX：{r.value_hex}")
            lines.append(f"  解析值：{r.value_text}")
        lines.append(f"  格式说明：{r.explanation}")
    lines.append("\n════════════════════════════════════════")
    return "\n".join(lines)


def frame_structure_report(frame: Frame, raw: bytes, lookup: dict[str, dict] | None = None) -> str:
    from .protocol import frame_to_text

    lines = [
        "──────── GB/T 20999 报文结构拆解 ────────",
        f"原始报文 ({len(raw)} 字节)：",
        format_hex_display(raw),
        "",
        frame_to_text(frame, lookup),
    ]
    return "\n".join(lines)


def set_ack_rows_from_frame(frame: Frame, lookup: dict[str, dict] | None = None) -> list[ResultRow]:
    rows: list[ResultRow] = []
    for dv in frame.data_values:
        code = dv.address.code_str()
        name, category, item = _lookup_name(code, lookup)
        cls_name = CLASS_NAMES.get(dv.address.class_id, f"类{dv.address.class_id}")
        status = dv.status if dv.status is not None else 0
        status_label, hint, ok = describe_value_status(status)
        rows.append(
            ResultRow(
                index=dv.index,
                code=code,
                name=name or "(未命名)",
                category=category or cls_name,
                class_name=cls_name,
                element_id=dv.address.element_id,
                value_hex=format_hex(dv.value) if dv.value else "",
                value_text=decode_value(dv.value) if dv.value else "",
                explanation=hint if not ok else "信号机已接受该参数设置",
                status_hex=f"0x{status:02X}",
                status_text=status_label,
                error_hint=hint if not ok else None,
                ok=ok,
            )
        )
    return rows


def summarize_set_ack(rows: list[ResultRow]) -> str:
    if not rows:
        return "无设置应答数据"
    ok_count = sum(1 for r in rows if r.ok is True)
    fail_count = sum(1 for r in rows if r.ok is False)
    unknown = len(rows) - ok_count - fail_count
    if fail_count == 0 and unknown == 0:
        return f"全部成功 ({ok_count}/{len(rows)})"
    if ok_count == 0 and unknown == 0:
        return f"全部失败 ({fail_count}/{len(rows)})"
    return f"成功 {ok_count}，失败 {fail_count}，未知 {unknown}，共 {len(rows)} 项"
