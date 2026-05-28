# -*- coding: utf-8 -*-
"""GB/T 20999 上位机 GUI — 查询页 + 参数设置页。"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import messagebox, scrolledtext, ttk
from typing import Any

from .ip_history import load_ip_history, save_ip_to_history
from .protocol import (
    DataAddress,
    ProtocolConfig,
    build_heartbeat_query,
    build_heartbeat_response,
    build_query_frame,
    build_set_frame,
    encode_set_value,
    encode_set_value_for_item,
    format_hex,
    format_hex_display,
    frame_to_text,
    guess_value_width,
    is_query_reply,
    load_catalog,
    parse_frame,
    parse_hex,
    patch_element_in_sample,
)
from .result_view import (
    frame_structure_report,
    query_explanation_report,
    query_rows_from_frame,
    set_ack_rows_from_frame,
    summarize_query_ack,
    summarize_set_ack,
)
from .udp_comm import UdpComm


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("GB/T 20999 信号机通信上位机")
        self.geometry("1360x860")
        self.minsize(1150, 720)

        self.catalog = load_catalog()
        self.lookup = self.catalog.get("lookup", {})
        self.comm = UdpComm()
        self.comm.on_receive = self._on_receive
        self.comm.on_log = self._append_log

        self._query_selected: list[dict] = []  # {"item", "element"}
        self._pending_query_seq: int | None = None
        self._query_sent_at: str | None = None
        self._last_query_raw: bytes | None = None
        self._last_query_frame = None
        self._frame_structure_win: tk.Toplevel | None = None
        self._set_entries: list[dict] = []
        self._tree_items: dict[str, dict] = {}
        self._category_nodes: dict[str, str] = {}

        self._build_fixed_header()
        self._build_main_body()
        self._build_log_area()
        self._populate_tree()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- 顶部紧凑通信栏（为右侧查询回复留出空间） ----------
    def _build_fixed_header(self) -> None:
        wrap = ttk.Frame(self, padding=(8, 6, 8, 0))
        wrap.pack(fill=tk.X)

        bar = ttk.Frame(wrap)
        bar.pack(fill=tk.X)
        bar.columnconfigure(3, weight=1)

        ttk.Label(bar, text="本机:").grid(row=0, column=0, padx=(0, 2))
        self.var_local_port = tk.StringVar(value="5051")
        ttk.Entry(bar, textvariable=self.var_local_port, width=6).grid(row=0, column=1, padx=2)

        ttk.Label(bar, text="信号机 IP:").grid(row=0, column=2, padx=(8, 2))
        self._ip_history = load_ip_history()
        default_ip = self._ip_history[0] if self._ip_history else "192.168.40.85"
        self.var_remote_host = tk.StringVar(value=default_ip)
        self.cmb_remote_host = ttk.Combobox(
            bar,
            textvariable=self.var_remote_host,
            values=self._ip_history,
            width=16,
        )
        self.cmb_remote_host.grid(row=0, column=3, sticky=tk.EW, padx=2)

        ttk.Label(bar, text="端口:").grid(row=0, column=4, padx=(8, 2))
        self.var_remote_port = tk.StringVar(value="4050")
        ttk.Entry(bar, textvariable=self.var_remote_port, width=6).grid(row=0, column=5, padx=2)

        self.btn_udp = ttk.Button(bar, text="启动 UDP", command=self._toggle_udp, width=10)
        self.btn_udp.grid(row=0, column=6, padx=(10, 4))

        self.lbl_udp_status = ttk.Label(
            wrap,
            text="未连接",
            foreground="gray",
            wraplength=900,
            justify=tk.LEFT,
            font=("", 9),
        )
        self.lbl_udp_status.pack(fill=tk.X, anchor=tk.W, pady=(4, 0))

        def _resize_status(event: tk.Event) -> None:
            self.lbl_udp_status.configure(wraplength=max(event.width - 16, 240))

        wrap.bind("<Configure>", _resize_status)

        # 协议参数变量（控件在左侧面板）
        self.var_ver_major = tk.StringVar(value="1")
        self.var_ver_minor = tk.StringVar(value="1")
        self.var_host_id = tk.StringVar(value="7")
        self.var_signal_id = tk.StringVar(value="009A2109")
        self.var_cross_id = tk.StringVar(value="0")
        self.var_seq = tk.StringVar(value="1")

    def _build_main_body(self) -> None:
        body = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        left = ttk.LabelFrame(body, text="参数与协议", padding=4)
        body.add(left, weight=1)
        self._build_param_panel(left)

        right = ttk.Frame(body, padding=0)
        body.add(right, weight=5)

        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tab_query = ttk.Frame(self.notebook, padding=4)
        self.tab_set = ttk.Frame(self.notebook, padding=4)
        self.notebook.add(self.tab_query, text="  数据查询  ")
        self.notebook.add(self.tab_set, text="  参数设置  ")

        self._build_query_tab(self.tab_query)
        self._build_set_tab(self.tab_set)

    def _build_param_panel(self, parent: ttk.Widget) -> None:
        proto = ttk.LabelFrame(parent, text="协议参数", padding=4)
        proto.pack(fill=tk.X, pady=(0, 4))
        proto.columnconfigure(1, weight=1)

        ttk.Label(proto, text="版本").grid(row=0, column=0, sticky=tk.W, padx=2, pady=1)
        ver_f = ttk.Frame(proto)
        ver_f.grid(row=0, column=1, sticky=tk.W, pady=1)
        ttk.Entry(ver_f, textvariable=self.var_ver_major, width=3).pack(side=tk.LEFT)
        ttk.Label(ver_f, text=".").pack(side=tk.LEFT)
        ttk.Entry(ver_f, textvariable=self.var_ver_minor, width=3).pack(side=tk.LEFT)

        ttk.Label(proto, text="上位机").grid(row=1, column=0, sticky=tk.W, padx=2, pady=1)
        ttk.Entry(proto, textvariable=self.var_host_id, width=6).grid(
            row=1, column=1, sticky=tk.W, pady=1
        )

        ttk.Label(proto, text="信号机ID").grid(row=2, column=0, sticky=tk.W, padx=2, pady=1)
        ttk.Entry(proto, textvariable=self.var_signal_id, width=12).grid(
            row=2, column=1, sticky=tk.EW, pady=1
        )

        ttk.Label(proto, text="路口/流水").grid(row=3, column=0, sticky=tk.W, padx=2, pady=1)
        ids_f = ttk.Frame(proto)
        ids_f.grid(row=3, column=1, sticky=tk.W, pady=1)
        ttk.Entry(ids_f, textvariable=self.var_cross_id, width=4).pack(side=tk.LEFT)
        ttk.Label(ids_f, text="/").pack(side=tk.LEFT, padx=2)
        ttk.Entry(ids_f, textvariable=self.var_seq, width=4).pack(side=tk.LEFT)

        search_row = ttk.Frame(parent)
        search_row.pack(fill=tk.X, pady=2)
        self.var_search = tk.StringVar()
        self.var_search.trace_add("write", lambda *_: self._filter_tree())
        ttk.Entry(search_row, textvariable=self.var_search).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(search_row, text="清空", command=lambda: self.var_search.set("")).pack(side=tk.LEFT, padx=4)

        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("code", "name"),
            show="tree headings",
            selectmode="extended",
            height=14,
        )
        self.tree.heading("#0", text="分类")
        self.tree.heading("code", text="编号")
        self.tree.heading("name", text="名称")
        self.tree.column("#0", width=120)
        self.tree.column("code", width=90)
        self.tree.column("name", width=200)
        ysb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        elem_row = ttk.Frame(parent)
        elem_row.pack(fill=tk.X, pady=4)
        ttk.Label(elem_row, text="元素编号:").pack(side=tk.LEFT)
        self.var_element = tk.StringVar(value="1")
        ttk.Entry(elem_row, textvariable=self.var_element, width=6).pack(side=tk.LEFT, padx=4)
        ttk.Label(elem_row, text="(方案/灯组/相位等)", foreground="gray").pack(side=tk.LEFT)

        btn_row = ttk.Frame(parent)
        btn_row.pack(fill=tk.X, pady=2)
        ttk.Button(btn_row, text="→ 加入查询", command=self._add_query_selected).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_row, text="→ 加入设置", command=self._add_set_selected).pack(
            side=tk.LEFT, padx=2
        )

    def _build_query_tab(self, parent: ttk.Frame) -> None:
        tool = ttk.Frame(parent)
        tool.pack(fill=tk.X)
        ttk.Button(tool, text="构建查询报文", command=self._build_query).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool, text="发送查询", command=self._send_query).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool, text="样例 HEX", command=self._use_sample_query).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool, text="心跳查询", command=self._send_heartbeat_query).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool, text="清空结果", command=self._clear_query_results).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool, text="查看报文结构", command=self._open_frame_structure_window).pack(
            side=tk.LEFT, padx=2
        )

        sel_q = ttk.LabelFrame(parent, text="已选查询参数", padding=4)
        sel_q.pack(fill=tk.X, pady=4)
        qlist_row = ttk.Frame(sel_q)
        qlist_row.pack(fill=tk.X)
        self.list_query_selected = tk.Listbox(qlist_row, height=3)
        self.list_query_selected.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.list_query_selected.bind("<<ListboxSelect>>", self._on_query_list_select)
        qbtn = ttk.Frame(qlist_row)
        qbtn.pack(side=tk.RIGHT, padx=4)
        ttk.Button(qbtn, text="更新选中项\n元素编号", command=self._apply_element_to_query_entry).pack(
            pady=2
        )
        ttk.Button(qbtn, text="移除/清空", command=self._clear_query_list).pack(pady=2)

        send_f = ttk.LabelFrame(parent, text="发送报文 (HEX)", padding=4)
        send_f.pack(fill=tk.X)
        self.txt_send = scrolledtext.ScrolledText(
            send_f, height=3, font=("Consolas", 9), wrap=tk.WORD
        )
        self.txt_send.pack(fill=tk.X)

        result_f = ttk.LabelFrame(parent, text="查询结果（随每次查询更新）", padding=4)
        result_f.pack(fill=tk.BOTH, expand=True, pady=4)

        self.lbl_query_summary = ttk.Label(
            result_f, text="等待查询应答 (0x20)...", font=("", 10, "bold")
        )
        self.lbl_query_summary.pack(anchor=tk.W, pady=(0, 2))

        self.lbl_query_hint = ttk.Label(
            result_f,
            text="「查询结果」按值状态判断成功/失败；失败时见「格式说明」中的排查建议。报文结构请点击「查看报文结构」在独立窗口打开。",
            foreground="gray",
            wraplength=880,
        )
        self.lbl_query_hint.pack(anchor=tk.W, pady=(0, 4))

        tree_wrap = ttk.Frame(result_f)
        tree_wrap.pack(fill=tk.BOTH, expand=True)
        cols = ("idx", "code", "name", "element", "result", "status", "value", "explain", "hex")
        self.tree_query_result = ttk.Treeview(
            tree_wrap, columns=cols, show="headings", height=8
        )
        headings = {
            "idx": ("序号", 36),
            "code": ("编号", 82),
            "name": ("参数名称", 120),
            "element": ("元素", 40),
            "result": ("查询结果", 72),
            "status": ("值状态", 88),
            "value": ("解析值", 88),
            "explain": ("格式说明/排查", 260),
            "hex": ("原始HEX", 120),
        }
        for c, (text, w) in headings.items():
            self.tree_query_result.heading(c, text=text)
            self.tree_query_result.column(c, width=w, minwidth=32)
        self.tree_query_result.tag_configure("ok", background="#e8f5e9")
        self.tree_query_result.tag_configure("fail", background="#ffebee")
        self.tree_query_result.tag_configure("partial", background="#fff8e1")
        ysb = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self.tree_query_result.yview)
        self.tree_query_result.configure(yscrollcommand=ysb.set)
        self.tree_query_result.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)

        explain_f = ttk.LabelFrame(parent, text="格式解析说明", padding=4)
        explain_f.pack(fill=tk.BOTH, expand=True)
        self.txt_query_explain = scrolledtext.ScrolledText(
            explain_f, height=10, font=("", 9), wrap=tk.WORD
        )
        self.txt_query_explain.pack(fill=tk.BOTH, expand=True)

        report_f = ttk.LabelFrame(parent, text="主动上报 (0x60)", padding=4)
        report_f.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        rep_tool = ttk.Frame(report_f)
        rep_tool.pack(fill=tk.X)
        ttk.Button(rep_tool, text="清空上报", command=self._clear_active_reports).pack(
            side=tk.RIGHT, padx=2
        )
        self.txt_active_report = scrolledtext.ScrolledText(
            report_f, height=6, font=("Consolas", 9), wrap=tk.WORD
        )
        self.txt_active_report.pack(fill=tk.BOTH, expand=True)
        self.txt_active_report.insert(
            tk.END, "仅显示帧类型 0x60 主动上报报文。\n"
        )

    def _build_set_tab(self, parent: ttk.Frame) -> None:
        tool = ttk.Frame(parent)
        tool.pack(fill=tk.X)
        ttk.Button(tool, text="构建设置报文", command=self._build_set).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool, text="发送设置", command=self._send_set_built).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool, text="发送 HEX(高级)", command=self._send_set_hex).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool, text="清空设置项", command=self._clear_set_entries).pack(side=tk.LEFT, padx=2)

        hint = ttk.Label(
            parent,
            text="提示：为每个参数填写设置值（十进制、HEX 如 64 或 00 00 00 64、字符串）。"
            "多参数可一次设置。发送后查看下方设置结果。",
            foreground="gray",
            wraplength=900,
        )
        hint.pack(anchor=tk.W, pady=4)

        values_outer = ttk.LabelFrame(parent, text="待设置参数及数值", padding=4)
        values_outer.pack(fill=tk.BOTH, expand=True)

        self.canvas_set = tk.Canvas(values_outer, highlightthickness=0, height=160)
        set_scroll = ttk.Scrollbar(values_outer, orient=tk.VERTICAL, command=self.canvas_set.yview)
        self.frame_set_values = ttk.Frame(self.canvas_set)
        self.frame_set_values.bind(
            "<Configure>",
            lambda e: self.canvas_set.configure(scrollregion=self.canvas_set.bbox("all")),
        )
        self.canvas_set.create_window((0, 0), window=self.frame_set_values, anchor=tk.NW)
        self.canvas_set.configure(yscrollcommand=set_scroll.set)
        self.canvas_set.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        set_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        ttk.Label(self.frame_set_values, text="从左侧选择参数后点击「→ 加入设置」").pack(anchor=tk.W)

        send_f = ttk.LabelFrame(parent, text="设置报文 (HEX)", padding=4)
        send_f.pack(fill=tk.X, pady=4)
        self.txt_set_send = scrolledtext.ScrolledText(
            send_f, height=3, font=("Consolas", 9), wrap=tk.WORD
        )
        self.txt_set_send.pack(fill=tk.X)

        ack_f = ttk.LabelFrame(parent, text="设置应答与结果判断 (0x40)", padding=4)
        ack_f.pack(fill=tk.BOTH, expand=True)

        self.lbl_set_summary = ttk.Label(
            ack_f, text="等待设置应答...", font=("", 11, "bold")
        )
        self.lbl_set_summary.pack(anchor=tk.W, pady=(0, 4))

        cols = ("idx", "code", "name", "result", "status", "note")
        self.tree_set_result = ttk.Treeview(ack_f, columns=cols, show="headings", height=8)
        for c, text, w in [
            ("idx", "序号", 40),
            ("code", "编号", 90),
            ("name", "参数名称", 200),
            ("result", "设置结果", 80),
            ("status", "状态码", 70),
            ("note", "说明", 120),
        ]:
            self.tree_set_result.heading(c, text=text)
            self.tree_set_result.column(c, width=w)
        self.tree_set_result.tag_configure("ok", background="#e8f5e9")
        self.tree_set_result.tag_configure("fail", background="#ffebee")
        ysb2 = ttk.Scrollbar(ack_f, orient=tk.VERTICAL, command=self.tree_set_result.yview)
        self.tree_set_result.configure(yscrollcommand=ysb2.set)
        self.tree_set_result.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb2.pack(side=tk.RIGHT, fill=tk.Y)

        self.txt_set_detail = scrolledtext.ScrolledText(ack_f, height=5, font=("Consolas", 9))
        self.txt_set_detail.pack(fill=tk.X, pady=(4, 0))

    def _build_log_area(self) -> None:
        log_frame = ttk.LabelFrame(self, text="通信日志", padding=4)
        log_frame.pack(fill=tk.X, padx=8, pady=(0, 8))
        self.txt_log = scrolledtext.ScrolledText(
            log_frame, height=4, font=("Consolas", 9), wrap=tk.WORD
        )
        self.txt_log.pack(fill=tk.BOTH, expand=True)

    # ---------- 协议与数据 ----------
    def _protocol_config(self) -> ProtocolConfig:
        return ProtocolConfig(
            version_major=int(self.var_ver_major.get() or "1"),
            version_minor=int(self.var_ver_minor.get() or "0"),
            host_id=int(self.var_host_id.get() or "7"),
            signal_id=int(self.var_signal_id.get() or "0", 16),
            cross_id=int(self.var_cross_id.get() or "0"),
            seq=int(self.var_seq.get() or "1") & 0xFF,
        )

    def _populate_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._tree_items.clear()
        self._category_nodes.clear()
        for item in self.catalog["items"]:
            cat = item["category"]
            if cat not in self._category_nodes:
                self._category_nodes[cat] = self.tree.insert("", tk.END, text=cat, open=False)
            iid = self.tree.insert(
                self._category_nodes[cat],
                tk.END,
                text=item["name"],
                values=(item["code"], item["name"]),
            )
            self._tree_items[iid] = item

    def _filter_tree(self) -> None:
        keyword = self.var_search.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        self._tree_items.clear()
        self._category_nodes.clear()
        for item in self.catalog["items"]:
            text = f"{item['category']} {item['name']} {item['code']}".lower()
            if keyword and keyword not in text:
                continue
            cat = item["category"]
            if cat not in self._category_nodes:
                self._category_nodes[cat] = self.tree.insert("", tk.END, text=cat, open=True)
            iid = self.tree.insert(
                self._category_nodes[cat],
                tk.END,
                text=item["name"],
                values=(item["code"], item["name"]),
            )
            self._tree_items[iid] = item

    def _on_tree_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        item = self._tree_items.get(sel[0])
        if not item:
            return
        parts = item["code"].split(".")
        if len(parts) >= 4 and parts[3] not in ("0", "N"):
            self.var_element.set(parts[3])

    def _parse_element(self) -> int:
        return int(self.var_element.get() or "0")

    def _element_for_item(self, item: dict, element: int | None = None) -> int:
        el = self._parse_element() if element is None else element
        if item.get("needs_element") or item.get("element_is_wildcard"):
            return el
        return item.get("element_id") or el

    def _add_query_selected(self) -> None:
        el = self._parse_element()
        for iid in self.tree.selection():
            item = self._tree_items.get(iid)
            if not item:
                continue
            key = (item["code"], self._element_for_item(item, el))
            if any(
                e["item"]["code"] == item["code"]
                and self._element_for_item(e["item"], e["element"]) == key[1]
                for e in self._query_selected
            ):
                continue
            self._query_selected.append({"item": item, "element": el})
        self._refresh_query_list()

    def _refresh_query_list(self) -> None:
        self.list_query_selected.delete(0, tk.END)
        for entry in self._query_selected:
            item = entry["item"]
            el = self._element_for_item(item, entry["element"])
            self.list_query_selected.insert(
                tk.END, f"{item['code']}  {item['name']}  [元素={el}]"
            )

    def _on_query_list_select(self, _event=None) -> None:
        idx = self.list_query_selected.curselection()
        if not idx:
            return
        entry = self._query_selected[idx[0]]
        self.var_element.set(str(entry["element"]))

    def _apply_element_to_query_entry(self) -> None:
        idx = self.list_query_selected.curselection()
        if not idx:
            messagebox.showinfo("提示", "请先在已选列表中选中一项")
            return
        self._query_selected[idx[0]]["element"] = self._parse_element()
        self._refresh_query_list()
        self.list_query_selected.selection_set(idx[0])

    def _clear_query_list(self) -> None:
        idx = self.list_query_selected.curselection()
        if idx:
            del self._query_selected[idx[0]]
        else:
            self._query_selected.clear()
        self._refresh_query_list()

    def _add_set_selected(self) -> None:
        for iid in self.tree.selection():
            item = self._tree_items.get(iid)
            if not item:
                continue
            if any(e["item"]["code"] == item["code"] for e in self._set_entries):
                continue
            var = tk.StringVar()
            sv = item.get("sample_value")
            if sv is not None and sv != "":
                var.set(str(sv))
            self._set_entries.append({"item": item, "var": var})
        self._rebuild_set_value_rows()
        self.notebook.select(self.tab_set)

    def _rebuild_set_value_rows(self) -> None:
        for w in self.frame_set_values.winfo_children():
            w.destroy()
        if not self._set_entries:
            ttk.Label(self.frame_set_values, text="从左侧选择参数后点击「→ 加入设置」").pack(
                anchor=tk.W
            )
            return
        header = ttk.Frame(self.frame_set_values)
        header.pack(fill=tk.X, pady=2)
        for text, w in [("编号", 12), ("参数名称", 28), ("元素", 6), ("设置值", 24), ("", 4)]:
            ttk.Label(header, text=text, width=w, anchor=tk.W).pack(side=tk.LEFT, padx=2)

        for i, entry in enumerate(self._set_entries):
            item = entry["item"]
            row = ttk.Frame(self.frame_set_values)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=item["code"], width=12).pack(side=tk.LEFT, padx=2)
            ttk.Label(row, text=item["name"][:24], width=28).pack(side=tk.LEFT, padx=2)
            ttk.Label(row, text=str(self._element_for_item(item)), width=6).pack(side=tk.LEFT, padx=2)
            ttk.Entry(row, textvariable=entry["var"], width=28).pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)
            ttk.Button(row, text="删", width=3, command=lambda idx=i: self._remove_set_entry(idx)).pack(
                side=tk.LEFT, padx=2
            )

    def _remove_set_entry(self, idx: int) -> None:
        if 0 <= idx < len(self._set_entries):
            del self._set_entries[idx]
            self._rebuild_set_value_rows()

    def _clear_set_entries(self) -> None:
        self._set_entries.clear()
        self._rebuild_set_value_rows()
        self.txt_set_send.delete("1.0", tk.END)

    def _query_addresses(self) -> list[DataAddress]:
        return [
            DataAddress(
                entry["item"]["class_id"],
                entry["item"]["object_id"],
                entry["item"]["attr_id"],
                self._element_for_item(entry["item"], entry["element"]),
            )
            for entry in self._query_selected
        ]

    def _set_payload_entries(self) -> list[tuple[DataAddress, bytes]]:
        result: list[tuple[DataAddress, bytes]] = []
        for entry in self._set_entries:
            item = entry["item"]
            addr = DataAddress(
                item["class_id"],
                item["object_id"],
                item["attr_id"],
                self._element_for_item(item),
            )
            width = guess_value_width(item, item.get("sample_value"))
            val = encode_set_value_for_item(
                item, entry["var"].get(), width if width else None
            )
            result.append((addr, val))
        return result

    def _build_query(self) -> None:
        if not self._query_selected:
            messagebox.showwarning("提示", "请先加入查询参数")
            return
        try:
            addresses = self._query_addresses()
            if len(addresses) == 1:
                item = self._query_selected[0]["item"]
                if item.get("sample_send"):
                    hex_text = patch_element_in_sample(
                        item["sample_send"], addresses[0].element_id
                    )
                    self._set_send_hex(hex_text)
                    self._append_log("已使用样例查询报文")
                    return
            frame = build_query_frame(self._protocol_config(), addresses)
            self._set_send_hex(format_hex(frame))
            self._append_log("已构建查询报文")
        except Exception as exc:
            messagebox.showerror("构建失败", str(exc))

    def _build_set(self) -> None:
        if not self._set_entries:
            messagebox.showwarning("提示", "请先加入设置参数并填写设置值")
            return
        try:
            entries = self._set_payload_entries()
            frame = build_set_frame(self._protocol_config(), entries)
            self.txt_set_send.delete("1.0", tk.END)
            self.txt_set_send.insert(tk.END, format_hex(frame))
            self._append_log(f"已构建设置报文，共 {len(entries)} 项")
        except Exception as exc:
            messagebox.showerror("构建失败", str(exc))

    def _use_sample_query(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择协议项")
            return
        item = self._tree_items.get(sel[0])
        if not item or not item.get("sample_send"):
            messagebox.showwarning("提示", "该项无样例报文")
            return
        elem = int(self.var_element.get() or "1")
        self._set_send_hex(patch_element_in_sample(item["sample_send"], elem))

    def _set_send_hex(self, text: str) -> None:
        self.txt_send.delete("1.0", tk.END)
        self.txt_send.insert(tk.END, text)

    def _ensure_udp(self) -> bool:
        if self.comm.is_running:
            return True
        messagebox.showwarning("提示", "请先启动 UDP")
        return False

    def _send_bytes(self, data: bytes) -> None:
        if not self._ensure_udp():
            return
        try:
            self.comm.send(data)
        except Exception as exc:
            messagebox.showerror("发送失败", str(exc))

    def _send_query(self) -> None:
        text = self.txt_send.get("1.0", tk.END).strip()
        if not text:
            self._build_query()
            text = self.txt_send.get("1.0", tk.END).strip()
        if not text:
            return
        try:
            pending_seq = int(self.var_seq.get()) & 0xFF
        except ValueError:
            pending_seq = 1
        expected = len(self._query_selected) or None
        self._begin_query_wait(pending_seq, expected)
        self._send_bytes(parse_hex(text))

    def _send_set_built(self) -> None:
        text = self.txt_set_send.get("1.0", tk.END).strip()
        if not text:
            self._build_set()
            text = self.txt_set_send.get("1.0", tk.END).strip()
        if text:
            self._send_bytes(parse_hex(text))

    def _send_set_hex(self) -> None:
        from tkinter import simpledialog

        hex_text = simpledialog.askstring("高级设置", "粘贴完整设置 HEX 报文:", parent=self)
        if hex_text:
            self.txt_set_send.delete("1.0", tk.END)
            self.txt_set_send.insert(tk.END, hex_text.strip())
            self._send_bytes(parse_hex(hex_text))

    def _send_heartbeat_query(self) -> None:
        frame = build_heartbeat_query(self._protocol_config())
        self._set_send_hex(format_hex(frame))
        self._send_bytes(frame)

    def _toggle_udp(self) -> None:
        if self.comm.is_running:
            self.comm.stop()
            self.btn_udp.config(text="启动 UDP")
            self.lbl_udp_status.config(
                text="未连接 — 请先启动 UDP", foreground="gray"
            )
            return
        try:
            self.comm.local_port = int(self.var_local_port.get())
            host = self.var_remote_host.get().strip()
            self._ip_history = save_ip_to_history(host)
            self.cmb_remote_host["values"] = self._ip_history
            self.comm.update_target(host, int(self.var_remote_port.get()))
            self.comm.start()
            self.btn_udp.config(text="停止 UDP")
            self.lbl_udp_status.config(
                text=(
                    f"已连接  本机 :{self.comm.local_port}  →  "
                    f"{self.comm.remote_host}:{self.comm.remote_port}"
                ),
                foreground="green",
            )
        except Exception as exc:
            messagebox.showerror("启动失败", str(exc))

    def _append_log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        if "|" in msg and ("收 " in msg or "发 " in msg):
            prefix, _, hexpart = msg.partition("|")
            if hexpart.strip() and "\n" not in hexpart:
                try:
                    raw = parse_hex(hexpart.replace("\n", " "))
                    msg = f"{prefix.strip()}\n{format_hex_display(raw)}"
                except ValueError:
                    pass
        self.txt_log.insert(tk.END, f"[{ts}] {msg}\n")
        self.txt_log.see(tk.END)

    def _clear_query_results(self) -> None:
        self._pending_query_seq = None
        self._query_sent_at = None
        self._last_query_raw = None
        self._last_query_frame = None
        self.tree_query_result.delete(*self.tree_query_result.get_children())
        self.lbl_query_summary.config(text="等待查询应答 (0x20)...", foreground="")
        self.txt_query_explain.delete("1.0", tk.END)

    def _clear_active_reports(self) -> None:
        self.txt_active_report.delete("1.0", tk.END)
        self.txt_active_report.insert(tk.END, "仅显示帧类型 0x60 主动上报报文。\n")

    def _begin_query_wait(self, pending_seq: int, expected_count: int | None) -> None:
        """每次发送查询前清空结果区，仅展示本次查询的应答。"""
        self._pending_query_seq = pending_seq
        self._query_sent_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.tree_query_result.delete(*self.tree_query_result.get_children())
        self.txt_query_explain.delete("1.0", tk.END)
        exp = f"，预计 {expected_count} 项" if expected_count else ""
        self.lbl_query_summary.config(
            text=f"查询已发送，等待应答 (0x20)  流水号={pending_seq}{exp}  {self._query_sent_at}",
            foreground="#e65100",
        )
        self.txt_query_explain.insert(
            tk.END,
            f"已发送查询，流水号 {pending_seq}，发送时间 {self._query_sent_at}。\n"
            "收到 0x20 查询应答后将在此显示格式解析说明。\n",
        )
        self.notebook.select(self.tab_query)
        self.update_idletasks()

    def _fill_query_result_tree(self, rows: list) -> None:
        self.tree_query_result.delete(*self.tree_query_result.get_children())
        for r in rows:
            tag = "ok" if r.ok else ("fail" if r.ok is False else "partial")
            result_txt = "成功" if r.ok else ("失败" if r.ok is False else "未知")
            self.tree_query_result.insert(
                "",
                tk.END,
                values=(
                    r.index,
                    r.code,
                    r.name,
                    r.element_id,
                    result_txt,
                    f"{r.status_text} {r.status_hex or ''}".strip(),
                    r.value_text,
                    r.explanation,
                    r.value_hex,
                ),
                tags=(tag,),
            )
        self.tree_query_result.update_idletasks()

    def _show_query_results(self, frame, raw: bytes) -> None:
        rows = query_rows_from_frame(frame, self.lookup)
        recv_at = datetime.now().strftime("%H:%M:%S")
        summary, tone = summarize_query_ack(rows)
        self._last_query_raw = raw
        self._last_query_frame = frame
        self._fill_query_result_tree(rows)
        colors = {"ok": "#2e7d32", "fail": "#c62828", "partial": "#e65100"}
        self.lbl_query_summary.config(
            text=f"本次查询 — {summary}  |  流水号 {frame.config.seq}  |  {recv_at}",
            foreground=colors.get(tone, "#1565c0"),
        )
        self.txt_query_explain.delete("1.0", tk.END)
        self.txt_query_explain.insert(
            tk.END,
            query_explanation_report(
                frame,
                self.lookup,
                pending_seq=self._pending_query_seq,
                sent_at=self._query_sent_at,
            ),
        )
        self._pending_query_seq = None
        self.notebook.select(self.tab_query)
        self.update_idletasks()

    def _show_query_error(self, message: str, raw: bytes | None = None) -> None:
        """查询应答异常（CRC/帧格式等）。"""
        self._pending_query_seq = None
        self.tree_query_result.delete(*self.tree_query_result.get_children())
        self.tree_query_result.insert(
            "",
            tk.END,
            values=("", "", "—", "", "失败", "—", "", message, ""),
            tags=("fail",),
        )
        self.lbl_query_summary.config(text="查询应答异常", foreground="#c62828")
        lines = [
            "════════ 查询应答异常 ════════",
            f"错误：{message}",
            "",
            "常见排查：",
            "  1. CRC 校验失败 — 确认信号机与上位机使用相同 CRC 算法(多项式 0x1005)；",
            "  2. 帧头/帧尾错误 — 检查是否为 7E … 7D 完整帧；",
            "  3. 流水号不一致 — 可能收到旧应答或其他设备报文；",
            "  4. 报文截断 — 检查 UDP 网络与报文长度字段是否一致。",
        ]
        if raw:
            lines.extend(["", f"原始数据：", format_hex_display(raw)])
        self.txt_query_explain.delete("1.0", tk.END)
        self.txt_query_explain.insert(tk.END, "\n".join(lines))
        self.notebook.select(self.tab_query)

    def _open_frame_structure_window(self) -> None:
        if not self._last_query_raw or not self._last_query_frame:
            messagebox.showinfo("提示", "请先完成一次查询并成功收到应答后再查看报文结构")
            return
        if self._frame_structure_win and self._frame_structure_win.winfo_exists():
            self._frame_structure_win.lift()
            self._refresh_frame_structure_window()
            return
        win = tk.Toplevel(self)
        win.title("报文结构 — 最近一次查询应答")
        win.geometry("900x620")
        win.minsize(520, 360)
        self._frame_structure_win = win
        txt = scrolledtext.ScrolledText(win, font=("Consolas", 9), wrap=tk.NONE)
        txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self._txt_frame_structure = txt
        self._refresh_frame_structure_window()
        win.protocol("WM_DELETE_WINDOW", self._close_frame_structure_window)

    def _refresh_frame_structure_window(self) -> None:
        if not getattr(self, "_txt_frame_structure", None):
            return
        self._txt_frame_structure.delete("1.0", tk.END)
        if self._last_query_raw and self._last_query_frame:
            self._txt_frame_structure.insert(
                tk.END,
                frame_structure_report(self._last_query_frame, self._last_query_raw, self.lookup),
            )

    def _close_frame_structure_window(self) -> None:
        if self._frame_structure_win:
            self._frame_structure_win.destroy()
        self._frame_structure_win = None

    def _show_set_ack(self, frame, raw: bytes) -> None:
        rows = set_ack_rows_from_frame(frame, self.lookup)
        self.tree_set_result.delete(*self.tree_set_result.get_children())
        for r in rows:
            tag = "ok" if r.ok else ("fail" if r.ok is False else "")
            self.tree_set_result.insert(
                "",
                tk.END,
                values=(
                    r.index,
                    r.code,
                    r.name,
                    r.status_text or "",
                    r.status_hex or "",
                    r.explanation if r.explanation else (
                        "设置成功" if r.ok else "设置失败"
                    ),
                ),
                tags=(tag,) if tag else (),
            )
        summary = summarize_set_ack(rows)
        color = "green" if "全部成功" in summary else ("red" if "全部失败" in summary else "#e65100")
        self.lbl_set_summary.config(text=f"设置应答 — {summary}", foreground=color)
        self.txt_set_detail.delete("1.0", tk.END)
        self.txt_set_detail.insert(tk.END, f"原始报文: {format_hex(raw)}\n\n")
        self.txt_set_detail.insert(tk.END, frame_to_text(frame, self.lookup))
        self.notebook.select(self.tab_set)

    def _append_active_report(self, raw: bytes, frame) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.txt_active_report.insert(tk.END, f"\n{'='*50}\n[{ts}] 主动上报 (0x60)\n")
        self.txt_active_report.insert(tk.END, f"原始:\n{format_hex_display(raw)}\n\n")
        self.txt_active_report.insert(
            tk.END, frame_structure_report(frame, raw, self.lookup) + "\n"
        )
        self.txt_active_report.see(tk.END)
        self.notebook.select(self.tab_query)

    def _on_receive(self, data: bytes, addr: tuple) -> None:
        def update() -> None:
            try:
                frame = parse_frame(data)
                if is_query_reply(frame.frame_type):
                    if (
                        self._pending_query_seq is not None
                        and frame.config.seq != self._pending_query_seq
                    ):
                        self._append_log(
                            f"忽略非本次查询应答: 应答流水号={frame.config.seq} "
                            f"期望={self._pending_query_seq}"
                        )
                        return
                    self._show_query_results(frame, data)
                elif frame.frame_type == 0x40:
                    self._show_set_ack(frame, data)
                elif frame.frame_type == 0x60:
                    self._append_active_report(data, frame)
                elif frame.frame_type == 0x71:
                    self._append_log(f"心跳应答: {format_hex(data)}")
                else:
                    self._append_log(f"收到 {frame.type_name}: {format_hex(data)}")
            except Exception as exc:
                if self._pending_query_seq is not None:
                    self._show_query_error(str(exc), data)
                elif data and data[0] == 0x7E:
                    self._append_log(f"报文解析失败: {exc}")
                else:
                    self._append_log(f"收到非标准数据: {format_hex(data)}")

        self.after(0, update)

    def _on_close(self) -> None:
        self.comm.stop()
        self.destroy()


def run() -> None:
    App().mainloop()
