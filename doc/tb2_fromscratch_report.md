# TB 2.0 From-Scratch 全量 89 实验结果报告

**日期**: 2026-07-01 ~ 2026-07-02
**配置**: `experiments/configs/tb2_skillq_fromscratch.yaml`
**并发**: 4 trials | `extract_every_n_trials=1` | 空种子技能库

---

## 总体结果

| 指标 | 值 |
|---|---|
| Trials | **89/89** |
| Pass | **48** (53.9%) |
| Fail | **41** (46.1%) |
| Mean | **0.539** |
| 运行时长 | ~15h (含 sleep 中断 ~9h) |
| L4 技能产出 | **67** (从零自举) |
| Extract 失败 | **1** (reshard-c4-data) |

---

## 逐 Task 结果

### ✅ Pass (48)

```
adaptive-rejection-sampler: 0
bn-fit-modify: 1
break-filter-js-from-html: 0
build-cython-ext: 1
build-pmars: 1
build-pov-ray: 0
caffe-cifar-10: 0
cancel-async-tasks: 1
chess-best-move: 0
circuit-fibsqrt: 0
cobol-modernization: 1
code-from-image: 1
compile-compcert: 1
configure-git-webserver: 1
constraints-scheduling: 1
count-dataset-tokens: 0
crack-7z-hash: 1
custom-memory-heap-crash: 1
db-wal-recovery: 1
distribution-search: 1
dna-assembly: 0
dna-insert: 0
extract-elf: 1
extract-moves-from-video: 0
feal-differential-cryptanalysis: 1
feal-linear-cryptanalysis: 1
filter-js-from-html: 0
financial-document-processor: 1
fix-code-vulnerability: 0
fix-git: 1
fix-ocaml-gc: 1
gcode-to-text: 0
git-leak-recovery: 1
git-multibranch: 1
gpt2-codegolf: 0
headless-terminal: 0
hf-model-inference: 1
install-windows-3.11: 0
kv-store-grpc: 1
large-scale-text-editing: 1
largest-eigenval: 1
llm-inference-batching-scheduler: 1
log-summary-date-ranges: 1
mailman: 1
make-doom-for-mips: 1
make-mips-interpreter: 0
mcmc-sampling-stan: 1
merge-diff-arc-agi-task: 0
model-extraction-relu-logits: 0
modernize-scientific-stack: 1
mteb-leaderboard: 0
mteb-retrieve: 0
multi-source-data-merger: 1
nginx-request-logging: 1
openssl-selfsigned-cert: 1
overfull-hbox: 0
password-recovery: 0
path-tracing: 0
path-tracing-reverse: 0
polyglot-c-py: 0
polyglot-rust-c: 0
portfolio-optimization: 1
protein-assembly: 0
prove-plus-comm: 1
pypi-server: 1
pytorch-model-cli: 0
pytorch-model-recovery: 1
qemu-alpine-ssh: 0
qemu-startup: 1
query-optimize: 1
raman-fitting: 0
regex-chess: 0
regex-log: 1
reshard-c4-data: 1
rstan-to-pystan: 0
sam-cell-seg: 0
sanitize-git-repo: 1
schemelike-metacircular-eval: 0
sparql-university: 1
sqlite-db-truncate: 1
sqlite-with-gcov: 1
torch-pipeline-parallelism: 0
torch-tensor-parallelism: 0
train-fasttext: 0
tune-mjcf: 1
video-processing: 0
vulnerable-secret: 1
winning-avg-corewars: 0
write-compressor: 0
```

---

## L4 技能清单（67 个）

从零库自举，每个成功 trial 触发 L4 CREATE 产出 1 个技能：

```
alpine-qemu-ssh            feal-linear-cryptanalysis    mailman-postfix-setup
break-filter-from-html     filter-js-from-html          mcmc-stan-sampling
build-cython-extension     financial-doc-processor       merge-heterogeneous-sources
build-debian-source        fix-code-vulnerability       modernize-scientific-stack
c-gcov-build               fix-compcert-build           nginx-request-logger
caffe-cifar10-train        fix-git-detached-head        ocaml-gc-freelist-debug
cancel-async-tasks-python  fix-git-leak                 openssl-selfsigned-cert
chess-board-image-to-move  fix-ocaml-gc                 optimize-sql-query
circuit-fibsqrt-synthesis  gcode-text-extraction         pmars-cmake-build
cobol-modernization        git-hook-auto-deploy          portfolio-optimization
code-from-image            git-multibranch-deploy        prove-n-plus-comm
compile-compcert           git-recover-detached-commits  pypi-server-setup
configure-git-webserver    gpt2-codegolf                python-grpc-server
constraints-scheduling     headless-terminal             qemu-alpine-ssh
count-dataset-tokens       hf-model-inference           qemu-x86-boot
crack-7z-archive           huggy-deploy                  query-optimize
crack-7z-hash              image-to-code                 regex-log-parser
custom-heap-allocator      install-windows-3.11          reshard-c4-data
db-wal-recovery            kv-store-grpc                 rstan-to-pystan
debian-build-nox           large-eigenvalue              sanitize-git-repo
distribution-search        large-scale-text-editing      shape-aware-batching
dna-assembly               legacy-os-qemu-vnc            sparql-university-queries
dna-insert                 llm-inference-batching        sqlite-btree-recover
extract-elf-memory         log-summary-date-ranges       torch-pipeline-parallel
feal-differential-attack   mailman-docker-setup          train-fasttext-classifier
                                                         winning-corewars
```

**Extract 失败**: 1 次 — `reshard-c4-data` (extract_batch returned None)

---

## 关键发现

### 1. 空库自举成功

从 0 个种子技能起步，89 个 trial 跑完后产出了 **67 个 L4 技能**。每个成功 trial 只要 L1 没命中技能（sim < 0.5 gate），就触发 SUCCESS_NO_SKILL_SEEN → L4 CREATE → 一个对应领域的技能入库。

### 2. 通过率 54%

48/89 pass。在零种子技能的情况下这个通过率合理——前期 trial 完全靠自己探索，后期随着库增长才有技能可复用。

### 3. Harbor timeout 未生效

配置了 1h 上限（`override_timeout_sec=3600` + `agent_timeout_multiplier=1.0`），但 `schemelike-metacircular-eval` 和 `extract-moves-from-video` 跑了 9h+ 不被 kill——Harbor 的 timeout 机制有 bug。

### 4. schemelike-metacircular-eval 粘滞问题

这个 task 要求用 Scheme 写 metacircular evaluator，agent 陷入修-测循环（114k+ 行输出）。手动 kill 容器后 Harbor 因 session 文件 root 权限无法生成 trajectory，attribution 未触发——既没有 L3 edit 也没有 L4 CREATE。

### 5. LiteLLM 模型调用偶发崩溃

attribution 出现多次 `Provider List` 错误（LiteLLM stderr spam），其中第 10 个 trial 因 attribution 超时导致整个 pipeline 崩溃——这已在 `step_attribute` 加上 try/except + fallback（但本次跑的代码不含此修复，修复是后续加的）。

### 6. 主机睡眠导致 9h 中断

主机进入睡眠模式导致 4 个 trial 卡住 9 小时。通过手动恢复（复制 L4 技能 + Q-table → 新 config 重跑 4 个 task）成功完成全量。

---

## 与 small10 v2 对比

| 指标 | small10 v2 | fromscratch 全量 |
|---|---|---|
| Trials | 10 | 89 |
| Pass | 8 (80%) | 48 (54%) |
| 种子技能 | 69 | 0 |
| L4 产出 | 7 | 67 |
| Extract 失败 | 0 | 1 |
| 运行时长 | ~45min | ~6h (不含 sleep) |

全量通过率低于 small10 v2 是预期内的——small10 v2 有 69 个种子技能，fromscratch 从零开始。
