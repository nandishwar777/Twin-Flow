# TwinFlow - Python Edition

Digital Twin AI Personal Productivity & Scheduling System.

TwinFlow is a full-stack web app that learns your daily habits such as sleep,
focus, tasks, breaks, and energy, then uses a scikit-learn model to predict
energy and generate a personalized AI schedule.

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | HTML, CSS, vanilla JavaScript, Chart.js |
| Backend | Python 3.11+, FastAPI |
| Database | PostgreSQL or SQLite + SQLAlchemy ORM |
| Machine Learning | scikit-learn, pandas, numpy, joblib |
| Auth | passlib + bcrypt + Starlette sessions |

## Features

- Sign up / sign in with bcrypt-hashed passwords using email or mobile number
- Forgot-password OTP via Email, SMS, or Telegram
- Free Telegram bot integration for reminders and OTP delivery
- Daily reminders through Email, SMS, and Telegram with per-channel toggles
- Reliable weekly reports with catch-up delivery if the app was offline
- Daily productivity log and AI-generated schedule
- Streaks, badges, task completion tracking, and ML feedback loop
- Dashboard analytics and 30-day trend charts
- Auto-generated API docs at `/docs`

## Setup

### 1. Install prerequisites

- Python 3.11 or newer
- PostgreSQL 14 or newer if you want PostgreSQL

### 2. Create the database

Mac/Linux:

```bash
createdb twinflow
```

Windows in `psql`:

```sql
CREATE DATABASE twinflow;
```

### 3. Create and activate the virtual environment

```bash
cd backend
python -m venv venv
```

Activate it:

- Mac/Linux: `source venv/bin/activate`
- Windows: `venv\Scripts\activate`

Install dependencies:

```bash
pip install -r requirements.txt
```

### 4. Configure environment

Copy `backend/.env.example` to `backend/.env`:

```bash
cp backend/.env.example backend/.env
```

Windows:

```bat
copy backend\.env.example backend\.env
```

Set your real values in `backend/.env`:

```env
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/twinflow
SESSION_SECRET=any-long-random-string-at-least-32-characters
HOST=0.0.0.0
PORT=8000
TELEGRAM_BOT_TOKEN=
```

If `DATABASE_URL` is blank, TwinFlow falls back to local SQLite automatically.

### 5. Train the ML model

```bash
python -m ml.train_model
```

If you skip this, the backend will train automatically on first use.

### 6. Run the server

```bash
python main.py
```

Open `http://localhost:8000` in your browser.

## SMS Setup

To enable SMS reminders and OTP:

1. Create a free Fast2SMS account
2. Copy your authorization key
3. Put it in `backend/.env`

```env
FAST2SMS_API_KEY=your-fast2sms-api-key-here
```

Without Fast2SMS, the app still works. SMS options just stay unavailable.

## Telegram Setup

TwinFlow can send daily reminders, weekly summaries, and forgot-password OTPs
through Telegram. This is completely free.

### Create the bot

1. Open Telegram and chat with `@BotFather`
2. Send `/newbot`
3. Follow the prompts for bot name and username
4. Copy the bot token BotFather returns
5. Put it in `backend/.env`

```env
TELEGRAM_BOT_TOKEN=your-bot-token-here
```

### Set the webhook

```bash
curl -F "url=https://your-app-url/api/telegram/webhook" https://api.telegram.org/bot<TOKEN>/setWebhook
```

### Local development note

For local development, use `ngrok` or another public tunnel if you want the
Telegram webhook to work. If you skip the webhook, outbound Telegram messages
still work, but manual `/connect <code>` linking will not.

### Link a user account

1. Open TwinFlow Settings
2. Click `Connect Telegram`
3. Open your bot in Telegram
4. Send `/start`
5. Send `/connect <code>`

Without `TELEGRAM_BOT_TOKEN`, the app still works perfectly. Telegram options
hide gracefully.

## Auth Flow

- Register with username, email, mobile number, and password
- Login with email or mobile number
- Forgot password with Email, SMS, or Telegram OTP
- Toggle Email, SMS, and Telegram reminders independently in Settings

## Scheduler Notes

- Daily reminders run every morning at 8 AM by default
- Weekly reports run every Sunday at 6 PM by default
- A catch-up job resends missed weekly reports after downtime
- Schedule completion feedback is captured nightly at 23:55

## Project Structure

```text
Twin Flow/
|-- backend/
|   |-- main.py
|   |-- database.py
|   |-- models.py
|   |-- schemas.py
|   |-- auth.py
|   |-- telegram_bot.py
|   |-- telegram_routes.py
|   |-- productivity.py
|   |-- schedule.py
|   |-- dashboard.py
|   |-- notifications.py
|   |-- notifications_routes.py
|   |-- scheduler_jobs.py
|   `-- ml/
|       |-- train_model.py
|       |-- predict.py
|       |-- scheduler.py
|       `-- model.pkl
`-- frontend/
    |-- login.html
    |-- register.html
    |-- forgot-password.html
    |-- dashboard.html
    |-- log.html
    |-- schedule.html
    |-- settings.html
    `-- ...
```

## Common Issues

- `password authentication failed`: check `DATABASE_URL`
- `database "twinflow" does not exist`: create the DB first
- `ModuleNotFoundError`: activate the virtual environment
- Port 8000 already in use: change `PORT`

## License

MIT
