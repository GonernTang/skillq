---
name: hf-flask-classify
description: Serve a Hugging Face transformer model behind a Flask HTTP endpoint that classifies text. Use when asked to deploy a pretrained HF model (e.g. sentiment analysis) as a REST API on a local machine.
---

# Serve a Hugging Face Model with Flask

## When to use
Deploy a pretrained Hugging Face model (typically `AutoModelForSequenceClassification`) as a JSON-over-HTTP classification service using Flask.

## Procedure

1. **Install dependencies**
   ```
   pip install transformers torch flask
   ```

2. **Pre-download the model to a local cache**
   Create a cache directory (e.g. `./model_cache`) and use the HF API to materialize weights:
   ```python
   from transformers import AutoTokenizer, AutoModelForSequenceClassification
   MODEL_NAME = "<repo-id>"          # e.g. "distilbert-base-uncased-finetuned-sst-2-english"
   CACHE_DIR   = "./model_cache"
   tok   = AutoTokenizer.from_pretrained(MODEL_NAME, cache_dir=CACHE_DIR)
   model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, cache_dir=CACHE_DIR)
   tok.save_pretrained(CACHE_DIR)
   model.save_pretrained(CACHE_DIR)
   ```
   Loading once at startup (not on every request) keeps latency predictable.

3. **Load the model at Flask startup time**
   ```python
   model = AutoModelForSequenceClassification.from_pretrained(CACHE_DIR)
   tokenizer = AutoTokenizer.from_pretrained(CACHE_DIR)
   model.eval()
   ```
   Use `model.config.id2label` to recover the label ordering — do not hard-code it.

4. **Define a single POST endpoint** that:
   - Requires `request.is_json`; reject non-JSON with HTTP 400.
   - Reads `text` from the JSON body; reject if missing or not a non-empty string.
   - Tokenizes with `return_tensors="pt"`, `truncation=True`, `padding=True`.
   - Runs the forward pass inside `torch.no_grad()`.
   - Applies `torch.nn.functional.softmax` to the logits to get probabilities.
   - Picks the argmax index and maps it via `model.config.id2label` for the predicted class.
   - Returns JSON shaped like:
     ```json
     {"sentiment": "<label>", "confidence": {"<label_a>": 0.93, "<label_b>": 0.07}}
     ```
     — always include *all* class probabilities in `confidence`, not just the top one.
   - Wraps inference in `try/except` and returns HTTP 500 with `{"error": "..."}` on failure.

5. **Run the server in the background**
   ```python
   if __name__ == "__main__":
       app.run(host="0.0.0.0", port=5000)
   ```
   Launch via `nohup python app.py > server.log 2>&1 &` so the process survives the shell exiting.

6. **Verify end-to-end with curl**
   - Happy path: `curl -X POST -H "Content-Type: application/json" -d '{"text":"I love this"}' http://localhost:5000/predict`
   - Missing field: should return 4xx.
   - Non-JSON body: should return 4xx.
   - Empty / malformed text: should return 4xx.
   Confirm `sentiment` is a valid label and `confidence` sums to ~1.0.

## Pitfalls
- Tokenizing per-request without `padding=True` will crash on variable-length batches.
- Forgetting `torch.no_grad()` wastes memory and slows inference.
- Returning only the top score hides signal from downstream callers — always return the full distribution.
- Hard-coding `["NEGATIVE","POSITIVE"]` breaks the moment you swap the model.
- Running Flask in the foreground blocks the agent loop — always background it and verify the port is listening before curling.