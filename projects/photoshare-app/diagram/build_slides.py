"""Build a self-contained slides.html with the three Phase 2 diagrams embedded
as base64 PNGs (no external image files, so it works wherever it's opened).

Run:  python build_slides.py   # regenerates slides.html in this folder
"""
import base64
import pathlib

HERE = pathlib.Path(__file__).parent
SLIDES = [
    ("photoshare_phase2.png", "PhotoShare Phase 2 — main architecture"),
    ("photoshare_phase2_pipeline.png", "PhotoShare Phase 2 — async image pipeline"),
    ("photoshare_phase2_build_ops.png", "PhotoShare Phase 2 — build & operations"),
]


def data_uri(png_name: str) -> str:
    raw = (HERE / png_name).read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{b64}"


def main() -> None:
    sections = []
    for idx, (png, alt) in enumerate(SLIDES):
        active = " active" if idx == 0 else ""
        sections.append(
            f'  <section class="slide{active}"><img src="{data_uri(png)}" alt="{alt}" /></section>'
        )
    slides_html = "\n".join(sections)

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>PhotoShare — Phase 2 Architecture</title>
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; height: 100%; background: #fff; overflow: hidden; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
  .deck {{ position: fixed; inset: 0; }}
  .slide {{ position: absolute; inset: 0; display: none; align-items: center; justify-content: center; padding: 3vh 3vw; background: #fff; }}
  .slide.active {{ display: flex; }}
  .slide img {{ max-width: 96vw; max-height: 94vh; object-fit: contain; }}
  .chrome {{ position: fixed; left: 0; right: 0; bottom: 0; height: 5px; background: #e3e8ee; z-index: 10; }}
  .bar {{ height: 100%; width: 0; background: #ec7211; transition: width .2s ease; }}
  .nav {{ position: fixed; bottom: 12px; right: 16px; display: flex; gap: 8px; z-index: 11; }}
  .nav button {{ border: 0; background: rgba(35,47,62,.85); color: #fff; width: 38px; height: 34px; border-radius: 8px; font-size: 18px; cursor: pointer; }}
  .nav button:hover {{ background: #ec7211; }}
  .counter {{ position: fixed; bottom: 14px; left: 18px; color: #5b6b7b; font-size: 14px; z-index: 11; }}
  .hint {{ position: fixed; top: 12px; right: 16px; color: #aeb9c4; font-size: 12px; z-index: 11; }}
</style>
</head>
<body>
<div class="deck" id="deck">
{slides_html}
</div>

<div class="hint">&larr; &rarr; navigate &middot; F fullscreen</div>
<div class="counter"><span id="cur">1</span> / <span id="total">{len(SLIDES)}</span></div>
<div class="nav">
  <button id="prev" aria-label="Previous">&lsaquo;</button>
  <button id="next" aria-label="Next">&rsaquo;</button>
</div>
<div class="chrome"><div class="bar" id="bar"></div></div>

<script>
  var slides = Array.prototype.slice.call(document.querySelectorAll('.slide'));
  var i = 0;
  var cur = document.getElementById('cur');
  var bar = document.getElementById('bar');
  document.getElementById('total').textContent = slides.length;
  function show(n) {{
    i = Math.max(0, Math.min(slides.length - 1, n));
    slides.forEach(function (s, k) {{ s.classList.toggle('active', k === i); }});
    cur.textContent = i + 1;
    bar.style.width = ((i + 1) / slides.length * 100) + '%';
    location.hash = i + 1;
  }}
  function next() {{ show(i + 1); }}
  function prev() {{ show(i - 1); }}
  document.addEventListener('keydown', function (e) {{
    if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') {{ e.preventDefault(); next(); }}
    else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {{ e.preventDefault(); prev(); }}
    else if (e.key === 'Home') {{ show(0); }}
    else if (e.key === 'End') {{ show(slides.length - 1); }}
    else if (e.key === 'f' || e.key === 'F') {{
      if (!document.fullscreenElement) {{ document.documentElement.requestFullscreen(); }}
      else {{ document.exitFullscreen(); }}
    }}
  }});
  document.getElementById('next').addEventListener('click', next);
  document.getElementById('prev').addEventListener('click', prev);
  document.getElementById('deck').addEventListener('click', function (e) {{
    if (e.target.closest('button')) return;
    (e.clientX > window.innerWidth / 2) ? next() : prev();
  }});
  var start = parseInt((location.hash || '').replace('#', ''), 10);
  show(isNaN(start) ? 0 : start - 1);
</script>
</body>
</html>
"""
    (HERE / "slides.html").write_text(html, encoding="utf-8")
    print("wrote slides.html", (HERE / "slides.html").stat().st_size, "bytes")


if __name__ == "__main__":
    main()
