---
name: grpc-python-server
description: Design primers for one-pot Golden Gate assembly with BsaI-HFv2, including parsing FASTA, selecting overhangs, computing melting temperatures with oligotm, and outputting FASTA primers.
---

# Design Primers for Golden Gate Assembly

## When to use
Use this skill when you need to design primers for a one‑pot Golden Gate assembly using BsaI‑HFv2. The input is a FASTA file containing one circular backbone and one or more linear inserts. The output is a FASTA file with eight primers (four pairs) that append BsaI recognition sites and unique 4‑bp overhangs, enabling a circular assembly.

## Procedure

### 1. Parse input sequences
Read the FASTA file. Identify the circular backbone (it is the only sequence that is circular) and the linear inserts. Determine the circular assembly order: the backbone is amplified whole, and the inserts are amplified as linear fragments, each excluding the overhang sequences provided by the adjacent fragments.

### 2. Choose unique 4‑bp overhangs
For each junction between fragments, select a 4‑bp overhang **that is not the BsaI recognition site** (`GGTCTC`). The overhangs must be complementary between adjacent fragments:
- The forward overhang of fragment *i* equals the reverse complement of the reverse overhang of fragment *i+1*.
- In a circular assembly of *N* fragments (including backbone), there are *N* junctions.

### 3. Design each primer
For each fragment, design a forward and a reverse primer. Each primer consists of (in order):
1. The BsaI recognition site: `GGTCTC`
2. A lowercase spacer `t`
3. The 4‑bp overhang (written uppercase for clarity)
4. The annealing region (15–45 nt) that is complementary to the template.

**Notes on annealing region:**
- For the backbone, the primers amplify the entire circular sequence, leaving out the overhang portions that will be provided by the adjacent inserts.
- For each insert, the primers amplify a subregion that **excludes** the overhang sequences that are already supplied by the adjacent fragments (so that the overhang is only present on the primer, not on the amplified product).

### 4. Compute melting temperature
Use the `oligotm` command with the exact flags:
```
oligotm -tp 1 -sc 1 -mv 50 -dv 2 -n 0.8 -d 500
```
Compute the Tm of the annealing part only (the 15–45 nt region, **excluding** the BsaI site, spacer, and overhang). Ensure:
- Each annealing part has Tm between 58°C and 72°C.
- The difference in Tm between the forward and reverse primer of the same fragment is ≤ 5°C.

### 5. Validate the primers
- All overhangs are properly paired cyclically (each junction’s forward overhang matches the reverse complement of the following fragment’s reverse overhang).
- Every primer contains the BsaI site `GGTCTC`.
- Annealing part length is 15–45 nt.
- Tm values are within the allowed range and paired Tm difference ≤ 5°C.
- The output FASTA file contains no blank lines (except a single trailing newline).

### 6. Output the primers in FASTA format
Write one FASTA entry per primer, with headers in the format:
```
>fragmentname_fwd
>fragmentname_rev
```
For example:
```
>backbone_fwd
GGTCTCtTGAGtgaggatcccgggaattctcg
>backbone_rev
GGTCTCtTGCTcatatgtatatctccttcttaaagttaaacaaaatt
>egfp_fwd
GGTCTCtAGCAagggcgaggagctgttca
...
```
Ensure no empty lines appear between entries.

## Pitfalls
- **Overhang uniqueness:** Never use `GGTCTC` as an overhang – it is the BsaI recognition site.
- **Annealing region length:** Count only the part that hybridizes to the template; do **not** include the BsaI site, spacer, or overhang.
- **Tm calculation:** Use only the annealing region (15–45 nt) with the exact `oligotm` flags shown above. Do not guess or use other methods.
- **Circular consistency:** Every junction must have complementary overhangs; the last fragment’s reverse overhang must complement the backbone’s forward overhang.
- **FASTA formatting:** No blank lines between entries; the file must end with exactly one newline.

## Verification
After generating the primers, run the following checks:
1. Confirm the assembly order is circular and overhangs are correctly paired.
2. Run `oligotm -tp 1 -sc 1 -mv 50 -dv 2 -n 0.8 -d 500` on each annealing region and verify Tm constraints.
3. Verify that the total number of primers is 2× (number of fragments).
4. Check that the output FASTA file has no blank lines (use `grep -c '^$' primers.fasta`; it should return 0).