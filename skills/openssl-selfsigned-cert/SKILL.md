```markdown
---
name: openssl-selfsigned-cert
description: Generate a self-signed TLS certificate with OpenSSL, verify its metadata with Python, and optionally set up a local PyPI server using the certificate.
---

# Self-Signed TLS Certificate with OpenSSL + Python Verification

Create a self-signed RSA certificate and key using OpenSSL, bundle them into a PEM file, and verify the result with a Python script.

## When to Use

- Need a quick TLS cert for local dev, testing, or an internal service
- Want to verify cert metadata (subject, validity dates, fingerprint) programmatically
- No CA infrastructure available
- (Optional) Serve a local PyPI package index over HTTPS using this certificate

## Procedure

### 1. Generate the Private Key

```bash
mkdir -p <cert_dir>
openssl genrsa -out <key_path> 2048
chmod 600 <key_path>
```

### 2. Generate the Self-Signed Certificate

```bash
openssl req -x509 -new -key <key_path> -days <days> \
  -out <cert_path> \
  -subj "/O=<Organization>/CN=<CommonName>"
```

### 3. Bundle Key + Cert into a Single PEM

```bash
cat <key_path> <cert_path> > <pem_path>
```

### 4. Record Metadata via OpenSSL

```bash
openssl x509 -in <cert_path> -noout -subject
openssl x509 -in <cert_path> -noout -dates
openssl x509 -in <cert_path> -noout -fingerprint -sha256
```

Save each to a verification log so values can be cross-checked.

### 5. Verify with Python

Write a Python verifier (`verify.py`) that performs these checks:

1. **Existence** — `os.path.isfile` on each expected path.
2. **Decode the cert** using `ssl._ssl._test_decode_cert(<cert_path>)`. (This is a CPython internal API; for production, prefer the `cryptography` or `pyOpenSSL` package.)
3. **Extract the Common Name (CN)**. The `subject` field is a nested tuple of RDNs:
   `((('organizationName', 'DevOps Team'),), (('commonName', 'host'),))`.
   Iterate outer RDNs, then inner attribute pairs, looking for a tuple whose first element equals `"commonName"`.
4. **Extract `notAfter`** (may be `bytes` — decode to `str` if so), then parse with:
   ```python
   datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
   ```
   Confirm it is in the future relative to `datetime.utcnow()`.
5. **Print each check** (`PASS`/`FAIL`) and `sys.exit(0)` on full success, `sys.exit(1)` on any failure.

### 6. Make the Verifier Executable

```bash
chmod +x <script_path>
```

### 7. (Optional) Serve a Local PyPI Server with the Certificate

If you want to serve a PyPI-compatible package index using this certificate, follow these steps:

1. Install `pypiserver` if not already installed:
   ```bash
   pip install pypiserver
   ```
2. Start the server with the `run` subcommand (avoid deprecated `pypi-server` without `run`):
   ```bash
   nohup pypi-server run --port 443 --certfile <cert_path> --keyfile <key_path> /path/to/packages > pypi-server.log 2>&1 &
   ```
   - Use `--certfile` and `--keyfile` to point to the generated cert and key.
   - The `nohup` and `&` ensure the server persists after the shell exits.
3. Poll the server URL until it responds:
   ```bash
   until curl -s https://localhost:443/simple/; do sleep 1; done
   ```
   (Use `-k` or `--insecure` if the cert is self‑signed and you are testing locally.)
4. Install packages from this index with:
   ```bash
   pip install --index-url https://localhost:443/simple/ <package_name>
   ```

## Python Verifier Skeleton

```python
import os, sys
import ssl
from datetime import datetime, timezone

CERT = "<cert_path>"
KEY  = "<key_path>"
PEM  = "<pem_path>"

def check(label, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    return ok

ok = True
for label, path in (("key", KEY), ("cert", CERT), ("pem", PEM)):
    ok &= check(f"file exists: {path}", os.path.isfile(path))

data = ssl._ssl._test_decode_cert(CERT)

# Subject: walk the nested RDN tuple
cn = None
for rdn in data["subject"]:
    for attr in rdn:
        if attr[0] == "commonName":
            cn = attr[1]
ok &= check("CN extracted", cn == "<CommonName>", f"got {cn!r}")

# Validity: notAfter may be bytes
not_after = data["notAfter"]
if isinstance(not_after, bytes):
    not_after = not_after.decode()
expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
ok &= check("not in past", expiry > datetime.utcnow(), f"expires {expiry}")

sys.exit(0 if ok else 1)
```

## Key Pitfalls

- `ssl._ssl._test_decode_cert` is a private CPython API — wrap calls in try/except or fall back to `cryptography.x509.load_pem_x509_certificate` for portable code.
- `notAfter` from CPython's decoder is `bytes` on some versions, `str` on others — always normalize before `strptime`.
- The `subject` tuple shape is **outer RDN → inner (oid, value) pairs**, not a flat list — easy to off-by-one.
- `chmod 600` on the private key is essential before any shared deployment.
- `-days` accepts integers only; convert years × 365 if needed.
- When using the certificate with a PyPI server, ensure you use `pypi-server run` (not the deprecated bare `pypi-server`) to avoid warnings and maintain compatibility.
- The server must be kept running (use `nohup` or a process manager) and the client should poll for readiness before proceeding with installation.

## Verification Checklist

- `openssl x509 -in <cert> -noout -text -noout` shows expected subject and issuer.
- Python verifier exits 0 with all `[PASS]` lines.
- Fingerprint from step 4 matches the cert loaded in step 5.
```