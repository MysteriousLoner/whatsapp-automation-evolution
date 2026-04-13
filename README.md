# WhatsApp Automation Demo Access

This project exposes two browser-facing pages for the demo.

## 1. Contract Status UI

Open:

`http://localhost:8093/admin/contracts`

If you are on a VPS, replace `localhost` with your VPS public IP or domain.

This page is public in demo mode and does not require an API key.

## 2. Evolution API Manager

Open:

`http://localhost:8094/manager`

If you are on a VPS, replace `localhost` with your VPS public IP or domain.

## Current Port Map

- WhatsApp automation Flask app: `8093`
- Evolution API: `8094`
- PostgreSQL: `5434`
- Redis: `6381`

## Notes

- `WEBHOOK_PUBLIC_URL` and `CONTRACT_BASE_URL` are set for the Flask app host.
- The Evolution API container is exposed on host port `8094`, while the internal container port stays `8080`.
- If you change ports again, update `docker-compose.yml` and `.env` together.
