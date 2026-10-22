# wikipedia-mirror
Locally download, search, annotate and incrementally update a Wikipedia mirror.

Defaults to the lightweight **Simple English Wikipedia** (`simplewiki`) article
dump from <https://dumps.wikimedia.org/>. Pure Python stdlib; storage is a single
SQLite file with an FTS5 (BM25-ranked, stemmed) full-text index.

```
pip install .
wikimirror download            # resumable download + streaming import
wikimirror search "solar system"
wikimirror show "Moon"         # page text plus your notes
wikimirror note add Moon "check orbit period"
wikimirror note list [TITLE]   # / note delete ID
wikimirror update              # diff-update: only pages changed since last sync
wikimirror stats | random
```

`update` replays the wiki's recent-changes feed since the last sync, fetches only
changed pages (50 per request), and applies edits, creations and deletions.
If the mirror is older than ~28 days (feed retention) it asks for a fresh
`download`. Use `--home DIR` or `$WIKIMIRROR_HOME` to choose the data directory
(default `~/.wikimirror`); `--wiki enwiki` selects another dump (very large).

Tests: `python -m unittest discover tests`
