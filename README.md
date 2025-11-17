# Flask Event Ticket Booking System

A full-stack ticketing platform built with Flask. Customers can order VIP or Regular tickets (max five per order), and administrators manage approvals, inventory, and queues from a live dashboard.

## Key Tools & Technologies

| Layer | Tooling | Purpose |
|-------|--------|---------|
| Runtime | Python 3.11+ | Primary language and runtime |
| Web Framework | Flask 3.x | Routing, templating, session handling |
| Database ORM | Flask-SQLAlchemy 3.x | Models, migrations, and persistence |
| Database | SQLite (SQLAlchemy default) | Lightweight relational store (`instance/inventory.db`) |
| Auth | Werkzeug security helpers | Password hashing and verification |
| Frontend | Bootstrap 5.3, HTML5, Vanilla JS (Fetch API) | Responsive UI and dashboard interactions |
| Task Scheduling | `setInterval` (browser) | Auto-refreshing admin metrics |

## Features

- User self-service ordering with real-time availability and queue fallback
- Admin approval workflow that decrements inventory only after approval/completion
- VIP prioritization pipeline with mixed-order handling
- CSV exports for transactions and sales summaries
- Inventory management with price and quantity controls
- Comprehensive JSON APIs for tickets, orders, and queue operations

## Project Structure

```
src
├── app.py                 # Flask app factory & blueprint registration
├── config.py              # Environment-aware configuration (database URI, secrets)
├── database.py            # SQLAlchemy initialization helpers
├── models
│   └── inventory.py       # ORM models: User, Ticket, Order, OrderItem, Queue
├── routes
│   ├── admin.py           # Admin dashboard endpoints & CSV exports
│   ├── auth.py            # User registration, login, session APIs
│   ├── purchases.py       # Legacy inventory purchase endpoints
│   └── tickets.py         # Ticket catalog, ordering, queue APIs
├── templates              # Jinja2 templates (user pages & admin UI)
└── static
    └── style.css          # Custom styling layered on Bootstrap
```

## Architecture Overview

- **Blueprint-driven routing** keeps concerns separated (auth, tickets, admin).
- **SQLAlchemy models** enforce relationships and cascade deletes (e.g., `Order -> OrderItem`).
- **Service-style helpers** inside blueprints aggregate VIP vs Regular orders for priority handling.
- **Templates + Fetch API** provide a responsive admin dashboard with auto-refreshing metrics.
- **Session-backed auth** for both users and admin, with hashed passwords and cookie-based sessions.

## Setup & Tooling

### 1. Create and activate a virtual environment (recommended)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install Python dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure environment variables (optional)

| Variable | Purpose | Default |
|----------|---------|---------|
| `FLASK_ENV` | `development` enables debug mode | `production` if unset |
| `DATABASE_URL` | Override SQLite path (e.g., PostgreSQL) | `sqlite:///instance/inventory.db` |
| `SECRET_KEY` | Flask session signing key | Randomly generated per run |

Create a `.env` file or export values in your shell before launching the app.

### 4. Run the development server

```powershell
python src/app.py
```

The server boots at `http://127.0.0.1:5000`, creates `instance/inventory.db`, and seeds default tickets.

### 5. Default entry points

- `http://127.0.0.1:5000/` — Customer storefront
- `http://127.0.0.1:5000/auth/login` — User login
- `http://127.0.0.1:5000/admin/login` — Admin login (`admin` / `admin123` — change in `admin.py` for production)
- `http://127.0.0.1:5000/admin/dashboard` — Live dashboard (stats refresh every 10 seconds)

## Core Workflows

### Customer Ordering
1. Browse ticket availability (VIP, Regular) via `/`.
2. Submit an order (max five tickets across all types).
3. Order enters `pending` state until an admin approves.
4. On approval/completion, inventory decrements and receipts become available.
5. If tickets are sold out, customers can join the queue for a ticket type.

### Admin Dashboard
- **Stats panel** aggregates revenue, completed/approved orders, and queue sizes.
- **Pending orders** are prioritized VIP → Mixed → Regular using backend sorting.
- **Process Next Ticket** button approves the highest-priority order via Fetch API.
- **Inventory widget** sets available quantities and ticket prices (server validates non-negative stock).
- **Queues** show both waiting-list entries and pending orders containing that ticket type.
- **Exports** provide CSV downloads (`transactions.csv`, `summary.csv`).

## API Catalog

| Method | Endpoint | Notes |
|--------|----------|-------|
| `GET` | `/api/tickets` | Public ticket list with prices and availability |
| `POST` | `/api/orders` | Create pending order (requires login; enforces quantity cap) |
| `POST` | `/api/orders/<id>/complete` | Finalize approved orders and decrement stock |
| `GET` | `/api/orders/<id>` | View own order details |
| `POST` | `/api/orders/<id>/cancel` | Refund approved/completed orders back to stock |
| `POST` | `/api/queue` | Join VIP/Regular queue when sold out |
| `GET` | `/admin/api/stats` | Dashboard metrics (admin session) |
| `POST` | `/admin/api/tickets` | Update price or set available quantity |
| `POST` | `/admin/api/orders/<id>/approve` | Approve pending order with auto-reject guard |
| `POST` | `/admin/api/orders/<id>/reject` | Reject pending order with optional notes |
| `POST` | `/admin/api/queue/<id>/fulfill` | Mark queue entries as fulfilled |
| `GET` | `/admin/api/orders?status=pending` | Filtered admin order listings |

All admin routes require a logged-in admin session (`/admin/login`).

## Database Model Summary

- **User**: Auth accounts, hashed passwords, one-to-many relationship with `Order`.
- **Ticket**: VIP/Regular enumeration, price, available vs sold counts.
- **Order**: Tracks lifecycle (`pending`, `approved`, `completed`, `rejected`, `cancelled`) with timestamps and admin notes.
- **OrderItem**: Aggregates ticket quantities per order and records purchase price.
- **Queue**: Waiting list per ticket type with FIFO order (`joined_at`).

## Development Tips

- Run with `FLASK_ENV=development` for hot reload and debugger.
- Use the admin `Reset All Data` button to reseed defaults during testing.
- Password validation enforces minimum length and at least one special symbol (see `routes/auth.py`).
- When altering ticket defaults, edit the seeding logic in `routes/admin.py` or issue direct SQLAlchemy updates inside an app context.

## Future Enhancements (Ideas)

- Add automated tests using `pytest` and `Flask-Testing`.
- Introduce role-based admin accounts with dynamic credentials stored in the database.
- Integrate email notifications for queue fulfillment and order approval.
- Support payment gateways and webhook-driven inventory adjustments.

## License

Released under the MIT License. See `LICENSE` (add one if distributing publicly).