---
name: openssl-selfsigned-cert
description: Generate a self-signed X.509/TLS certificate with OpenSSL (RSA private key, custom subject, validity period, combined PEM), then verify it with a Python script. Use when asked to create a self-signed certificate, generate TLS key+cert pairs for local/testing use, or scaffold PKI artifacts.
---

# Self-Signed X.509 Certificate with OpenSSL

## Overview

Produce a self-signed certificate (private key + cert + combined PEM) and verify it programmatically. Suitable for local development, testing, or internal services that need TLS material without a CA.

## Procedure

### 1. Prepare artifact directory

Create a dedicated directory to hold the key, cert, and combined PEM. Keep the private key off shared paths.

### 2. Generate a 2048-bit RSA private key

```bash
openssl genrsa -out key.pem 2048
chmod 600 key.pem
```

The key file must be mode 600 (owner read/write only). If you need a stronger key, use 4096; avoid <2048.

### 3. Create the self-signed X.509 certificate

```bash
openssl req -new -x509 -key key.pem -out cert.pem -days 365 \
  -subj "/O=<Organization>/CN=<CommonName>"
```

- `-x509` makes it a self-signed certificate (not a CSR).
- `-days` sets validity period (365 is typical; 825 max for browser-trusted leaf certs).
- `-subj` supplies the subject inline so openssl does not prompt.
- Add more subject components as needed, e.g. `/C=US/ST=.../L=.../O=.../CN=...`.
- For Subject Alternative Names (SANs) — required by modern browsers/clients — add an extensions file and pass it with `-extfile`. Without SANs, many TLS clients will reject the cert.

### 4. Combine key + cert into a single PEM

```bash
cat key.pem cert.pem > fullchain.pem
chmod 600 fullchain.pem
```

This PEM contains both the private key and the leaf certificate and is what most TLS servers (nginx, Apache, haproxy, etc.) expect when configured with a single `ssl_certificate` + `ssl_certificate_key` pair collapsed into one file.

### 5. Extract certificate metadata

```bash
openssl x509 -in cert.pem -noout -subject -dates -fingerprint -sha256
```

Use `-noout` so the base64 cert body is not printed. Capture: subject DN, `notBefore`, `notAfter`, and SHA-256 fingerprint for pinning or inventory.

### 6. Write a Python verification script

The script should:

1. Check that `key.pem`, `cert.pem`, and `fullchain.pem` exist (use `pathlib.Path`).
2. Load the cert. Prefer `ssl._ssl._test_decode_cert` (stdlib, no extra deps) on the PEM bytes, or `ssl.PEM_cert_to_DER_cert` + `cryptography.x509.load_der_x509_certificate` if `cryptography` is installed.
3. Parse the subject and pull out `CN` (Common Name) and `O` (Organization).
4. Decode `notBefore` / `notAfter` from ASN.1 time string (`YYYYMMDDHHMMSSZ` or `YYYYMMDDHHMMSS+HHMM`) and print in ISO-8601.
5. Compute and print the SHA-256 fingerprint, matching the openssl output.
6. Verify the cert is valid at "now" (`notBefore <= now <= notAfter`).
7. Print a clear success/failure line and exit non-zero on any failure.

### 7. Run the verification

```bash
python3 verify_cert.py
```

Confirm the printed subject, dates, and fingerprint match what `openssl x509` reported. Fix and rerun if anything is off.

## Verification checklist

- [ ] Private key file is mode 600.
- [ ] `openssl x509 -in cert.pem -noout -text` shows the expected subject and validity.
- [ ] Cert validity window includes the current date.
- [ ] Python verification script exits 0 and prints matching CN, dates, fingerprint.
- [ ] Combined PEM starts with `-----BEGIN PRIVATE KEY-----` and contains the cert after it.

## Common pitfalls

- Forgetting `-x509` produces a CSR, not a certificate.
- Forgetting `-noout` on metadata commands dumps the entire base64 cert to stdout.
- Key permissions left at 644 — many servers refuse to start with a world-readable key.
- Missing SANs — modern TLS clients reject leaf certs without them; add `-addext "subjectAltName=DNS:hostname"`.
- Validity period past the maximum (398 days for public browser trust as of 2020+) — use 365 unless you know your trust store permits longer.