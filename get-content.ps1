# Путь к директории, которую сканируем (по умолчанию текущая)
$rootPath = Get-Location

# Путь к выходному файлу
$outputFile = Join-Path $rootPath "py_files_dump.txt"

# Удаляем старый файл, если он существует
if (Test-Path $outputFile) {
    Remove-Item $outputFile -Force
}

# Получаем все .py файлы рекурсивно, исключая папки с именем .venv
$pyFiles = Get-ChildItem -Path $rootPath -Recurse -Filter "*.py" -File | Where-Object { $_.FullName -notlike "*\.venv\*" }

foreach ($file in $pyFiles) {
    # Получаем относительный путь от корня
    $relativePath = $file.FullName.Replace($rootPath, "").TrimStart("\").Replace("\", "/")

    # Заголовок блока, используем относительный путь для уникальности
    $startTag = "===== START: $relativePath ====="
    $endTag =   "===== END: $relativePath ====="

    # Содержимое файла
    $fileContent = Get-Content $file.FullName -Raw

    # Собираем финальный блок с корректным Markdown для Python
    $block = @"

$startTag
```python
$fileContent
```
$endTag
"@

    # Добавляем в итоговый файл
    Add-Content -Path $outputFile -Value $block
}

Write-Host "Все .py-файлы (за исключением папки .venv) успешно собраны в $outputFile"