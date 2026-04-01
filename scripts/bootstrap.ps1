$ErrorActionPreference = "Stop"

$InstallProfile = if ($env:INSTALL_PROFILE) { $env:INSTALL_PROFILE.Trim() } else { "full" }
$VenvDir = if ($env:VENV_DIR) { $env:VENV_DIR.Trim() } else { ".venv" }
$PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN.Trim() } else { "python" }

function Invoke-CheckedExternal {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )
    & $FilePath @Arguments
    if (${LASTEXITCODE} -ne 0) {
        throw "Command failed: $FilePath $($Arguments -join ' ')"
    }
}

function Test-HostDependencies {
    Invoke-CheckedExternal $PythonBin @("scripts/host_diagnostics.py", "--json")
}

if (Test-Path $VenvDir) {
    Write-Host "reusing existing virtualenv: $VenvDir"
} else {
    # uv "venv" "--seed" $VenvDir
    Invoke-CheckedExternal "uv" @("venv", "--seed", $VenvDir)
}

Test-HostDependencies

# Install awp-wallet if not present
$AwpWallet = Get-Command awp-wallet -ErrorAction SilentlyContinue
if (-not $AwpWallet) {
    Write-Host "Installing awp-wallet..."
    $Npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $Npm) {
        throw "npm not found. Please install Node.js from https://nodejs.org"
    }
    Invoke-CheckedExternal "npm" @("install", "-g", "@aspect/awp-wallet")
    Write-Host "awp-wallet installed successfully"
} else {
    Write-Host "awp-wallet already installed: $($AwpWallet.Source)"
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
Invoke-CheckedExternal $VenvPython @("-m", "pip", "install", "-r", "requirements-core.txt")
if ($InstallProfile -eq "browser" -or $InstallProfile -eq "full") {
    Invoke-CheckedExternal $VenvPython @("-m", "pip", "install", "-r", "requirements-browser.txt")
}
if ($InstallProfile -eq "full") {
    Invoke-CheckedExternal $VenvPython @("-m", "pip", "install", "-r", "requirements-dev.txt")
}
Invoke-CheckedExternal $VenvPython @("scripts/verify_env.py", "--profile", $InstallProfile)
Invoke-CheckedExternal $VenvPython @("scripts/smoke_test.py")

Write-Host ""
Write-Host "Running post-install check..."
Invoke-CheckedExternal $VenvPython @("scripts/post_install_check.py")
