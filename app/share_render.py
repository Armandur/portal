"""Rendering av delade textfiler till självbärande, stylade HTML-sidor.

Markdown renderas med python-markdown och saneras med nh3 (rå-HTML i källan
tas bort så en delad .md inte kan köra skript - python-markdown släpper annars
igenom rå-HTML oavsett md_in_html). Sidan är helt fristående: inline CSS, inga
externa resurser, mörkt/ljust via prefers-color-scheme, mobil-först.

Generell nog att utökas: render_text_page() ger samma skelett med innehållet
i en <pre> (för t.ex. .txt).
"""

from html import escape

import markdown
import nh3

# Taggar/attribut vi tillåter i renderad markdown. Allt annat (script, iframe,
# on*-attribut, style, javascript:-URL:er) tas bort av nh3.
_ALLOWED_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "br", "hr", "blockquote",
    "ul", "ol", "li", "dl", "dt", "dd",
    "strong", "em", "b", "i", "u", "del", "ins", "sub", "sup", "mark",
    "code", "pre", "kbd", "samp", "a", "img", "span", "div",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption",
}
_ALLOWED_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "h1": {"id"}, "h2": {"id"}, "h3": {"id"},
    "h4": {"id"}, "h5": {"id"}, "h6": {"id"},
    "th": {"align"}, "td": {"align"},
    "ol": {"start"}, "li": {"id"},
    "code": {"class"}, "span": {"class"}, "div": {"class"},
}

_PAGE = """<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>@@TITLE@@</title>
<style>
/* Portalens identitet (samma palett som kortvyn/dokumentationen), inline
   eftersom sidan ska vara helt självbärande utan externa resurser. */
:root {
  color-scheme: light dark;
  --bg: #f5f6f8; --surface: #ffffff; --text: #1c2330; --muted: #66707f;
  --border: #dde1e7; --accent: #2563eb; --code-bg: #eef1f5;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #12161d; --surface: #1b212b; --text: #e6e9ee; --muted: #94a0b0;
    --border: #2c3542; --accent: #6d9bf5; --code-bg: #232b37;
  }
}
* { box-sizing: border-box; }
html { font-size: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  line-height: 1.65; overflow-wrap: break-word;
}
.wrap { max-width: 52rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
.bar {
  display: flex; justify-content: space-between; align-items: baseline;
  gap: 1rem; margin-bottom: 1rem; font-size: 0.85rem;
}
.bar .name { color: var(--muted); font-family: ui-monospace, Menlo, Consolas, monospace; }
.bar a { color: var(--accent); text-decoration: none; }
.bar a:hover { text-decoration: underline; }
.doc {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 1.5rem;
}
@media (min-width: 40rem) { .doc { padding: 2rem 2.25rem; } }
.doc > :first-child { margin-top: 0; }
.doc > :last-child { margin-bottom: 0; }
h1, h2, h3, h4, h5, h6 { color: var(--text); line-height: 1.25; margin: 1.6rem 0 0.7rem; }
h1 { font-size: 1.7rem; } h2 { font-size: 1.35rem; } h3 { font-size: 1.15rem; }
a { color: var(--accent); }
p, ul, ol, blockquote, table, pre { margin: 0 0 1rem; }
blockquote {
  border-left: 3px solid var(--border); margin-left: 0; padding: 0.2rem 1rem;
  color: var(--muted);
}
pre {
  background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 0.85rem 1rem; overflow-x: auto;
  font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.88rem; line-height: 1.5;
}
code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.9em; }
:not(pre) > code {
  background: var(--code-bg); padding: 0.12rem 0.35rem; border-radius: 4px; font-size: 0.85em;
}
.tablewrap { overflow-x: auto; margin: 0 0 1rem; }
table { border-collapse: collapse; font-size: 0.95rem; }
th, td { border: 1px solid var(--border); padding: 0.45rem 0.7rem; text-align: left; }
th { background: var(--code-bg); }
img { max-width: 100%; height: auto; }
hr { border: none; border-top: 1px solid var(--border); margin: 2rem 0; }
</style>
</head>
<body>
<main class="wrap">
<div class="bar"><span class="name">@@NAME@@</span><a href="@@RAW@@">visa källa</a></div>
<article class="doc">
@@BODY@@
</article>
</main>
</body>
</html>
"""


def _page(title: str, name: str, raw_url: str, body_html: str) -> str:
    return (
        _PAGE.replace("@@TITLE@@", escape(title))
        .replace("@@NAME@@", escape(name))
        .replace("@@RAW@@", escape(raw_url, quote=True))
        .replace("@@BODY@@", body_html)
    )


def render_markdown_page(md_text: str, filename: str, raw_url: str) -> str:
    """Renderar markdown till en fristående, sanerad HTML-sida."""
    html = markdown.markdown(
        md_text, extensions=["tables", "fenced_code", "toc"], output_format="html"
    )
    html = nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer nofollow",
    )
    # Wrappa tabeller så breda tabeller scrollar horisontellt i stället för att
    # spränga sidbredden på mobil. Wrappern läggs efter saneringen.
    html = html.replace("<table>", '<div class="tablewrap"><table>').replace(
        "</table>", "</table></div>"
    )
    return _page(filename, filename, raw_url, html)


def render_text_page(text: str, filename: str, raw_url: str) -> str:
    """Renderar ren text i en <pre> med samma skelett (för t.ex. .txt)."""
    body = f"<pre>{escape(text)}</pre>"
    return _page(filename, filename, raw_url, body)
