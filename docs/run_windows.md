# Run On Windows

This is the shortest practical path to run the current prototype on Windows.

## Fastest path

If you want the least manual setup, double-click:

```text
windows\Launch SNP Primer Desktop.cmd
```

That launcher will:

- install everything into `snp_primer_runtime\`
- create a private virtual environment
- install this app
- install `primer3-py`
- download BLAST+ for Windows
- download the latest Windows MUSCLE build
- launch the desktop UI

All downloaded files now stay inside the project directory:

- `snp_primer_runtime\python311`
- `snp_primer_runtime\venv`
- `snp_primer_runtime\bin`
- `snp_primer_runtime\workspace`
- `snp_primer_runtime\references`
- `snp_primer_runtime\downloads`
- `snp_primer_runtime\tmp`

You only need to provide a reference FASTA for local mode if you do not already have one under `snp_primer_runtime\references`.
If the launcher still fails, check these log files:

- `snp_primer_runtime\bootstrap.log`
- `snp_primer_runtime\desktop_startup_error.log`

## 1. Prepare the project

If you do not want the automatic bootstrap, use the manual path below.

Open PowerShell and go to the project root:

```powershell
cd C:\path\to\snp_primer_windows_app
```

Create and activate a virtual environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

## 2. Prepare the `bin` folder

Create this layout:

```text
snp_primer_windows_app/
  bin/
    blastn.exe
    blastdbcmd.exe
    makeblastdb.exe
    muscle.exe
    primer3_core.exe
    primer3_config/
```

Notes:

- `blastn.exe`, `blastdbcmd.exe`, and `makeblastdb.exe` come from NCBI BLAST+ for Windows.
- `muscle.exe` can be taken from the Windows release assets of `rcedgar/muscle`: `https://github.com/rcedgar/muscle/releases`
- `primer3_core.exe` can be built on Windows as documented by Primer3: `https://primer3.org/manual.html#installWindows`
- `primer3_config/` must be present for thermodynamic parameters. The safest setup is to place that folder next to `primer3_core.exe`.
- If you use the automatic bootstrap launcher, the app can also run through `primer3-py` and does not require `primer3_core.exe`.

If you do not want to put `primer3_config` inside `bin`, set:

```powershell
$env:PRIMER3_CONFIG_DIR="C:\path\to\primer3_config"
```

## 3. Prepare a reference FASTA

You only need the FASTA file at first, for example:

```text
C:\data\wheat\reference.fa
```

You do not need to build the BLAST database manually unless you want to.
The app will run `makeblastdb` automatically if the BLAST sidecar files do not exist yet.

## 4. Start the desktop app

From the project root:

```powershell
snp-primer-desktop
```

If that script is not found, use:

```powershell
python -m snp_primer_app.desktop
```

## 5. Fill the fields in the UI

Pick one of these modes:

- `Local BLAST DB or FASTA`
  Use `Local BLAST DB` if you already have a BLAST database prefix.
  Otherwise set `Reference FASTA` and the app will build the DB automatically.
- `NCBI Online BLAST`
  Set `Online database`, for example `nt`, `core_nt`, or `refseq_genomes`.
- `Other Online Provider`
  Currently wired for `ebi`.
  Set `Online database`, `Fetch database`, and `Contact email`.

Then fill any local paths you need:

- `Reference FASTA`: your FASTA path, for example `C:\data\wheat\reference.fa`
- `Binary root`: `C:\path\to\snp_primer_windows_app\snp_primer_runtime\bin`
- `Working dir`: any writable folder, for example `C:\path\to\snp_primer_windows_app\snp_primer_runtime\workspace`
- paste SNP lines into the input box, for example:

```text
IWB_50236,7A,AAACCC[A/G]TTT
Marker1,7B,TT[A/C]GG
```

Then click:

- `Run Pipeline`

## 6. Where results appear

After the run finishes, results are shown in the tabs:

- `Log`
- `KASP`
- `CAPS`
- `Summary`

Files are also written under the working directory:

- `for_blast.fa`
- `blast_out.txt`
- `temp_range.txt`
- `KASP_output\`
- `CAPS_output\`
- `Potential_KASP_primers.tsv`
- `Potential_CAPS_primers.tsv`
- `All_alignment_raw.fa`

## 7. Run without the GUI

If you want to test the whole pipeline first in PowerShell:

```powershell
snp-primer run-pipeline `
  .\input.csv `
  .\workspace `
  --reference-fasta C:\data\wheat\reference.fa `
  --binary-root .\bin `
  --design-kasp `
  --design-caps
```

## 8. Most common failure points

- `blastn not found`: `bin` does not contain BLAST+ executables, or `Binary root` points to the wrong folder.
- `primer3_core not found`: `primer3_core.exe` is missing.
- `primer3_config` errors: the `primer3_config` folder is not next to `primer3_core.exe` and `PRIMER3_CONFIG_DIR` was not set.
- `muscle not found`: `muscle.exe` is missing from `bin`.
- online mode produces no usable hits: the selected remote database did not return subject titles or accessions that can be mapped back to the chromosome naming used by your marker set.
- primer specificity BLAST is skipped in online modes because that step still expects a local BLAST database.
- empty KASP or CAPS output: the input SNP or reference region did not produce valid candidates under the current constraints.
