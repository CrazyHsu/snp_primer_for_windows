@echo off
REM ============================================================
REM  Build a single-file SNPPrimerDesktop.exe with PyInstaller.
REM
REM  Difference from build_windows.bat (onedir):
REM   - Uses --onefile  -> single .exe (no _internal\ + bin\ siblings)
REM   - Bundles binaries via --add-binary  -> they get extracted to
REM     %TEMP%\_MEIxxxxxx\bin\ at launch
REM   - 5-15 s startup delay each launch (PyInstaller bootloader
REM     extracts the bundle to a temp dir)
REM
REM  Prerequisite: same as build_windows.bat -- run "windows\Launch
REM  SNP Primer Desktop.cmd" once first to bootstrap venv +
REM  download all binaries to snp_primer_runtime\bin\.
REM
REM  Output: dist\SNPPrimerDesktop.exe (single file)
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

REM --- Step 5: PyInstaller --onefile build ---------------------
REM   --onefile               : pack everything into one .exe; at runtime
REM                             the bootloader extracts to %TEMP%\_MEIxxxx\
REM   --windowed              : no console window for the .exe
REM   --paths src --paths .   : let PyInstaller find both src/ and core/
REM   --add-data ...          : ship core/assets (NEB / global_settings /
REM                             primer3_config) + references catalog
REM   --add-binary ...;bin    : land each NCBI .exe / DLL under
REM                             _MEIPASS\bin\ at runtime;
REM                             runtime_paths._default_bin (frozen mode)
REM                             auto-falls back to _MEIPASS\bin when no
REM                             <exe_dir>\bin exists (== onefile case).
REM                             core/pipeline.py:_no_window_kwargs scrubs
REM                             _MEIPASS from PATH for subprocess so NCBI
REM                             .exe doesn't shadow-load Python's
REM                             MSVCP140 / VCRUNTIME140 (avoids the
REM                             0xC0000005 access violation).
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
echo  BUILD SUCCESS (--onefile)
echo  Output : %ROOT%\dist\SNPPrimerDesktop.exe
echo  Size   :
for %%S in ("%ROOT%\dist\SNPPrimerDesktop.exe") do echo    %%~zS bytes
echo ============================================================
echo  Distribute the single SNPPrimerDesktop.exe file.
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
