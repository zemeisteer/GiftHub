# GiftHub — Comprehensive Pre-Implementation Project Audit

**Audit Date:** September 2026  
**Auditor:** Antigravity AI Engineering Team  
**Project:** GiftHub  
**Repository Branch:** `dev`  

---

## 1. Executive Summary

**GiftHub** is a Telegram-based digital commerce platform that enables users to purchase Telegram Stars, Telegram Premium subscriptions, digital gifts, and custom digital services via Telegram Bot and Telegram Mini App (Web App) using Uzbek national payment providers (Click, Payme, and direct card transfers), with backend fulfillment integrated into Fragment.com and TON Blockchain.

While the existing codebase demonstrates a functional prototype with extensive UI and basic end-to-end flows, this audit identified **critical financial vulnerabilities, security risks, lack of transaction safety, absence of database migrations, and structural technical debt** that must be resolved prior to production readiness.

---

## 2. Current Architecture

```text
               ┌───────────────────────┐
               │     Telegram User     │
               └───────────┬───────────┘
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
    ┌────────────────┐          ┌─────────────────┐
    │  Telegram Bot  │          │ Telegram Mini   │
    │  (Aiogram 3)   │          │ App (Web App)   │
    └────────┬───────┘          └────────┬────────┘
             │                           │
             ▼                           ▼
    ┌─────────────────────────────────────────────┐
    │          FastAPI Web Application            │
    │  - Auth: Telegram WebApp initData (partial) │
    │  - Endpoints: Products, Orders, Topup       │
    │  - Payments: Click, Payme, AutoPayCard      │
    └──────────────────────┬──────────────────────┘
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
    ┌────────────────┐          ┌─────────────────┐
    │ SQLite DB      │          │ Fragment / TON  │
    │ (stellar.db)   │          │ Blockchain      │
    └────────────────┘          └─────────────────┘
```

### Key Components:
1. **Entry Point (`main.py`):** Runs FastAPI via Uvicorn and Aiogram 3 Telegram Bot polling concurrently using `asyncio.gather()`. Memory-based FSM (`MemoryStorage`).
2. **Web Backend (`app/web/server.py`):** Monolithic 1,935-line FastAPI application serving both the REST API, payment webhooks, admin APIs, and mounting static HTML/JS for `/app` and `/admin`.
3. **Database Layer (`database/`):**
   - `db.py`: SQLite engine by default (`sqlite+aiosqlite:///data/stellar.db`). Uses `Base.metadata.create_all` and ad-hoc `ALTER TABLE` raw SQL statements inside `init_db()`.
   - `models.py`: Declarative SQLAlchemy models. Money stored as `Float`.
   - `queries.py`: 915-line repository and procedural queries mixed with business logic.
4. **Payments (`app/web/payments/`):**
   - Click: Basic MD5 hash verification, prepare & complete actions.
   - Payme: JSON-RPC handler (Basic Auth).
   - AutoPayCard: Basic webhook without database transaction model or idempotency.
5. **Frontends (`web/user/index.html` & `web/admin/index.html`):**
   - Single-file HTML/CSS/JS frontend applications interfacing directly with the FastAPI REST API.

---

## 3. Current Features & Capabilities

| Feature Area | Current Status | Audit Evaluation |
| :--- | :--- | :--- |
| **Telegram Bot** | Working | Aiogram 3.31 with inline and reply keyboards. Uses direct Telegram IP resolver. |
| **Telegram Mini App** | Working | Modern UI with dark/light themes, tabs for Stars, Premium, Gifts, Services, Orders, and Wallet. |
| **Admin Panel** | Working | Extensive single-page dashboard for pricing, statistics, broadcast, channels, and orders. |
| **Telegram Stars Flow** | Working | Package and custom amount calculators. Integration with Fragment Tonkeeper deep links. |
| **Telegram Premium Flow**| Working | 3, 6, 12 month subscriptions. |
| **Digital Gifts Flow** | Working | 12 digital gifts with 3D/classic/VIP categorization. |
| **Custom Services** | Working | Dynamic services catalog with admin CRUD. |
| **Referrals** | Partial | Simple 5% referral earning, tracking `referrer_id` and total count. No tiered commissions or dedicated referral ledger. |
| **Mandatory Channels** | Working | Gate screen checking ordinary subscriptions, join requests, and external links via `my_chat_member`. |
| **Promotions** | Partial | `PromoCode` and `PromoCodeUsage` models. Basic percentage/balance bonus. Lacks concurrency locks and product-specific restrictions. |
| **Click Payment** | Working | Prepare & complete flow. |
| **Payme Payment** | Working | Paycom JSON-RPC standard methods (`CheckPerformTransaction`, `CreateTransaction`, `PerformTransaction`, `CancelTransaction`). |
| **AutoPayCard** | Fragile | Ad-hoc card webhook without transaction table or signature verification. |

---

## 4. Current Database Structure

The current schema contains 14 tables:
- `users`: Stores user info, role, balance (`Float`), referral counts, and earnings (`Float`).
- `pricing_settings`: Holds base TON rates, margins, discount JSON, and gifts JSON.
- `orders`: Tracks purchases with `status` (`pending`, `done`, `cancel`), fulfillment details, and prices in `Float`.
- `transactions`: Log of balance movements (`topup`, `purchase`, `refund`, `referral_bonus`), but not a double-entry ledger.
- `channel_requirements` & `user_join_requests`: Gate subscription requirements.
- `admin_audit_logs`: High-level log of admin actions.
- `referral_settings`: Commission percentage and minimum spend requirements.
- `payment_settings`: Payment method toggles and card details.
- `payment_cards`: Cards for P2P/manual transfer.
- `fragment_settings`: Seed phrase, TonAPI credentials, wallet address, and auto-buy toggles.
- `broadcast_drafts`: Saved broadcast message drafts.
- `click_transactions`: Click prepare and complete transaction tracking.
- `payme_transactions`: Payme Paycom transaction lifecycle state machine.
- `promo_codes` & `promo_code_usages`: Coupons and redemption logs.
- `custom_services`: Dynamic digital services.

---

## 5. Critical Security Findings

### 🔴 Severity: CRITICAL — Arbitrary Wallet Credit via Unauthenticated Topup Endpoint
In `app/web/server.py` (lines 391–426):
```python
@app.post("/api/wallet/topup")
async def topup_wallet(req: TopupRequest, user: User = Depends(get_current_user)):
    ...
    updated_user = await queries.update_user_balance(
        session=session, user_id=user.id, amount=req.amount, ...
    )
```
Any authenticated user can call `/api/wallet/topup` with arbitrary amounts (e.g., `{"amount": 100000000, "method": "click"}`) and immediately credit their wallet balance without making any real payment.

### 🔴 Severity: CRITICAL — Client-Controlled Order Pricing (Price Tampering)
In `app/web/server.py` (lines 526–556):
```python
class PurchaseRequest(BaseModel):
    product_type: str
    item_title: str
    amount: int = 1
    total_price: float # <--- CLIENT SUPPLIED!
...
@app.post("/api/orders/create")
async def create_order_endpoint(req: PurchaseRequest, user: User = Depends(get_current_user)):
    ...
    if u.balance < req.total_price:
        raise HTTPException(...)
    order, bonus, referrer = await queries.create_order(
        ..., total_price=req.total_price, ...
    )
```
The client sends `total_price` in the payload, and the backend deducts whatever `total_price` the client supplies. An attacker can set `total_price: 1` and purchase 50,000 Telegram Stars or 12 Months of Telegram Premium for 1 UZS!

### 🔴 Severity: CRITICAL — Authentication Bypass via Fake Headers
In `app/web/server.py` (lines 70–121, 122–167):
```python
async def get_current_user(
    x_telegram_init_data: Optional[str] = Header(None),
    x_auth_user_id: Optional[str] = Header(None),
    auth_user_id: Optional[int] = Query(None),
):
    ...
    effective_uid = auth_user_id
    if not effective_uid and x_auth_user_id and x_auth_user_id.isdigit():
        effective_uid = int(x_auth_user_id)
```
Any caller can impersonate any user or admin by sending `x-auth-user-id: <admin_id>` or `?auth_user_id=<admin_id>`. This completely bypasses Telegram cryptographic authentication in production.

### 🔴 Severity: HIGH — Missing initData Expiration Check & Replay Protection
In `app/web/auth.py`:
The HMAC-SHA256 signature is verified, but `auth_date` is not checked. Stolen or captured `initData` tokens can be replayed indefinitely.

### 🔴 Severity: HIGH — Floating-Point Precision for Financial Operations
In all models (`User.balance`, `Order.total_price`, `Transaction.amount`), amounts are stored as Python `float` and SQLite/PostgreSQL `Float`. This leads to rounding errors, penny drops, and discrepancies in accounting.

### 🔴 Severity: HIGH — Lack of Database Transaction Atomicity & Row Locking
In `create_order` and payment handlers, balance checks and deductions are not wrapped in database row locks (`with_for_update()`). Concurrent requests can cause balance double-spending (race condition).

### 🔴 Severity: MEDIUM — Missing Payment Idempotency Layer for AutoPayCard & Generic Providers
While Click and Payme store their respective provider IDs, there is no generic unified `PaymentTransaction` table with database-level uniqueness on `(provider, provider_transaction_id)`. AutoPayCard webhook has no transaction recording or idempotency check at all.

---

## 6. Technical Debt & Codebase Flaws

1. **Monolithic Files:** `app/web/server.py` is 1,935 lines and mixes routing, HTML rendering, CSV export, broadcast handling, admin logic, payment endpoints, and notifications.
2. **Branding Inconsistencies:** Multiple files still refer to "Stellar Bot" instead of the official project name: **GiftHub**.
3. **No Database Migrations:** No Alembic setup. Database schema relies on runtime `create_all()` and procedural `ALTER TABLE` statements in `init_db()`.
4. **No Automated Test Suite:** Zero unit tests, integration tests, or end-to-end tests exist in the repository.
5. **In-Memory FSM in Production:** Aiogram bot uses `MemoryStorage`, meaning user states are lost on restart and cannot scale across workers.
6. **No Background Worker Queue:** Async tasks are dispatched via unmanaged `asyncio.create_task()`, which can be dropped on server termination.
7. **No Health / Readiness Endpoints:** Monitoring probes (`/health`, `/ready`) are absent.

---

## 7. Missing Features (Against Production Spec)

- **Dedicated Wallet Ledger:** No immutable `wallet_transactions` ledger with before/after balances and traceable reference IDs.
- **Strict Order State Machine:** Missing transitions (`CREATED`, `AWAITING_PAYMENT`, `PAID`, `PROCESSING`, `COMPLETED`, `FAILED`, `CANCELLED`, `REFUNDED`, `EXPIRED`) with recorded timestamps.
- **Checkout Price Lock:** No price lock snapshot or TTL mechanism for volatile exchange rates during checkout.
- **RBAC Permissions System:** Admins are differentiated only by string roles (`super_admin`, `price_admin`, etc.) without fine-grained server-enforced permissions (`orders.refund`, `pricing.update`, etc.).
- **Support / Ticket System:** No support ticket model, conversation history, or admin support management.
- **Refund Management:** No dedicated refund workflow with ledger tracking and idempotency.
- **Redis Integration:** No Redis caching, distributed locks, rate-limiting, or FSM storage.
- **Containerization & CI/CD:** No `Dockerfile`, `docker-compose.yml`, or GitHub Actions workflows.

---

## 8. Proposed Migration & Implementation Plan

### Phase P0: Financial Correctness & Security Hardening
1. **Financial Precision:** Refactor all models and queries to use `Decimal` and PostgreSQL `NUMERIC(18, 2)`.
2. **PostgreSQL & Alembic:** Configure async PostgreSQL engine with connection pooling and initialize Alembic migrations.
3. **Unified Payment Ledger & Idempotency:** Create `payment_transactions` with unique constraints on `(provider, provider_transaction_id)`.
4. **Immutable Wallet Ledger:** Create `wallet_transactions` capturing `balance_before`, `balance_after`, `reference_type`, `reference_id`, and `created_at`.
5. **Order State Machine:** Implement strict state machine with audited transitions.
6. **Eliminate Critical Vulnerabilities:**
   - Remove unauthenticated `/api/wallet/topup` backdoor.
   - Enforce server-authoritative price calculation on order creation.
   - Enforce strict Telegram `initData` HMAC-SHA256 validation with `auth_date` 24h expiration and remove header-spoofing backdoor in production.
   - Add database row-level locking (`with_for_update()`) on balance and order operations.

### Phase P1: Modular Architecture & Redis Infrastructure
1. Structure into `app/core/`, `app/api/`, `app/services/`, `app/repositories/`, `app/models/`, `app/bot/`.
2. Integrate Redis for Aiogram FSM, distributed locks, and rate limiting.
3. Setup background worker architecture (Redis + ARQ or asynchronous task queue).
4. Implement fine-grained RBAC permissions (`orders.read`, `orders.update`, `orders.refund`, etc.).
5. Standardize error handling and domain exceptions.

### Phase P2: Commerce Features & Fulfillment
1. Checkout Price Locking with 10-minute snapshot expiration.
2. Robust Promo Code system with concurrent usage locks and per-user limits.
3. Tiered referral system with idempotency.
4. Support ticket system with messaging history.
5. In-app and Telegram notification center.
6. Refund processing pipeline.

### Phase P3: Admin Panel & UX Improvements
1. Server-side pagination, search, and filtering for orders, users, and transactions.
2. Advanced analytics metrics (Revenue, AOV, provider distribution, conversion).
3. Admin manual recovery actions (retry fulfillment, refund, balance adjustment with required reason).
4. Consistent **GiftHub** branding across bot and web interfaces.

### Phase P4: Engineering Quality & Production Readiness
1. Comprehensive automated tests: unit, integration, and concurrency e2e.
2. Code formatting and linting (`ruff`, `mypy`).
3. Dependency management in `pyproject.toml` and pinned `requirements.txt`.
4. Dockerfile and `docker-compose.yml` (app, postgres, redis, worker).
5. GitHub Actions CI pipeline.
6. Health and readiness endpoints (`/health`, `/ready`).
7. Complete `README.md` and `POST_IMPLEMENTATION_AUDIT.md`.
