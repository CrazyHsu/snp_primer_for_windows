# Windows App Blueprint

## Product goal

Build a standalone Windows app that:

- accepts the same SNP text input pattern as the current web form
- exposes the same key options as `snprimer`
- runs primer design locally
- manages reference genomes through an installable catalog
- exports KASP and CAPS or dCAPS results as tables

## UI shape

The UI can mirror the existing web form closely:

- reference genome selector
- ploidy selector
- maximum NEB enzyme price
- CAPS or dCAPS toggle
- KASP toggle
- maximum primer Tm
- maximum primer size
- pick-anyway toggle
- multi-line SNP input box
- run button
- results tabs:
  - KASP
  - CAPS or dCAPS
  - alignment
  - logs

## Desktop stack recommendation

### Preferred: PySide6

Use when the primary need is a reliable Windows desktop app with minimal packaging complexity.

Pros:

- single backend language
- easier to ship worker processes and bundled executables
- simpler filesystem and progress handling
- easier packaging with PyInstaller or Nuitka

Cons:

- UI styling takes deliberate design work
- web-like polish is not automatic

### Alternative: Tauri + React + Python backend

Use only if you want a more web-native front-end team workflow.

Pros:

- easy to reproduce a website-like UI
- smaller shell than Electron

Cons:

- Rust plus Node plus Python packaging chain
- harder process coordination
- more moving parts for Windows distribution

## Runtime split

### Rewritten Python modules

Should live inside the app package:

- SNP input parsing
- BLAST hit filtering
- flanking extraction planning
- result aggregation
- job metadata and log collection
- reference installation and update logic

### Bundled executables

Should stay as external binaries shipped with the app:

- `blastn.exe`
- `blastdbcmd.exe`
- `makeblastdb.exe`
- `primer3_core.exe`
- `muscle.exe`

## Workspace layout at runtime

Recommended per-job working directory:

`%LOCALAPPDATA%/SNPPrimer/jobs/<timestamp>-<job-id>/`

Inside each job directory:

- `input.csv`
- `for_blast.fa`
- `blast_out.txt`
- `temp_range.txt`
- `marker_batches/`
- `flanking_sequences/`
- `KASP_output/`
- `CAPS_output/`
- `All_alignment_raw.fa`
- `run.log`

## Reference management modes

### Recommended mode: online catalog, local compute

Keep a remote JSON catalog that lists:

- reference id
- display name
- supported ploidy modes
- FASTA URL
- BLAST DB URL
- checksum
- version

The app should:

1. fetch the catalog
2. show install status for each genome
3. download missing references to local storage
4. verify checksum
5. run everything locally

### Optional remote mode

You can also host the reference databases and sequence-extraction service remotely.

This reduces local disk usage but means:

- you must maintain a backend
- server cost returns
- private input may leave the local machine

For your use case, this should be optional, not the default.

## Packaging notes

### Installer contents

Include:

- Python runtime
- app code
- UI assets
- BLAST+ executables
- Primer3 executable
- MUSCLE executable
- small default reference catalog

Do not include by default:

- every reference FASTA and BLAST database

### Binary discovery

At startup, resolve bundled tools from:

- app install directory first
- user-configured override path second

This allows a power user to swap in newer BLAST builds without rebuilding the app.

## Migration plan from upstream pipeline

### Phase 1

- port `parse_polymarker_input.py`
- port `getflanking.py`
- replace shell splitting logic with Python file generation

### Phase 2

- port `getkasp3.py` to Python 3
- port `getCAPS.py` to Python 3
- remove direct Unix shell assumptions

### Phase 3

- implement desktop UI
- add job queue and progress reporting
- add reference install manager

### Phase 4

- package Windows installer
- run validation against known markers and compare with the current server output

## Practical conclusion

Yes, this app is feasible on Windows.

The right version is not "package the old repo unchanged".
The right version is "rewrite orchestration and file handling, keep the proven bioinformatics engines bundled, and manage references through an online catalog plus local cache."
