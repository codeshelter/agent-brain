"""Render a project's cards as one self-contained HTML5 kanban page (BOARD.html).

No external scripts, fonts or network calls: the page opens from disk (file://) in any
modern browser and works offline. All card text is HTML-escaped.
"""
import html
import re

COLUMNS = [  # (status, label)
    ("doing", "Doing"),
    ("blocked", "Blocked"),
    ("review", "Review"),
    ("todo", "To do"),
    ("done", "Done"),
]


def _inline(text):
    """Escape, then turn `code` spans into <code>."""
    out = html.escape(text)
    return re.sub(r"`([^`\n]+)`", r"<code>\1</code>", out)


def _card_parts(text):
    """(body, [log lines]) from a card file's text."""
    after_header = text.split("\n\n", 1)[1] if "\n\n" in text else ""
    body, _, log = after_header.partition("\n## Log")
    logs = [l[2:].strip() for l in log.splitlines() if l.startswith("- ")]
    return body.strip(), logs


def render(project, cards, generated):
    """cards: list of dicts with num,title,status,kind,jira,created,updated,text."""
    by_status = {s: [] for s, _ in COLUMNS}
    for c in cards:
        by_status.setdefault(c["status"] or "todo", []).append(c)
    by_status["done"] = sorted(by_status["done"], key=lambda c: c["updated"], reverse=True)
    kinds = sorted({c["kind"] for c in cards if c["kind"]})
    open_n = sum(len(v) for k, v in by_status.items() if k != "done")

    cols = []
    for status, label in COLUMNS:
        items = by_status.get(status, [])
        cards_html = []
        for c in items:
            body, logs = _card_parts(c["text"])
            jira = c["jira"] if c["jira"] not in ("", "None") else ""
            chips = "".join(filter(None, [
                f'<span class="chip kind">{html.escape(c["kind"])}</span>' if c["kind"] else "",
                f'<span class="chip jira">{html.escape(jira)}</span>' if jira else "",
            ]))
            log_html = "".join(f"<li>{_inline(l)}</li>" for l in logs[-12:])
            search = html.escape(" ".join([str(c["num"]), c["title"], c["kind"], jira, body]).lower(),
                                 quote=True)
            cards_html.append(f"""
      <article class="card" data-kind="{html.escape(c['kind'])}" data-search="{search}">
        <details>
          <summary>
            <span class="num">#{c['num']}</span>
            <span class="title">{_inline(c['title'])}</span>
            <span class="meta">{chips}<span class="date" title="last updated">{html.escape(c['updated'])}</span></span>
          </summary>
          <div class="body">{_inline(body)}</div>
          {f'<h4>Log</h4><ul class="log">{log_html}</ul>' if log_html else ''}
        </details>
      </article>""")
        empty = '<p class="empty">Nothing here</p>' if not items else ""
        cols.append(f"""
    <section class="col s-{status}" data-status="{status}">
      <header><h2>{label}</h2><span class="count">{len(items)}</span></header>
      <div class="cards">{''.join(cards_html)}{empty}</div>
    </section>""")

    kind_buttons = "".join(
        f'<button type="button" class="filter" data-kind="{html.escape(k)}" aria-pressed="false">{html.escape(k)}</button>'
        for k in kinds)
    title = html.escape(project.get("title") or project.get("id", "Board"))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Board</title>
<style>
:root {{
  --bg: #f6f7f9; --panel: #eceef2; --card: #ffffff; --text: #1d2330; --muted: #5d6677;
  --line: #d9dde5; --chip: #e8ebf1; --code: #eef0f4;
  --doing: #2f6fdb; --blocked: #c93b3b; --review: #b7791f; --todo: #6b7385; --done: #2f8f5b;
  color-scheme: light dark;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #14171d; --panel: #1b1f27; --card: #232833; --text: #e6e9ef; --muted: #9aa3b5;
          --line: #323846; --chip: #2d3340; --code: #2a303c; }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--text);
       font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
.top {{ position: sticky; top: 0; z-index: 2; background: var(--bg); border-bottom: 1px solid var(--line);
        padding: 14px 20px; display: flex; flex-wrap: wrap; gap: 10px 18px; align-items: center; }}
.top h1 {{ font-size: 18px; margin: 0; }}
.top .sub {{ color: var(--muted); font-size: 12px; }}
.tools {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-left: auto; }}
input[type=search] {{ min-width: 220px; padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px;
                      background: var(--card); color: var(--text); font: inherit; }}
button.filter, label.toggle {{ border: 1px solid var(--line); background: var(--card); color: var(--text);
  border-radius: 999px; padding: 4px 10px; font: inherit; font-size: 12px; cursor: pointer; }}
button.filter[aria-pressed=true] {{ background: var(--text); color: var(--bg); border-color: var(--text); }}
label.toggle input {{ margin: 0 4px 0 0; vertical-align: -2px; }}
main {{ display: grid; grid-template-columns: repeat(5, minmax(250px, 1fr)); gap: 14px; padding: 16px 20px 40px;
        overflow-x: auto; align-items: start; }}
.col {{ background: var(--panel); border-radius: 10px; border-top: 4px solid var(--c); min-width: 250px; }}
.col header {{ display: flex; justify-content: space-between; align-items: center; padding: 10px 12px 6px; }}
.col h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: .04em; margin: 0; color: var(--c); }}
.count {{ font-size: 12px; color: var(--muted); background: var(--chip); border-radius: 999px; padding: 1px 8px; }}
.cards {{ display: flex; flex-direction: column; gap: 8px; padding: 4px 10px 12px; }}
.s-doing {{ --c: var(--doing); }} .s-blocked {{ --c: var(--blocked); }} .s-review {{ --c: var(--review); }}
.s-todo {{ --c: var(--todo); }} .s-done {{ --c: var(--done); }}
.card {{ background: var(--card); border: 1px solid var(--line); border-left: 3px solid var(--c); border-radius: 8px; }}
.card summary {{ list-style: none; cursor: pointer; padding: 9px 10px; display: grid; gap: 4px; }}
.card summary::-webkit-details-marker {{ display: none; }}
.card summary:focus-visible {{ outline: 2px solid var(--c); outline-offset: 2px; border-radius: 6px; }}
.num {{ font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; }}
.title {{ font-weight: 600; }}
.meta {{ display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }}
.chip {{ font-size: 11px; background: var(--chip); border-radius: 4px; padding: 1px 6px; }}
.chip.jira {{ font-family: ui-monospace, Consolas, monospace; }}
.date {{ margin-left: auto; font-size: 11px; color: var(--muted); }}
.body {{ white-space: pre-wrap; padding: 0 10px 8px; color: var(--text); border-top: 1px dashed var(--line); padding-top: 8px; }}
h4 {{ margin: 4px 10px; font-size: 11px; text-transform: uppercase; color: var(--muted); letter-spacing: .04em; }}
.log {{ margin: 0 10px 10px; padding-left: 16px; color: var(--muted); font-size: 12px; }}
code {{ font-family: ui-monospace, Consolas, monospace; font-size: 12px; background: var(--code); border-radius: 3px; padding: 0 3px; }}
.empty {{ color: var(--muted); font-size: 12px; margin: 4px 2px; }}
.hidden {{ display: none; }}
body.hide-done .s-done {{ display: none; }}
body.hide-done main {{ grid-template-columns: repeat(4, minmax(250px, 1fr)); }}
@media (max-width: 700px) {{ main, body.hide-done main {{ grid-template-columns: minmax(0, 1fr); overflow-x: visible; padding: 12px; }}
  .col {{ min-width: 0; }} .tools {{ margin-left: 0; width: 100%; }} input[type=search] {{ min-width: 0; width: 100%; }}
  .top {{ padding: 12px; }} .title {{ overflow-wrap: anywhere; }} }}
@media print {{ .top {{ position: static; }} .tools {{ display: none; }} }}
</style>
</head>
<body class="hide-done">
<div class="top">
  <div>
    <h1>{title}</h1>
    <div class="sub">{open_n} open · {len(by_status['done'])} done · generated {html.escape(generated)} from cards/</div>
  </div>
  <div class="tools">
    <input type="search" id="q" placeholder="Search cards…" aria-label="Search cards">
    {kind_buttons}
    <label class="toggle"><input type="checkbox" id="showDone">Show done</label>
  </div>
</div>
<main>{''.join(cols)}
</main>
<script>
(function () {{
  var q = document.getElementById('q'), kinds = new Set();
  function apply() {{
    var term = q.value.trim().toLowerCase();
    document.querySelectorAll('.col').forEach(function (col) {{
      var shown = 0;
      col.querySelectorAll('.card').forEach(function (c) {{
        var ok = (!term || c.dataset.search.indexOf(term) !== -1) &&
                 (kinds.size === 0 || kinds.has(c.dataset.kind));
        c.classList.toggle('hidden', !ok); if (ok) shown++;
      }});
      col.querySelector('.count').textContent = shown;
    }});
  }}
  q.addEventListener('input', apply);
  document.querySelectorAll('button.filter').forEach(function (b) {{
    b.addEventListener('click', function () {{
      var k = b.dataset.kind, on = !kinds.has(k);
      on ? kinds.add(k) : kinds.delete(k); b.setAttribute('aria-pressed', on); apply();
    }});
  }});
  document.getElementById('showDone').addEventListener('change', function (e) {{
    document.body.classList.toggle('hide-done', !e.target.checked);
  }});
}})();
</script>
</body>
</html>
"""
