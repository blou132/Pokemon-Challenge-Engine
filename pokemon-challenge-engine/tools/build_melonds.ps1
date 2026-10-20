param(
    [Parameter(Mandatory = $true)][string]$SourceDir,
    [Parameter(Mandatory = $true)][string]$MsysRoot,
    [int]$Jobs = 4
)

$ErrorActionPreference = 'Stop'
$sourcePath = (Resolve-Path -LiteralPath $SourceDir).Path
$toolchainPath = Join-Path (Resolve-Path -LiteralPath $MsysRoot).Path 'ucrt64\bin'
$cmakePath = Join-Path $toolchainPath 'cmake.exe'
$compilerPath = Join-Path $toolchainPath 'g++.exe'
if (!(Test-Path -LiteralPath $cmakePath -PathType Leaf) -or !(Test-Path -LiteralPath $compilerPath -PathType Leaf)) {
    throw 'MSYS2 UCRT64 GCC et CMake sont requis dans le dossier local fourni.'
}
if (!(Test-Path -LiteralPath (Join-Path $sourcePath 'pce-source.json') -PathType Leaf)) {
    throw 'Preparer le checkout exact avec tools/prepare_melonds_source.py avant le build.'
}
$buildPath = Join-Path $sourcePath 'build-pce'
$previousPath = $env:PATH
try {
    $env:PATH = $toolchainPath + [IO.Path]::PathSeparator + $env:PATH
    & $cmakePath -S $sourcePath -B $buildPath -G Ninja `
        '-DCMAKE_BUILD_TYPE=Release' '-DCMAKE_POLICY_VERSION_MINIMUM=3.5' `
        '-DUSE_QT6=OFF' '-DUSE_VCPKG=OFF' '-DBUILD_STATIC=OFF' `
        '-DENABLE_GDBSTUB=OFF' '-DENABLE_JIT=ON' '-DENABLE_LTO_RELEASE=OFF' `
        '-DPORTABLE=ON' '-DMELONDS_VERSION_SUFFIX=-pce.1'
    if ($LASTEXITCODE -ne 0) { throw 'Configuration CMake melonDS en echec.' }
    & $cmakePath --build $buildPath --parallel $Jobs
    if ($LASTEXITCODE -ne 0) { throw 'Compilation melonDS en echec.' }
    $metadata = [ordered]@{
        bridge_version = '1.1-pce.1'
        compiler = (& $compilerPath --version | Select-Object -First 1)
        cmake = (& $cmakePath --version | Select-Object -First 1)
        qt = 'Qt5 dynamic, from the UCRT64 package database'
        options = @('Release', 'ENABLE_GDBSTUB=OFF', 'ENABLE_JIT=ON', 'ENABLE_LTO_RELEASE=OFF', 'PORTABLE=ON')
    }
    [IO.File]::WriteAllText((Join-Path $sourcePath 'pce-build.json'),
        ($metadata | ConvertTo-Json -Depth 4) + [Environment]::NewLine,
        (New-Object System.Text.UTF8Encoding($false)))
} finally {
    $env:PATH = $previousPath
}
