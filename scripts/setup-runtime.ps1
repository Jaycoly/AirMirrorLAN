[CmdletBinding()]
param(
    [switch]$SkipMsysUpdate
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$msysRoot = 'C:\msys64'
$bash = Join-Path $msysRoot 'usr\bin\bash.exe'
$runtimeExe = Join-Path $msysRoot 'ucrt64\bin\uxplay.exe'
$sourceArchive = Join-Path $projectRoot 'vendor\UxPlay-master.zip'
$expectedSourceSha256 = '7FDA6A6BF7227063388E67F7ADB15ADA222A5EEE5E45B139C881DB8F15E655A6'

function Invoke-Msys {
    param([Parameter(Mandatory)][string]$Command)
    $env:MSYSTEM = 'UCRT64'
    $env:CHERE_INVOKING = 'yes'
    & $script:bash -lc $Command
    if ($LASTEXITCODE -ne 0) {
        throw "MSYS2 命令失败，退出代码 $LASTEXITCODE`n$Command"
    }
}

if (-not (Test-Path -LiteralPath $bash)) {
    Write-Host '正在从 MSYS2 官方仓库下载运行环境…' -ForegroundColor Cyan
    $installer = Join-Path ([IO.Path]::GetTempPath()) 'AirMirrorLAN-msys2.sfx.exe'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://repo.msys2.org/distrib/msys2-x86_64-latest.sfx.exe' -OutFile $installer
    $signature = Get-AuthenticodeSignature -LiteralPath $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Christoph Reiter') {
        throw 'MSYS2 安装包的数字签名无效，已停止安装。'
    }
    & $installer -y -oC:\
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $bash)) {
        throw 'MSYS2 解压失败。'
    }
}

# Prefer nearby official mirrors while retaining package signature verification.
$mirrorFiles = @(
    @{ Path = Join-Path $msysRoot 'etc\pacman.d\mirrorlist.mingw'; Lines = @(
        'Server = https://mirrors.ustc.edu.cn/msys2/mingw/$repo/',
        'Server = https://mirrors.tuna.tsinghua.edu.cn/msys2/mingw/$repo/'
    ) },
    @{ Path = Join-Path $msysRoot 'etc\pacman.d\mirrorlist.msys'; Lines = @(
        'Server = https://mirrors.ustc.edu.cn/msys2/msys/$arch/',
        'Server = https://mirrors.tuna.tsinghua.edu.cn/msys2/msys/$arch/'
    ) }
)
foreach ($entry in $mirrorFiles) {
    $content = Get-Content -LiteralPath $entry.Path
    $missing = @($entry.Lines | Where-Object { $_ -notin $content })
    if ($missing.Count -gt 0) {
        $marker = [Array]::IndexOf($content, '## Primary')
        if ($marker -ge 0) {
            $content = @($content[0..$marker]) + $missing + @($content[($marker + 1)..($content.Count - 1)])
            Set-Content -LiteralPath $entry.Path -Value $content -Encoding utf8
        }
    }
}

if (-not $SkipMsysUpdate) {
    Write-Host '正在更新 MSYS2 软件包数据库…' -ForegroundColor Cyan
    Invoke-Msys 'pacman --noconfirm -Syyu'
    Invoke-Msys 'pacman --noconfirm -Syu'
}

Write-Host '正在安装编译器和 GStreamer 依赖（首次约占 2.5 GB）…' -ForegroundColor Cyan
$packages = @(
    'unzip',
    'mingw-w64-ucrt-x86_64-cmake',
    'mingw-w64-ucrt-x86_64-gcc',
    'mingw-w64-ucrt-x86_64-libplist',
    'mingw-w64-ucrt-x86_64-gstreamer',
    'mingw-w64-ucrt-x86_64-gst-plugins-base',
    'mingw-w64-ucrt-x86_64-gst-plugins-good',
    'mingw-w64-ucrt-x86_64-gst-plugins-bad',
    'mingw-w64-ucrt-x86_64-gst-libav'
)
Invoke-Msys ('pacman --noconfirm --needed -S ' + ($packages -join ' '))

if (-not (Test-Path -LiteralPath $sourceArchive)) {
    throw "缺少固定版本源码归档：$sourceArchive"
}
$actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourceArchive).Hash
if ($actualSha256 -ne $expectedSourceSha256) {
    throw "UxPlay 源码校验失败。期望 $expectedSourceSha256，实际 $actualSha256"
}

$buildRoot = Join-Path ([IO.Path]::GetTempPath()) ("AirMirrorLAN-build-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $buildRoot | Out-Null
try {
    Expand-Archive -LiteralPath $sourceArchive -DestinationPath $buildRoot
    $drive = $buildRoot.Substring(0, 1).ToLowerInvariant()
    $rest = $buildRoot.Substring(2).Replace('\', '/')
    $env:AIRMIRROR_SOURCE_UNIX = "/$drive$rest/UxPlay-master"
    Write-Host '正在编译 UxPlay 1.74…' -ForegroundColor Cyan
    Invoke-Msys 'mkdir -p "$AIRMIRROR_SOURCE_UNIX/build" && cd "$AIRMIRROR_SOURCE_UNIX/build" && cmake -G Ninja -DNO_MARCH_NATIVE=ON -DCMAKE_BUILD_TYPE=Release .. && ninja && cmake --install . --prefix /ucrt64'
} finally {
    if ((Test-Path -LiteralPath $buildRoot) -and $buildRoot.StartsWith([IO.Path]::GetTempPath(), [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $buildRoot -Recurse -Force
    }
}

$env:Path = (Join-Path $msysRoot 'ucrt64\bin') + ';' + $env:Path
& $runtimeExe -h | Select-Object -First 2
if ($LASTEXITCODE -ne 0) {
    throw 'UxPlay 已编译，但启动检查失败。'
}
Write-Host "`n安装完成：$runtimeExe" -ForegroundColor Green
Write-Host '下一步：启动 AirMirrorLAN.exe，点击“配置防火墙”，再点击“启动接收”。' -ForegroundColor Green
