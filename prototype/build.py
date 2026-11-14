"""Build prototype/index.html from src/app.html and src/nasa_data.js.

Run from anywhere:  python3 prototype/build.py
The result is a single static page; Astronaut.glb must sit next to it.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent
page = (root / "src" / "app.html").read_text(encoding="utf-8")
data = (root / "src" / "nasa_data.js").read_text(encoding="utf-8")
page = page.replace("/*__NASA__*/", data)

shell = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    "<style>body{margin:0}[hidden]{display:none!important}</style></head><body>"
    + page
    + "</body></html>"
)
(root / "index.html").write_text(shell, encoding="utf-8")
print("wrote", root / "index.html", f"({len(shell) // 1024} KB)")
