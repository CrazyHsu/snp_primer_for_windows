@echo off
setlocal

REM Example build script for Windows packaging.
REM Requires PyInstaller in the active Python environment.

pyinstaller ^
  --name SNPPrimerDesktop ^
  --windowed ^
  --paths src ^
  --add-data "references;references" ^
  --collect-all snp_primer_app ^
  src\snp_primer_app\desktop.py

endlocal
