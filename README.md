# 🎁 GiftHub — Production Telegram Digital Commerce Platform

**GiftHub** is an enterprise-grade digital commerce platform built around a Telegram Bot, Telegram Mini App (Web App), Admin Control Panel, automated order fulfillment (Telegram Stars, Telegram Premium, Digital Gifts, Custom Services), dynamic pricing with price locks, immutable double-entry wallet ledger, and secure multi-provider payment integrations (Click, Payme, AutoPayCard).

---

## 🏛️ High-Level System Architecture

```text
                            Telegram Users & Admins
                                       │
            ┌──────────────────────────┴──────────────────────────┐
            │                                                     │
      Telegram Bot                                       Telegram Mini App / Admin
   (Aiogram 3 + FSM)                                        (FastAPI REST API)
            │                                                     │
            └──────────────────────────┬──────────────────────────┘
                                       │
                                 Service Layer
      ┌────────────────────────────────┼────────────────────────────────┐
      │                                │                                │
Order Service                   Payment Service                  Pricing Service
(State Machine & Timeline)     (Idempotent Webhooks)            (Authoritative Locks)
      │                                │                                │
Wallet Ledger                   Referral Service                 Fulfillment Service
(Atomic DB Locks)              (Commission Tiers)                (Circuit Breaker Worker)
      │                                │                                │
      └────────────────────────────────┼────────────────────────────────┘
                                       │
            ┌──────────────────────────┴──────────────────────────┐
            │                                                     │
      PostgreSQL 16                                            Redis 7
   (AsyncPG + Alembic)                                   (FSM / Locks / Queues)
            │                                                     │
            └──────────────────────────┬──────────────────────────┘
                                       │
                               Background Worker
                         (Transactional Outbox / DLQ)
```

---

## ✨ Core Production Features

### 1. Financial Invariants & Wallet Ledger
- **No Floating-Point Arithmetic:** All money and currency operations are strictly calculated using Python `Decimal` and PostgreSQL `NUMERIC(18, 2)`.
- **Immutable Transaction Ledger (`wallet_transactions`):** User balance cannot be mutated directly without creating a traceable, non-repudiable audit ledger entry (`deposit`, `purchase`, `refund`, `referral_bonus`, `admin_adjustment`).
- **Atomic Operations & Row Locking:** Wallet credit, debit, order updates, and referral bonuses execute within safe transactions utilizing row-level locks (`SELECT ... FOR UPDATE`) to prevent double-spending and race conditions.

### 2. Payment Architecture & Idempotency
- **Unified Provider Interface:** Seamless abstractions for **Click**, **Payme**, and **AutoPayCard**.
- **Hard Webhook Idempotency:** Enforces unique compound constraints on `(provider, provider_transaction_id)`. If Click or Payme resends the same webhook multiple times, balance is credited exactly once, referral rewards are dispatched exactly once, and duplicate deliveries are prevented.
- **Server-Side Authorization:** Client assertions of payment success are ignored. Orders transition to `PAID` exclusively via verified server-side webhook signatures and transaction IDs.

### 3. Order Lifecycle State Machine & Audit Timeline
- Strict state progression:
  ```text
  CREATED ──► AWAITING_PAYMENT ──► PAID ──► PROCESSING ──► COMPLETED
                                    │          │
                                    │          └──► FAILED
                                    └──► REFUNDED
  ```
- Prevents illegal state transitions (e.g. `COMPLETED` to `PROCESSING` or `REFUNDED` to `COMPLETED`).
- **Public Reference IDs:** Orders receive collision-resistant, human-friendly public tracking codes (`GH-XXXXXX`, e.g. `GH-K8F2B1`).
- **Immutable Status History (`order_status_history`):** Non-repudiable audit log recording every transition with source state, destination state, acting entity (`USER`, `ADMIN:<id>`, `SYSTEM`, `PAYMENT_GATEWAY`), timestamp, and operational reason.
- **Financial Snapshots:** Every order permanently freezes `unit_price`, `cost_price`, `margin`, `exchange_rate`, and `currency` at purchase time, insulating historical reporting from subsequent market fluctuations.

### 4. Dynamic Pricing, Price Locks & Preview Simulation
- **Authoritative Calculations:** Prices for Stars, Premium, and Gifts are calculated server-side based on TON/UZS exchange rates, margin parameters, and bulk volume discount curves.
- **Price Lock Mechanism:** Customers entering checkout receive a cryptographically tracked `price_lock` valid for a fixed duration (default: 10 minutes), shielding transactions from sudden exchange-rate volatility.
- **Price Preview Simulation:** Administrators can simulate proposed price updates against live catalog items before committing them, previewing resulting consumer prices, gross profit margins, and volume sensitivity curves (`POST /api/v1/admin/pricing/preview`).

### 5. Automated Order Fulfillment, Worker & Circuit Breakers
- Automatic delivery of Telegram Stars and Premium subscriptions via Fragment automation.
- Maximum retry budget (default: 3 attempts) with exponential backoff and admin escalation alerts.
- Dedicated background worker queue (`app/services/worker.py`) offloading heavy tasks from request threads.
- **Provider Circuit Breakers:** Fulfillment and payment providers utilize three-state circuit breakers (`CLOSED`, `OPEN`, `HALF_OPEN`) to stop traffic during outages and prevent cascading latency.

### 6. Problem Orders Dashboard & Remediation
- Dedicated administrative triage view categorizing problematic orders into 5 operational buckets:
  1. `fulfillment_failed` — Exhausted fulfillment retries.
  2. `pending_15m` — Created orders awaiting payment exceeding 15 minutes.
  3. `payment_failed` — Orders with payment gateway anomalies or rejected captures.
  4. `stuck_processing_10m` — Orders in `processing` state for more than 10 minutes without completion.
  5. `manual_action_needed` — Orders flagged for administrative inspection or refund verification.
- **One-Click Remediation:** Administrators can directly trigger instant fulfillment retries (`POST /api/v1/admin/orders/{id}/retry-fulfillment`) or perform verified manual fulfillments (`POST /api/v1/admin/orders/{id}/manual-fulfill`) directly from the dashboard.

### 7. Production Readiness & Observability Semantics
- **`/health/live`:** High-frequency, low-overhead liveness probe (< 5ms) returning `{"status": "healthy", "live": true}` for container orchestrators (Kubernetes / Docker).
- **`/health/ready`:** Deep readiness probe verifying critical runtime dependencies:
  - PostgreSQL database connection and round-trip query latency.
  - Redis cache and distributed lock ping response.
  - Background worker heartbeat freshness (verifying worker is actively consuming tasks).
  - Fragment fulfillment provider circuit breaker status.
- **`/api/v1/admin/health/system`:** Comprehensive administrator diagnostics API detailing bot status, PostgreSQL connection pool metrics, Redis latency, worker heartbeat, payment provider statuses, queue depths, and dead-letter queue (DLQ) counts.

### 8. User Experience Enhancements
- **Saved Recipients:** Frequently gifted friend handles and Telegram IDs can be saved with custom nicknames for 1-click recipient selection (`/api/v1/recipients`).
- **Pre-Purchase Confirmation Dialog:** Client modal verifies balance sufficiency, recipient accuracy, and displays non-refundable warnings before order commitment.
- **Digital Receipts:** Comprehensive digital receipts generated for every completed purchase (`/api/v1/orders/{code}/receipt`), printable and shareable with full order metadata.
- **1-Click "Buy Again":** Repeat previous orders with live real-time price recalculation (`/api/v1/orders/{code}/buy-again-details`).

### 9. Enterprise Reliability Architecture
- **Transactional Outbox Pattern (`app/models/outbox.py`, `app/services/outbox/`):** Critical post-payment events (`ORDER_FULFILLMENT_REQUESTED`, `WALLET_DEPOSIT_COMPLETED`, `ORDER_REFUNDED`) are committed atomically within the same database transaction as payment ledger mutations. Eliminates lost fulfillment jobs on server crashes.
- **Dead Letter Queue (DLQ) (`app/models/dlq.py`, `app/services/dlq/`):** Exhausted fulfillment jobs are automatically routed to persistent DLQ storage with complete error diagnostics, payload snapshots, and stack traces for manual retry or resolution from the Admin Panel.
- **Payment Reconciliation Engine (`app/models/reconciliation.py`, `app/services/reconciliation/`):** Periodically compares provider statements against internal orders and ledger entries to detect paid unpaid orders, missing wallet transactions, unfulfilled orders (> 5 min), amount mismatches, duplicate provider transactions, and refund anomalies.
- **Single-Loop Graceful Shutdown:** Gracefully drains running connections, bot sessions, Redis connection pools, worker loops, and database engines within a single unified asyncio event loop upon receiving `SIGINT` or `SIGTERM`.
- **Configurable `drop_pending_updates`:** Controlled via the `TELEGRAM_DROP_PENDING_UPDATES` environment variable (disabled in production to guarantee zero lost user interactions, enabled in local development).
- **Database-Level Financial Constraints:** Engine-enforced `CHECK` constraints on `balance >= 0`, `referral_earnings >= 0`, `amount != 0`, `balance_before >= 0`, `balance_after >= 0`, and `total_price >= 0`.
- **Automated Backup & Restore Strategy (`scripts/backup_postgres.py`, `scripts/restore_postgres.py`):** Automated compressed `pg_dump` with SHA-256 integrity verification, retention rotation, and automated restore testing.

---

## 🛠️ Technology Stack

| Layer | Technology | Production Requirement |
|---|---|---|
| **Bot Framework** | Aiogram 3.17+ | Async FSM with RedisStorage |
| **Backend & REST API** | FastAPI 0.115+, Uvicorn (ASGI) | Async endpoints, Pydantic v2 validation |
| **Primary Database** | PostgreSQL 16 (AsyncPG driver) | Mandatory for production (Strict row locks & NUMERIC precision) |
| **ORM & Migrations** | SQLAlchemy 2.0 Async, Alembic 1.14+ | Async session management |
| **Cache & Distributed Locks** | Redis 7, aioredis | Mandatory for production (FSM, idempotency locks, queues) |
| **Validation & Settings** | Pydantic 2.7+, Pydantic-Settings | Strongly-typed environment configuration |
| **Frontend** | Vanilla HTML5, CSS3, JavaScript | Modern responsive design, Sora & Inter typography |
| **Testing** | Pytest, Pytest-AsyncIO, HTTPX | 100% test coverage on critical financial & lifecycle flows |
| **Containers** | Docker, Docker Compose | Multi-stage production container |

---

## 📁 Repository Structure

```text
GiftHub/
├── app/
│   ├── api/                   # Versioned REST APIs
│   │   └── v1/
│   │       └── router.py      # System health, problematic orders, recipients, preview APIs
│   ├── core/                  # Core infrastructure
│   │   ├── config.py          # Validated Pydantic settings & env management
│   │   ├── database.py        # Async SQLAlchemy engine, session scopes & get_db dependency
│   │   ├── redis.py           # Redis client, distributed locks, production RedisStorage
│   │   ├── security.py        # Telegram HMAC-SHA256 validation & RBAC
│   │   ├── logging.py         # Structured logging with secret masking & exception context
│   │   └── exceptions.py      # Domain exceptions
│   ├── models/                # SQLAlchemy declarative models (Decimal precision)
│   │   ├── user.py            # User & referral relations
│   │   ├── wallet.py          # WalletTransaction immutable ledger
│   │   ├── order.py           # Order state machine, snapshots & OrderStatusHistory
│   │   ├── recipient.py       # SavedRecipient quick-select contacts
│   │   ├── payment.py         # PaymentTransaction with unique compound constraint
│   │   ├── pricing.py         # Pricing settings & PriceLock
│   │   ├── promo.py           # PromoCode & redemption tracking
│   │   ├── support.py         # SupportTicket & TicketMessage
│   │   ├── outbox.py          # Transactional Outbox events
│   │   ├── dlq.py             # Dead Letter Queue jobs
│   │   ├── provider.py        # Provider health & CircuitBreaker state
│   │   └── audit.py           # AdminAuditLog
│   ├── services/              # Domain service layer
│   │   ├── payments/          # Click, Payme, AutoPayCard & idempotency service
│   │   ├── wallet/            # Atomic balance operations & ledger journal
│   │   ├── orders/            # Order state lifecycle, GH-XXXXXX generator & refunds
│   │   ├── pricing/           # Authoritative price calculation, price locks & preview
│   │   ├── fulfillment/       # Fragment automated delivery
│   │   ├── providers/         # Circuit breaker provider monitoring
│   │   ├── outbox/            # Outbox publisher & event dispatcher
│   │   ├── dlq/               # Dead letter queue management
│   │   ├── reconciliation/    # Payment statement reconciliation engine
│   │   └── worker.py          # Background worker queue & job processor
│   ├── handlers/              # Aiogram Telegram Bot handlers
│   ├── keyboards/             # Telegram inline & webapp keyboards
│   └── web/                   # FastAPI server & static web assets
│       ├── server.py          # REST API endpoints, liveness/readiness probes
│       └── auth.py            # WebApp authentication dependencies
├── database/                  # Backward compatibility bridge (queries & models)
├── migrations/                # Alembic database migrations
├── docs/                      # Documentation & Specifications
│   ├── audits/                # Historical security & architectural audit reports
│   └── specifications/        # Platform engineering specifications
├── tests/                     # Comprehensive test suite
│   ├── unit/                  # Pricing, wallet, orders, audit v2, promotions tests
│   ├── integration/           # Idempotent payments, security, crash recovery, refunds
│   └── e2e/                   # API health probes, products & admin stats tests
├── web/                       # Web application frontends
│   ├── user/index.html        # Telegram Mini App (GiftHub Client Store & Receipts)
│   └── admin/index.html       # GiftHub Admin Control Panel & Health Dashboard
├── scripts/                   # Production utility scripts
│   ├── backup_postgres.py     # Automated PostgreSQL dump with SHA-256
│   └── restore_postgres.py    # Backup verification and test restore
├── Dockerfile                 # Multi-stage production container
├── docker-compose.yml         # Compose stack (App, Worker, Postgres, Redis)
├── pytest.ini                 # Test runner configuration
├── requirements.txt           # Pinned dependencies
├── .env.example               # Environment template
└── README.md                  # System documentation
```

---

## 🚀 Quick Start & Local Setup

### 1. Clone & Set Up Virtual Environment

```bash
git clone https://github.com/zemeisteer/GiftHub.git
cd GiftHub

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your secrets:

```bash
cp .env.example .env
```

```ini
# Bot Configuration
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
ADMINS=7195359577
TELEGRAM_DROP_PENDING_UPDATES=false

# Web & URLs
WEB_HOST=0.0.0.0
WEB_PORT=8000
WEB_APP_URL=http://localhost:8000/app
ADMIN_APP_URL=http://localhost:8000/admin

# Database & Cache (PostgreSQL 16 + Redis 7 for production)
DATABASE_URL=postgresql+asyncpg://gifthub:password@localhost:5432/gifthub
REDIS_URL=redis://localhost:6379/0

# For isolated local unit testing only:
# DATABASE_URL=sqlite+aiosqlite:///data/gifthub.db

# Payment Gateways
CLICK_SERVICE_ID=your_click_service_id
CLICK_MERCHANT_ID=your_click_merchant_id
CLICK_SECRET_KEY=your_click_secret

PAYME_MERCHANT_ID=your_payme_merchant_id
PAYME_SECRET_KEY=your_payme_secret
```

### 3. Run Database Migrations

Apply all schema revisions to your database:

```bash
alembic upgrade head
```

### 4. Run GiftHub (Runtime Modes)

GiftHub supports dedicated runtime modes for scalable microservice deployments as well as a combined mode for local development:

```bash
# 1. Combined Development Mode (FastAPI + Aiogram Bot + Background Worker in one process)
python main.py --mode=combined

# 2. Production API Service (FastAPI REST API, Mini App & Webhooks only)
python main.py --mode=api

# 3. Production Bot Service (Telegram Bot polling or webhook dispatch only)
python main.py --mode=bot

# 4. Production Worker Service (Transactional Outbox, DLQ retries & Reconciliation only)
python main.py --mode=worker
```

Access the interfaces:
- **Telegram Mini App:** `http://localhost:8000/app`
- **Admin Control Panel:** `http://localhost:8000/admin`
- **Interactive OpenAPI v1 Docs:** `http://localhost:8000/docs`
- **Liveness Probe:** `http://localhost:8000/health/live`
- **Readiness Dependency Probe:** `http://localhost:8000/health/ready`
- **System Health Diagnostics:** `http://localhost:8000/api/v1/admin/health/system`
- **Problem Orders Dashboard:** `http://localhost:8000/admin#problem-orders`

---

## 🐳 Docker Deployment

To launch the complete production stack (PostgreSQL 16, Redis 7, GiftHub API/Bot, and Worker) in Docker:

```bash
docker-compose up -d --build
```

To view logs:
```bash
docker-compose logs -f app worker
```

To run migrations within Docker:
```bash
docker-compose exec app alembic upgrade head
```

---

## 🧪 Automated Testing

Execute the test suite covering pricing, wallet ledger, idempotency, order transitions, problem orders, system health probes, promotions, and security:

```bash
pytest
```

---

## 🔒 Security Summary

1. **HMAC-SHA256 WebApp Verification:** Validates Telegram initData hash using the bot token as an HMAC key, combined with `auth_date` expiry rejection (< 86,400s).
2. **Payment Webhook Idempotency:** Duplicate payment webhooks are discarded via DB uniqueness constraints and transactional row locks.
3. **No Financial Spoofing:** Prices and discounts sent by clients are completely disregarded; backend calculates all amounts authoritatively.
4. **Audit Logging & Timeline:** Every administrative refund, balance adjustment, setting change, and order transition is immutably logged with actor ID, reason, and timestamp.
5. **Circuit Breakers & Fault Tolerance:** Automatic isolation of failing external providers with graceful degradation and alert dispatch.
