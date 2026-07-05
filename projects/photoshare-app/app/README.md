# PhotoShare API — self-built app image

A minimal **FastAPI** replacement for `kodekloud/photosharing-app`, honoring the
same runtime contract so it drops into the existing infra unchanged.

## Contract (why it works as a drop-in)

| Expectation | How this app meets it |
| --- | --- |
| Listens on **8000** | `uvicorn ... --port 8000` (compose maps `80:8000`) |
| `GET /health` returns 200 | shallow health endpoint (ALB target + Docker healthcheck) |
| env `S3_BUCKET`, `AWS_SECRET_NAME` | read at startup; DB creds fetched from Secrets Manager |
| images in S3, metadata in MySQL | `POST /photos` does both |
| Lambda callback after upload | `POST /internal/metadata` (guarded by `INTERNAL_API_KEY`) |

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | shallow liveness (ALB) |
| GET | `/health/deep` | liveness + DB reachability (debug) |
| POST | `/photos` | upload image (multipart `file` + `title`) → S3 + DB row |
| GET | `/photos` | list recent photos (metadata) |
| GET | `/photos/{id}/image` | stream image through the app (bucket is private) |
| POST | `/internal/metadata` | Lambda callback; sets size + status=processed |

## Run locally

```bash
cp .env.example .env      # edit values; needs AWS creds with S3 + Secrets access
docker compose up --build
# open http://localhost/health  and  http://localhost/docs (Swagger UI)
```

## Build & push to ECR (for real deploys)

Your own image belongs in **ECR** (private registry), not Docker Hub:

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
REPO=photoshare-app

aws ecr create-repository --repository-name $REPO 2>/dev/null || true
aws ecr get-login-password --region $REGION \
  | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com

docker build -t $REPO .
docker tag $REPO:latest $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:latest
docker push $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:latest
```

Then set the CloudFormation `AppImageUri` parameter to
`<account>.dkr.ecr.us-east-1.amazonaws.com/photoshare-app:latest`. The EC2
instances pull it on launch (their role has `AmazonEC2ContainerRegistryReadOnly`).

## Ideas to tweak (the whole point of owning it)

- Generate **thumbnails** in the Lambda (needs a Pillow layer) and store a
  `thumb_key`; serve thumbnails on the list view.
- Add **pagination** and a real `uploader` once auth (Cognito) is added.
- Return **presigned URLs** instead of streaming, if you'd rather offload
  bandwidth from the app (tradeoff vs. the "served through the app" design).
- Add input validation (max size, allowed content types).

## Notes / limitations

- Not yet run end-to-end here — treat as a first working draft; `docker compose
  up --build` locally is the fastest way to smoke-test.
- Single uvicorn worker by design — scale **out** via the ASG, not up via workers.
