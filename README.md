# Twilio + OpenAI Realtime Voice Agent

A minimal example connecting a Twilio phone call to an OpenAI Realtime voice agent using [Pipecat](https://github.com/pipecat-ai/pipecat).

## How it works

```
Caller dials Twilio number
    → Twilio sends POST /twiml
    → Server returns TwiML with <Stream> WebSocket URL
    → Twilio opens WebSocket to /twilio/{session_id}
    → Audio streams bidirectionally via OpenAI Realtime API
    → Caller hears the AI voice agent in real time
```

## Prerequisites

- [Twilio account](https://www.twilio.com/try-twilio) (free, includes $15 credit)
- [OpenAI API key](https://platform.openai.com/api-keys) with Realtime API access
- [ngrok](https://ngrok.com/download) for local development
- Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/)

---

## Step 1 — Set up Twilio

### Register a free account

1. Go to [twilio.com/try-twilio](https://www.twilio.com/try-twilio)
2. Sign up — Twilio gives you **$15 free credit** on registration
3. Verify your email and phone number

### Buy a phone number

1. In the Twilio Console, go to **Phone Numbers → Manage → Buy a number**
2. Search for a local number (US numbers cost ~$1.15/month)
3. Click **Buy** and confirm

Your Account SID and Auth Token are on the [Console homepage](https://console.twilio.com).

---

## Step 2 — Set up OpenAI

1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Create a new secret key
3. Make sure your account has access to the Realtime API (`gpt-4o-realtime-preview`)

---

## Step 3 — Local setup

### Install dependencies

```bash
uv sync
```

### Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in the required values:

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | Your OpenAI secret key |
| `PUBLIC_BASE_URL` | Yes | Your ngrok `https://` URL (set after Step 4) |
| `TWILIO_ACCOUNT_SID` | No | Needed only if you want the bot to hang up calls programmatically |
| `TWILIO_AUTH_TOKEN` | No | Same as above |
| `OPENAI_REALTIME_MODEL` | No | Defaults to `gpt-4o-realtime-preview` |
| `OPENAI_TRANSCRIPTION_MODEL` | No | Defaults to `gpt-4o-transcribe` |
| `OPENAI_VOICE` | No | TTS voice — defaults to `marin` |
| `OPENAI_TTS_SPEED` | No | Speech speed multiplier — defaults to `1.0` |
| `AGENT_INSTRUCTIONS` | No | System prompt for the agent |
| `AGENT_GREETING` | No | First thing the agent says when a call connects |

---

## Step 4 — Expose the server with ngrok

In a terminal, start ngrok:

```bash
ngrok http 8000
```

Copy the `https://` forwarding URL (e.g. `https://example.ngrok-free.app`) and set it as `PUBLIC_BASE_URL` in your `.env`.

---

## Step 5 — Configure the Twilio webhook

1. In the Twilio Console, go to **Phone Numbers → Manage → Active numbers**
2. Click your phone number
3. Open the **Configure** tab
4. Under **Voice Configuration**, set:
   - **A call comes in**: `Webhook`
   - **URL**: `https://your-ngrok-domain.ngrok-free.app/twiml`
   - **HTTP**: `HTTP POST`
5. Click **Save configuration**

The server responds to that webhook with TwiML that tells Twilio to open a WebSocket stream back to your server:

```xml
<Response>
  <Connect>
    <Stream url="wss://your-ngrok-domain.ngrok-free.app/twilio/dev-session" />
  </Connect>
</Response>
```

---

## Step 6 — Run and test

Start the server:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Verify it's reachable:

```bash
curl https://your-ngrok-domain.ngrok-free.app/health
# → {"status":"ok"}
```

Call your Twilio number — you should hear the agent greeting within a few seconds.

---

## Notes

- **ngrok URL changes on every restart.** Each time you restart ngrok you must update `PUBLIC_BASE_URL` in `.env` *and* the webhook URL in the Twilio Console. A paid ngrok plan gives you a stable domain.
- **A2P 10DLC.** The Twilio Console may show a banner about A2P 10DLC registration. This only applies to SMS/MMS — it does not affect voice calls.
- **Emergency address warning.** Twilio may warn about a missing emergency address. Add one in the Console to avoid a $75 fee per emergency call.
- **TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN** are optional for basic inbound call handling. They are only needed if you want the agent to hang up calls via the Twilio REST API (set `auto_hang_up=True` in `twilio_handler.py`).
