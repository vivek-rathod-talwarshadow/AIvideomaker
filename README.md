# ViralForge

Render-friendly Django platform for generating lightweight vertical slideshow videos and publishing them to YouTube Shorts, with Instagram Reels and Pinterest kept disabled for now.

## What this repo includes

- Django project scaffold optimized for low CPU and RAM usage
- Database-backed content pipeline and publish queue
- Sleep-friendly automation with optional APScheduler support
- Lightweight video generation services using `ffmpeg`, `moviepy`, `Pillow`, and `edge-tts`
- Upload adapter structure for YouTube, Instagram, and Pinterest
- Real YouTube Shorts upload flow using the official YouTube Data API
- Docker-based Render deployment config and operational guidance
- Production-minded implementation plan in [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md)

## Core constraints

- Full hands-off scheduling is limited on Render Free because free web services spin down after 15 minutes of inactivity.
- Render cron jobs are not fully free.
- This architecture therefore uses:
  - one Django web service
  - one optional in-process scheduler
  - a DB queue
  - optional GitHub Actions trigger for reliable automation

## Render free-tier safety

- A constant in-process scheduler or a frequent uptime ping can consume Render Free instance hours and suspend the service for the rest of the billing month.
- This repo now defaults to a sleep-friendly deployment on Render:
  - `ENABLE_SCHEDULER=False`
  - `RENDER_SLEEP_FRIENDLY_MODE=True`
  - GitHub Actions automation runs twice per day instead of every 30 minutes
- The website still wakes up and works when someone visits it, but it no longer tries to stay awake all month.
- If you need near-continuous automation, use a paid Render plan or explicitly re-enable the scheduler.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## YouTube setup

The project is currently configured to focus on YouTube only.

1. Put your Google OAuth client ID and client secret into `.env`
2. Run `python manage.py generate_youtube_refresh_token`
3. Copy the printed refresh token into `YOUTUBE_REFRESH_TOKEN` in `.env`
4. Restart Django

The `YOUTUBE_API_KEY` is useful for read-only API calls, but uploads require OAuth plus a refresh token.

## Environment variables

See `.env.example` for required settings.

## Recommended free stack

- Text/topic generation: rule templates first, Gemini free tier second
- Voiceover: `edge-tts`
- Media sourcing: Pexels, Pixabay, Reddit JSON, Wikimedia/Wikipedia
- Video render: `ffmpeg` with simple slideshow transitions
- Scheduler: GitHub Actions trigger on Render Free, APScheduler for local or paid always-on deployments
- Database: SQLite locally, Render Postgres in deployment

## Deployment note

The included Render blueprint uses Docker because `ffmpeg` is an OS package and Docker is the most reliable way to keep the free-tier deployment reproducible.

## Project layout

See [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) for architecture, workflow, rate-limit policy, and deployment notes.
