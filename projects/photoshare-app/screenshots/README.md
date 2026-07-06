# Screenshots

Drop PhotoShare screenshots here. Referenced from
[`../walkthrough.md`](../walkthrough.md) and
[`../../photoshare-app.md`](../../photoshare-app.md).

## Naming convention

Numbered + kebab-case, so they sort in a sensible order:

| Suggested filename | What to capture |
| --- | --- |
| `01-frontend-hero.png` | The app landing page (hero + CTA) |
| `02-gallery.png` | Gallery with uploaded photos (status dots, dimensions) |
| `03-architecture.png` | Architecture diagram (optional) |
| `04-cfn-stack-complete.png` | CloudFormation stack `CREATE_COMPLETE` / resource list |
| `05-alb-targets-healthy.png` | ALB target group — healthy targets across 2 AZs |
| `06-rds-multiaz.png` | RDS instance showing Multi-AZ = Yes, not publicly accessible |
| `07-s3-block-public-access.png` | S3 image bucket with Block All Public Access on |
| `08-cloudwatch.png` | CloudWatch dashboard / alarms |

## How to reference

Standard markdown (renders in Obsidian and on GitHub):

```markdown
![Gallery view](./screenshots/02-gallery.png)
```

From `photoshare-app.md` (one level up), the path is
`./photoshare-app/screenshots/02-gallery.png`.

Keep images reasonably sized (< ~500 KB, PNG/JPG) so the repo stays light.
