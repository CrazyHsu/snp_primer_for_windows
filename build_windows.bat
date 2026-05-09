@echo off
REM ============================================================
REM  Build a self-contained SNPPrimerDesktop.exe with PyInstaller.
REM
REM  Prerequisite: run "windows\Launch SNP Primer Desktop.cmd"
REM  at least once. That bootstrap creates snp_primer_runtime\venv
REM  and downloads BLAST+/primer3/muscle binaries to
REM  snp_primer_runtime\bin\ -- this script reads from both.
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
  echo [ERROR] dev venv not found at:
  echo   %VENV_ACT%
  echo Run "windows\Launch SNP Primer Desktop.cmd" once to bootstrap it.
  goto :err
)
call "%VENV_ACT%" || goto :err

REM --- Step 2: install / upgrade PyInstaller -------------------
echo [BUILD] installing pyinstaller into venv...
python -m pip install --upgrade pyinstaller
if errorlevel 1 goto :err

REM --- Step 3: verify required Windows binaries exist ----------
set "BIN=%ROOT%\snp_primer_runtime\bin"
for %%F in (blastn.exe blastdbcmd.exe makeblastdb.exe primer3_core.exe muscle.exe nghttp2.dll ncbi-vdb-md.dll) do (
  if not exist "%BIN%\%%F" (
    echo [ERROR] missing binary: %BIN%\%%F
    echo Run "windows\Launch SNP Primer Desktop.cmd" once first; bootstrap will download all binaries.
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
REM   --add-binary ...;bin    : land each .exe / .dll under <bundle>/bin
REM                             so runtime_paths._default_bin (frozen mode)
REM                             auto-points binary_root_var there
REM   --collect-submodules    : pull all snp_primer_app + core submodules
echo [BUILD] running PyInstaller...
pyinstaller --noconfirm --clean ^
  --name SNPPrimerDesktop ^
  --windowed ^
  --paths "%ROOT%\src" ^
  --paths "%ROOT%" ^
  --add-data "%ROOT%\core\assets;core\assets" ^
  --add-data "%ROOT%\references\catalog.example.json;references" ^
  --add-binary "%BIN%\blastn.exe;bin" ^
  --add-binary "%BIN%\blastdbcmd.exe;bin" ^
  --add-binary "%BIN%\makeblastdb.exe;bin" ^
  --add-binary "%BIN%\primer3_core.exe;bin" ^
  --add-binary "%BIN%\muscle.exe;bin" ^
  --add-binary "%BIN%\nghttp2.dll;bin" ^
  --add-binary "%BIN%\ncbi-vdb-md.dll;bin" ^
  --collect-submodules snp_primer_app ^
  --collect-submodules core ^
  "%ROOT%\src\snp_primer_app\launch_gui.py"
if errorlevel 1 goto :err

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
