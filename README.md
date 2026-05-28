# 20999-test-first
这是我在GitHub上的第一个项目，是关于交通信号控制20999协议的相关软件开发记录
基于 GB/T 20999-2017 的 UDP 通信上位机：数据查询、参数设置、应答解析、主动上报与心跳。

## 功能

- **数据查询**：多参数查询、0x20/0x21 应答、成功/失败与格式说明
- **参数设置**：方案链等定长字段编码、设置应答解析
- **通信**：UDP 本机 5051 → 信号机 4050，IP 历史记录
- **协议**：GB/T 20999 CRC16（多项式 0x1005）、报文结构查看

## 环境要求

- Python 3.10+
- Windows / Linux / macOS（界面为 Tkinter，随 Python 提供）

## 快速开始

```bash
# 安装可选依赖（仅重新从 Excel 导出协议库时需要）
pip install -r requirements.txt

# 运行
python main.py
```

Windows 也可双击 `run.bat`。

## 协议参数

左侧面板配置：**版本**、**上位机 ID**、**信号机 ID (HEX)**、**路口 ID**、**流水号**。

- 流水号默认 `1`，可手动修改，**发送后不会自动递增**
- 现场设备参数请与信号机一致（需求样例常用上位机 `07`、信号机 `009A2109`；Excel 样例常用 `05` / `00000000`）

## 打包 exe（Windows）

```bash
pip install pyinstaller
build_exe.bat
```

生成 `dist/20999上位机.exe`。

## 协议库

`protocol_catalog.json` 为内置参数目录（177 项）。若持有 `20999查询协议.xlsx`，可重新生成：

```bash
pip install openpyxl
# 将 xlsx 放在项目根目录后执行
python scripts/export_catalog.py
```

## 目录结构

```
├── main.py                 # 入口
├── gb20999/                # 主程序包
│   ├── app.py              # GUI
│   ├── protocol.py         # 编解码 / CRC
│   ├── udp_comm.py         # UDP
│   ├── result_view.py      # 结果解析
│   └── ip_history.py       # IP 历史
├── protocol_catalog.json   # 协议参数库
├── scripts/                # 辅助脚本（导出、联机测试等）
├── tests/                  # 自动化测试
└── docs/                   # 需求与补充说明文档
```

## 测试

```bash
python tests/test_regression_all.py
python tests/test_crc_gb20999.py
python tests/test_excel_success_cases.py   # 需 Excel 样例文件
```

## 文档

详见 `docs/` 目录：`需求描述.txt`、`补充描述1~5.txt`、`crc校验逻辑.txt`。

## 上传到 GitHub

本目录 `20999-host-github` 即为整理后的仓库内容，可直接：

```bash
cd 20999-host-github
git init
git add .
git commit -m "Initial commit: GB/T 20999 host"
git remote add origin <你的仓库地址>
git push -u origin main
```

同目录上一级的 `20999-host-github.zip` 为压缩包，便于拷贝或上传。

**未纳入版本库的内容**（见 `.gitignore`）：`build/`、`dist/`、exe、`ip_history.json`、联机测试 CSV、临时导出文件等。

