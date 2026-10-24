---
title: SPA ↔ API Wiring (how a static frontend connects to the API front door)
type: note
domain: architecting
date: 2026-10-23
source: "Own notes + Kiro explanation"
tags:
  - aws
  - architecting
  - serverless
  - cloudfront
  - s3
  - api-gateway
  - cors
  - spa
  - saa-c03
---

# SPA ↔ API Wiring

> Part of [[learning-plan/10-architecting/10-architecting|Architecting & best practices]].
> Related: [[learning-plan/02-compute/when-to-use-serverless-and-patterns|Serverless: when + patterns]]
> · [[learning-plan/04-networking/load-balancers|Load balancers]] · worked examples:
> [[projects/clear-thinking-app|Clear Thinking]] (serverless/JWT) · [[projects/video-streaming-app/DESIGN|Video Streaming]] (single-domain/signed-cookie)

> The confusion this clears up: **`S3 + CloudFront` (static frontend) and
> `API Gateway` (API front door) are NOT wired to each other on the backend.**
> The thing that connects them is the **user's browser at runtime.**

## Two independent delivery paths, joined by the browser

- **S3 + CloudFront** ships **static files** — `index.html`, `app.js`, `styles.css`. Dumb files, no logic.
- **API Gateway → Lambda** (or any backend) serves **dynamic data** — JSON computed on demand.

Neither calls the other. The sequence:

```
1. Browser → CloudFront → S3        : "give me the site"  → returns index.html + app.js
2. Browser RUNS app.js              : the code executes in the user's browser (not on S3)
3. app.js → fetch("…/api/videos")   : the browser makes an HTTP call to the API endpoint
4.          → API Gateway → Lambda → DynamoDB → JSON back to the browser
5. app.js renders that JSON
```

Two precisions that make the model airtight:

1. **The code runs in the browser, not on S3.** S3 only *hosts/serves* the file; the
   browser downloads and runs it. The API call originates from the **client**.
2. **The browser calls an HTTP *endpoint*, not Lambda directly.** `app.js` knows only a
   URL; **API Gateway** is what invokes the backend. The frontend speaks HTTP/JSON and
   has **no idea** whether Lambda, a container, or an EC2 app answers — the backend is
   **swappable** without touching the frontend. That decoupling is the whole point of
   an "API front door."

## How the frontend learns the API URL

The static JS must know *what URL to fetch*. It's just a string — baked in at build
time, or loaded at startup from a small **generated `config.json`**. Both projects below
use the runtime-config approach (a `config.json` written at deploy time with
`apiBaseUrl`), so the same frontend can point at a different API by changing one value.

## Two topologies

**Topology 1 — two domains (needs CORS):**
```
Browser ── site.cloudfront.net      ─→ S3 (static)
Browser ── abc.execute-api…amazonaws ─→ API Gateway (JSON)
```
Different hostnames → different origins → the API must send **CORS** headers or the
browser blocks the call. Works, but you manage CORS and two URLs.

**Topology 2 — one CloudFront domain, path-based behaviors (preferred):**
```
                         ┌── behavior  /*      → S3 (static site)
Browser ── one.cloudfront.net ──┤
                         └── behavior  /api/*  → API Gateway (→ backend)
```
One distribution, multiple **behaviors**. Frontend and API share **one origin**, so:
**no CORS**, **cookies work same-origin**, and there's **one URL** to reason about.

## The auth dimension (how the browser authenticates each API call)

Same wiring, two common ways the browser proves identity on its `fetch`:

| | Mechanism | Carried how |
|---|---|---|
| **Cognito JWT** (bearer token) | SPA signs in (Hosted UI / PKCE), gets a JWT | `Authorization: Bearer <token>` header on each API call |
| **CloudFront signed cookies** | API sets cookies scoped to a path | Browser auto-attaches cookies **same-origin** |

JWT works across origins (just a header); signed cookies specifically motivate the
**single-domain** topology (cookies attach only same-origin).

## Worked examples (your projects)

- **[[projects/clear-thinking-app|Clear Thinking]]** — pure serverless: `CloudFront + S3`
  SPA → **API Gateway (HTTP API) → Lambda → DynamoDB**, authenticated with a **Cognito
  JWT** authorizer. The canonical "entire app on Lambda."
- **[[projects/video-streaming-app/DESIGN|Video Streaming]]** — **single-domain**
  CloudFront: default behavior → S3 SPA, `/api/*` → API Gateway (→ VPC Link → ALB →
  **FastAPI on EC2**, *not* Lambda), `/media/*` → output bucket. Auth for playback is
  **signed cookies**, which is *why* it uses one origin. Same frontend pattern, different
  backend — the frontend can't tell.

## One-sentence model

> The static frontend is your app's code **shipped to the browser**; the API is **where
> that code fetches data**. They connect only because the delivered JavaScript calls the
> API URL — and putting both behind one CloudFront domain makes that call same-origin
> (no CORS, cookies work).

## Exam-relevant notes

- "SPA on S3/CloudFront calling an API on a different domain fails in the browser" → **CORS** (enable on the API).
- "Serve SPA and API under **one domain**" → **CloudFront with multiple behaviors** (`/*` → S3, `/api/*` → API).
- "Secure an API behind API Gateway for a web app" → **Cognito** JWT authorizer (or signed cookies if same-origin).
- Backend behind API Gateway is **swappable** (Lambda / ALB+containers / EC2) — the frontend only knows the URL.
