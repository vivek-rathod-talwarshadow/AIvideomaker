# ViralForge Implementation Plan

## 1. Architecture

### Primary design goal

Build a stable, low-RAM, mostly free automation platform that creates lightweight vertical slideshow videos and posts them sequentially to YouTube Shorts, Instagram Reels, and Pinterest Idea Pins.

### Recommended deployment shape

- `web`: single Django service on Render Free using Docker
- `db`: Render Postgres Free for persistent relational data
- `scheduler`: GitHub Actions trigger on Render Free, APScheduler only when always-on hosting is acceptable
- `queue`: database-backed queue using `PublishJob`
- `media`: ephemeral local filesystem for temporary render artifacts

### Why this design

- Avoids always-on Redis and Celery worker costs
- Avoids browser automation and Chrome memory usage
- Avoids heavy GPU image/video generation
- Keeps concurrency at 1 so Render free CPU/RAM is less likely to thrash
- Uses deterministic templates and stock assets instead of expensive AI

## 2. Hard constraints and honest tradeoffs

### Render Free limitations

- Free web services spin down after 15 minutes idle.
- Local files disappear on restart, redeploy, or spin-down.
- Cron jobs are not fully free.
- Free Postgres is suitable for hobby use, but it can restart and has no backups.

### Practical implication

Pure Render Free cannot guarantee 24/7 autonomous scheduling with no external help.

### FFmpeg deployment recommendation

Bundle `ffmpeg` through Docker on Render. This is the cleanest way to avoid native-runtime package uncertainty while staying on a free web service.

### Recommended free reliability options

1. Use GitHub Actions scheduled workflow to hit `/automation/run-once/` once or twice per day.
2. Or accept best-effort automation only while the service is awake.
3. Use `APScheduler` only on local development or paid always-on hosting.

## 3. Folder structure

```text
AIvideomaker/
├─ config/
├─ studio/
│  ├─ management/commands/
│  ├─ services/
│  ├─ admin.py
│  ├─ apps.py
│  ├─ enums.py
│  ├─ models.py
│  ├─ scheduler.py
│  ├─ urls.py
│  └─ views.py
├─ docs/
├─ build.sh
├─ start.sh
├─ render.yaml
├─ requirements.txt
└─ .env.example
```

## 4. Data model

### Main models

- `ChannelProfile`: per-platform channel config and posting limits
- `ContentTemplate`: reusable script/hook templates by niche
- `ViralTopic`: generated title, hook, script, hashtags, metadata
- `VideoProject`: one renderable short-form video
- `MediaAsset`: downloaded or cached image/audio/subtitle assets
- `PublishJob`: sequential posting queue by platform
- `SchedulerLock`: DB lock preventing duplicate runs
- `EventLog`: audit trail, failure logs, debug events

### Sequential posting rule

For each `VideoProject`, create three jobs:

1. YouTube Shorts
2. Instagram Reels
3. Pinterest Idea Pin

Each downstream job waits until the previous one is marked `posted`.

## 5. Background worker logic

### Lightweight worker choice

Use APScheduler instead of Celery for the default deployment.

### Poll cycle

Every 2 to 5 minutes:

1. Acquire DB lock
2. Create daily project if daily quota not met
3. Pick next due publish job
4. Generate media if project is not already ready
5. Upload to the current platform
6. Log success or failure
7. Release lock

### Why not Celery by default

- Needs Redis or equivalent
- Adds memory and operational complexity
- Not ideal for strict free-tier deployments

### When Celery becomes worth it

- More than 3 to 5 videos per day
- More than one concurrent channel
- Need dedicated retries and dead-letter queues

## 6. Video generation pipeline

### Low-cost pipeline

1. Generate topic from rule templates, RSS, Reddit, or Gemini free tier
2. Build hook, title, hashtags, and 20 to 45 second script
3. Split script into 4 to 7 scenes
4. Fetch vertical-friendly images from Pexels/Pixabay/Wikimedia
5. Generate voiceover with `edge-tts`
6. Generate `.srt` subtitles
7. Render slideshow with `ffmpeg`
8. Burn captions with high-contrast styling
9. Export MP4 with `libx264` preset `veryfast`

### Render-friendly defaults

- Duration: `20-35s`
- Resolution: `720x1280` in free mode, `1080x1920` optionally
- FPS: `24` or `30`
- Slides per video: `4-6`
- Transition style: simple fade or zoompan only

### Best optimization

Render most shorts at `720x1280` first. Upscaling to 1080p is optional, but on free-tier CPU the safest path is native 720p vertical output with strong captions.

## 7. Upload automation pipeline

### YouTube Shorts

- Best option: official YouTube Data API via OAuth
- Upload as normal video with vertical format and short duration
- Mark metadata, tags, description, and privacy state

### Instagram Reels

- `instagrapi` is the practical free option
- Risk: unofficial automation can trigger checkpoints or login challenges
- Reduce risk with slow posting cadence and stable IP behavior

### Pinterest Idea Pins

- Prefer official Pinterest API if your app/account supports the needed endpoint
- Otherwise treat Pinterest posting as optional/manual fallback because unofficial automation is less stable

### Sequential order

1. Upload to YouTube
2. Wait for success and record remote ID
3. Upload same MP4 to Instagram
4. Wait for success and record remote ID
5. Upload to Pinterest
6. Clean up temporary audio/subtitle files

## 8. Free API integrations

### Topic and source inputs

- Reddit JSON feeds for story prompts
- Wikipedia/Wikidata for facts
- RSS feeds for tech/business topics
- ZenQuotes style free quote APIs as optional input

### Asset sources

- Pexels free API
- Pixabay free API
- Wikimedia Commons
- Unsplash only if license and API quota fit the use case

### Text generation

Priority order:

1. Rule-based templates
2. Gemini free tier
3. Hugging Face free inference when available
4. Ollama only for local development, not Render Free

## 9. FFmpeg settings

### Recommended command profile

```bash
ffmpeg -y \
  -r 30 \
  -i input.mp4 \
  -pix_fmt yuv420p \
  -c:v libx264 \
  -preset veryfast \
  -crf 28 \
  -movflags +faststart \
  -c:a aac \
  -b:a 128k \
  output.mp4
```

### Why these values

- `veryfast`: lower CPU cost
- `crf 28`: smaller file, faster export
- `yuv420p`: maximum compatibility
- `+faststart`: faster mobile playback start

### More memory-saving tips

- Use still images instead of source videos
- Pre-resize images with Pillow before ffmpeg
- Avoid transparent overlays and too many compositing layers
- Use one font and one subtitle track

## 10. UI requirements mapping

### Admin dashboard can manage

- content niche templates
- generated topics
- queued and posted videos
- upload logs
- retry failed jobs
- channel enable/disable switches
- daily quotas

### Suggested next UI improvements

- custom preview page for latest render artifacts
- calendar-style schedule view
- one-click regenerate script
- one-click regenerate hashtags

## 11. Error handling strategy

### Rules

- Never process more than one publish job at a time
- Log every state transition in `EventLog`
- Retry transient network failures up to 3 times
- Mark platform-specific auth failures as manual intervention required
- Delete temp artifacts after successful posting
- Keep final MP4 until all platform uploads finish

### Failure categories

- `auth_error`
- `rate_limit`
- `upload_timeout`
- `render_error`
- `asset_fetch_error`
- `scheduler_lock_timeout`

## 12. Rate-limit handling and ban avoidance

### Recommended posting frequency

- Start with `1 video/day`
- Scale to `2 videos/day` only after 2 to 3 stable weeks
- Keep at least `45-90 minutes` between platforms if using unofficial automation

### Safe automation habits

- Keep the same device/IP profile for Instagram logins
- Avoid editing captions repeatedly after upload
- Don’t mass-post multiple reels in a short burst
- Keep hashtag count moderate, around `5-12`
- Randomize caption wording slightly between videos
- Use human review for failures and login checkpoints

## 13. Best niches for automation

### Highest-fit automated niches

- Facts
- Did-you-know
- Quotes
- Motivation
- AI facts
- Tech facts
- Money tips

### Medium-fit niches

- Business tips
- Gym motivation

### Higher-risk niches

- Horror stories
- Reddit stories

These need better narrative pacing, stronger hooks, and copyright/sensitivity review.

## 14. Viral content strategy

### Hook formula

- curiosity gap
- immediate surprise
- concrete promise
- fast emotional payoff

### Best structure for 20 to 35 second videos

1. Hook in first 1.5 seconds
2. Proof or surprising detail by second 5
3. Escalation in middle
4. Quick payoff near end
5. Call to action in final 2 seconds

### Make videos feel less AI-generated

- Use imperfect, conversational phrasing
- Mix short and long subtitle lines
- Add subtle zoom or pan movement
- Rotate caption highlight color by niche
- Include source references in description
- Use niche-specific emoji sparingly
- Use real stock photography instead of generic AI art

## 15. Best free alternatives by feature

| Feature | Primary Choice | Free Alternative | Notes |
|---|---|---|---|
| Topic generation | Rule templates | Gemini free tier | Most stable to start template-first |
| Stories | Reddit JSON | RSS + manual curation | Reddit rate limits can vary |
| Voiceover | edge-tts | gTTS | `edge-tts` usually sounds better |
| Media | Pexels | Pixabay/Wikimedia | Cache locally until upload completes |
| Rendering | ffmpeg | moviepy wrapper | Direct ffmpeg is lighter |
| Scheduler | APScheduler | GitHub Actions trigger | Free and simple |
| Queue | DB table | SQLite local / Postgres prod | Keep concurrency at 1 |
| IG upload | instagrapi | manual fallback | Unofficial and riskier |
| Pinterest | official API if available | manual fallback | Availability varies by account/app |

## 16. Scalability path

### Phase 1

- single Django service
- APScheduler
- DB queue
- one video/day

### Phase 2

- move scheduler to dedicated worker
- add Redis + Celery only if needed
- store assets on S3-compatible object storage
- add per-channel queue limits

### Phase 3

- multiple niches
- A/B hooks
- trend scoring
- thumbnail variants
- analytics-driven topic selection

## 17. Production readiness checklist

- add migrations
- install `ffmpeg` in deployment image
- complete real uploader adapters and OAuth flows
- add protected admin and secret rotation
- add tests for pipeline lock and sequential posting
- add health checks and alerting
- add backup/export strategy for free Postgres limitations
