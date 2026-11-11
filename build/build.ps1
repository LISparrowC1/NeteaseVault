# Build the single-file executable and smoke-test the result.
# Run from the project root:  pwsh -File build/build.ps1

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

$project = Split-Path -Parent $PSScriptRoot
Set-Location $project

$python = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "未找到虚拟环境: $python" }

# Bundle a Node runtime so the program does not depend on the host having one.
$runtime = Join-Path $project 'runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$nodeTarget = Join-Path $runtime 'node.exe'
if (-not (Test-Path $nodeTarget)) {
    $node = (Get-Command node -ErrorAction SilentlyContinue).Source
    if (-not $node) { throw "本机没有 node，无法打包引擎运行时" }
    Copy-Item $node $nodeTarget
    Write-Output "已内置 node 运行时: $node"
}

& $python -m pip install --quiet --disable-pip-version-check pyinstaller

& $python -m PyInstaller --noconfirm --clean --distpath $project `
    --workpath (Join-Path $project 'build\work') (Join-Path $PSScriptRoot 'build.spec')

$exe = Join-Path $project 'NeteaseVault.exe'
if (-not (Test-Path $exe)) { throw "构建产物不存在" }

$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Output "构建完成: $exe ($size MB)"

$out = Join-Path $project 'selftest.txt'
if (Test-Path $out) { Remove-Item $out -Force }
$proc = Start-Process -FilePath $exe -ArgumentList '--selftest' -PassThru
if (-not $proc.WaitForExit(90000)) { $proc.Kill(); throw "自检超时（进程未在 90 秒内退出）" }
if (-not (Test-Path $out)) { throw "自检未产生结果文件（退出码 $($proc.ExitCode)）" }
$content = Get-Content $out -Raw
Write-Output "自检输出: $content"
if ($content -notmatch 'selftest ok') { throw "自检失败" }
Write-Output "构建与自检通过。"
