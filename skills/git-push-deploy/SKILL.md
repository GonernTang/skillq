---
name: git-push-deploy
description: Recover the weight matrix of a one-layer ReLU network from black-box queries using kink detection, gradient jump measurement, clustering, and magnitude recovery.
---

# Model Extraction for One-Layer ReLU Network

Extract the first-layer weight matrix \(A_1\) (up to permutation and scaling) of a scalar-output ReLU network \(f(x) = A_2 \cdot \mathrm{ReLU}(A_1 x + b_1) + b_2\) using only the forward function \(f\).

## Procedure

### 1. Sweep random 1D slices

Choose a large number of random directions \(d \in \mathbb{R}^n\) (e.g., 250). Along each direction, sample the function at many equally spaced points (e.g., 15,000) covering a wide range.

```python
import numpy as np

def sweep_slices(f, n_dirs=250, n_pts=15000, span=10.0):
    n = f.input_dim
    directions = np.random.randn(n_dirs, n)
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    t = np.linspace(-span, span, n_pts)
    slices = np.zeros((n_dirs, n_pts))
    for i, d in enumerate(directions):
        pts = t[:, None] * d[None, :]       # (n_pts, n)
        slices[i] = np.array([f(p) for p in pts])
    return t, directions, slices
```

### 2. Detect kinks (ReLU pre-activation zero-crossings)

Compute the second difference of \(f\) along each slice. Kinks appear as sharp spikes (ReLU turning points). Threshold above the noise floor (e.g., 10× the median absolute second-difference).

```python
def detect_kinks(t, slices, threshold_factor=10):
    # second difference
    d2 = slices[:, 2:] - 2*slices[:, 1:-1] + slices[:, :-2]
    noise = np.median(np.abs(d2)) * threshold_factor
    kink_indices = np.where(np.abs(d2) > noise)
    # (dir_idx, point_idx in the second-difference array)
    return kink_indices, d2
```

### 3. Compute gradient jump vectors

For each detected kink at parameter \(t_k\), compute the full gradient on both sides using finite differences on the original input \(x_k = t_k \cdot d\). The jump vector is \(\nabla f(x_k^+) - \nabla f(x_k^-) = a_{2,i} \cdot a_{1,i}\) for the neuron that just switched.

```python
def gradient_jump(f, x, eps=1e-5):
    fx = f(x)
    grad = np.zeros_like(x)
    for i in range(len(x)):
        xp = x.copy(); xp[i] += eps
        xm = x.copy(); xm[i] -= eps
        grad[i] = (f(xp) - f(xm)) / (2*eps)
    return grad

jump_vectors = []
for dir_idx, pt_idx in zip(*kink_indices):
    t_k = t[pt_idx + 1]  # offset because second diff shrinks by 2
    x_k = t_k * directions[dir_idx]
    # sample epsilon away on both sides
    x_plus = x_k + 1e-5 * directions[dir_idx]
    x_minus = x_k - 1e-5 * directions[dir_idx]
    # full gradient at each side
    g_plus = gradient_jump(f, x_plus)
    g_minus = gradient_jump(f, x_minus)
    jump = g_plus - g_minus
    if np.linalg.norm(jump) > 1e-12:
        jump_vectors.append(jump)
jump_vectors = np.array(jump_vectors)
```

### 4. Normalize and cluster

Unit-normalize each jump vector. Because each neuron appears with both +a1 and -a1 directions, run KMeans with twice the estimated hidden dimension. Merge antipodal clusters (centroids that are nearly opposite).

```python
from sklearn.cluster import KMeans
norms = np.linalg.norm(jump_vectors, axis=1)
unit_jumps = jump_vectors / norms[:, None]
n_hidden_est = ...  # estimate from number of distinct kink frequencies or just overcluster
kmeans = KMeans(n_clusters=2 * n_hidden_est, random_state=0).fit(unit_jumps)
centroids = kmeans.cluster_centers_
labels = kmeans.labels_

# Merge antipodal pairs
merged = []
assigned = [False] * len(centroids)
for i in range(len(centroids)):
    if assigned[i]: continue
    best_j = -1
    best_dot = -2
    for j in range(i+1, len(centroids)):
        if assigned[j]: continue
        dot = np.dot(centroids[i], centroids[j])
        if dot < best_dot:
            best_dot = dot
            best_j = j
    if best_j != -1 and best_dot < -0.9:
        # merge clusters i and best_j
        merged.append((i, best_j))
        assigned[i] = assigned[best_j] = True
    else:
        # keep as a single neuron (unpaired)
        merged.append((i,))
        assigned[i] = True
# After merging, each group corresponds to one hidden neuron.
# For each group, collect all jump vectors that belong to either cluster.
neuron_vectors = []
for group in merged:
    vecs = []
    for idx in group:
        vecs.append(jump_vectors[labels == idx])
    neuron_vectors.append(np.vstack(vecs))
```

### 5. Recover magnitude and direction

For each neuron, the jump vectors are all parallel to \(a_1\) (or anti-parallel). Take the median norm as the magnitude estimate. The direction is the mean of the unit-normalized vectors (signed consistently).

```python
recovered_rows = []
for vecs in neuron_vectors:
    # median norm
    mag = np.median(np.linalg.norm(vecs, axis=1))
    # direction from unit-norm sign-corrected average
    unit = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
    # align all to point in the same half-space
    ref = unit[0]
    for i in range(1, len(unit)):
        if np.dot(unit[i], ref) < 0:
            unit[i] = -unit[i]
    dir_vec = np.mean(unit, axis=0)
    dir_vec /= np.linalg.norm(dir_vec)
    recovered_rows.append(mag * dir_vec)
recovered_A1 = np.array(recovered_rows)
```

### 6. Validate (optional)

Compare recovered rows to ground truth using Hungarian matching on absolute cosine similarity. Expect median ~0.999, with weak rows corresponding to neurons whose output weight \(a_{2,i}\) is near zero.

```python
from scipy.optimize import linear_sum_assignment
cos_sim = np.abs(recovered_A1 @ true_A1.T) / (np.linalg.norm(recovered_A1, axis=1, keepdims=True) * np.linalg.norm(true_A1, axis=1))
row_ind, col_ind = linear_sum_assignment(-cos_sim)
match_scores = cos_sim[row_ind, col_ind]
print("Median cosine similarity:", np.median(match_scores))
```

## Common pitfalls

- **Noise threshold too low** — may detect spurious kinks from floating point noise. Use a robust estimator (median absolute second-difference) and a multiplier (e.g., 10–20).
- **Insufficient slicing** — too few directions or points can miss kinks, especially for neurons with small output weights. Increase `n_dirs` and `n_pts`.
- **Weak neurons** — neurons with \(|a_{2,i}|\) near zero produce tiny gradient jumps that may be buried in noise. Expect some poor recovery for those.
- **Finite-difference epsilon** — too large biases the gradient estimate; too small triggers numerical instability. Use \(10^{-5}\) for normalized inputs.
- **Cluster count** — over-cluster (2× hidden dimension) then merge antipodal pairs. If the true hidden dimension is unknown, try multiple values and pick the one with highest average pairwise cosine similarity within clusters.