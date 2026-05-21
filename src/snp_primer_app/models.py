from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class BlastQueryRecord:
    """A single polymarker-style SNP record."""

    name: str
    chromosome: str
    raw_sequence: str
    snp_index: int
    iupac_code: str
    blast_query_id: str
    blast_sequence: str


@dataclass(frozen=True)
class BlastAlignment:
    """A parsed row from the BLAST tabular file used by the upstream pipeline."""

    query_id: str
    subject_id: str
    alignment_length: int
    mismatches: int
    gap_opens: int
    query_start: int
    query_end: int
    subject_start: int
    subject_end: int
    query_sequence: str
    subject_sequence: str
    subject_length: int
    subject_title: str | None = None
    subject_chromosome: str | None = None

    @property
    def derived_identity(self) -> float:
        return 100 - ((self.mismatches + self.gap_opens) / self.alignment_length) * 100


@dataclass(frozen=True)
class FlankingTarget:
    """A single flanking extraction request."""

    query_id: str
    output_query_id: str
    subject_id: str
    range_start: int
    range_end: int
    strand: str
    query_hit_count: int
    subject_title: str | None = None
    subject_chromosome: str | None = None

    @property
    def batch_file_content(self) -> str:
        return f"{self.subject_id} {self.range_start}-{self.range_end} {self.strand}\n"


@dataclass(frozen=True)
class ReferenceGenome:
    """Reference genome metadata used by the desktop app."""

    reference_id: str
    display_name: str
    ploidy_modes: list[str]
    fasta_url: str | None = None
    blast_db_url: str | None = None
    sha256: str | None = None
    install_subdir: str | None = None
    size_bytes: int | None = None
    enabled: bool = True
    notes: str | None = None

    def install_path(self, root_dir: Path) -> Path:
        subdir = self.install_subdir or self.reference_id
        return root_dir / subdir


@dataclass(frozen=True)
class PipelineRequest:
    """User-facing settings for a single design run."""

    input_csv: Path
    reference_fasta: Path | None
    ploidy: int
    max_enzyme_price: int
    design_caps: bool
    design_kasp: bool
    blast_primers: bool
    max_tm: int
    max_primer_size: int
    pick_anyway: bool
    blast_mode: str = "local"
    local_blast_db: Path | None = None
    remote_provider: str | None = None
    remote_database: str | None = None
    remote_fetch_database: str | None = None
    remote_email: str | None = None
    # v13: 用户在 GUI 选的物种 key（core.species.SPECIES_TABLE 的 key，默认 "wheat"
    # 保留 v12 行为字节等价）。详见 v13 CLAUDE.md §6.22。
    species_key: str = "wheat"


@dataclass(frozen=True)
class BinaryBundle:
    """Locations of bundled third-party executables."""

    blastn: Path
    blastdbcmd: Path
    makeblastdb: Path
    primer3_core: Path
    muscle: Path


@dataclass(frozen=True)
class PipelinePlan:
    """A serializable plan that a GUI can show before execution."""

    working_dir: Path
    steps: list[list[str]] = field(default_factory=list)


@dataclass(frozen=True)
class PipelineRunResult:
    """Output files from a completed end-to-end run."""

    working_dir: Path
    input_csv: Path
    blast_fasta: Path
    blast_output: Path
    temp_range: Path
    all_alignment_raw: Path
    potential_kasp: Path | None = None
    potential_caps: Path | None = None
    kasp_reports: list[Path] = field(default_factory=list)
    caps_reports: list[Path] = field(default_factory=list)


@dataclass
class Primer:
    """A primer parsed from Primer3 output."""

    name: str = ""
    start: int = 0
    end: int = 0
    length: int = 0
    tm: float = 0.0
    gc: float = 0.0
    anys: float = 0.0
    three: float = 0.0
    hairpin: float = 0.0
    end_stability: float = 0.0
    seq: str = ""
    difthreeall: str = "NO"
    difnum: int = 0
    direction: str = ""


@dataclass
class PrimerPair:
    """A primer pair parsed from Primer3 output."""

    left: Primer = field(default_factory=Primer)
    right: Primer = field(default_factory=Primer)
    compl_any: str = "NA"
    compl_end: str = "NA"
    penalty: str = "NA"
    product_size: int = 0
    score: float = 0.0


@dataclass
class RestrictionEnzyme:
    """Restriction enzyme metadata and marker-specific annotations."""

    name: str
    seq: str
    length: int
    template_seq: str = ""
    primer_end_pos: list[int] = field(default_factory=list)
    caps: str = "No"
    dcaps: str = "No"
    allpos: list[int] = field(default_factory=list)
    change_pos: int | None = None
    potential_primer: str = ""
    price: int = 0


@dataclass(frozen=True)
class MarkerMetadata:
    """Metadata encoded in a flanking marker file name."""

    snpname: str
    chrom: str
    allele: str
    pos: int


@dataclass(frozen=True)
class VariationAnalysis:
    """Variation summary extracted from the target vs homeolog alignment."""

    target_id: str
    homeolog_ids: list[str]
    seq_template: str
    variation: list[int]
    variation_partial: list[int]
    diffarray: dict[int, list[int]]
    gap_left: int
    gap_right: int
