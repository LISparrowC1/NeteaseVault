# Build the onedir program and compile the green installer from source.
# Run: pwsh -NoProfile -File build/build.ps1

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

$project = Split-Path -Parent $PSScriptRoot
$parent = Split-Path -Parent $project
$distRoot = Join-Path $parent 'dist'
$releaseRoot = Join-Path $parent 'release'
Set-Location $project

$python = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "未找到虚拟环境: $python" }
$version = (& $python -c "from app.version import __version__; print(__version__)").Trim()
if (-not $version) { throw "无法读取版本号" }

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

New-Item -ItemType Directory -Force -Path $distRoot, $releaseRoot | Out-Null
$appDir = Join-Path $distRoot 'NeteaseVault'
if (Test-Path $appDir) { Remove-Item -LiteralPath $appDir -Recurse -Force }

& $python -m PyInstaller --noconfirm --clean --distpath $distRoot `
    --workpath (Join-Path $project 'build\work') (Join-Path $PSScriptRoot 'build.spec')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败" }

$exe = Join-Path $appDir 'NeteaseVault.exe'
if (-not (Test-Path $exe)) { throw "构建产物不存在: $exe" }

$out = Join-Path $appDir 'selftest.txt'
if (Test-Path $out) { Remove-Item $out -Force }
$proc = Start-Process -FilePath $exe -ArgumentList '--selftest' -WorkingDirectory $appDir -PassThru
if (-not $proc.WaitForExit(90000)) { $proc.Kill(); throw "自检超时（进程未在 90 秒内退出）" }
if (-not (Test-Path $out)) { throw "自检未产生结果文件（退出码 $($proc.ExitCode)）" }
$content = Get-Content $out -Raw
Write-Output "自检输出: $content"
if ($content -notmatch 'selftest ok') { throw "自检失败" }
Remove-Item $out -Force
foreach ($extra in 'data\tmp', 'music') {
    $path = Join-Path $appDir $extra
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
}

# Package the onedir payload as a resource for the C# installer.
$payload = Join-Path $distRoot 'payload.zip'
if (Test-Path $payload) { Remove-Item $payload -Force }
[IO.Compression.ZipFile]::CreateFromDirectory(
    $appDir, $payload, [IO.Compression.CompressionLevel]::Optimal, $false)

$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
if (-not (Test-Path $csc)) { throw "找不到 csc.exe" }

$installer = Join-Path $distRoot "NeteaseVault-$version-Setup.exe"
$icon = Join-Path $PSScriptRoot 'icon.ico'
$program = Join-Path $PSScriptRoot 'installer\Program.cs'
$assembly = Join-Path $PSScriptRoot 'installer\AssemblyInfo.cs'
$cscArgs = @(
    '/nologo', '/target:winexe', '/optimize+',
    "/out:$installer", "/win32icon:$icon", "/resource:$payload,payload.zip",
    '/r:System.dll', '/r:System.Core.dll', '/r:System.Drawing.dll',
    '/r:System.Windows.Forms.dll', '/r:System.IO.Compression.dll',
    '/r:System.IO.Compression.FileSystem.dll',
    $program, $assembly
)
& $csc $cscArgs
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $installer)) { throw "安装器编译失败" }

# release/ is the final publish folder: only the source-built installer.
Get-ChildItem -LiteralPath $releaseRoot -File -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
$releaseInstaller = Join-Path $releaseRoot (Split-Path -Leaf $installer)
Copy-Item -LiteralPath $installer -Destination $releaseInstaller -Force
$hash = (Get-FileHash -LiteralPath $releaseInstaller -Algorithm SHA256).Hash

$size = [math]::Round((Get-Item $installer).Length / 1MB, 1)
Write-Output "构建完成: $installer ($size MB)"
Write-Output "投放文件: $releaseInstaller"
Write-Output "SHA256: $hash"
