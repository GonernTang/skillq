---
name: huggingface-inference
description: Procedure for deploying a Hugging Face transformer model as a local inference API with Flask. Use when the user wants to serve an HF model (classification, NER, text generation, etc.) over HTTP with proper input validation, softmax confidence scores, and a background-launched service on a fixed port.
---

# Hugging Face Model Inference API

End-to-end procedure for downloading a Hugging Face transformer, persisting it locally, and exposing it as a REST endpoint with Flask. The shape generalizes across `AutoModel` task heads.

## 1. Install dependencies

```
pip install flask transformers torch
```

## 2. Download and persist the model

Use the `Auto*` factory classes so the same code works across architectures. Save both model and tokenizer to a local directory so the API can load them offline and deterministically.

```python
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_ID = "<huggingface-model-id>"   # e.g. "distilbert-base-uncased-finetuned-sst-2-english"
LOCAL_DIR = "./model_cache"

model = AutoModelForSequenceClassification.from_pretrained(MODEL_ID)
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
model.save_pretrained(LOCAL_DIR)
tokenizer.save_pretrained(LOCAL_DIR)
```

Caching locally avoids repeated network calls and lets the serving process be hermetic.

## 3. Build the Flask service

Load the model once at module level (not per request). Wrap inference in `torch.no_grad()` to disable gradient tracking, then apply softmax to logits to get a probability distribution over labels.

```python
from flask import Flask, request, jsonify
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

app = Flask(__name__)
LOCAL_DIR = "./model_cache"
model = AutoModelForSequenceClassification.from_pretrained(LOCAL_DIR)
tokenizer = AutoTokenizer.from_pretrained(LOCAL_DIR)
model.eval()

LABELS = list(model.config.id2label.values())  # canonical label order from the checkpoint

@app.post("/predict")
def predict():
    payload = request.get_json(silent=True) or {}
    text = payload.get("text", "").strip()
    if not text:
        return jsonify({"error": "field 'text' is required and must be non-empty"}), 400

    inputs = tokenizer(text, return_tensors="pt", truncation=True, padding=True)
    with torch.no_grad():
        logits = model(**inputs).logits
    probs = torch.nn.functional.softmax(logits, dim=-1).squeeze().tolist()
    pred_idx = int(torch.tensor(probs).argmax())

    return jsonify({
        "label": LABELS[pred_idx],
        "confidence": dict(zip(LABELS, probs)),
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
```

### Invariants to preserve across variants

- **Validate input first** — reject missing/empty `text` with HTTP 400 *before* tokenizing, so a malformed request never reaches the model.
- **No gradients at inference** — always use `torch.no_grad()` to save memory and time.
- **Softmax the logits** — raw logits are not probabilities; downstream consumers (and the `confidence` field) expect a proper distribution.
- **Stable label mapping** — read `model.config.id2label` rather than hard-coding `0→negative, 1→positive`; this stays correct if the checkpoint changes or you fine-tune.
- **Bind to `0.0.0.0`, not `127.0.0.1`** — required when the service is reached from outside the host (containers, other machines).

## 4. Launch as a background service

For long-lived use, detach the process so the API survives the spawning shell:

```
nohup python app.py > server.log 2>&1 &
```

For a foreground dev run, omit the `&` to see logs and stop with Ctrl-C.

## 5. Verify

```
curl -X POST http://localhost:5000/predict \
     -H "Content-Type: application/json" \
     -d '{"text": "I love this"}'
```

Expect a JSON body with `label` (a string) and a `confidence` dict keyed by the model's label set, with values that sum to ~1.0.

## Adapting to other tasks

- **Text generation** — swap to `AutoModelForCausalLM`, call `model.generate(...)`, decode with `tokenizer.decode(..., skip_special_tokens=True)`, and return the string instead of `{label, confidence}`.
- **Token classification / NER** — use `AutoModelForTokenClassification`, take `argmax` along the last dim per token, and aggregate sub-word pieces into spans.
- **Custom fine-tuned model** — if you trained it yourself, `id2label` already reflects your training labels, so no code change is needed in the serving layer.
- **Batching** — for higher throughput, accept a list of texts in the payload and stack the tokenized inputs before a single forward pass; return a list of per-item predictions.