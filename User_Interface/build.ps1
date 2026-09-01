[CmdletBinding()]
param(
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvRoot = Join-Path $projectRoot '.venv'
$python = Join-Path $venvRoot 'Scripts\python.exe'

function Remove-GeneratedDirectory {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    if (-not $resolved.StartsWith($projectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove generated path outside the project: $resolved"
    }
    Get-ChildItem -LiteralPath $resolved -Recurse -Force | ForEach-Object {
        $_.Attributes = $_.Attributes -band (-bnot [System.IO.FileAttributes]::ReadOnly)
    }
    $directory = Get-Item -LiteralPath $resolved -Force
    $directory.Attributes = $directory.Attributes -band (-bnot [System.IO.FileAttributes]::ReadOnly)
    Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction Stop
}

Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $python)) {
        py -3.12 -m venv $venvRoot
    }
    $pythonVersion = & $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($pythonVersion.Trim() -ne '3.12') {
        throw "The build virtual environment must use Python 3.12; found $pythonVersion. Recreate .venv with: py -3.12 -m venv .venv"
    }
    if (-not $SkipInstall) {
        & $python -m pip install --upgrade pip
        & $python -m pip install -r requirements-dev.txt
    }
    & $python tools\make_icon.py build\generated\fdem.ico
    & $python -m pytest
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    & $python tools\gui_smoke.py
    Remove-GeneratedDirectory (Join-Path $projectRoot 'build\FDEM_TX_Controller')
    Remove-GeneratedDirectory (Join-Path $projectRoot 'dist\FDEM TX Controller')
    & $python -m PyInstaller --noconfirm --clean FDEM_TX_Controller.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
    $executable = Join-Path $projectRoot 'dist\FDEM TX Controller\FDEM TX Controller.exe'
    if (-not (Test-Path -LiteralPath $executable)) {
        throw "Expected executable was not produced: $executable"
    }
    $process = Start-Process -FilePath $executable -ArgumentList '--version' -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Packaged smoke test failed with exit code $($process.ExitCode)"
    }
    $guiProcess = Start-Process -FilePath $executable -ArgumentList '--smoke-gui' -WindowStyle Hidden -Wait -PassThru
    if ($guiProcess.ExitCode -ne 0) {
        throw "Packaged GUI smoke test failed with exit code $($guiProcess.ExitCode)"
    }
    # PyInstaller leaves a non-distributable intermediate EXE in build/. It
    # cannot locate the adjacent Python DLLs and is easy to mistake for the
    # finished application, so remove that workspace after a successful build.
    Remove-GeneratedDirectory (Join-Path $projectRoot 'build\FDEM_TX_Controller')
    Write-Host "Build complete: $executable"
}
finally {
    Pop-Location
}
