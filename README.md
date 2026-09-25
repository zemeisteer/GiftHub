# 🎁 GiftHub — Production Telegram Digital Commerce Platform

**GiftHub** is an enterprise-grade digital commerce platform built around a Telegram Bot, Telegram Mini App (Web App), Admin Control Panel, automated order fulfillment (Telegram Stars, Telegram Premium, Digital Gifts, Custom Services), dynamic pricing with price locks, immutable double-entry wallet ledger, and secure multi-provider payment integrations (Click, Payme, AutoPayCard).

---

## 🏛️ High-Level System Architecture

```text
                           Telegram Users & Admins
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            │                                                   │
     Telegram Bot                                      Telegram Mini App / Admin
  (Aiogram 3 + FSM)                                       (FastAPI REST API)
            │                                                   │
            └─────────────────────────┬─────────────────────────┘
                                      │
                                Service Layer
     ┌────────────────────────────────┼────────────────────────────────┐
     │                                │                                │
Order Service                  Payment Service                  Pricing Service
(State Machine)              (Idempotent Webhooks)            (Authoritative Locks)
     │                                │                                │
Wallet Ledger                  Referral Service                Fulfillment Service
(Atomic DB Locks)             (Commission Tiers)               (Fragment Worker)
     │                                │                                │
     └────────────────────────────────┼────────────────────────────────┘
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            │                                                   │
      PostgreSQL 16                                          Redis 7
   (AsyncPG + Alembic)                                 (FSM / Locks / Queue)
            │                                                   │
            └─────────────────────────┬─────────────────────────┘
                                      │
                              Background Worker
                        (Async Queue / Retries / TTL)
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

### 3. Order Lifecycle State Machine
- Strict state progression:
  ```text
  CREATED ──► AWAITING_PAYMENT ──► PAID ──► PROCESSING ──► COMPLETED
                                    │          │
                                    │          └──► FAILED
                                    └──► REFUNDED
  ```
- Prevents illegal state transitions (e.g. `COMPLETED` to `PROCESSING` or `REFUNDED` to `COMPLETED`).
- Detailed audit timestamps: `created_at`, `paid_at`, `processing_at`, `completed_at`, `refunded_at`.

### 4. Dynamic Pricing & Checkout Price Locks
- **Authoritative Calculations:** Prices for Stars, Premium, and Gifts are calculated server-side based on TON/UZS exchange rates, margin parameters, and bulk volume discount curves.
- **Price Lock Mechanism:** Customers entering checkout receive a cryptographically tracked `price_lock` valid for a fixed duration (default: 10 minutes), shielding transactions from sudden exchange-rate volatility.

### 5. Automated Order Fulfillment & Worker
- Automatic delivery of Telegram Stars and Premium subscriptions via Fragment automation.
- Maximum retry budget (default: 3 attempts) with exponential backoff and admin escalation alerts.
- Dedicated background worker queue (`app/services/worker.py`) offloading heavy tasks from request threads.

### 6. Role-Based Access Control (RBAC) & Security
- **Granular Permissions:** `orders.read`, `orders.refund`, `pricing.update`, `admins.manage`, `support.reply`, `broadcast.send`, etc.
- **Roles:** `super_admin`, `price_admin`, `support_admin`, `marketing_admin`, `user`.
- **Telegram WebApp Auth:** Strict HMAC-SHA256 signature verification and `auth_date` timestamp age checks (< 86,400 seconds) preventing credential spoofing and replay attacks.
- **Immutable Admin Audit Log:** Records administrative interventions (refunds, balance adjustments, pricing changes) with actor IDs, reasons, and timestamps.

### 7. Support Tickets, Promotions & Notifications
- Threaded customer support ticket system integrated with the Admin Panel.
- Promo codes supporting percentage and fixed discounts with global and per-user redemption limits.
- In-app notification center alongside Telegram alerts for real-time order status tracking.

---

## 🛠️ Technology Stack

| Layer | Technology |
|---|---|
| **Bot Framework** | Aiogram 3.17+ (Async FSM, Inline Query Handlers) |
| **Backend & REST API** | FastAPI 0.115+, Uvicorn (ASGI) |
| **Primary Database** | PostgreSQL 16 (AsyncPG driver) / SQLite for local development |
| **ORM & Migrations** | SQLAlchemy 2.0 Async, Alembic 1.14+ |
| **Cache & Distributed Locks** | Redis 7, aioredis |
| **Validation & Settings** | Pydantic 2.7+, Pydantic-Settings |
| **Frontend** | Vanilla HTML5, CSS3, JavaScript (Sora & Inter typography) |
| **Testing** | Pytest, Pytest-AsyncIO, HTTPX |
| **Code Quality** | Ruff, Mypy |
| **Containers** | Docker, Docker Compose |

---

## 📁 Repository Structure

```text
GiftHub/
├── app/
│   ├── core/                  # Core infrastructure
│   │   ├── config.py          # Validated Pydantic settings & env management
│   │   ├── database.py        # Async SQLAlchemy engine & session scopes
│   │   ├── redis.py           # Redis client, distributed locks, FSM storage
│   │   ├── security.py        # Telegram HMAC-SHA256 validation & RBAC
│   │   ├── logging.py         # Structured logging with secret masking
│   │   └── exceptions.py      # Domain exceptions
│   ├── models/                # SQLAlchemy declarative models (Decimal precision)
│   │   ├── user.py            # User & referral relations
│   │   ├── wallet.py          # WalletTransaction immutable ledger
│   │   ├── order.py           # Order state machine & timestamps
│   │   ├── payment.py         # PaymentTransaction with unique constraint
│   │   ├── pricing.py         # Pricing settings & PriceLock
│   │   ├── promo.py           # PromoCode & redemption tracking
│   │   ├── support.py         # SupportTicket & TicketMessage
│   │   └── audit.py           # AdminAuditLog
│   ├── services/              # Domain service layer
│   │   ├── payments/          # Click, Payme, AutoPayCard & idempotency service
│   │   ├── wallet/            # Atomic balance operations & ledger journal
│   │   ├── orders/            # Order state lifecycle & refunds
│   │   ├── pricing/           # Authoritative price calculation & price locks
│   │   ├── fulfillment/       # Fragment automated delivery
│   │   ├── promotions/        # Promo validation & safe redemptions
│   │   ├── referrals/         # Referral bonus calculation
│   │   └── worker.py          # Background worker queue & job processor
│   ├── handlers/              # Aiogram Telegram Bot handlers
│   ├── keyboards/             # Telegram inline & webapp keyboards
│   └── web/                   # FastAPI server & static web assets
│       ├── server.py          # REST API endpoints & route handlers
│       └── auth.py            # WebApp authentication dependencies
├── database/                  # Backward compatibility bridge (queries & models)
├── migrations/                # Alembic database migrations
├── tests/                     # Comprehensive test suite
│   ├── unit/                  # Pricing, wallet, orders, promotions tests
│   ├── integration/           # Idempotent payments, security, refund tests
│   └── e2e/                   # API health & endpoint integration tests
├── web/                       # Web application frontends
│   ├── user/index.html        # Telegram Mini App (GiftHub Client Store)
│   └── admin/index.html       # GiftHub Admin Control Panel
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

# Web & URLs
WEB_HOST=0.0.0.0
WEB_PORT=8000
WEB_APP_URL=http://localhost:8000/app
ADMIN_APP_URL=http://localhost:8000/admin

# Database & Cache (PostgreSQL + Redis for production)
DATABASE_URL=postgresql+asyncpg://gifthub:password@localhost:5432/gifthub
# For local SQLite development:
# DATABASE_URL=sqlite+aiosqlite:///data/stellar.db
REDIS_URL=redis://localhost:6379/0

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

### 4. Run GiftHub

Start the application (launches FastAPI server, Telegram Bot polling, and background worker concurrently):

```bash
python main.py
```

Access the interfaces:
- **Telegram Mini App:** `http://localhost:8000/app`
- **Admin Control Panel:** `http://localhost:8000/admin`
- **Interactive OpenAPI Docs:** `http://localhost:8000/docs`
- **Health Check Probe:** `http://localhost:8000/health`

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

Execute the test suite covering pricing, wallet ledger, idempotency, order transitions, promotions, and security:

```bash
pytest
```

---

## 🔒 Security Summary

1. **HMAC-SHA256 WebApp Verification:** Validates Telegram initData hash using the bot token as an HMAC key, combined with `auth_date` expiry rejection.
2. **Payment Webhook Idempotency:** Duplicate payment webhooks are discarded via DB uniqueness constraints and transactional row locks.
3. **No Financial Spoofing:** Prices and discounts sent by clients are completely disregarded; backend calculates all amounts authoritatively.
4. **Audit Logging:** Every administrative refund, balance adjustment, and setting change is immutably logged with admin Telegram ID, reason, and IP metadata.
