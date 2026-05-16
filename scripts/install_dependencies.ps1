# 报销系统 - 一键依赖安装脚本
# This script automatically installs all required dependencies

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptRoot
$RequirementsFile = Join-Path $ProjectRoot "requirements.txt"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "报销系统 - 依赖安装脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check Python version
Write-Host "正在检查 Python 版本..." -ForegroundColor Yellow
$PythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ 错误: 未找到 Python。请先安装 Python 3.8 或更高版本。" -ForegroundColor Red
    exit 1
}
Write-Host "✓ 找到 Python: $PythonVersion" -ForegroundColor Green
Write-Host ""

# Check if requirements.txt exists
if (-not (Test-Path $RequirementsFile)) {
    Write-Host "❌ 错误: 找不到 requirements.txt 文件" -ForegroundColor Red
    Write-Host "   期望位置: $RequirementsFile" -ForegroundColor Red
    exit 1
}

Write-Host "正在安装依赖库..." -ForegroundColor Yellow
Write-Host "依赖文件: $RequirementsFile" -ForegroundColor Gray
Write-Host ""

# Install dependencies
python -m pip install --upgrade pip -q
python -m pip install -r $RequirementsFile

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "✓ 安装完成！" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "已安装的库:" -ForegroundColor Yellow
    python -m pip list | Select-String -Pattern "reportlab|pillow"
    Write-Host ""
    Write-Host "下一步操作:" -ForegroundColor Yellow
    Write-Host "  运行: python scripts/generate_reimbursement_pdf.py" -ForegroundColor Cyan
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "❌ 安装失败。请检查错误信息上方的内容。" -ForegroundColor Red
    exit 1
}
