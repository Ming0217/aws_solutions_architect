---
title: Apache Web Server
type: note
domain: compute
date: 2026-06-11
source: Own notes (context: WordPress on AWS example)
tags:
  - aws
  - compute
  - web-server
  - apache
  - lamp
---

# Apache Web Server

> Part of [[learning-plan/02-compute/02-compute|Compute]].
> Related: [[learning-plan/10-architecting/stateless-compute-shared-state|Stateless Compute + Shared State]]

**Apache HTTP Server** (a.k.a. `httpd`) is one of the most widely used **web server**
programs — the software that listens for web requests and returns web pages. It's what
runs on the EC2 instances to serve PHP pages in the WordPress-on-AWS example.

## What a web server does (the HTTP loop)

Apache speaks **HTTP/HTTPS** (typically port 80 / 443). The basic loop:

1. A browser connects and sends a request, e.g. `GET /index.html`.
2. Apache parses the request.
3. It decides what to do (serve a file vs generate content).
4. It builds an HTTP response (status code + headers + content) and sends it back.
5. The browser renders the result.

## Static vs dynamic content

- **Static** — for `/logo.png`, Apache reads the file from disk and returns it as-is.
- **Dynamic** — for a WordPress page, the response is *generated*: Apache hands the
  request to **PHP**, PHP runs WordPress code (which queries **MySQL** for the post,
  comments, etc.), produces HTML, and Apache returns it. This is the **LAMP stack** —
  **L**inux, **A**pache, **M**ySQL, **P**HP.

## How Apache is built (why it scales)

- **Modular** — the core handles HTTP; features are modules (`mod_ssl` for HTTPS, PHP
  handling, `mod_rewrite` for URL rewriting). Enable only what you need.
- **Concurrent** — handles many requests at once via a worker model (MPMs:
  Multi-Processing Modules) — a pool of processes/threads.
- **Virtual hosts** — one Apache instance can serve multiple sites/domains, picking the
  site by requested hostname.
- **Config-driven** — `httpd.conf`, `.htaccess` set document roots, permissions,
  redirects, module settings.

## Where it fits on AWS

```
Browser → ALB (load balancer) → EC2 running Apache + PHP + WordPress → RDS (MySQL) + EFS (files)
```

The load balancer spreads traffic across multiple EC2 instances, each running its own
Apache.

**Alternatives / landscape:** **Nginx** is the other dominant web server (often a reverse
proxy / great for static content and high concurrency). Static assets are frequently
served via **CloudFront** (CDN). But for serving WordPress's dynamic PHP pages, Apache is
the classic choice.
