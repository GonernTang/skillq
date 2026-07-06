---
name: hf-flask-serve
description: Step-by-step procedure for downloading a Hugging Face transformer model (e.g. sequence classification), persisting it to a local cache, and exposing inference through a Flask POST endpoint that returns structured predictions with confidence scores.
---

# Serve a Hugging Face Model via Flask

Use this procedure when the task is to turn a pretrained HF transformer into a
small HTTP inference service backed by Flask.

## When to use

- The model is on the Hugging Face Hub and loadable via
  `AutoModelForSequenceClassification` (sentiment, NLI, multi-class classification,
  etc.).
- The deliverable is a JSON-over-HTTP endpoint, not a CLI or batch job.
- You need the response to include both a label (e.g. `positive`/`negative`)
  and a confidence value per class.

## Procedure

### 1. Install dependencies

```
pip install transformers torch flask
```

Pin versions if reproducibility matters; otherwise the above is sufficient.

### 2. Prepare a local model cache directory

Create a dedicated directory (e.g. `./model_cache`) and set
`os.environ["TRANSFORMERS_CACHE"]` (or pass `cache_dir=` to
`from_pretrained`). Caching avoids re-downloading weights across restarts.

### 3. Download and persist the model + tokenizer

Use the `Auto*` classes so the same code works across architectures:

```python
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_NAME = "<hub model id, e.g. distilbert-base-uncased-finetuned-sst-2-english>"
CACHE_DIR  = "./model_cache"

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, cache_dir=CACHE_DIR)
model     = AutoModelForSequenceClassification.from_pretrained(
    MODEL_NAME, cache_dir=CACHE_DIR
)
tokenizer.save_pretrained(CACHE_DIR)
model.save_pretrained(CACHE_DIR)
```

`saved_pretrained` ensures the artifacts are available offline on subsequent
boots.

### 4. Build the Flask app

Structure the server as follows:

1. Load `model` and `tokenizer` **at module level** so they are initialized
   once per worker, not per request.
2. Define a single `POST` route (e.g. `/predict`).
3. Parse + validate JSON: require a non-empty `text` field; reject with HTTP
   400 on missing/malformed input.
4. Tokenize: `inputs = tokenizer(text, return_tensors="pt", truncation=True,
   padding=True)`.
5. Run inference under `torch.no_grad()`: `outputs = model(**inputs)`.
6. Convert logits to probabilities with `torch.softmax(outputs.logits,
   dim=-1)`.
7. Build a `confidence` dict mapping each label id (as string) to its
   probability: `{str(i): float(p) for i, p in enumerate(probs[0])}`.
8. Resolve the predicted label id (`int(torch.argmax(probs, dim=-1))`) and
   map it through `model.config.id2label` to a human-readable string (e.g.
   `POSITIVE` / `NEGATIVE`).
9. Return `jsonify({"sentiment": label, "confidence": confidence_dict})`.

Keep the response schema stable — downstream callers will key off it.

### 5. Launch the service

Bind to `0.0.0.0` so the port is reachable from outside the container/host:

```python
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
```

Run in the background so subsequent steps can hit the endpoint:

```
nohup python3 app.py > server.log 2>&1 &
```

### 6. Smoke-test the endpoint

After launch, verify with a real request before declaring done:

```
curl -s -X POST http://localhost:5000/predict \
     -H "Content-Type: application/json" \
     -d '{"text": "I love this."}'
```

Expect HTTP 200 with `sentiment` (string) and `confidence` (object) fields.
A 500 here usually means a tokenization shape mismatch, a missing
`id2label` mapping, or the model not yet finished loading.

## Common pitfalls

- **Per-request model loading.** Never call `from_pretrained` inside the
  request handler — load once at import time.
- **Forgetting `torch.no_grad()`.** Without it, PyTorch builds an autograd
  graph on every request and memory grows unbounded.
- **Returning raw logits.** Clients want probabilities, not logits.
- **Hardcoding label names.** Use `model.config.id2label` so the code
  survives model swaps.
- **Listening on `127.0.0.1`.** Use `0.0.0.0` unless the service is
  strictly local.