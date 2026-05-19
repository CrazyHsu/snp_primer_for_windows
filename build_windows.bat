@echo off
REM ============================================================
REM  Build a self-contained SNPPrimerDesktop.exe with PyInstaller.
REM
REM  Prerequisite: none in the normal case. If venv/bin are missing, this
REM  script bootstraps them first. BLAST/primer3/muscle are copied from
REM  windows\bin\ when present, so no download is needed for those tools.
REM
REM  Output: dist\SNPPrimerDesktop\SNPPrimerDesktop.exe
REM    (a folder distribution; ~70-100 MB; double-click to launch,
REM     no Python install required on the target machine)
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

REM --- Step 5: PyInstaller build -------------------------------
REM   --windowed              : no console window for the .exe
REM   --paths src --paths .   : let PyInstaller find both src/ and core/
REM   --add-data              : ship core/assets (NEB / global_settings /
REM                             primer3_config) + references catalog
REM   NOTE: we do NOT --add-binary the BLAST/primer3/muscle .exe / .dll.
REM   PyInstaller's binary dep analyzer scatters Python's MSVCP140 /
REM   VCRUNTIME140 / api-ms-win-* into _internal/, and when subprocess
REM   launches NCBI .exe with PATH inheriting _internal/, those wrong-
REM   version DLLs shadow what NCBI was built against -> rc=0xC0000005
REM   (access violation, no stderr). Instead we COPY the bin tree to a
REM   sibling folder of _internal/ in Step 6, completely outside the
REM   PyInstaller bundle.
REM   --collect-submodules    : pull all snp_primer_app + core submodules
echo [BUILD] running PyInstaller...
pyinstaller --noconfirm --clean ^
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

REM --- Step 5b: copy NCBI binaries to dist\SNPPrimerDesktop\bin\ ---
REM This puts blastn / blastdbcmd / makeblastdb / primer3_core / muscle
REM + their DLLs in a CLEAN sibling folder of _internal/, so when
REM subprocess launches them, Windows DLL search finds nghttp2.dll /
REM ncbi-vdb-md.dll alongside the .exe (correct behavior) WITHOUT
REM contention from Python's bundled VC runtime in _internal/.
echo [BUILD] copying NCBI binaries to dist\SNPPrimerDesktop\bin\ ...
if not exist "%ROOT%\dist\SNPPrimerDesktop\bin" mkdir "%ROOT%\dist\SNPPrimerDesktop\bin"
for %%F in (blastn.exe blastdbcmd.exe makeblastdb.exe primer3_core.exe muscle.exe nghttp2.dll ncbi-vdb-md.dll) do (
  copy /Y "%BIN%\%%F" "%ROOT%\dist\SNPPrimerDesktop\bin\%%F" >nul
  if errorlevel 1 goto :err
)

REM --- Step 6: success summary ---------------------------------
echo.
echo ============================================================
echo  BUILD SUCCESS
echo  Output : %ROOT%\dist\SNPPrimerDesktop\SNPPrimerDesktop.exe
echo  Size   :
for %%S in ("%ROOT%\dist\SNPPrimerDesktop\SNPPrimerDesktop.exe") do echo    %%~zS bytes
echo ============================================================
echo  Distribute the entire "dist\SNPPrimerDesktop\" folder.
echo  End users double-click SNPPrimerDesktop.exe -- no Python needed.
echo  Workspace / logs land next to the .exe under snp_primer_runtime\.
goto :end

:err
echo.
echo *** BUILD FAILED ***
echo See errors above. Common causes:
echo   - venv not bootstrapped (run Launch SNP Primer Desktop.cmd once)
echo   - bin\ missing .exe / .dll (same fix)
echo   - antivirus quarantining pyinstaller bootloader

:end
echo.
pause
endlocal
