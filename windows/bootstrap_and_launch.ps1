param(
    [Parameter(Mandatory = $false)]
    [string]$AppRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,

    [Parameter(Mandatory = $false)]
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$AppDataRoot = Join-Path (Resolve-Path $AppRoot).Path "snp_primer_runtime"
$BundledBinRoot = Join-Path (Resolve-Path $AppRoot).Path "windows\bin"
$RuntimeRoot = $AppDataRoot
$PythonRoot = Join-Path $AppDataRoot "python311"
$VenvRoot = Join-Path $AppDataRoot "venv"
$BinRoot = Join-Path $AppDataRoot "bin"
$WorkspaceRoot = Join-Path $AppDataRoot "workspace"
$ReferenceRoot = Join-Path $AppDataRoot "references"
$DownloadsRoot = Join-Path $AppDataRoot "downloads"
$TempRoot = Join-Path $AppDataRoot "tmp"
$BootstrapLog = Join-Path $AppDataRoot "bootstrap.log"
$PythonArchiveUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.zip"
$PythonArchiveSha256 = "4ba90a4ab8990891033d37ff04d2047fdae8948d0d2729a68d3a6a17c585b681"
$BlastTarUrl = "https://ftp.ncbi.nlm.nih.gov/blast/executables/LATEST/ncbi-blast-2.17.0+-x64-win64.tar.gz"

function Write-Status {
    param([string]$Message)
    Write-Host "[SNPPrimer] $Message"
}

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Test-DownloadedFile {
    param(
        [string]$Path,
        [int]$MinBytes = 0,
        [string]$Sha256 = "",
        [string]$Context = "File"
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return $false
    }
    if ($MinBytes -gt 0) {
        try {
            $sz = (Get-Item -LiteralPath $Path).Length
        } catch {
            Write-Status "$Context $Path could not be inspected; re-downloading"
            return $false
        }
        if ($sz -lt $MinBytes) {
            Write-Status "$Context $Path is $sz bytes (< $MinBytes expected); re-downloading"
            return $false
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($Sha256)) {
        try {
            $ActualSha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        } catch {
            Write-Status "$Context $Path could not be hashed; re-downloading"
            return $false
        }
        if ($ActualSha256 -ne $Sha256.ToLowerInvariant()) {
            Write-Status "$Context $Path SHA256 mismatch; re-downloading"
            return $false
        }
    }
    return $true
}

function Invoke-Download {
    # Robust download with crash-safe semantics:
    #  - Writes to a .partial sidecar; renames to OutFile only on full success.
    #  - Any failure during download cleans the .partial up, so the next retry
    #    re-downloads from scratch and does NOT reuse a corrupt cached file.
    #  - Optional -MinBytes catches truncated downloads that did NOT raise an
    #    HTTP error (antivirus / proxy mid-stream cuts).
    #  - Optional -Sha256 catches full-size but modified/corrupt cached files.
    # Guards against corrupt Python runtime downloads. See CLAUDE.md section
    # 6.10 for the bug history.
    param(
        [string]$Url,
        [string]$OutFile,
        [int]$MinBytes = 0,
        [string]$Sha256 = ""
    )
    if (Test-Path -LiteralPath $OutFile) {
        if (Test-DownloadedFile -Path $OutFile -MinBytes $MinBytes -Sha256 $Sha256 -Context "Cached") {
            return
        } else {
            Remove-Item -LiteralPath $OutFile -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Status "Downloading $Url"
    $Partial = "$OutFile.partial"
    if (Test-Path -LiteralPath $Partial) {
        Remove-Item -LiteralPath $Partial -Force -ErrorAction SilentlyContinue
    }
    try {
        Invoke-WebRequest -Uri $Url -OutFile $Partial -UseBasicParsing
    } catch {
        if (Test-Path -LiteralPath $Partial) {
            Remove-Item -LiteralPath $Partial -Force -ErrorAction SilentlyContinue
        }
        throw ("Download failed: " + $Url + " -- " + $_.Exception.Message + `
               ". If this is a network / antivirus problem, fix the network and re-run. " + `
               "Or manually place the file at: " + $OutFile)
    }
    if (-not (Test-DownloadedFile -Path $Partial -MinBytes $MinBytes -Sha256 $Sha256 -Context "Downloaded")) {
        Remove-Item -LiteralPath $Partial -Force -ErrorAction SilentlyContinue
        throw ("Downloaded $Url failed validation. Connection may have been " + `
               "truncated or modified by antivirus / proxy. Re-run to retry.")
    }
    Move-Item -LiteralPath $Partial -Destination $OutFile -Force
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$Description
    )
    Write-Status $Description
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

function Get-ExistingPython {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try {
            $pythonPath = & $pyLauncher.Source -3.11 -c "import sys; print(sys.executable)"
            if ($LASTEXITCODE -eq 0 -and $pythonPath) {
                return $pythonPath.Trim()
            }
        }
        catch {
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        try {
            $versionText = & $python.Source -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"
            if ($LASTEXITCODE -eq 0 -and $versionText) {
                $parts = $versionText.Trim().Split(".")
                if ([int]$parts[0] -gt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11)) {
                    return $python.Source
                }
            }
        }
        catch {
        }
    }

    return $null
}

function Test-PythonRuntime {
    param(
        [string]$PythonExe,
        [string]$Context
    )
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        return $false
    }
    try {
        $Probe = "import sys, venv, ensurepip, tkinter; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
        $null = & $PythonExe "-c" $Probe 2>$null
        if ($LASTEXITCODE -eq 0) {
            return $true
        }
        Write-Status "$Context failed Python runtime probe (exit=$LASTEXITCODE)"
    } catch {
        Write-Status "$Context could not run Python runtime probe"
    }
    return $false
}

function Ensure-LocalPython {
    $ExistingPython = Get-ExistingPython
    if ($ExistingPython) {
        Write-Status "Using existing Python: $ExistingPython"
        return $ExistingPython
    }

    $PythonExe = Join-Path $PythonRoot "python.exe"
    if (Test-Path -LiteralPath $PythonExe) {
        if (Test-PythonRuntime -PythonExe $PythonExe -Context "Existing local Python") {
            return $PythonExe
        }
        Write-Status "Existing local Python runtime is broken; rebuilding"
        Remove-Item -LiteralPath $PythonRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    Ensure-Directory (Split-Path -Parent $PythonRoot)
    Ensure-Directory $DownloadsRoot
    Ensure-Directory $TempRoot
    $Archive = Join-Path $DownloadsRoot "python-3.11.9-amd64.zip"
    # python-3.11.9-amd64.zip is ~32 MB; refuse anything under 30 MB as truncated.
    Invoke-Download -Url $PythonArchiveUrl -OutFile $Archive -MinBytes 30000000 -Sha256 $PythonArchiveSha256

    $ExtractRoot = Join-Path $TempRoot "python311_extract"
    if (Test-Path -LiteralPath $ExtractRoot) {
        Remove-Item -LiteralPath $ExtractRoot -Recurse -Force
    }
    Ensure-Directory $ExtractRoot
    Write-Status "Extracting local Python runtime"
    try {
        Expand-Archive -LiteralPath $Archive -DestinationPath $ExtractRoot -Force
    } catch {
        Remove-Item -LiteralPath $ExtractRoot -Recurse -Force -ErrorAction SilentlyContinue
        throw ("Failed to extract Python runtime archive: " + $_.Exception.Message)
    }

    $StagedPython = Join-Path $ExtractRoot "python.exe"
    $StagedRoot = $ExtractRoot
    if (-not (Test-Path -LiteralPath $StagedPython)) {
        $FoundPython = Get-ChildItem -Path $ExtractRoot -Filter "python.exe" -Recurse | Select-Object -First 1
        if (-not $FoundPython) {
            Remove-Item -LiteralPath $ExtractRoot -Recurse -Force -ErrorAction SilentlyContinue
            throw "Python runtime archive did not contain python.exe"
        }
        $StagedPython = $FoundPython.FullName
        $StagedRoot = Split-Path -Parent $StagedPython
    }
    if (-not (Test-PythonRuntime -PythonExe $StagedPython -Context "Staged local Python")) {
        Remove-Item -LiteralPath $ExtractRoot -Recurse -Force -ErrorAction SilentlyContinue
        throw "Extracted Python runtime failed validation"
    }

    if (Test-Path -LiteralPath $PythonRoot) {
        Remove-Item -LiteralPath $PythonRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $PythonRoot) {
        Remove-Item -LiteralPath $ExtractRoot -Recurse -Force -ErrorAction SilentlyContinue
        throw "Could not remove old Python runtime at $PythonRoot"
    }
    Move-Item -LiteralPath $StagedRoot -Destination $PythonRoot -Force
    if (Test-Path -LiteralPath $ExtractRoot) {
        Remove-Item -LiteralPath $ExtractRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-PythonRuntime -PythonExe $PythonExe -Context "Installed local Python")) {
        throw "Failed to prepare Python runtime into $PythonRoot"
    }
    return $PythonExe
}

function Ensure-Venv {
    # A venv carries a hard-coded path to its base interpreter in pyvenv.cfg.
    # If a bundle is built on machine A and copied to machine B with a different
    # Python install path, the venv launcher errors with
    #   No Python at '<machine A path>'
    # and pip / project install fail with exit code 103. Detect that here by
    # running the launcher; if it can't import sys, blow the venv away and
    # recreate it against the current $PythonExe. See CLAUDE.md section 6.11.
    param([string]$PythonExe)
    $VenvPython = Join-Path $VenvRoot "Scripts\python.exe"
    $NeedRecreate = $false
    if (Test-Path -LiteralPath $VenvPython) {
        try {
            $null = & $VenvPython "-c" "import sys" 2>$null
            if ($LASTEXITCODE -ne 0) {
                Write-Status "Existing venv is broken (launcher exit=$LASTEXITCODE); will recreate"
                $NeedRecreate = $true
            }
        } catch {
            Write-Status "Existing venv launcher could not run; will recreate"
            $NeedRecreate = $true
        }
    } else {
        $NeedRecreate = $true
    }
    if ($NeedRecreate) {
        if (Test-Path -LiteralPath $VenvRoot) {
            Write-Status "Removing stale venv: $VenvRoot"
            Remove-Item -LiteralPath $VenvRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
        Invoke-Checked -FilePath $PythonExe -Arguments @("-m", "venv", $VenvRoot) -Description "Creating virtual environment"
    }
    return $VenvPython
}

function Ensure-ProjectInstalled {
    param([string]$VenvPython)
    Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip") -Description "Upgrading pip"
    # NOTE: v5 now uses the primer3_core binary + upstream global_settings.txt
    # (see core/getCAPS.py and Ensure-Primer3Core). primer3-py is no longer needed.
    Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "--editable", $AppRoot) -Description "Installing SNP Primer app"
}

function Ensure-BlastTools {
    # NCBI BLAST+ ships a few helper DLLs alongside the .exe (nghttp2.dll for
    # blastn HTTP/2, ncbi-vdb-md.dll for SRA/DB ops). They MUST sit in the same
    # directory as the .exe -- otherwise blastn.exe fails to load with
    # 0xC0000135 STATUS_DLL_NOT_FOUND, with no visible error message.
    # Earlier versions of this script only copied the .exe and missed these.
    if (
        (Test-Path -LiteralPath (Join-Path $BinRoot "blastn.exe")) -and
        (Test-Path -LiteralPath (Join-Path $BinRoot "blastdbcmd.exe")) -and
        (Test-Path -LiteralPath (Join-Path $BinRoot "makeblastdb.exe")) -and
        (Test-Path -LiteralPath (Join-Path $BinRoot "nghttp2.dll"))
    ) {
        return
    }

    Ensure-Directory (Split-Path -Parent $BootstrapLog)
    Ensure-Directory $BinRoot
    Ensure-Directory $DownloadsRoot
    Ensure-Directory $TempRoot
    $TarPath = Join-Path $DownloadsRoot "ncbi-blast-x64-win64.tar.gz"
    $ExtractRoot = Join-Path $TempRoot "blast_extract"
    # NCBI BLAST 2.17 win64 tar.gz is ~75 MB; refuse anything under 50 MB
    Invoke-Download -Url $BlastTarUrl -OutFile $TarPath -MinBytes 50000000
    if (Test-Path -LiteralPath $ExtractRoot) {
        Remove-Item -LiteralPath $ExtractRoot -Recurse -Force
    }
    Ensure-Directory $ExtractRoot
    Invoke-Checked -FilePath "tar" -Arguments @("-xf", $TarPath, "-C", $ExtractRoot) -Description "Extracting BLAST+"
    $BlastBin = Get-ChildItem -Path $ExtractRoot -Directory | Select-Object -First 1
    if (-not $BlastBin) {
        throw "Could not unpack BLAST+ archive"
    }
    $SrcBin = Join-Path $BlastBin.FullName "bin"
    # Copy every .exe and .dll from the extracted bin/ into our $BinRoot.
    # Future-proofs against NCBI adding more bundled DLLs.
    Get-ChildItem -Path $SrcBin -File | Where-Object {
        $_.Extension -in @(".exe", ".dll")
    } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $BinRoot $_.Name) -Force
    }
}

function Copy-BundledBinaries {
    if (-not (Test-Path -LiteralPath $BundledBinRoot)) {
        return
    }
    Ensure-Directory $BinRoot
    # Accept both muscle5.exe (correct, v9+) and muscle.exe (legacy v8 name).
    # Whichever exists under windows/bin gets copied through; Ensure-Muscle
    # handles any rename/migration on the runtime side.
    $Names = @(
        "blastdbcmd.exe",
        "blastn.exe",
        "makeblastdb.exe",
        "muscle5.exe",
        "muscle.exe",
        "ncbi-vdb-md.dll",
        "nghttp2.dll",
        "primer3_core.exe"
    )
    foreach ($Name in $Names) {
        $Src = Join-Path $BundledBinRoot $Name
        if (-not (Test-Path -LiteralPath $Src)) {
            continue
        }
        $Dst = Join-Path $BinRoot $Name
        $NeedCopy = $true
        if (Test-Path -LiteralPath $Dst) {
            try {
                $NeedCopy = ((Get-Item -LiteralPath $Dst).Length -ne (Get-Item -LiteralPath $Src).Length)
            } catch {
                $NeedCopy = $true
            }
        }
        if ($NeedCopy) {
            Write-Status "Copying bundled binary: $Name"
            Copy-Item -LiteralPath $Src -Destination $Dst -Force
        }
    }
}

function Ensure-Primer3Core {
    # v5 uses the primer3_core binary + upstream global_settings.txt (not primer3-py).
    # The upstream SNP_Primer_Pipeline repo ships a Windows-compatible primer3_core.exe.
    if (-not $BinRoot) {
        throw "Ensure-Primer3Core: BinRoot is null. Bootstrap variable scope is broken."
    }
    Ensure-Directory $BinRoot
    $Primer3Exe = Join-Path $BinRoot "primer3_core.exe"
    if (Test-Path -LiteralPath $Primer3Exe) {
        try {
            $Size = (Get-Item -LiteralPath $Primer3Exe).Length
            if ($Size -gt 0) { return }
            Remove-Item -LiteralPath $Primer3Exe -Force  # 0-byte WSL leftover
        } catch {}
    }
    $Url = "https://raw.githubusercontent.com/pinbo/SNP_Primer_Pipeline/master/bin/primer3_core.exe"
    # primer3_core.exe is ~150 KB upstream; refuse anything under 50 KB
    Invoke-Download -Url $Url -OutFile $Primer3Exe -MinBytes 50000
    if (-not (Test-Path -LiteralPath $Primer3Exe)) {
        throw "Failed to download primer3_core.exe to $BinRoot"
    }
}

function Remove-LinuxJunkBinaries {
    # Earlier WSL test sessions may have left 0-byte "broken Linux symlinks" inside
    # bin/, sharing names with the Windows .exe (e.g. blastn vs blastn.exe). They
    # would trick core.pipeline._which() into returning a non-PE path, which
    # Windows then refuses to execute -> [WinError 1920]. Clean them up here.
    if (-not $BinRoot) { return }
    if (-not (Test-Path -LiteralPath $BinRoot)) { return }
    $Names = @("blastn", "blastdbcmd", "makeblastdb", "muscle", "muscle5", "primer3_core")
    foreach ($n in $Names) {
        $p = Join-Path $BinRoot $n
        if (Test-Path -LiteralPath $p) {
            try {
                $Size = (Get-Item -LiteralPath $p).Length
                if ($Size -eq 0) {
                    Write-Status "Removing 0-byte WSL leftover: $p"
                    Remove-Item -LiteralPath $p -Force
                }
            } catch {}
        }
    }
}

function Test-VCRedistInstalled {
    # Microsoft Visual C++ 2015-2022 Redistributable (x64) writes this registry
    # key on install. Both VC 14.0 (2015) and 14.x (2017/2019/2022) report under
    # the "VC\Runtimes\x64" subtree -- they are binary-compatible by design.
    $Key = "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
    if (-not (Test-Path -LiteralPath $Key)) { return $false }
    try {
        $val = Get-ItemProperty -Path $Key -Name "Installed" -ErrorAction Stop
        return ($val.Installed -eq 1)
    } catch {
        return $false
    }
}

function Install-VCRedist {
    Write-Status "Microsoft Visual C++ Redistributable not detected; downloading installer..."
    Ensure-Directory $DownloadsRoot
    $Url = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
    $InstallerPath = Join-Path $DownloadsRoot "vc_redist.x64.exe"
    # vc_redist.x64.exe is ~25 MB; refuse anything under 10 MB
    Invoke-Download -Url $Url -OutFile $InstallerPath -MinBytes 10000000
    Write-Host ""
    Write-Host "==============================================================" -ForegroundColor Yellow
    Write-Host " About to install Microsoft Visual C++ Redistributable (x64)." -ForegroundColor Yellow
    Write-Host " Windows will prompt for administrator approval (UAC dialog)." -ForegroundColor Yellow
    Write-Host " This is required so blastn / primer3_core / muscle can run." -ForegroundColor Yellow
    Write-Host "==============================================================" -ForegroundColor Yellow
    Write-Host ""
    try {
        $proc = Start-Process -FilePath $InstallerPath `
            -ArgumentList @("/install", "/quiet", "/norestart") `
            -Verb RunAs -Wait -PassThru
        $code = $proc.ExitCode
    } catch {
        throw ("Could not run VC++ Redistributable installer: " + $_.Exception.Message + `
               ". Please install manually: https://aka.ms/vs/17/release/vc_redist.x64.exe")
    }
    # 0 = success, 1638 = newer version already installed, 3010 = success but reboot needed
    if ($code -eq 0 -or $code -eq 1638) {
        Write-Status "VC++ Redistributable installed."
        return
    }
    if ($code -eq 3010) {
        Write-Host ""
        Write-Host "VC++ Redistributable installed, but Windows needs a REBOOT before BLAST can run." -ForegroundColor Yellow
        Write-Host "Please reboot, then re-run Launch SNP Primer Desktop.cmd." -ForegroundColor Yellow
        Write-Host ""
        throw "VC++ Redistributable installed but reboot required"
    }
    throw ("VC++ Redistributable installer returned exit code " + $code + `
           ". Try installing manually: https://aka.ms/vs/17/release/vc_redist.x64.exe")
}

function Ensure-VCRedist {
    if (Test-VCRedistInstalled) {
        Write-Status "Microsoft Visual C++ Redistributable detected"
        return
    }
    Install-VCRedist
    if (-not (Test-VCRedistInstalled)) {
        throw "VC++ Redistributable still not detected after install attempt - reboot may be required"
    }
}

function Test-BinaryRunnable {
    # Smoke-test a Windows .exe by launching it with a harmless flag (e.g. -version)
    # and inspecting the exit code. The point is to catch 0xC0000135
    # (STATUS_DLL_NOT_FOUND) up front, which happens when Microsoft Visual C++
    # Redistributable is not installed - NCBI BLAST+ / primer3 / muscle all link
    # against vcruntime140.dll / msvcp140.dll. Without VC++ Redist the .exe
    # cannot start and the error surface (in the GUI) is an empty stderr +
    # returncode 3221225781, which is impossible for a user to diagnose.
    param([string]$Path, [string]$Name, [string[]]$VersionArgs)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Name binary not found at $Path"
    }
    Write-Status ("Smoke-testing " + $Name)
    $tmpOut = [System.IO.Path]::GetTempFileName()
    $tmpErr = [System.IO.Path]::GetTempFileName()
    try {
        $proc = Start-Process -FilePath $Path -ArgumentList $VersionArgs `
            -NoNewWindow -PassThru -Wait `
            -RedirectStandardOutput $tmpOut `
            -RedirectStandardError $tmpErr
        $code = $proc.ExitCode
    } catch {
        throw ("$Name could not be launched: " + $_.Exception.Message)
    } finally {
        Remove-Item -LiteralPath $tmpOut, $tmpErr -ErrorAction SilentlyContinue
    }
    if ($code -eq 0) { return }
    # 0xC0000135 = -1073741515 (signed int32) = 3221225781 (unsigned uint32).
    # PowerShell may surface either depending on environment.
    if ($code -eq -1073741515 -or $code -eq 3221225781) {
        Write-Host ""
        Write-Host ("ERROR: " + $Name + " failed to start (0xC0000135 STATUS_DLL_NOT_FOUND).") -ForegroundColor Red
        Write-Host "  Microsoft Visual C++ 2015-2022 Redistributable (x64) is required but missing." -ForegroundColor Red
        Write-Host "  Download and install from:" -ForegroundColor Red
        Write-Host "    https://aka.ms/vs/17/release/vc_redist.x64.exe" -ForegroundColor Yellow
        Write-Host "  Then re-run Launch SNP Primer Desktop.cmd." -ForegroundColor Red
        Write-Host ""
        throw ($Name + " unrunnable - install VC++ Redistributable first")
    }
    # Some tools (e.g. muscle) may return non-zero on -version. Only treat
    # actual launch failure (negative status code) as fatal; otherwise warn
    # and continue.
    if ($code -lt 0 -or $code -gt 1000000) {
        throw ("$Name returned exit code " + $code + " (likely Windows NTSTATUS error)")
    }
    Write-Status ("  " + $Name + " smoke test exit=" + $code + ", continuing")
}

function Ensure-Muscle {
    # NCBI muscle v5 uses '-align <in> -output <out>'; v3 used '-in <in> -out <out>'.
    # core/getkasp3.py:_muscle_align_cmd selects syntax by filename:
    #   muscle5.exe -> v5 syntax
    #   muscle.exe  -> v3 syntax (fallback)
    # We always download v5 (rcedgar/muscle latest), so always save as muscle5.exe.
    # get_software_path() also prefers muscle5.exe over muscle.exe. See CLAUDE.md
    # section 6.12 for the bug history (KASP `[Errno 2] alignment_raw_*.fa`).
    $Muscle5Exe = Join-Path $BinRoot "muscle5.exe"
    $LegacyMuscle = Join-Path $BinRoot "muscle.exe"

    # Migrate existing installs that saved v5 as muscle.exe (v8 / early v9).
    # One-time rename, idempotent.
    if ((Test-Path -LiteralPath $LegacyMuscle) -and (-not (Test-Path -LiteralPath $Muscle5Exe))) {
        Write-Status "Renaming legacy bin\muscle.exe to muscle5.exe (v5 download had the wrong name)"
        Move-Item -LiteralPath $LegacyMuscle -Destination $Muscle5Exe -Force
    }
    if (Test-Path -LiteralPath $Muscle5Exe) {
        return
    }

    Ensure-Directory $BinRoot
    Write-Status "Downloading MUSCLE latest Windows release"
    $Release = Invoke-RestMethod -Uri "https://api.github.com/repos/rcedgar/muscle/releases/latest"
    $Asset = $Release.assets | Where-Object {
        $_.name -match "win" -and ($_.name -match "\.exe$" -or $_.name -match "\.zip$")
    } | Select-Object -First 1
    if (-not $Asset) {
        throw "Could not find a Windows MUSCLE asset in the latest GitHub release."
    }
    Ensure-Directory $DownloadsRoot
    Ensure-Directory $TempRoot
    $AssetPath = Join-Path $DownloadsRoot $Asset.name
    # muscle-win64.v5.3.exe is ~5 MB; refuse anything under 1 MB as truncated
    Invoke-Download -Url $Asset.browser_download_url -OutFile $AssetPath -MinBytes 1000000
    if ($Asset.name -match "\.zip$") {
        $ExtractRoot = Join-Path $TempRoot "muscle_extract"
        if (Test-Path -LiteralPath $ExtractRoot) {
            Remove-Item -LiteralPath $ExtractRoot -Recurse -Force
        }
        Expand-Archive -LiteralPath $AssetPath -DestinationPath $ExtractRoot
        $Found = Get-ChildItem -Path $ExtractRoot -Filter "muscle*.exe" -Recurse | Select-Object -First 1
        if (-not $Found) {
            throw "Downloaded MUSCLE archive but no muscle.exe was found."
        }
        Copy-Item -LiteralPath $Found.FullName -Destination $Muscle5Exe -Force
        return
    }
    Copy-Item -LiteralPath $AssetPath -Destination $Muscle5Exe -Force
}

Ensure-Directory $RuntimeRoot
Ensure-Directory (Split-Path -Parent $PythonRoot)
Ensure-Directory $DownloadsRoot
Ensure-Directory $TempRoot
Ensure-Directory $WorkspaceRoot
Ensure-Directory $ReferenceRoot

Start-Transcript -Path $BootstrapLog -Append | Out-Null
try {
    $PythonExe = Ensure-LocalPython
    $VenvPython = Ensure-Venv -PythonExe $PythonExe
    Ensure-ProjectInstalled -VenvPython $VenvPython
    Remove-LinuxJunkBinaries
    Copy-BundledBinaries
    Ensure-BlastTools
    Ensure-Muscle
    Ensure-Primer3Core

    # Visual C++ Runtime is required for all three .exe tools above. Detect
    # via registry; if missing, prompt for elevation and install silently.
    Ensure-VCRedist

    # Catch missing-DLL failures (0xC0000135) before the GUI hits them
    # mid-pipeline with an empty stderr. Should always pass after Ensure-VCRedist.
    Test-BinaryRunnable -Path (Join-Path $BinRoot "blastn.exe") -Name "blastn" -VersionArgs @("-version")
    Test-BinaryRunnable -Path (Join-Path $BinRoot "primer3_core.exe") -Name "primer3_core" -VersionArgs @("-about")
    # Prefer muscle5.exe; fall back to legacy muscle.exe if user has the old name.
    $MuscleProbe = Join-Path $BinRoot "muscle5.exe"
    if (-not (Test-Path -LiteralPath $MuscleProbe)) {
        $MuscleProbe = Join-Path $BinRoot "muscle.exe"
    }
    Test-BinaryRunnable -Path $MuscleProbe -Name "muscle" -VersionArgs @("-version")

    if ($NoLaunch) {
        Write-Status "Bootstrap complete; not launching desktop app because -NoLaunch was set"
        return
    }

    $env:SNP_PRIMER_HOME = $RuntimeRoot
    $env:SNP_PRIMER_BINARY_ROOT = $BinRoot
    $env:SNP_PRIMER_WORKDIR = $WorkspaceRoot
    $KnownReference = Get-ChildItem -Path $ReferenceRoot -Recurse -Include *.fa,*.fasta,*.fna -File | Select-Object -First 1
    if ($KnownReference) {
        $env:SNP_PRIMER_REFERENCE_FASTA = $KnownReference.FullName
    }

    $Pythonw = Join-Path $VenvRoot "Scripts\pythonw.exe"
    $PythonCli = Join-Path $VenvRoot "Scripts\python.exe"
    Write-Status "Launching desktop app"
    if (Test-Path -LiteralPath $Pythonw) {
        $GuiProcess = Start-Process -FilePath $Pythonw -WorkingDirectory $AppRoot -ArgumentList @("-m", "snp_primer_app.launch_gui") -PassThru
        Start-Sleep -Seconds 2
        if ($GuiProcess.HasExited) {
            throw "Desktop process exited immediately. See $RuntimeRoot\desktop_startup_error.log"
        }
    } else {
        Invoke-Checked -FilePath $PythonCli -Arguments @("-m", "snp_primer_app.launch_gui") -Description "Launching desktop app"
    }
}
catch {
    Write-Host ""
    Write-Host "Bootstrap failed. See log: $BootstrapLog" -ForegroundColor Red
    throw
}
finally {
    Stop-Transcript | Out-Null
}
