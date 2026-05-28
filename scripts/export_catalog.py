# -*- coding: utf-8 -*-
"""Export protocol catalog from Excel to JSON."""
import json
import os
import re
import openpyxl

# 项目根目录（脚本位于 scripts/）
base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(base)

def parse_code(code_str):
    """Parse '9.2.3.1' -> class_id=9, object_id=2, attr_id=3, element_id=1"""
    if not code_str:
        return None
    code_str = str(code_str).strip()
    parts = code_str.split('.')
    if len(parts) < 3:
        return None
    try:
        class_id = int(parts[0])
        object_id = int(parts[1])
        attr_id = int(parts[2])
        element_id = int(parts[3]) if len(parts) > 3 and parts[3] not in ('0', 'N') else 0
        return {
            'class_id': class_id,
            'object_id': object_id,
            'attr_id': attr_id,
            'element_id': element_id,
            'code': code_str,
            'needs_element': len(parts) > 3 and parts[3] not in ('0',),
            'element_is_wildcard': len(parts) > 3 and parts[3] == 'N',
        }
    except ValueError:
        return None

def hex_to_bytes(hex_str):
    if not hex_str:
        return None
    hex_str = re.sub(r'\s+', ' ', str(hex_str).strip())
    try:
        return [int(x, 16) for x in hex_str.split() if x]
    except ValueError:
        return None

items = []
wb = openpyxl.load_workbook([f for f in os.listdir('.') if f.endswith('.xlsx') and '20999' in f][0], data_only=True)
ws = wb['Sheet1']
current_category = ''
for row in ws.iter_rows(min_row=2, values_only=True):
    cat, name, code, send_hex, resp_hex, success, note, str_val = row[:8]
    if cat:
        current_category = str(cat)
    if not name or not code:
        continue
    parsed = parse_code(code)
    if not parsed:
        continue
    send_bytes = hex_to_bytes(send_hex)
    items.append({
        'category': current_category,
        'name': str(name),
        'code': str(code),
        **parsed,
        'sample_send': send_hex.strip() if send_hex else '',
        'sample_response': str(resp_hex).strip() if resp_hex else '',
        'note': note or '',
        'sample_value': str(str_val) if str_val is not None else '',
    })
wb.close()

# Frame types from protocol
FRAME_TYPES = {
    0x10: '查询',
    0x20: '查询应答',
    0x30: '设置',
    0x40: '设置应答',
    0x60: '主动上报',
    0x70: '心跳查询',
    0x71: '心跳应答',
}

catalog = {
    'frame_types': FRAME_TYPES,
    'items': items,
}

with open('protocol_catalog.json', 'w', encoding='utf-8') as f:
    json.dump(catalog, f, ensure_ascii=False, indent=2)

print(f'Exported {len(items)} protocol items')
