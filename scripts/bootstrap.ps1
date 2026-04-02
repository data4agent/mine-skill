$ErrorActionPreference = "Stop"

$InstallProfile = if ($env:INSTALL_PROFILE) { $env:INSTALL_PROFILE.Trim() } else { "full" }
$VenvDir = if ($env:VENV_DIR) { $env:VENV_DIR.Trim() } else { ".venv" }
$PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN.Trim() } else { "python" }

if (-not $env:HOME -and $env:USERPROFILE) {
    $env:HOME = $env:USERPROFILE
}

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
    Write-Host "Installing awp-wallet from GitHub..."

    # Check prerequisites
    $Git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $Git) {
        throw "git not found. Please install Git from https://git-scm.com"
    }

    $Node = Get-Command node -ErrorAction SilentlyContinue
    if (-not $Node) {
        throw "Node.js not found. Please install Node.js 20+ from https://nodejs.org"
    }

    # Determine version to install (prefer latest tag, fallback to main)
    $AwpVersion = $env:AWP_WALLET_VERSION
    if (-not $AwpVersion) {
        try {
            $tags = git ls-remote --tags --sort=-v:refname https://github.com/awp-core/awp-wallet.git 2>$null
            $AwpVersion = ($tags | Select-String -Pattern 'v\d+\.\d+\.\d+' -AllMatches).Matches.Value | Select-Object -First 1
        } catch {
            $AwpVersion = $null
        }
    }
    if (-not $AwpVersion) { $AwpVersion = "main" }
    Write-Host "  Target version: $AwpVersion"

    # Clone and install from GitHub
    $TempDir = Join-Path $env:TEMP "awp-wallet-install"
    if (Test-Path $TempDir) {
        Remove-Item $TempDir -Recurse -Force
    }

    Invoke-CheckedExternal "git" @("clone", "--branch", $AwpVersion, "--depth", "1", "https://github.com/awp-core/awp-wallet.git", $TempDir)
    Push-Location $TempDir
    try {
        Invoke-CheckedExternal "npm" @("install")
        Invoke-CheckedExternal "npm" @("install", "-g", ".")
        Write-Host "awp-wallet $AwpVersion installed successfully from GitHub"
    } finally {
        Pop-Location
        Remove-Item $TempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
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
if (($InstallProfile -eq "browser" -or $InstallProfile -eq "full") -and $IsWindows) {
    Write-Host "Checking Windows local browser mode..."
    Invoke-CheckedExternal $VenvPython @("auto-browser/scripts/vrd.py", "check")
}
Invoke-CheckedExternal $VenvPython @("scripts/verify_env.py", "--profile", $InstallProfile)
Invoke-CheckedExternal $VenvPython @("scripts/smoke_test.py")

Write-Host ""
Write-Host "Running post-install check..."
Invoke-CheckedExternal $VenvPython @("scripts/post_install_check.py")
