#!/usr/bin/env bash
set -euo pipefail

PUBLIC_IP="172.160.249.201"
CERT_DIR="./certs"

echo "🔐 Generating Self-Signed SSL Certificate for IP: ${PUBLIC_IP}..."
mkdir -p "${CERT_DIR}"

# Generate private key and certificate with Subject Alternative Name (SAN)
openssl req -newkey rsa:2048 -sha256 -nodes -keyout "${CERT_DIR}/webhook_pkey.pem" \
  -x509 -days 3650 -out "${CERT_DIR}/webhook_cert.pem" \
  -subj "/C=IQ/ST=Sulaymaniyah/L=Sulaymaniyah/O=Pird Dubbing/CN=${PUBLIC_IP}" \
  -addext "subjectAltName = IP:${PUBLIC_IP}"

chmod 600 "${CERT_DIR}/webhook_pkey.pem"
chmod 644 "${CERT_DIR}/webhook_cert.pem"

echo "✅ Certificate generated successfully in ${CERT_DIR}/"
