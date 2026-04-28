# Playto Pay — Merchant Payout Engine

Cross-border payout infrastructure for Indian merchants. Merchants accumulate balance when international customers pay, and withdraw to their Indian bank account.

Built as part of the Playto Founding Engineer Challenge 2026.

---

## Live Demo

- **Frontend:** https://playto-payout-frontend-7gpu.onrender.com
- **Backend API:** https://playto-payout-production-7b6e.up.railway.app

### Test Credentials
Use one of these tokens from the seed data:
- merchant_rahul: `89980e93cd4ea935627d9a4bdd58846bbb73d262`
- merchant_priya: `0197e1d6f31de59f77f0216fa83175268dabd660`
- merchant_devcraft: `356ab890846486ad48021eac3e76a1dd9be01148`

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 4.2 + Django REST Framework |
| Database | PostgreSQL 15 |
| Background Jobs | Celery 5.6 + Redis 7 |
| Task Scheduling | Celery Beat with DatabaseScheduler |
| Frontend | React + Vite + Tailwind CSS |
| Deployment | Railway |
| Containerization | Docker + docker-compose |

---

## Architecture

```
React Frontend → Django API → PostgreSQL
                           ↓
                    Redis (broker)
                           ↓
              Celery Worker + Celery Beat
```

---

## Core Features

**Merchant Ledger** — Append-only event log. Balance always derived from `SUM(amount_paise)` over ledger events. Never stored. Never a float.

**Payout Request API** — `POST /api/v1/payouts/` with idempotency key header. Funds held atomically on request via negative ledger entry.

**Payout Processor** — Celery worker simulates bank settlement: 70% success, 20% failure, 10% hang. Failed payouts reverse funds atomically in one transaction.

**Merchant Dashboard** — React dashboard with live status updates via 5-second polling.

---

## Local Setup

### Prerequisites

- Python 3.9+
- PostgreSQL 15
- Redis
- Node.js 18+

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your DB credentials

python manage.py migrate
python manage.py seed
python manage.py runserver
```

### Celery Worker (new terminal)

```bash
cd backend
source venv/bin/activate
celery -A config worker --loglevel=info
```

### Celery Beat (new terminal)

```bash
cd backend
source venv/bin/activate
celery -A config beat --loglevel=info \
  --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` and paste a token from the seed output.

---

## Docker Setup (Recommended)

```bash
docker-compose up --build
```

Starts PostgreSQL, Redis, Django, Celery Worker, and Celery Beat together. Seed runs automatically on startup.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/balance/` | Available, held, total balance |
| GET | `/api/v1/ledger/` | All ledger events |
| GET | `/api/v1/bank-accounts/` | Merchant bank accounts |
| POST | `/api/v1/payouts/` | Create payout request |
| GET | `/api/v1/payouts/` | List all payouts |
| GET | `/api/v1/payouts/<id>/` | Single payout status |

### Authentication

All endpoints require:

```
Authorization: Token <merchant_token>
```

### Example Payout Request

```bash
curl -X POST http://localhost:8000/api/v1/payouts/ \
  -H "Authorization: Token <token>" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000" \
  -d '{"amount_paise": 50000, "bank_account_id": 1}'
```

---

## Running Tests

```bash
cd backend
python manage.py test tests --verbosity=2
```

7 tests total — concurrency and idempotency suites.

---

## Seed Data

Run `python manage.py seed` to populate:

| Merchant | Balance |
|----------|---------|
| Rahul Design Studio | ₹4,600 |
| Priya Content Co | ₹6,200 |
| DevCraft Solutions | ₹14,250 |

Tokens are printed to terminal after seeding.

---

## Django Admin

```
URL:      /admin/
Username: admin
Password: admin123
```

---

## Technical Highlights

- **Append-only ledger** with Postgres immutability trigger — ledger rows cannot be modified or deleted at the database level
- **Three-layer overdraft protection** — Python balance check + `SELECT FOR UPDATE` row lock + Postgres balance check trigger
- **Write-first idempotency** — key written before processing, handles simultaneous duplicate requests via `unique_together` constraint
- **Atomic fund reversal** — failed payout state transition and credit reversal entry happen in one `transaction.atomic()` block
- **State machine** enforced in model layer — `VALID_TRANSITIONS` dict, illegal transitions raise `ValueError` before any DB write
- **Event sourcing** — balance is a projection of ledger events, never a stored field