# 报销系统

ISDN4002 项目的报销管理和 PDF 生成系统。

## 项目结构

```
Reimbursement/
├── data/              # 从 Notion 导出的原始数据
│   ├── *.md          # 采购项目详细信息（Markdown 格式）
│   ├── *.csv         # 报销表格数据（CSV 格式）
│   └── README.md     # 数据文件夹说明
├── output/           # 生成的输出文件
│   ├── reimbursement_report.md
│   └── reimbursement_report.pdf
├── scripts/          # Python 脚本
│   ├── generate_reimbursement_pdf.py
│   └── install_dependencies.ps1
├── README.md         # 本文件
├── .gitignore        # Git 忽略规则
└── requirements.txt  # Python 依赖
```

## 环境需求

- Python 3.8 或更高版本
- Windows PowerShell（用于安装脚本）

## 快速开始

### 方法 1：一键安装脚本（推荐）

在项目根目录运行：

```powershell
.\scripts\install_dependencies.ps1
```

脚本会自动：
- 检查 Python 版本
- 安装必要的依赖库
- 验证安装

### 方法 2：手动安装

```bash
python -m pip install -r requirements.txt
```

## 项目依赖

本项目使用以下第三方库：

| 库 | 版本 | 用途 |
|---|---|---|
| **reportlab** | ≥4.0 | PDF 文档生成和排版 |
| **pillow** | ≥10.0 | 图像处理和转换 |

所有其他导入均来自 Python 标准库。
生成 PDF 时，脚本会使用 `pillow` 按页面显示尺寸缩放截图，并在嵌入前做适度压缩以控制输出体积。

## 使用方法

### 生成报销 PDF 和总结文档

```bash
python scripts/generate_reimbursement_pdf.py
```

**可选参数：**

```bash
python scripts/generate_reimbursement_pdf.py \
  --csv path/to/reimbursement.csv \
  --data-dir ./data \
  --output-dir ./output
```

- `--csv`：指定 CSV 文件路径（默认自动从 data 文件夹选择）
- `--data-dir`：数据文件夹路径（默认 `./data`）
- `--output-dir`：输出文件夹路径（默认 `./output`）

### 输出文件

脚本生成以下文件：

- `output/reimbursement_report.md`：报销总结（Markdown 格式）
- `output/reimbursement_report.pdf`：报销总结（PDF 格式）

## 数据准备

详见 [data/README.md](data/README.md) 了解如何从 Notion 导出数据。

**Notion 模板链接：** https://www.notion.so/279b326fce3d824a99c10159765659cf?v=14fb326fce3d823eaabe08caac642025&source=copy_link

## 常见问题

**Q: 缺少 PDF 依赖错误**

A: 运行安装脚本或执行：
```bash
python -m pip install reportlab pillow
```

**Q: 找不到 CSV 文件**

A: 确保在 `data/` 文件夹中有 `.csv` 文件，参考 [data/README.md](data/README.md)。

**Q: PDF 生成失败**

A: 检查 `data/` 文件夹中的 Markdown 文件是否存在且格式正确。

## 许可证

Internal Project
