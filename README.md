# FarmOps SMS 🐄

**Cattle management via text message.** No app required — works on any phone, including flip phones.

Built for ranchers who need to track cattle records from the field without fumbling with apps.

## Features

- **SMS Commands** — Natural language, no codes to memorize
- **Voice Support** — Call in and speak your updates
- **Web Dashboard** — View all records in a browser
- **Offline-Ready** — Records queue when service is spotty

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/Javacabra/farmops-sms.git
cd farmops-sms
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your credentials:
# - TWILIO_ACCOUNT_SID
# - TWILIO_AUTH_TOKEN  
# - TWILIO_PHONE_NUMBER
# - OPENAI_API_KEY (for voice transcription)
# - AUTHORIZED_NUMBERS (comma-separated phone numbers)
```

### 3. Run

```bash
# Development
python -m uvicorn app.main:app --reload --port 8000

# Production
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 4. Expose for Twilio

For development, use ngrok:
```bash
ngrok http 8000
```

Then configure Twilio webhooks:
- **SMS Webhook:** `https://your-ngrok-url.ngrok.io/sms/incoming`
- **Voice Webhook:** `https://your-ngrok-url.ngrok.io/voice/incoming`

## SMS Commands

Just text naturally — no special syntax required:

| You Text | What Happens |
|----------|--------------|
| `Add calf born today red tag` | Creates calf record with red tag identifier |
| `Cow 42 moved to north pasture` | Updates location for cow #42 |
| `How many calves this month` | Returns count of calves born this month |
| `Vet visit cow 15 pink eye` | Logs health event for cow #15 |
| `Sold 5 steers today $1.85/lb avg 1100` | Records sale |
| `Status` | Returns farm overview |
| `Help` | Lists available commands |

## Voice Usage

1. Call your Twilio number
2. Speak your command (same as SMS)
3. Hear confirmation
4. Continue or hang up

## Web Dashboard

Visit `http://localhost:8000` to see:
- Total head count
- Calves YTD
- Sales YTD (head & revenue)
- Full cattle inventory
- Recent events timeline

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web dashboard |
| `/sms/incoming` | POST | Twilio SMS webhook |
| `/voice/incoming` | POST | Twilio voice webhook |
| `/voice/process` | POST | Voice transcription handler |
| `/api/stats` | GET | JSON stats |
| `/api/cattle` | GET | All cattle records |
| `/api/cattle/{tag}` | GET | Single cattle record |
| `/health` | GET | Health check |

## Database Schema

SQLite database with tables:
- **cattle** — Individual animal records (tag, type, breed, status, location)
- **events** — Health records, movements, notes
- **locations** — Pastures and areas
- **sales** — Sale transactions
- **messages** — SMS/voice log for debugging

## Deployment

### Fly.io (Recommended)

```bash
fly launch
fly secrets set TWILIO_ACCOUNT_SID=xxx TWILIO_AUTH_TOKEN=xxx ...
fly deploy
```

### Railway

Connect your repo and add environment variables in the dashboard.

### VPS

```bash
# With systemd
sudo cp farmops.service /etc/systemd/system/
sudo systemctl enable farmops
sudo systemctl start farmops
```

## Project Structure

```
farmops-sms/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app, webhooks
│   ├── database.py      # SQLite operations
│   └── parser.py        # Natural language parser
├── templates/
│   └── dashboard.html   # Web dashboard
├── static/              # Static assets
├── data/                # SQLite database (created on first run)
├── requirements.txt
├── .env.example
└── README.md
```

## License

MIT — Use it, modify it, help your neighbors use it.

---

*Built for Mom's cattle operation in Pace, FL. 🤠*
