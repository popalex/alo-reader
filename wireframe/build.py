#!/usr/bin/env python3
"""Generate 5 visual-style mockups of the alo-reader three-pane UI.

All five share IDENTICAL markup + content (CSS Zen Garden style) so the only
variable is the visual direction. Run:  python build.py
Outputs: index.html + console.html, studio.html, reader.html, classic.html, nocturne.html
The three-pane SHAPE is fixed by DESIGN.md 1.7; these explore the free axes
(type, palette, density, light/dark) that WP-09 must pin down.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- Lucide-style inline icons (stroke = currentColor) -------------------
def ic(paths, fill="none", extra=""):
    return (f'<svg class="ic" viewBox="0 0 24 24" fill="{fill}" stroke="currentColor" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" {extra}>'
            f'{paths}</svg>')

I_REFRESH = ic('<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/>'
               '<path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/>')
I_CHECK   = ic('<path d="m3 12 5 5L20 5"/><path d="m14 14 3 3L23 8"/>')
I_STAR    = ('<svg class="ic star" viewBox="0 0 24 24" stroke="currentColor" '
             'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
             '<path d="M12 3.5l2.6 5.3 5.9.9-4.2 4.1 1 5.8-5.3-2.8-5.3 2.8 1-5.8'
             '-4.2-4.1 5.9-.9z"/></svg>')
I_EXT     = ic('<path d="M15 3h6v6"/><path d="M10 14 21 3"/>'
               '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>')
I_PLUS    = ic('<path d="M12 5v14M5 12h14"/>')
I_SEARCH  = ic('<circle cx="11" cy="11" r="7"/><path d="m21 21-4.1-4.1"/>')
I_CHEV    = ic('<path d="m6 9 6 6 6-6"/>')
I_ENV     = ic('<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>')
I_INBOX   = ic('<path d="M3 12h5l2 3h4l2-3h5"/><path d="M4 6h16v12H4z"/>')

# ---- feed favicons: initials + brand-ish color (via inline --fc) ---------
def fav(txt, color):
    return f'<span class="fav" style="--fc:{color}">{txt}</span>'

F_SW  = ('SW', '#E8622C'); F_HN = ('HN', '#FF6600'); F_V = ('V', '#5B21B6')
F_JE  = ('JE', '#DB2777'); F_BBC = ('B', '#BB1919'); F_CT = ('CT', '#F97316')
F_R   = ('R', '#EA6A16')

# ---- article list rows ---------------------------------------------------
# (feed_initials, feed_color), source, title, snippet, time, unread, starred, selected
ROWS = [
    (F_SW,  'Simon Willison', 'Running a local LLM with a single command',
     'The llm CLI now installs and runs Llama models with one line, no GPU config, no Docker.',
     '12m', True, False, True),
    (F_HN,  'Hacker News', 'Show HN: A calm, keyboard-first RSS reader',
     'I got tired of algorithmic feeds, so I built an inbox for the web — chronological, no ranking.',
     '34m', True, False, False),
    (F_V,   'The Verge', 'The browser wars are back, quietly',
     'Three rendering engines shipped major releases this year and almost nobody noticed.',
     '1h', True, False, False),
    (F_JE,  'Julia Evans', 'A few things I finally understand about DNS',
     'Resolvers, TTLs, and why your change still "isn’t live yet" an hour later.',
     '2h', True, True, False),
    (F_BBC, 'BBC News', 'Markets steady as inflation cools',
     'Investors welcomed softer price data as central banks signalled a pause on rate rises.',
     '3h', False, False, False),
    (F_HN,  'Hacker News', 'Ask HN: What’s your note-taking setup in 2026?',
     'Plain text, a personal wiki, or an app you slightly regret paying for? Let’s compare.',
     '5h', True, False, False),
    (F_CT,  'CSS-Tricks', 'Container queries are everywhere now',
     'The last holdout browser shipped support, so here’s how to actually restructure a layout.',
     '6h', False, False, False),
    (F_R,   'Reuters', 'Shipping routes shift after canal delays',
     'Carriers reroute around congestion, adding days to transit and pressure to freight rates.',
     '9h', False, True, False),
    (F_SW,  'Simon Willison', 'Notes on prompt caching',
     'Caching the shared prefix of a long prompt can cut both latency and cost dramatically.',
     '12h', False, False, False),
    (F_V,   'The Verge', 'A good keyboard is a quiet keyboard',
     'The loud mechanical trend is cooling in favour of softer, low-profile switches.',
     '1d', True, False, False),
    (F_BBC, 'BBC News', 'The town that switched off its streetlights',
     'One community’s experiment with darkness — and what its residents learned.',
     '1d', False, False, False),
    (F_R,   'Reuters', 'Central banks weigh their next move',
     'Policymakers signal caution as growth and employment data stay stubbornly mixed.',
     '2d', False, False, False),
]

def rows_html():
    out = []
    for (fi, fc), src, title, snip, t, unread, starred, sel in ROWS:
        cls = 'row'
        if unread: cls += ' unread'
        if sel: cls += ' selected'
        star = I_STAR if starred else ''
        starcls = ' starred' if starred else ''
        out.append(f'''    <li class="{cls}{starcls}" tabindex="0">
      <span class="dot" aria-hidden="true"></span>
      {fav(fi, fc)}
      <span class="src">{src}</span>
      <span class="title">{title}</span>
      <span class="snippet">{snip}</span>
      <span class="rowstar">{star}</span>
      <time>{t}</time>
    </li>''')
    return "\n".join(out)

# ---- sidebar -------------------------------------------------------------
def feed_row(name, initials, color, unread):
    cls = 'feed' + (' unread' if unread else '')
    badge = f'<span class="count">{unread}</span>' if unread else ''
    return (f'<a class="{cls}" href="#">{fav(initials, color)}'
            f'<span class="fname">{name}</span>{badge}</a>')

SIDEBAR = f'''  <aside class="side">
    <div class="side-head">
      <span class="logo">alo<span class="logo-dot">.</span></span>
      <button class="compose">{I_PLUS}<span>Subscribe</span></button>
    </div>
    <div class="search"><span class="si">{I_SEARCH}</span><input placeholder="Search all items" aria-label="Search"></div>
    <nav class="views">
      <a class="view active" href="#">{I_INBOX}<span>All items</span><span class="count">24</span></a>
      <a class="view" href="#">{I_ENV}<span>Unread</span><span class="count">24</span></a>
      <a class="view" href="#">{I_STAR}<span>Starred</span><span class="count">3</span></a>
    </nav>
    <div class="folders">
      <div class="folder">
        <div class="folder-head">{I_CHEV}<span>Tech</span><span class="count">11</span></div>
        {feed_row('Hacker News','HN','#FF6600',5)}
        {feed_row('The Verge','V','#5B21B6',3)}
        {feed_row('Simon Willison','SW','#E8622C',2)}
        {feed_row('CSS-Tricks','CT','#F97316',1)}
      </div>
      <div class="folder">
        <div class="folder-head">{I_CHEV}<span>News</span><span class="count">11</span></div>
        {feed_row('BBC News','B','#BB1919',7)}
        <a class="feed err" href="#">{fav('R','#EA6A16')}<span class="fname">Reuters</span><span class="edot" title="Last fetch failed"></span><span class="count">4</span></a>
      </div>
      <div class="folder">
        <div class="folder-head">{I_CHEV}<span>People</span><span class="count">2</span></div>
        {feed_row('Julia Evans','JE','#DB2777',2)}
      </div>
    </div>
  </aside>'''

# ---- reading pane --------------------------------------------------------
READER = f'''  <article class="reader">
    <div class="reader-actions">
      <button class="ract on">{I_STAR}<span>Starred</span></button>
      <button class="ract">{I_ENV}<span>Mark unread</span></button>
      <button class="ract">{I_EXT}<span>Open original</span></button>
    </div>
    <header class="reader-head">
      <div class="art-src">{fav('SW','#E8622C')}<span>Simon Willison’s Weblog</span></div>
      <h1 class="art-title">Running a local LLM with a single command</h1>
      <div class="art-meta">Simon Willison · 6 Jul 2026 · 4 min read</div>
    </header>
    <div class="art-body">
      <p>For a long time, running a language model on your own laptop meant a weekend of
      wrangling CUDA versions, quantisation formats, and a Python environment that broke
      the moment you looked at it. That era is quietly ending.</p>
      <p>The latest release of the <code>llm</code> command-line tool ships a plugin that
      downloads, quantises, and serves a small Llama model with a single command. There is
      no separate server to start and nothing to configure — <a href="#">read the release
      notes</a> for the full list of supported models.</p>
      <blockquote>The goal was never to compete with the hosted frontier models. It was to
      make the <em>smallest useful</em> model something you can run without thinking about it.</blockquote>
      <p>Installation is two lines, and the first run pulls the weights into a local cache:</p>
      <pre><code>llm install llm-llama
llm -m llama-local "Explain RSS to a five-year-old"</code></pre>
      <p>On an ordinary machine the first token comes back in about a second, and everything
      stays on the device. For a calm, offline-friendly reading workflow — summaries,
      tagging, the occasional translation — that turns out to be more than enough.</p>
      <h3>Where this is going</h3>
      <p>The interesting frontier is no longer raw capability; it is how invisibly these
      tools fold into software you already use. A feed reader that can quietly summarise a
      backlog while you sleep, without sending a single article to anyone’s server, is
      the kind of thing that only becomes possible once the model fits on the same box.</p>
    </div>
  </article>'''

def app(list_title="All items"):
    return f'''<div class="app">
{SIDEBAR}
  <section class="list">
    <header class="list-head">
      <h2>{list_title}</h2>
      <div class="list-tools">
        <button title="Refresh">{I_REFRESH}</button>
        <button title="Mark all read">{I_CHECK}</button>
        <span class="dsep"></span>
        <button class="density" title="Density">List</button>
      </div>
    </header>
    <ol class="rows">
{rows_html()}
    </ol>
  </section>
{READER}
</div>'''

# ==========================================================================
#  STYLES
# ==========================================================================
RESET = '''*{box-sizing:border-box}html,body{margin:0;height:100%}
body{-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
a{text-decoration:none;color:inherit}button{font:inherit;cursor:pointer;border:none;background:none;color:inherit}
input{font:inherit}ol,ul,nav{list-style:none;margin:0;padding:0}
.ic{width:16px;height:16px;flex:none}
.app{display:grid;grid-template-columns:var(--c1) var(--c2) 1fr;height:100vh;overflow:hidden}
.side,.list,.reader{min-height:0;overflow-y:auto}
.side{display:flex;flex-direction:column}
.list{display:flex;flex-direction:column}
.reader{padding:0}
.rows{flex:1}
.fav{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;
  border-radius:3px;background:var(--fc,#888);color:#fff;font-size:9px;font-weight:700;flex:none;letter-spacing:-.02em}
.row{display:grid;align-items:center;cursor:pointer}
.list-tools{display:flex;align-items:center;gap:2px}
.side-head{display:flex;align-items:center;justify-content:space-between}
.compose{display:inline-flex;align-items:center;gap:6px}
.view,.feed{display:flex;align-items:center;gap:8px}
.folder-head{display:flex;align-items:center;gap:6px}
.reader-actions{display:flex;gap:4px}.ract{display:inline-flex;align-items:center;gap:6px}
.art-src{display:flex;align-items:center;gap:8px}
:focus-visible{outline:2px solid var(--focus,#4c8bf5);outline-offset:-2px}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
@media (max-width:900px){.app{grid-template-columns:1fr}.side,.reader{display:none}}
'''

# ---- 1. CONSOLE : light monospace developer tool -------------------------
CONSOLE = RESET + '''
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap');
:root{--c1:250px;--c2:400px;--mono:"JetBrains Mono",ui-monospace,"SF Mono",Menlo,monospace;
  --bg:#f8f8f6;--panel:#fdfdfb;--ink:#242a2e;--dim:#8b9096;--line:#e2e1db;--acc:#0f766e;--focus:#0f766e}
body{background:var(--bg);color:var(--ink);font-family:var(--mono);font-size:12.5px;line-height:1.5}
.app{background:var(--bg)}
.side{background:var(--panel);border-right:1px solid var(--line);padding:14px 10px;gap:12px}
.side-head{padding:2px 6px 10px}
.logo{font-weight:700;font-size:16px;letter-spacing:-.03em}.logo-dot{color:var(--acc)}
.compose{font-size:11px;color:var(--acc);border:1px solid var(--acc);border-radius:4px;padding:4px 8px}
.compose .ic{width:13px;height:13px}
.search{display:flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:4px;padding:5px 8px;color:var(--dim)}
.search .ic{width:13px;height:13px}.search input{border:none;background:none;color:var(--ink);width:100%;outline:none;font-size:11.5px}
.views{display:flex;flex-direction:column;gap:1px}
.view{padding:5px 7px;border-radius:4px;color:var(--ink);font-size:11.5px}
.view .ic{width:14px;height:14px;color:var(--dim)}
.view .count{margin-left:auto;color:var(--dim);font-size:11px}
.view.active{background:var(--acc);color:#fff}.view.active .ic,.view.active .count{color:#cdeae6}
.folders{display:flex;flex-direction:column;gap:10px;margin-top:4px}
.folder-head{font-size:10px;text-transform:uppercase;letter-spacing:.12em;color:var(--dim);padding:2px 7px}
.folder-head .ic{width:12px;height:12px}.folder-head .count{margin-left:auto}
.feed{padding:4px 7px 4px 10px;border-radius:4px;color:var(--ink);font-size:11.5px}
.feed .fname{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.feed .count{margin-left:auto;color:var(--dim)}
.feed.unread .fname{font-weight:700}.feed.unread .count{color:var(--acc)}
.feed:hover{background:#eef0ee}
.edot{width:6px;height:6px;border-radius:50%;background:#c2410c;margin-left:auto}
.err .count{margin-left:6px}
.list{background:var(--bg);border-right:1px solid var(--line)}
.list-head{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);
  padding:12px 14px;display:flex;align-items:center;justify-content:space-between}
.list-head h2{margin:0;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.1em}
.list-tools button{color:var(--dim);padding:5px;border-radius:4px}.list-tools button:hover{color:var(--ink);background:#eef0ee}
.density{font-size:10px!important;text-transform:uppercase;letter-spacing:.1em;border:1px solid var(--line)!important;padding:3px 7px!important}
.dsep{width:1px;height:16px;background:var(--line);margin:0 4px}
.row{grid-template-columns:8px 16px 108px 1fr auto auto;gap:9px;padding:8px 14px;border-bottom:1px dotted var(--line);color:var(--dim)}
.row .dot{width:6px;height:6px;border-radius:50%;background:transparent}
.row .src{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px}
.row .title{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink)}
.row .snippet{display:none}
.row time{font-size:11px;color:var(--dim);font-variant-numeric:tabular-nums}
.row .rowstar{color:var(--acc)}.row .star{width:13px;height:13px;fill:var(--acc)}
.row.unread{color:var(--ink)}
.row.unread .dot{background:var(--acc)}
.row.unread .title{font-weight:700}
.row.unread .src{color:var(--ink)}
.row:hover{background:#eef0ee}
.row.selected{background:var(--acc);color:#fff}
.row.selected .title,.row.selected .src,.row.selected time{color:#fff}
.row.selected .dot{background:#fff}.row.selected .fav{outline:1px solid #ffffff77}
.row.selected .rowstar .star{fill:#fff;stroke:#fff}
.reader{background:var(--panel)}
.reader-actions{position:sticky;top:0;background:var(--panel);border-bottom:1px solid var(--line);padding:10px 20px}
.ract{font-size:11px;color:var(--dim);border:1px solid var(--line);border-radius:4px;padding:5px 9px}
.ract .ic{width:13px;height:13px}.ract:hover{color:var(--ink)}
.ract.on{color:var(--acc);border-color:var(--acc)}.ract.on .star{fill:var(--acc)}
.reader-head{padding:26px 40px 14px;max-width:760px}
.art-src{font-size:11px;color:var(--dim);margin-bottom:14px}
.art-title{font-size:22px;line-height:1.25;font-weight:700;letter-spacing:-.02em;margin:0 0 10px}
.art-meta{font-size:11px;color:var(--dim)}
.art-body{padding:8px 40px 60px;max-width:760px;font-size:13px;line-height:1.75}
.art-body p{margin:0 0 16px}.art-body a{color:var(--acc);border-bottom:1px solid var(--acc)}
.art-body h3{font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--dim);margin:26px 0 12px}
.art-body blockquote{margin:20px 0;padding:2px 0 2px 16px;border-left:2px solid var(--acc);color:var(--ink)}
.art-body code{background:#eef0ee;padding:1px 5px;border-radius:3px;font-size:12px}
.art-body pre{background:#20262b;color:#e6edf0;padding:14px 16px;border-radius:6px;overflow:auto;font-size:12px;line-height:1.6}
.art-body pre code{background:none;padding:0;color:inherit}
'''

# ---- 2. STUDIO : modern muted SaaS (Inter, one restrained indigo) --------
STUDIO = RESET + '''
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root{--c1:262px;--c2:404px;--sans:"Inter",system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  --bg:#f6f7f9;--panel:#fff;--ink:#1b1f24;--dim:#6b7280;--faint:#9aa1ab;--line:#eceef1;--acc:#4f46e5;--accbg:#eef0fe;--focus:#4f46e5}
body{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:13.5px;line-height:1.5}
.side{background:var(--bg);padding:16px 12px;gap:14px}
.side-head{padding:2px 6px 4px}
.logo{font-weight:700;font-size:17px;letter-spacing:-.02em}.logo-dot{color:var(--acc)}
.compose{font-size:12.5px;font-weight:600;color:#fff;background:var(--acc);border-radius:8px;padding:7px 12px;box-shadow:0 1px 2px rgba(79,70,229,.25)}
.compose .ic{width:15px;height:15px}
.search{display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 10px;color:var(--faint)}
.search input{border:none;background:none;color:var(--ink);width:100%;outline:none;font-size:13px}
.views{display:flex;flex-direction:column;gap:2px}
.view{padding:7px 10px;border-radius:8px;color:#33383f;font-weight:500;font-size:13.5px}
.view .ic{color:var(--faint)}.view .count{margin-left:auto;color:var(--faint);font-size:12px;font-weight:500}
.view.active{background:var(--accbg);color:var(--acc)}.view.active .ic{color:var(--acc)}.view.active .count{color:var(--acc)}
.folders{display:flex;flex-direction:column;gap:14px;margin-top:2px}
.folder-head{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--faint);padding:2px 10px}
.folder-head .ic{width:14px;height:14px}.folder-head .count{margin-left:auto}
.feed{padding:6px 10px;border-radius:8px;color:#40464e;font-size:13px}
.feed .fname{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.feed .count{margin-left:auto;color:var(--faint);font-size:12px}
.feed.unread{color:var(--ink);font-weight:600}.feed.unread .count{color:var(--acc)}
.feed:hover{background:#eef0f3}
.edot{width:6px;height:6px;border-radius:50%;background:#ef4444;margin-left:auto}.err .count{margin-left:7px}
.list{background:var(--panel);border-left:1px solid var(--line);border-right:1px solid var(--line)}
.list-head{position:sticky;top:0;background:rgba(255,255,255,.9);backdrop-filter:blur(6px);
  border-bottom:1px solid var(--line);padding:16px 20px;display:flex;align-items:center;justify-content:space-between}
.list-head h2{margin:0;font-size:15px;font-weight:700;letter-spacing:-.01em}
.list-tools button{color:var(--dim);padding:7px;border-radius:7px}.list-tools button:hover{background:#f2f3f5;color:var(--ink)}
.density{font-size:12px!important;font-weight:600;color:var(--dim)!important;padding:5px 10px!important;border:1px solid var(--line)!important;border-radius:7px!important}
.dsep{width:1px;height:18px;background:var(--line);margin:0 4px}
.row{grid-template-columns:8px 18px 1fr auto auto;gap:10px;padding:12px 20px 12px 16px;border-bottom:1px solid var(--line);position:relative}
.row .dot{width:7px;height:7px;border-radius:50%;background:transparent}
.row .src{grid-column:3;font-size:12px;color:var(--dim);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .title{grid-column:3;color:#2a2f36;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13.5px}
.row .snippet{grid-column:3;font-size:12.5px;color:var(--faint);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row time{grid-row:1;grid-column:4;font-size:12px;color:var(--faint);font-variant-numeric:tabular-nums;align-self:start;padding-top:1px}
.row .fav{grid-row:1;grid-column:2;align-self:start;margin-top:1px}
.row .dot{grid-row:1;grid-column:1;align-self:start;margin-top:6px}
.row .rowstar{grid-row:1;grid-column:5;align-self:start;color:#f5a623}.row .star{fill:#f5a623;width:15px;height:15px}
.row.unread .dot{background:var(--acc)}
.row.unread .title{font-weight:700;color:var(--ink)}
.row.unread .src{color:var(--acc)}
.row:hover{background:#fafbfc}
.row.selected{background:var(--accbg)}
.row.selected::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--acc)}
.reader{background:var(--panel)}
.reader-actions{position:sticky;top:0;background:rgba(255,255,255,.9);backdrop-filter:blur(6px);border-bottom:1px solid var(--line);padding:12px 24px}
.ract{font-size:12.5px;font-weight:500;color:var(--dim);border:1px solid var(--line);border-radius:8px;padding:7px 12px}
.ract:hover{background:#f7f8fa;color:var(--ink)}.ract.on{color:var(--acc);border-color:#c9c6f7;background:var(--accbg)}.ract.on .star{fill:var(--acc)}
.reader-head{padding:32px 48px 18px;max-width:720px}
.art-src{font-size:12.5px;color:var(--dim);font-weight:600;margin-bottom:16px}
.art-title{font-size:28px;line-height:1.22;font-weight:700;letter-spacing:-.02em;margin:0 0 12px}
.art-meta{font-size:12.5px;color:var(--faint)}
.art-body{padding:10px 48px 72px;max-width:720px;font-size:15px;line-height:1.72;color:#2b3138}
.art-body p{margin:0 0 18px}.art-body a{color:var(--acc);font-weight:500}
.art-body h3{font-size:18px;font-weight:700;letter-spacing:-.01em;margin:30px 0 12px;color:var(--ink)}
.art-body blockquote{margin:22px 0;padding:4px 0 4px 18px;border-left:3px solid var(--acc);color:#3b4149;font-size:16px}
.art-body code{background:#f1f2f4;padding:2px 6px;border-radius:5px;font-size:13.5px;font-family:ui-monospace,Menlo,monospace}
.art-body pre{background:#1b1f27;color:#e7ebf1;padding:16px 18px;border-radius:10px;overflow:auto;font-size:13px;line-height:1.6;font-family:ui-monospace,Menlo,monospace}
.art-body pre code{background:none;padding:0}
'''

# ---- 3. READER : warm editorial, reading-first, serif body ---------------
READER_S = RESET + '''
@import url('https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600;6..72,700&family=Inter:wght@400;500;600&display=swap');
:root{--c1:256px;--c2:388px;--sans:"Inter",system-ui,sans-serif;--serif:"Newsreader","Iowan Old Style",Georgia,serif;
  --bg:#faf7f1;--panel:#fefdfa;--ink:#242019;--dim:#8a8172;--faint:#a89e8d;--line:#e9e2d5;--acc:#1f5f5b;--accsoft:#e7efee;--focus:#1f5f5b}
body{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:13.5px;line-height:1.5}
.side{background:var(--bg);padding:16px 12px;gap:14px;border-right:1px solid var(--line)}
.side-head{padding:2px 6px 4px}
.logo{font-family:var(--serif);font-weight:600;font-size:20px;letter-spacing:-.01em}.logo-dot{color:var(--acc)}
.compose{font-size:12.5px;font-weight:500;color:#fff;background:var(--acc);border-radius:6px;padding:7px 12px}
.compose .ic{width:15px;height:15px}
.search{display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:8px 10px;color:var(--faint)}
.search input{border:none;background:none;color:var(--ink);width:100%;outline:none;font-size:13px}
.views{display:flex;flex-direction:column;gap:2px}
.view{padding:7px 10px;border-radius:6px;color:#463f34;font-weight:500}
.view .ic{color:var(--faint)}.view .count{margin-left:auto;color:var(--faint);font-size:12px}
.view.active{background:var(--accsoft);color:var(--acc)}.view.active .ic,.view.active .count{color:var(--acc)}
.folders{display:flex;flex-direction:column;gap:14px}
.folder-head{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--faint);padding:2px 10px}
.folder-head .ic{width:14px;height:14px}.folder-head .count{margin-left:auto}
.feed{padding:6px 10px;border-radius:6px;color:#4a4235;font-size:13px}
.feed .fname{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.feed .count{margin-left:auto;color:var(--faint);font-size:12px}
.feed.unread{color:var(--ink);font-weight:600}.feed.unread .count{color:var(--acc)}
.feed:hover{background:#f2ede3}
.edot{width:6px;height:6px;border-radius:50%;background:#b4531f;margin-left:auto}.err .count{margin-left:7px}
.list{background:var(--panel);border-right:1px solid var(--line)}
.list-head{position:sticky;top:0;background:var(--panel);border-bottom:1px solid var(--line);padding:16px 20px;display:flex;align-items:center;justify-content:space-between}
.list-head h2{margin:0;font-family:var(--serif);font-size:19px;font-weight:600;letter-spacing:-.01em}
.list-tools button{color:var(--dim);padding:7px;border-radius:6px}.list-tools button:hover{background:#f2ede3;color:var(--ink)}
.density{font-size:12px!important;color:var(--dim)!important;padding:5px 10px!important;border:1px solid var(--line)!important;border-radius:6px!important}
.dsep{width:1px;height:18px;background:var(--line);margin:0 4px}
.row{grid-template-columns:8px 18px 1fr auto;gap:10px;padding:14px 20px 14px 16px;border-bottom:1px solid var(--line);position:relative}
.row .dot{grid-row:1;grid-column:1;width:7px;height:7px;border-radius:50%;background:transparent;align-self:start;margin-top:6px}
.row .fav{grid-row:1;grid-column:2;align-self:start;margin-top:2px}
.row .src{grid-column:3;font-size:11.5px;color:var(--dim);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.row .title{grid-column:3;font-family:var(--serif);font-size:16px;line-height:1.3;color:#2c2820;margin:1px 0 2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .snippet{grid-column:3;font-size:12.5px;color:var(--faint);line-height:1.4;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical}
.row time{grid-row:1;grid-column:4;font-size:11.5px;color:var(--faint);align-self:start;font-variant-numeric:tabular-nums}
.row .rowstar{grid-row:2;grid-column:4;justify-self:end;color:var(--acc)}.row .star{fill:var(--acc);width:14px;height:14px}
.row.unread .dot{background:var(--acc)}
.row.unread .title{font-weight:700;color:var(--ink)}
.row.unread .src{color:var(--acc)}
.row:hover{background:#faf6ee}
.row.selected{background:var(--accsoft)}
.row.selected::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--acc)}
.reader{background:var(--panel)}
.reader-actions{position:sticky;top:0;background:var(--panel);border-bottom:1px solid var(--line);padding:12px 24px}
.ract{font-size:12.5px;color:var(--dim);border:1px solid var(--line);border-radius:6px;padding:7px 12px}
.ract:hover{background:#f7f2ea;color:var(--ink)}.ract.on{color:var(--acc);border-color:#bcd6d3;background:var(--accsoft)}.ract.on .star{fill:var(--acc)}
.reader-head{padding:40px 56px 20px;max-width:680px;border-bottom:1px solid var(--line)}
.art-src{font-size:12px;color:var(--dim);font-weight:600;text-transform:uppercase;letter-spacing:.06em;margin-bottom:18px}
.art-title{font-family:var(--serif);font-size:34px;line-height:1.16;font-weight:600;letter-spacing:-.015em;margin:0 0 14px}
.art-meta{font-size:13px;color:var(--faint);font-style:italic}
.art-body{padding:26px 56px 80px;max-width:680px;font-family:var(--serif);font-size:19px;line-height:1.68;color:#33302a}
.art-body p{margin:0 0 22px}
.art-body a{color:var(--acc);border-bottom:1px solid #9cc3bf}
.art-body h3{font-family:var(--serif);font-size:23px;font-weight:600;margin:34px 0 14px;color:var(--ink)}
.art-body blockquote{margin:26px 0;padding:6px 0 6px 24px;border-left:2px solid var(--acc);font-style:italic;color:#3f3b33;font-size:21px;line-height:1.5}
.art-body code{font-family:ui-monospace,Menlo,monospace;font-size:15px;background:#f0ebe0;padding:2px 6px;border-radius:4px}
.art-body pre{font-family:ui-monospace,Menlo,monospace;background:#2a2620;color:#efe9dc;padding:18px 20px;border-radius:8px;overflow:auto;font-size:14px;line-height:1.6}
.art-body pre code{background:none;padding:0;font-size:14px}
'''

# ---- 4. CLASSIC : authentic early-Gmail homage ---------------------------
CLASSIC = RESET + '''
:root{--c1:196px;--c2:376px;--sans:Arial,Helvetica,"Liberation Sans",sans-serif;
  --bg:#fff;--ink:#222;--dim:#777;--link:#15c;--line:#e8e8e8;--sel:#fdf6d8;--acc:#15c;--focus:#15c}
body{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:13px;line-height:1.4}
.app{border-top:2px solid #ded}
.side{background:#fafafa;padding:8px 0;gap:2px;border-right:1px solid var(--line)}
.side-head{padding:6px 12px 8px}
.logo{font-weight:700;font-size:18px;color:#c33;letter-spacing:-.02em}.logo-dot{color:var(--acc)}
.compose{font-size:12px;color:#222;background:#f1f1f1;border:1px solid #ccc;border-radius:2px;padding:4px 9px}
.compose .ic{width:13px;height:13px}
.search{display:flex;align-items:center;gap:5px;margin:0 8px 8px;border:1px solid #ccc;border-radius:2px;padding:4px 7px;color:#999;background:#fff}
.search .ic{width:13px;height:13px}.search input{border:none;outline:none;width:100%;font-size:12px;color:#222}
.views{display:flex;flex-direction:column}
.view{padding:3px 12px;color:#222;font-size:13px}.view .ic{width:14px;height:14px;color:#999}
.view .count{margin-left:auto;color:#777;font-size:12px}
.view.active{background:#e8eef7;font-weight:700}
.folders{display:flex;flex-direction:column;margin-top:8px}
.folder-head{padding:4px 12px 2px;font-size:11px;font-weight:700;color:#999;text-transform:uppercase;letter-spacing:.03em}
.folder-head .ic{width:11px;height:11px}.folder-head .count{margin-left:auto;font-weight:400}
.feed{padding:3px 12px 3px 16px;color:#333;font-size:13px}
.feed .fname{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.feed .count{margin-left:auto;color:#777;font-size:12px}
.feed.unread{font-weight:700;color:#000}.feed.unread .count{color:#000}
.feed:hover{background:#eee}
.edot{width:7px;height:7px;border-radius:50%;background:#d33;margin-left:auto}.err .count{margin-left:6px}
.list{background:#fff;border-right:1px solid var(--line)}
.list-head{position:sticky;top:0;background:#f5f5f5;border-bottom:1px solid #ddd;padding:6px 10px;display:flex;align-items:center;justify-content:space-between}
.list-head h2{margin:0;font-size:13px;font-weight:700}
.list-tools button{color:#555;padding:4px;border:1px solid transparent;border-radius:2px}.list-tools button:hover{background:#eee;border-color:#ccc}
.density{font-size:11px!important;padding:3px 7px!important;border:1px solid #ccc!important;border-radius:2px!important;background:#f1f1f1!important}
.dsep{width:1px;height:15px;background:#ccc;margin:0 3px}
.row{grid-template-columns:14px 15px 104px minmax(60px,auto) minmax(0,1fr) auto auto;gap:6px;padding:5px 10px;border-bottom:1px solid #f0f0f0;color:#555;line-height:1.3}
.row .dot{width:7px;height:7px;border-radius:50%;background:transparent}
.row .src{font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .title{color:#333;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:330px}
.row .title::after{content:" \\2014";color:#bbb}
.row .snippet{color:#888;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.row time{font-size:12px;color:#777;text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.row .rowstar{color:#e8a400}.row .star{fill:#f2b600;stroke:#d99a00;width:13px;height:13px}
.row.unread{color:#000}
.row.unread .dot{background:var(--acc)}
.row.unread .src{font-weight:700;color:#000}
.row.unread .title{font-weight:700;color:#000}
.row:hover{background:#f5f5f5}
.row.selected{background:var(--sel)}
.row.selected:hover{background:#faf0c8}
.reader{background:#fff}
.reader-actions{position:sticky;top:0;background:#f5f5f5;border-bottom:1px solid #ddd;padding:6px 16px}
.ract{font-size:12px;color:#333;border:1px solid #ccc;border-radius:2px;padding:4px 9px;background:#f1f1f1}
.ract .ic{width:13px;height:13px}.ract:hover{background:#eaeaea}
.ract.on{color:#a76a00;border-color:#d9b25a;background:#fdf6d8}.ract.on .star{fill:#f2b600}
.reader-head{padding:18px 28px 12px;border-bottom:1px solid #eee}
.art-src{font-size:12px;color:#777;margin-bottom:10px}
.art-title{font-size:20px;line-height:1.25;font-weight:700;margin:0 0 6px;color:#111}
.art-meta{font-size:12px;color:#777}
.art-body{padding:16px 28px 60px;max-width:660px;font-size:13.5px;line-height:1.62;color:#222}
.art-body p{margin:0 0 14px}.art-body a{color:var(--link);text-decoration:underline}
.art-body h3{font-size:15px;font-weight:700;margin:20px 0 10px}
.art-body blockquote{margin:14px 0;padding:8px 12px;background:#f7f7f7;border-left:3px solid #ccc;color:#333}
.art-body code{font-family:"Courier New",monospace;background:#f1f1f1;padding:1px 4px;border:1px solid #e2e2e2;font-size:12.5px}
.art-body pre{font-family:"Courier New",monospace;background:#f7f7f7;border:1px solid #e2e2e2;padding:12px;overflow:auto;font-size:12.5px;line-height:1.5}
.art-body pre code{background:none;border:none;padding:0}
'''

# ---- 5. NOCTURNE : calm low-contrast dark --------------------------------
NOCTURNE = RESET + '''
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
:root{--c1:258px;--c2:398px;--sans:"IBM Plex Sans",system-ui,sans-serif;
  --bg:#14161b;--panel:#181b21;--panel2:#1c2027;--ink:#d8dde4;--dim:#8b93a1;--faint:#6b7280;--line:#262a32;--acc:#7fb2a6;--accbg:#20302c;--focus:#7fb2a6}
body{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:13.5px;line-height:1.5}
.side{background:var(--bg);padding:16px 12px;gap:14px;border-right:1px solid var(--line)}
.side-head{padding:2px 6px 4px}
.logo{font-weight:700;font-size:17px;letter-spacing:-.01em;color:#eef1f5}.logo-dot{color:var(--acc)}
.compose{font-size:12.5px;font-weight:500;color:#0f1512;background:var(--acc);border-radius:7px;padding:7px 12px}
.compose .ic{width:15px;height:15px}
.search{display:flex;align-items:center;gap:8px;background:var(--panel2);border:1px solid var(--line);border-radius:7px;padding:8px 10px;color:var(--faint)}
.search input{border:none;background:none;color:var(--ink);width:100%;outline:none;font-size:13px}
.views{display:flex;flex-direction:column;gap:2px}
.view{padding:7px 10px;border-radius:7px;color:#c1c8d2;font-weight:500}
.view .ic{color:var(--faint)}.view .count{margin-left:auto;color:var(--faint);font-size:12px}
.view.active{background:var(--accbg);color:var(--acc)}.view.active .ic,.view.active .count{color:var(--acc)}
.folders{display:flex;flex-direction:column;gap:14px}
.folder-head{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.07em;color:var(--faint);padding:2px 10px}
.folder-head .ic{width:14px;height:14px}.folder-head .count{margin-left:auto}
.feed{padding:6px 10px;border-radius:7px;color:#aeb6c2;font-size:13px}
.feed .fname{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.feed .count{margin-left:auto;color:var(--faint);font-size:12px}
.feed.unread{color:#eef1f5;font-weight:600}.feed.unread .count{color:var(--acc)}
.feed:hover{background:var(--panel2)}
.edot{width:6px;height:6px;border-radius:50%;background:#d98a6a;margin-left:auto}.err .count{margin-left:7px}
.list{background:var(--panel);border-right:1px solid var(--line)}
.list-head{position:sticky;top:0;background:var(--panel);border-bottom:1px solid var(--line);padding:16px 20px;display:flex;align-items:center;justify-content:space-between}
.list-head h2{margin:0;font-size:15px;font-weight:600;color:#eef1f5}
.list-tools button{color:var(--dim);padding:7px;border-radius:7px}.list-tools button:hover{background:var(--panel2);color:var(--ink)}
.density{font-size:12px!important;color:var(--dim)!important;padding:5px 10px!important;border:1px solid var(--line)!important;border-radius:7px!important}
.dsep{width:1px;height:18px;background:var(--line);margin:0 4px}
.row{grid-template-columns:8px 18px 1fr auto auto;gap:10px;padding:12px 20px 12px 16px;border-bottom:1px solid var(--line);position:relative}
.row .dot{grid-row:1;grid-column:1;width:7px;height:7px;border-radius:50%;background:transparent;align-self:start;margin-top:6px}
.row .fav{grid-row:1;grid-column:2;align-self:start;margin-top:1px}
.row .src{grid-column:3;font-size:12px;color:var(--dim);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .title{grid-column:3;color:#b8c0cc;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13.5px}
.row .snippet{grid-column:3;font-size:12.5px;color:var(--faint);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row time{grid-row:1;grid-column:4;font-size:12px;color:var(--faint);align-self:start;font-variant-numeric:tabular-nums}
.row .rowstar{grid-row:1;grid-column:5;align-self:start;color:#e0b877}.row .star{fill:#e0b877;width:15px;height:15px}
.row.unread .dot{background:var(--acc)}
.row.unread .title{font-weight:600;color:#eef1f5}
.row.unread .src{color:var(--acc)}
.row:hover{background:var(--panel2)}
.row.selected{background:var(--accbg)}
.row.selected::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--acc)}
.reader{background:var(--panel)}
.reader-actions{position:sticky;top:0;background:var(--panel);border-bottom:1px solid var(--line);padding:12px 24px}
.ract{font-size:12.5px;color:var(--dim);border:1px solid var(--line);border-radius:7px;padding:7px 12px}
.ract:hover{background:var(--panel2);color:var(--ink)}.ract.on{color:var(--acc);border-color:#37564e;background:var(--accbg)}.ract.on .star{fill:var(--acc)}
.reader-head{padding:34px 48px 18px;max-width:700px}
.art-src{font-size:12.5px;color:var(--dim);font-weight:600;margin-bottom:16px}
.art-title{font-size:27px;line-height:1.24;font-weight:600;letter-spacing:-.015em;margin:0 0 12px;color:#f2f4f7}
.art-meta{font-size:12.5px;color:var(--faint)}
.art-body{padding:12px 48px 72px;max-width:700px;font-size:15px;line-height:1.74;color:#c4ccd6}
.art-body p{margin:0 0 18px}.art-body a{color:var(--acc);border-bottom:1px solid #4a6a62}
.art-body h3{font-size:18px;font-weight:600;margin:30px 0 12px;color:#eef1f5}
.art-body blockquote{margin:22px 0;padding:4px 0 4px 18px;border-left:3px solid var(--acc);color:#d2d9e2;font-size:16px}
.art-body code{background:#22272f;padding:2px 6px;border-radius:5px;font-size:13.5px;font-family:ui-monospace,Menlo,monospace}
.art-body pre{background:#0f1216;color:#cbd3dd;padding:16px 18px;border-radius:9px;overflow:auto;font-size:13px;line-height:1.6;font-family:ui-monospace,Menlo,monospace;border:1px solid var(--line)}
.art-body pre code{background:none;padding:0}
'''

STYLES = [
    ('console',  'Console — alo',   CONSOLE,  'All items'),
    ('studio',   'Studio — alo',    STUDIO,   'All items'),
    ('reader',   'Reader — alo',    READER_S, 'All items'),
    ('classic',  'Classic — alo',   CLASSIC,  'All items'),
    ('nocturne', 'Nocturne — alo',  NOCTURNE, 'All items'),
]

PAGE = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%TITLE%%</title>
<style>
%%CSS%%
</style>
</head>
<body>
%%BODY%%
</body>
</html>
'''

for slug, title, css, ltitle in STYLES:
    html = (PAGE.replace('%%TITLE%%', title)
                .replace('%%CSS%%', css)
                .replace('%%BODY%%', app(ltitle)))
    with open(os.path.join(HERE, slug + '.html'), 'w') as f:
        f.write(html)
    print('wrote', slug + '.html')

# ---- index / chooser -----------------------------------------------------
CARDS = [
    ('aligned',  'Aligned — the chosen system',  'Studio (light) + Nocturne (dark), unified',
     'The direction we are building for WP-09: Studio in light mode, Nocturne in dark, unified on Inter and one calm teal-green accent. Toggle light/dark bottom-right (or add ?theme=dark to the URL).'),
    ('console',  'Console',  'Light monospace developer tool',
     'JetBrains Mono throughout, teal accent, TUI-style inverse selection and keycap-tight rows. Reads as an instrument, not a magazine.'),
    ('studio',   'Studio',   'Modern muted product UI',
     'Inter, neutral grays, one restrained indigo. Soft radii, an accent bar on the selected row. The calm, safe, ships-anywhere choice.'),
    ('reader',   'Reader',   'Warm editorial, reading-first',
     'Serif (Newsreader) reserved for the reading pane, sans chrome around it, deep-teal accent on warm paper. Optimised for the article itself.'),
    ('classic',  'Classic',  'Authentic early-Gmail homage',
     'Arial 13px, maximum density, bold-unread label rail, pale-yellow selected row, blue links. The most literal reading of DESIGN.md §1.7.'),
    ('nocturne', 'Nocturne', 'Calm low-contrast dark',
     'IBM Plex Sans on soft slate (not black), a gentle desaturated green accent. Built for night reading — the opposite of harsh neon-on-black.'),
]
INDEX_CSS = '''*{box-sizing:border-box;margin:0}body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
background:#0f1115;color:#e7eaef;padding:56px 24px;line-height:1.5}
.wrap{max-width:920px;margin:0 auto}h1{font-size:26px;letter-spacing:-.02em;font-weight:700}
.sub{color:#98a0ac;margin:8px 0 4px;max-width:640px}.note{color:#6b7280;font-size:13px;margin-bottom:36px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:680px){.grid{grid-template-columns:1fr}}
a.card{display:block;background:#181b21;border:1px solid #262a32;border-radius:12px;padding:20px 22px;color:inherit;
transition:border-color .15s,transform .15s}a.card:hover{border-color:#4f7a70;transform:translateY(-2px)}
.card h2{font-size:17px;margin-bottom:2px;display:flex;align-items:center;gap:10px}
.tag{font-size:11px;color:#8b93a1;font-weight:500}.card p{color:#98a0ac;font-size:13.5px;margin-top:8px}
.open{margin-top:14px;font-size:13px;color:#7fb2a6;font-weight:600}
.sw{width:14px;height:14px;border-radius:4px;display:inline-block}
'''
def sw(colors):
    return ''.join(f'<span class="sw" style="background:{c}"></span>' for c in colors)
SWATCHES = {
 'aligned':['#f6f7f9','#0e7c6d','#14161b'],
 'console':['#f8f8f6','#0f766e','#242a2e'],'studio':['#f6f7f9','#4f46e5','#1b1f24'],
 'reader':['#faf7f1','#1f5f5b','#242019'],'classic':['#ffffff','#1155cc','#fdf6d8'],
 'nocturne':['#14161b','#7fb2a6','#d8dde4'],
}
cards_html = "\n".join(
    f'''<a class="card" href="{slug}.html">
      <h2>{name} <span style="display:inline-flex;gap:4px">{sw(SWATCHES[slug])}</span></h2>
      <div class="tag">{tag}</div>
      <p>{desc}</p>
      <div class="open">Open mockup →</div>
    </a>''' for slug, name, tag, desc in CARDS)
index = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>alo-reader — style directions</title><style>{INDEX_CSS}</style></head>
<body><div class="wrap">
<h1>alo-reader — five style directions</h1>
<p class="sub">Same three-pane layout and the same content in all five, so the only thing
that changes is the visual direction. The shape is fixed by DESIGN.md §1.7; these pin
down the type, palette, and density for WP-09.</p>
<p class="note">Open each full-screen to judge it. Best viewed at desktop width.</p>
<div class="grid">
{cards_html}
</div></div></body></html>'''
with open(os.path.join(HERE, 'index.html'), 'w') as f:
    f.write(index)
print('wrote index.html')

# ==========================================================================
#  ALIGNED : the chosen system — Studio (light) + Nocturne (dark) unified on
#  Inter + one teal-green accent, driven entirely by CSS custom properties.
#  This is the source of truth translated into web/src tokens for WP-09.
# ==========================================================================
LIGHTVARS = '''--c1:262px;--c2:404px;
--sans:"Inter",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
--mono:ui-monospace,"SF Mono",Menlo,monospace;
--bg:#f6f7f9;--panel:#ffffff;--panel2:#fafbfc;--hover:#f2f3f5;
--ink:#1b1f24;--ink2:#2b3138;--dim:#6b7280;--faint:#9aa1ab;
--line:#eceef1;--line2:#e7e9ec;
--acc:#0e7c6d;--acc-ink:#ffffff;--acc-weak:#e7f2ef;--acc-border:#bcdcd5;
--star:#d99a12;--err:#ef4444;
--code-bg:#1b1f27;--code-ink:#e7ebf1;--icode:#eef1f0;
--shadow:0 1px 2px rgba(14,124,109,.22);'''

DARKVARS = '''--bg:#14161b;--panel:#181b21;--panel2:#1c2027;--hover:#1c2027;
--ink:#eef1f5;--ink2:#c4ccd6;--dim:#8b93a1;--faint:#6b7280;
--line:#262a32;--line2:#262a32;
--acc:#7fb2a6;--acc-ink:#0f1512;--acc-weak:#20302c;--acc-border:#37564e;
--star:#e0b877;--err:#d98a6a;
--code-bg:#0f1216;--code-ink:#cbd3dd;--icode:#22272f;
--shadow:none;'''

UNIFIED_COMPONENTS = '''
body{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:13.5px;line-height:1.5}
.side{background:var(--bg);padding:16px 12px;gap:14px;border-right:1px solid var(--line)}
.side-head{padding:2px 6px 4px}
.logo{font-weight:700;font-size:17px;letter-spacing:-.02em;color:var(--ink)}.logo-dot{color:var(--acc)}
.compose{font-size:12.5px;font-weight:600;color:var(--acc-ink);background:var(--acc);border-radius:8px;padding:7px 12px;box-shadow:var(--shadow)}
.compose .ic{width:15px;height:15px}
.search{display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--line2);border-radius:8px;padding:8px 10px;color:var(--faint)}
.search input{border:none;background:none;color:var(--ink);width:100%;outline:none;font-size:13px}
.views{display:flex;flex-direction:column;gap:2px}
.view{padding:7px 10px;border-radius:8px;color:var(--ink2);font-weight:500;font-size:13.5px}
.view .ic{color:var(--faint)}.view .count{margin-left:auto;color:var(--faint);font-size:12px;font-weight:500}
.view.active{background:var(--acc-weak);color:var(--acc)}.view.active .ic,.view.active .count{color:var(--acc)}
.folders{display:flex;flex-direction:column;gap:14px;margin-top:2px}
.folder-head{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--faint);padding:2px 10px}
.folder-head .ic{width:14px;height:14px}.folder-head .count{margin-left:auto}
.feed{padding:6px 10px;border-radius:8px;color:var(--ink2);font-size:13px}
.feed .fname{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.feed .count{margin-left:auto;color:var(--faint);font-size:12px}
.feed.unread{color:var(--ink);font-weight:600}.feed.unread .count{color:var(--acc)}
.feed:hover{background:var(--hover)}
.edot{width:6px;height:6px;border-radius:50%;background:var(--err);margin-left:auto}.err .count{margin-left:7px}
.list{background:var(--panel);border-right:1px solid var(--line)}
.list-head{position:sticky;top:0;background:var(--panel);border-bottom:1px solid var(--line);padding:16px 20px;display:flex;align-items:center;justify-content:space-between;z-index:2}
.list-head h2{margin:0;font-size:15px;font-weight:700;letter-spacing:-.01em;color:var(--ink)}
.list-tools button{color:var(--dim);padding:7px;border-radius:7px}.list-tools button:hover{background:var(--hover);color:var(--ink)}
.density{font-size:12px!important;font-weight:600;color:var(--dim)!important;padding:5px 10px!important;border:1px solid var(--line2)!important;border-radius:7px!important}
.dsep{width:1px;height:18px;background:var(--line2);margin:0 4px}
.row{grid-template-columns:8px 18px 1fr auto auto;gap:10px;padding:12px 20px 12px 16px;border-bottom:1px solid var(--line);position:relative}
.row .dot{grid-row:1;grid-column:1;width:7px;height:7px;border-radius:50%;background:transparent;align-self:start;margin-top:6px}
.row .fav{grid-row:1;grid-column:2;align-self:start;margin-top:1px}
.row .src{grid-column:3;font-size:12px;color:var(--dim);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .title{grid-column:3;color:var(--ink2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13.5px}
.row .snippet{grid-column:3;font-size:12.5px;color:var(--faint);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row time{grid-row:1;grid-column:4;font-size:12px;color:var(--faint);font-variant-numeric:tabular-nums;align-self:start;padding-top:1px}
.row .rowstar{grid-row:1;grid-column:5;align-self:start;color:var(--star)}.row .star{fill:var(--star);width:15px;height:15px}
.row.unread .dot{background:var(--acc)}
.row.unread .title{font-weight:700;color:var(--ink)}
.row.unread .src{color:var(--acc)}
.row:hover{background:var(--panel2)}
.row.selected{background:var(--acc-weak)}
.row.selected::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--acc)}
.reader{background:var(--panel)}
.reader-actions{position:sticky;top:0;background:var(--panel);border-bottom:1px solid var(--line);padding:12px 24px;z-index:2}
.ract{font-size:12.5px;font-weight:500;color:var(--dim);border:1px solid var(--line2);border-radius:8px;padding:7px 12px}
.ract:hover{background:var(--panel2);color:var(--ink)}.ract.on{color:var(--acc);border-color:var(--acc-border);background:var(--acc-weak)}.ract.on .star{fill:var(--acc)}
.reader-head{padding:32px 48px 18px;max-width:720px}
.art-src{font-size:12.5px;color:var(--dim);font-weight:600;margin-bottom:16px}
.art-title{font-size:28px;line-height:1.22;font-weight:700;letter-spacing:-.02em;margin:0 0 12px;color:var(--ink)}
.art-meta{font-size:12.5px;color:var(--faint)}
.art-body{padding:10px 48px 90px;max-width:720px;font-size:15px;line-height:1.72;color:var(--ink2)}
.art-body p{margin:0 0 18px}.art-body a{color:var(--acc);font-weight:500;border-bottom:1px solid var(--acc-border)}
.art-body h3{font-size:18px;font-weight:700;letter-spacing:-.01em;margin:30px 0 12px;color:var(--ink)}
.art-body blockquote{margin:22px 0;padding:4px 0 4px 18px;border-left:3px solid var(--acc);color:var(--ink2);font-size:16px}
.art-body code{background:var(--icode);padding:2px 6px;border-radius:5px;font-size:13.5px;font-family:var(--mono)}
.art-body pre{background:var(--code-bg);color:var(--code-ink);padding:16px 18px;border-radius:10px;overflow:auto;font-size:13px;line-height:1.6;font-family:var(--mono)}
.art-body pre code{background:none;padding:0}
.themebar{position:fixed;bottom:16px;right:16px;display:flex;gap:2px;background:var(--panel);border:1px solid var(--line2);border-radius:10px;padding:3px;box-shadow:0 6px 20px rgba(0,0,0,.16);z-index:50}
.themebar button{display:inline-flex;padding:7px;border-radius:7px;color:var(--faint)}
.themebar button:hover{color:var(--ink);background:var(--hover)}
.themebar button.on{color:var(--acc);background:var(--acc-weak)}
.themebar .ic{width:16px;height:16px}
'''

UNIFIED = (RESET
    + "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');\n"
    + ':root{' + LIGHTVARS + '}\n'
    + ':root[data-theme="dark"]{' + DARKVARS + '}\n'
    + '@media (prefers-color-scheme:dark){:root:not([data-theme]){' + DARKVARS + '}}\n'
    + UNIFIED_COMPONENTS)

SUN = ic('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4'
         'M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>')
MOON = ic('<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/>')
MON = ic('<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>')
TOGGLE = ('<div class="themebar" role="group" aria-label="Theme">'
          '<button data-set="light" title="Light" aria-label="Light theme">' + SUN + '</button>'
          '<button data-set="dark" title="Dark" aria-label="Dark theme">' + MOON + '</button>'
          '<button data-set="system" title="Match system" aria-label="Match system theme">' + MON + '</button>'
          '</div>')
SCRIPT = ("<script>(function(){var r=document.documentElement;"
          "function mark(m){document.querySelectorAll('.themebar button').forEach("
          "function(b){b.classList.toggle('on',b.dataset.set===m);});}"
          "function apply(m){if(m==='system'){r.removeAttribute('data-theme');}"
          "else{r.setAttribute('data-theme',m);}try{localStorage.setItem('alo-theme',m);}"
          "catch(e){}mark(m);}var q=null;try{q=new URLSearchParams(location.search).get('theme');}"
          "catch(e){}var s=q;if(!s){try{s=localStorage.getItem('alo-theme');}catch(e){}}"
          "if(!s){s='system';}apply(s);document.querySelectorAll('.themebar button').forEach("
          "function(b){b.addEventListener('click',function(){apply(b.dataset.set);});});})();</script>")

aligned_html = (PAGE.replace('%%TITLE%%', 'Aligned — alo')
                    .replace('%%CSS%%', UNIFIED)
                    .replace('%%BODY%%', app('All items') + '\n' + TOGGLE + '\n' + SCRIPT))
with open(os.path.join(HERE, 'aligned.html'), 'w') as f:
    f.write(aligned_html)
print('wrote aligned.html')
