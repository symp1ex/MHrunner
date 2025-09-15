# ���� � ����������, ������� ��������� (�� ��������� �������)
$rootPath = Get-Location

# ���� � ��������� �����
$outputFile = Join-Path $rootPath "py_files_dump.txt"

# ������� ������ ����, ���� �� ����������
if (Test-Path $outputFile) {
    Remove-Item $outputFile -Force
}

# �������� ��� .py ����� ����������, �������� ����� � ������ .venv
$pyFiles = Get-ChildItem -Path $rootPath -Recurse -Filter "*.py" -File | Where-Object { $_.FullName -notlike "*\.venv\*" }

foreach ($file in $pyFiles) {
    # �������� ������������� ���� �� �����
    $relativePath = $file.FullName.Replace($rootPath, "").TrimStart("\").Replace("\", "/")

    # ��������� �����, ���������� ������������� ���� ��� ������������
    $startTag = "===== START: $relativePath ====="
    $endTag =   "===== END: $relativePath ====="

    # ���������� �����
    $fileContent = Get-Content $file.FullName -Raw

    # �������� ��������� ���� � ���������� Markdown ��� Python
    $block = @"

$startTag
```python
$fileContent
```
$endTag
"@

    # ��������� � �������� ����
    Add-Content -Path $outputFile -Value $block
}

Write-Host "��� .py-����� (�� ����������� ����� .venv) ������� ������� � $outputFile"