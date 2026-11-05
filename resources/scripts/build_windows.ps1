# =============================================================================================
# Build the Windows release of HDLDesigner with PyInstaller.
#
#     powershell -ExecutionPolicy Bypass -File resources\scripts\build_windows.ps1
#
# Run from anywhere: paths are taken relative to this script. Needs the packages of
# requirements.txt and PyInstaller (pip install pyinstaller) in the active Python.
# Result: dist\HDLDesigner\ and dist\HDLDesigner-<version>-windows-x64.zip
# =============================================================================================
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\..')        # repository root
Set-Location $root

# version of the release: __version__ of src/version.py
$version = python -c "import sys; sys.path.insert(0, 'src'); import version; print(version.__version__)"

# build the folder distribution (work files in build\, result in dist\HDLDesigner)
pyinstaller --noconfirm --distpath dist --workpath build resources\scripts\HDLDesigner.spec

# pack it for distribution. Right after the build a virus scanner often still holds the new
# files open ("being used by another process"): try again a few times before giving up.
$zip = "dist\HDLDesigner-$version-windows-x64.zip"
for ($try = 1; $try -le 5; $try++) {
    try {
        Compress-Archive -Path dist\HDLDesigner -DestinationPath $zip -Force -ErrorAction Stop
        Write-Host "Built $zip"
        exit 0
    } catch {
        Write-Host "Packing failed (try $try of 5): $($_.Exception.Message)"
        Start-Sleep -Seconds 5
    }
}
exit 1
