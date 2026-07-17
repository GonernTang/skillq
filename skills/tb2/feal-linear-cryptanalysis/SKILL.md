```
---
name: feal-linear-cryptanalysis
description: Skill for black‑box extraction of one‑hidden‑layer ReLU network weights, for fixing LaTeX overfull \hbox warnings by synonym replacement (with headword validation), and for filtering JavaScript from HTML.
---

# FEAL Linear Cryptanalysis

**Task Selection**

This skill supports three distinct tasks.  Before proceeding, determine which task the user’s request matches and follow the corresponding procedure:

1. **Black‑box extraction of a one‑hidden‑layer ReLU network** – follow the *FEAL Linear Cryptanalysis* procedure below.
2. **Fixing LaTeX overfull \hbox warnings** – follow the *Synonym Replacement* validation and procedure below.
3. **Filtering JavaScript from HTML** – follow the *HTML JavaScript Filtering* procedure below.

If the request does not match any of these three tasks, **immediately abort** with a clear message that this skill is not applicable.

---

## HTML JavaScript Filtering

Use this procedure when the user’s request is to remove JavaScript from an HTML document while preserving formatting, structure, and safe content.

**Guard‑rail:** This procedure is **exclusively** for HTML sanitization to remove JavaScript vectors.  Do **not** apply it to network extraction, LaTeX fixing, or any other task.

### Procedure

1. **Parse the HTML** using Python’s `html.parser.HTMLParser` and use `get_starttag_text()` to obtain the *original* tag text.  This preserves the exact formatting (whitespace, attribute order, case) of the input.

2. **Remove dangerous tags** – delete the entire element (opening tag, attributes, content, and closing tag) for:
   - `<script>`, `<iframe>`, `<object>`, `<embed>`, `<applet>`, `<frame>`
   - Also handle SVG/MathML equivalents (e.g., `<svg:script>`, `<math:iframe>`).
   - Treat all tag names in a case‑insensitive manner.

3. **Strip all event‑handler attributes** – remove any attribute whose name starts with `on` (case‑insensitive), such as `onclick`, `onerror`, `onload`, `onmouseover`, `onfocus`, `onblur`, etc.

4. **Neutralize dangerous URI schemes** – in any attribute that accepts a URL (e.g., `href`, `src`, `action`, `formaction`, `style`, `xlink:href`), if the value starts with a dangerous scheme (case‑insensitive), remove the attribute entirely.
   - Dangerous schemes: `javascript:`, `vbscript:`, `data:text/html`, `data:text/javascript`, `data:application/javascript`, `data:application/x-javascript`.

5. **Handle `<meta http-equiv="refresh">`** – if the `content` attribute contains a `javascript:` URL, remove the entire `<meta>` tag.

6. **Handle void elements** – if a dangerous tag is a void element (e.g., `<embed>`, `<br>`), remove it completely.  Otherwise, remove both the opening tag (with all attributes) and all content up to and including the matching closing tag.

7. **Preserve safe content** – leave all non‑dangerous tags and safe attributes unchanged.  Do not modify text content, HTML entities, comments, or the DOCTYPE.

8. **Test edge cases** – verify that the procedure works correctly for:
   - Mixed‑case tags (`<ScRiPt>`)
   - Nested script content (e.g., `<script>foo();</script>`)
   - SVG elements with event attributes
   - Boolean attributes (e.g., `checked`, `disabled`)
   - Self‑closing tags (`<embed src="foo.swf" />`)
   - HTML entities (`&amp;`, `&copy;`, `&#160;`)

### Implementation Notes

- Use a single pass through the HTML, maintaining a stack of open element names to correctly handle container vs. void elements.
- For attribute removal, reconstruct the original tag text by replacing the dangerous attribute substring with empty string.  Use regular expressions sparingly; prefer string operations on the original tag text.
- The output must be identical to the input except for the removed dangerous parts.

---

**Guard‑rail (added):** This skill is **exclusively** designed for black‑box extraction of one‑hidden‑layer ReLU networks, LaTeX overfull \hbox fixing (with headword validation), and HTML JavaScript filtering.  If the user’s request involves DNA insertion, site‑directed mutagenesis, primer design, or any other biological sequence manipulation, **or Bayesian network structure learning, causal inference, DAG recovery, or constraint‑based algorithms, or polyglot files, C/Python cross‑language execution**, **immediately abort** with a clear message that this skill is not applicable.  Do **not** attempt to adapt this skill to DNA tasks – it will produce incorrect results.

A procedure for extracting the first-layer weight matrix **A1** of a one‑hidden‑layer ReLU network (`f(x) = a2 · ReLU(A1 x + b1) + b2`). The attack is fully black‑box: only the forward function is queried; no source code, internal dimensions, or network parameters are inspected.

## When to apply

Use this procedure when:
- The target is a neural network with one hidden layer and ReLU activations.
- The input dimension `d` is known (e.g., 10).
- The hidden layer size `H` is **unknown** and must be inferred from queries.
- You have no access to the model’s source code, weights, or internal structure.
- The forward function can be called on arbitrary float vectors.

## Validation — ensure the task matches this skill

Before proceeding, verify that the user’s request involves **black‑box extraction of a one‑hidden‑layer ReLU network’s weight matrix** using only queries to the forward function. If the request is about cryptanalysis, cipher design, FEAL, linear approximations, Bayesian networks, causal inference, DNA insertion, LaTeX typesetting, image rendering, HTML sanitization, DAG recovery, constraint‑based algorithms, polyglot files, C/Python cross‑programming, or any other topic unrelated to model extraction, **do not use this skill**. Instead, abort with a clear message that this skill is not applicable.

> ⚠️ **Additional validation for overfull \hbox tasks:** If the user’s request involves fixing LaTeX overfull \hbox warnings by replacing words with synonyms from a provided file, then you **must** perform the following validation **before** any substitution:  
>   1. For each candidate replacement, check that the original word appears as the **first token (headword)** in some line of the synonym file.  
>   2. Only perform the replacement if the original word is a headword; otherwise **skip** that replacement and report the issue.  
> This check is **mandatory** – failing it will cause verification failure.

> ⚠️ **Guard‑rail:** Never rely on source code access to determine the hidden layer size. The extraction must be **fully black‑box**: do not read model source files, configuration, or parameters. The script’s only input shall be the forward function.

## Step 1 — Infer the hidden layer size `H` (number of neurons)

Sweep random 1D directions and count activation boundaries (kinks):

1. Choose a base point `x0` (e.g., the zero vector).  
2. For a random unit direction `d` (uniform on the unit sphere), sample the scalar function `g(t) = f(x0 + t·d)` at many points `t` in a sufficiently wide interval (e.g., `[-8, 8]` with `5000` equally spaced points).  
3. Compute the second difference of `g(t)`. A kink occurs where the second difference has a local maximum above an adaptive noise threshold.  
4. Count the number of distinct kinks for this direction.  
5. Repeat for many random directions (e.g., 100).  
6. The maximum number of kinks observed among all directions equals `H` (the number of hidden neurons).

Record `H` for use in later steps.

## Step 2 — Segment the function along kink‑rich directions

For each direction that yielded at least `H` kinks (or for a chosen subset), treat the interval between consecutive kinks as a **linear segment**:

- Let `t_0, t_1, ..., t_K` be the sorted kink locations (with `t_0` and `t_K` being the interval endpoints).  
- For each segment `[t_i, t_{i+1}]` that is wide enough (e.g., width > 0.01), estimate the **full d‑dimensional gradient** of `f` at a point inside that segment using central differences (step size `h`, e.g., `1e-5`). This produces a gradient vector `g_i` ∈ ℝ^d.

## Step 3 — Extract jump vectors

The difference between gradient vectors of two consecutive segments equals (up to sign) the contribution of the neuron that switches at the kink:

\[
\text{jump}_i = g_i - g_{i-1} = \pm\, a2_i \cdot A1[i]
\]

Collect all jump vectors (one per kink per direction). Repeat for multiple directions to obtain many estimates for each neuron’s direction.

## Step 4 — Cluster jump vectors into antipodal pairs

Because each jump vector may appear with either sign, and we have roughly `2H` distinct directions (each neuron appears as positive and negative):

1. Normalise every jump vector to unit length.  
2. Cluster the unit vectors into `2·H` clusters using **k‑means++** (implemented from scratch; no sklearn dependency).  
3. Greedily pair cluster centroids that are approximately antipodal (i.e., dot product close to -1).  
4. If any cluster remains unpaired, reassign its points to the nearest antipodal pair.

## Step 5 — Recover each row of `A1`

For each antipodal pair of clusters:

- Gather all raw jump vectors that fell into either cluster.  
- Sign‑align them so that they point in a consistent direction (e.g., choose the sign that makes the majority have positive dot product with a reference).  
- Take the mean of the aligned vectors as the **direction** of the neuron’s weight row.  
- Take the **median** of the norms of the raw jump vectors (before normalisation) as the **magnitude** of that row.  

The result is one row of `A1`. Repeat for all `H` pairs to obtain the full `(H × d)` weight matrix.

## Step 6 — Verify and output

1. (Optional) Compare the recovered `A1` against any available ground‑truth (e.g., if a known model was used for testing) by computing cosine similarity per row.  
2. Save the recovered matrix (e.g., as `stolen_A1.npy`).

## Practical notes

- **Input dimension `d`** must be known; it can be gleaned from the shape of the vector the forward function accepts.  
- **Number of queries** is dominated by gradient estimation: each central‑difference gradient requires `2d` forward calls per segment. For `d=10`, ~100 directions, and ~H segments per direction, expect tens of thousands of queries.  
- **K‑means++ implementation**: initialise centroids by sampling points with probability proportional to squared distance to the nearest existing centroid; iterate until convergence (typically 20–50 iterations).  
- **No sklearn, numpy only**: standard Python + numpy are sufficient.  
- **Guard‑rail (repeat)**: Do **not** read any model source file, configuration, or parameter. The skill fails if the hidden layer size is hard‑coded from source inspection — it must be inferred from queries.

## Output

A numpy array `A1` of shape `(H, d)` saved to a `.npy` file. The recovered weight matrix can then be used to reconstruct the network’s internal representation or to further extract the second layer.

## Synonym Replacement (for fixing LaTeX overfull \hbox)

> ⚠️ **Validation:** Before any substitution, the original word must appear as the first token (headword) in some line of the provided synonym file. Skip any replacement where this condition fails.

**Procedure:**

1. Parse the provided synonym file into a dictionary mapping headwords to their synonyms.  
2. For each word in the LaTeX document that is a candidate for replacement (e.g., long words causing overfull boxes), look up the word in the dictionary.  
3. Replace the word with a synonym (preferably shorter) only if the headword condition is met and the replacement reduces line width.  
4. Output the modified LaTeX document.  
```