<#
.SYNOPSIS
  Gera a release do Aimedget: testes, executável (PyInstaller), versão portátil (.zip), instalador (Inno Setup)
  e SHA256SUMS.txt, tudo em dist\release.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\build_release.ps1
  powershell -ExecutionPolicy Bypass -File tools\build_release.ps1 -SkipTests
#>
param(
    [switch]$SkipTests,
    [string]$Iscc = ""   # caminho do ISCC.exe; vazio = procura nas pastas padrão do Inno Setup 7 e 6
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# 1. Versão: fonte única em app\core\version.py
$versionLine = Select-String -Path "app\core\version.py" -Pattern '__version__\s*=\s*"([^"]+)"'
if (-not $versionLine) { throw "Versão não encontrada em app\core\version.py" }
$Version = $versionLine.Matches[0].Groups[1].Value
Write-Host "Aimedget v$Version" -ForegroundColor Green

# 2. Testes
if (-not $SkipTests) {
    Step "Testes"
    $env:QT_QPA_PLATFORM = "offscreen"
    $ErrorActionPreference = "Continue"
    $output = python -m pytest tests -q -p no:cacheprovider 2>&1 | Out-String
    $ErrorActionPreference = "Stop"
    Remove-Item Env:\QT_QPA_PLATFORM
    # O pytest às vezes encerra com código de erro DEPOIS de tudo passar (thread do WinRT viva no fechamento do
    # Python); por isso a decisão é pelo resumo, não pelo código de saída.
    $summary = ($output -split "`n" | Where-Object { $_ -match "\d+ passed" } | Select-Object -Last 1)
    if (-not $summary -or $summary -match "failed|error") { Write-Host $output; throw "Testes falharam" }
    Write-Host "  $($summary.Trim())"
}

# 3. Executável (pasta dist\Aimedget)
Step "PyInstaller"
if (Test-Path "dist\Aimedget") { Remove-Item -Recurse -Force "dist\Aimedget" }
$ErrorActionPreference = "Continue"   # o PyInstaller escreve avisos no stderr; quem decide é o código de saída
python -m PyInstaller Aimedget.spec --noconfirm --log-level WARN 2>&1 | Out-Null
$code = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($code -ne 0 -or -not (Test-Path "dist\Aimedget\Aimedget.exe")) { throw "PyInstaller falhou (código $code)" }

# 4. Nada de conteúdo privado no pacote (o tema exclusivo é distribuído à mão, fora do repositório)
Step "Conferindo o pacote"
$private = Get-ChildItem -Recurse "dist\Aimedget" | Where-Object { $_.Name -match "tassia|exclusive|lavanda|\.aimskin$" }
if ($private) { $private | ForEach-Object { Write-Host "  PRIVADO: $($_.FullName)" -ForegroundColor Red }; throw "Conteúdo privado no pacote" }
Copy-Item "THIRD_PARTY_NOTICES.txt" "dist\Aimedget\" -Force
Copy-Item "LICENSE" "dist\Aimedget\LICENSE.txt" -Force   # o portátil leva a licença junto, como o instalador
$sizeMb = [math]::Round(((Get-ChildItem -Recurse "dist\Aimedget" | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host "  dist\Aimedget: $sizeMb MB, sem conteúdo privado"

$Out = "dist\release"
if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
New-Item -ItemType Directory -Force $Out | Out-Null

# 5. Portátil: a mesma pasta, zipada (Aimedget\Aimedget.exe dentro do zip)
Step "Versão portátil"
$Portable = Join-Path $Out "Aimedget-$Version-portable.zip"
Compress-Archive -Path "dist\Aimedget" -DestinationPath $Portable -CompressionLevel Optimal

# 6. Instalador
Step "Instalador (Inno Setup)"
if (-not $Iscc) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    $Iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Iscc) { throw "ISCC.exe não encontrado. Instale o Inno Setup ou passe -Iscc <caminho>." }
& $Iscc "/DAppVersion=$Version" "/Q" "installer\Aimedget.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup falhou (código $LASTEXITCODE)" }

# 7. Hashes para conferência do download
Step "SHA256SUMS.txt"
$sums = Get-ChildItem $Out -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" } | ForEach-Object {
    "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name
}
# LF (não CRLF): é o formato que o sha256sum -c e o Get-FileHash dos usuários esperam
[IO.File]::WriteAllText((Join-Path (Resolve-Path $Out) "SHA256SUMS.txt"), (($sums -join "`n") + "`n"), [Text.Encoding]::ASCII)

Step "Pronto"
Get-ChildItem $Out | ForEach-Object { "  {0,-40} {1,8:N1} MB" -f $_.Name, ($_.Length / 1MB) }
