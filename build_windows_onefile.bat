@echo off
REM ============================================================
REM  Build a single-file SNPPrimerDesktop.exe with PyInstaller.
REM
REM  Difference from build_windows.bat (onedir):
REM   - Uses --onefile for the Python GUI -> single app .exe
REM   - Keeps third-party BLAST/primer3/muscle binaries in dist\bin\
REM     instead of embedding them into the PyInstaller onefile bundle.
REM     This avoids makeblastdb 0xC0000005 crashes seen when NCBI tools
REM     are spawned from a onefile PyInstaller process.
REM   - 5-15 s startup delay each launch (PyInstaller bootloader
REM     extracts the bundle to a temp dir)
REM
REM  Prerequisite: none in the normal case. If venv/bin are missing, this
REM  script bootstraps them first. BLAST/primer3/muscle are copied from
REM  windows\bin\ when present, so no download is needed for those tools.
REM
REM  Output: dist\SNPPrimerDesktop.exe + dist\bin\
REM    Workspace / logs land NEXT TO the .exe under
REM    snp_primer_runtime\ -- whatever directory the user double-
REM    clicks from. Suggest putting the .exe in its own folder
REM    (e.g. C:\Users\<you>\Desktop\SNPPrimer\) so workspace
REM    doesn't pollute the parent directory.
REM ============================================================
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

REM --- Step 1: activate dev venv -------------------------------
set "VENV_ACT=%ROOT%\snp_primer_runtime\venv\Scripts\activate.bat"
if not exist "%VENV_ACT%" (
  echo [BUILD] dev venv not found; bootstrapping runtime without launching GUI...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\windows\bootstrap_and_launch.ps1" -AppRoot "%ROOT%" -NoLaunch
  if errorlevel 1 goto :err
)
if not exist "%VENV_ACT%" (
  echo [ERROR] dev venv still not found after bootstrap:
  echo   %VENV_ACT%
  goto :err
)
call "%VENV_ACT%" || goto :err

REM --- Step 2: install / upgrade PyInstaller -------------------
echo [BUILD] installing pyinstaller into venv...
python -m pip install --upgrade pyinstaller
if errorlevel 1 goto :err

REM --- Step 3: verify required Windows binaries exist ----------
set "BIN=%ROOT%\snp_primer_runtime\bin"
set "NEED_BOOTSTRAP="
for %%F in (blastn.exe blastdbcmd.exe makeblastdb.exe primer3_core.exe muscle.exe nghttp2.dll ncbi-vdb-md.dll) do (
  if not exist "%BIN%\%%F" set "NEED_BOOTSTRAP=1"
)
if defined NEED_BOOTSTRAP (
  echo [BUILD] required runtime binaries missing; bootstrapping runtime without launching GUI...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\windows\bootstrap_and_launch.ps1" -AppRoot "%ROOT%" -NoLaunch
  if errorlevel 1 goto :err
)
for %%F in (blastn.exe blastdbcmd.exe makeblastdb.exe primer3_core.exe muscle.exe nghttp2.dll ncbi-vdb-md.dll) do (
  if not exist "%BIN%\%%F" (
    echo [ERROR] missing binary: %BIN%\%%F
    echo Check windows\bin\ or run "windows\Launch SNP Primer Desktop.cmd" once.
    goto :err
  )
)

REM --- Step 4: clean previous build artifacts ------------------
if exist "%ROOT%\dist"  rmdir /s /q "%ROOT%\dist"
if exist "%ROOT%\build" rmdir /s /q "%ROOT%\build"
if exist "%ROOT%\SNPPrimerDesktop.spec" del "%ROOT%\SNPPrimerDesktop.spec"

REM --- Step 5: PyInstaller --onefile build ---------------------
REM   --onefile               : pack everything into one .exe; at runtime
REM                             the bootloader extracts to %TEMP%\_MEIxxxx\
REM   --windowed              : no console window for the .exe
REM   --paths src --paths .   : let PyInstaller find both src/ and core/
REM   --add-data ...          : ship core/assets (NEB / global_settings /
REM                             primer3_config) + references catalog
REM   Third-party binaries are copied to dist\bin\ after the build. They are
REM   not bundled with --add-binary because makeblastdb can crash with
REM   0xC0000005 when launched from a PyInstaller onefile runtime.
REM   --collect-submodules    : pull all snp_primer_app + core submodules
echo [BUILD] running PyInstaller (--onefile, may take a couple minutes)...
pyinstaller --noconfirm --clean ^
  --onefile ^
  --name SNPPrimerDesktop ^
  --windowed ^
  --paths "%ROOT%\src" ^
  --paths "%ROOT%" ^
  --add-data "%ROOT%\core\assets;core\assets" ^
  --add-data "%ROOT%\references\catalog.example.json;references" ^
  --collect-submodules snp_primer_app ^
  --collect-submodules core ^
  "%ROOT%\src\snp_primer_app\launch_gui.py"
if errorlevel 1 goto :err

REM --- Step 5b: copy third-party binaries beside the onefile exe ----
echo [BUILD] copying runtime binaries to dist\bin\ ...
if not exist "%ROOT%\dist\bin" mkdir "%ROOT%\dist\bin"
for %%F in (blastn.exe blastdbcmd.exe makeblastdb.exe primer3_core.exe muscle.exe nghttp2.dll ncbi-vdb-md.dll) do (
  copy /Y "%BIN%\%%F" "%ROOT%\dist\bin\%%F" >nul
  if errorlevel 1 goto :err
)

REM --- Step 6: success summary ---------------------------------
echo.
echo ============================================================
echo  BUILD SUCCESS (--onefile)
echo  Output : %ROOT%\dist\SNPPrimerDesktop.exe
echo  Bin    : %ROOT%\dist\bin\
echo  Size   :
for %%S in ("%ROOT%\dist\SNPPrimerDesktop.exe") do echo    %%~zS bytes
echo ============================================================
echo  Distribute SNPPrimerDesktop.exe together with the dist\bin\ folder.
echo  End users double-click -- no Python needed.
echo  NOTE: first launch takes 5-15 s while PyInstaller extracts the
echo        bundle to %%TEMP%%\_MEIxxxxxx\ -- this is normal.
echo  TIP : put the .exe in its own folder so workspace / logs (which
echo        get created next to the .exe) don't pollute the parent dir.
goto :end

:err
echo.
echo *** BUILD FAILED ***
echo See errors above. Common causes:
echo   - venv not bootstrapped (run Launch SNP Primer Desktop.cmd once)
echo   - bin\ missing .exe / .dll (same fix)
echo   - antivirus quarantining pyinstaller bootloader (more likely
echo     with --onefile than --onedir; whitelist or use build_windows.bat
echo     for onedir build instead)

:end
echo.
pause
endlocal
