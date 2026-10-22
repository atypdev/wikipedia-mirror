"""Diff-checking updater: replays recent changes from the MediaWiki API."""
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

UA = "wikipedia-mirror/0.1 (https://github.com/atypdev/wikipedia-mirror)"
RC_RETENTION_DAYS = 28  # recentchanges is only kept ~30 days


class TooOld(Exception):
    """Mirror is older than the change feed; a full re-download is needed."""


def api_url(wiki="simplewiki"):
    host = wiki[:-4] + ".wikipedia.org" if wiki.endswith("wiki") else wiki
    return f"https://{host}/w/api.php"


def http_api(url, params, retries=4):
    q = urllib.parse.urlencode(dict(params, format="json", formatversion="2"))
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url + "?" + q, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def _parse(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def changed_titles(api, since, now=None):
    """Titles touched since `since` (ISO). Returns a set; raises TooOld."""
    now = now or datetime.now(timezone.utc)
    if now - _parse(since) > timedelta(days=RC_RETENTION_DAYS):
        raise TooOld(f"last sync {since} is older than {RC_RETENTION_DAYS} days")
    titles = set()
    params = {"action": "query", "list": "recentchanges", "rcdir": "newer",
              "rcstart": since, "rcnamespace": 0, "rclimit": 500,
              "rctype": "edit|new|log", "rcprop": "title|loginfo"}
    while True:
        data = api(params)
        for rc in data.get("query", {}).get("recentchanges", []):
            titles.add(rc["title"])
            target = (rc.get("logparams") or {}).get("target_title")
            if target:
                titles.add(target)
        cont = data.get("continue")
        if not cont:
            return titles
        params = dict(params, **cont)


def fetch_pages(api, titles):
    """Yield (title, page-dict-or-None) fetching current wikitext in batches of 50."""
    titles = sorted(titles)
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        data = api({"action": "query", "prop": "revisions", "titles": "|".join(batch),
                    "rvprop": "ids|timestamp|content", "rvslots": "main"})
        q = data.get("query", {})
        seen = {}
        for p in q.get("pages", []):
            seen[p["title"]] = p
        for t in batch:
            yield t, seen.get(t)


def apply_updates(mirror, api, since=None, now=None, progress=None):
    """Sync the mirror. Returns dict(added, updated, removed, unchanged)."""
    since = since or mirror.get_meta("last_sync") or mirror.max_timestamp()
    if not since:
        raise TooOld("mirror is empty; run `wikimirror download` first")
    start = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    titles = changed_titles(api, since, now)
    stats = dict(added=0, updated=0, removed=0, unchanged=0)
    for title, page in fetch_pages(api, titles):
        rev = (page or {}).get("revisions") or []
        text = ""
        if rev:
            text = (rev[0].get("slots", {}).get("main", {}).get("content")
                    or rev[0].get("content") or "")
        if not page or page.get("missing") or not rev \
                or text.lstrip()[:9].upper().startswith("#REDIRECT"):
            stats["removed"] += mirror.delete_page(title)
            continue
        existed = mirror.get_page(title) is not None
        if mirror.upsert_page(title, rev[0].get("revid"), rev[0].get("timestamp"), text):
            stats["updated" if existed else "added"] += 1
        else:
            stats["unchanged"] += 1
        if progress:
            progress(title)
    mirror.commit()
    # start is taken before querying, so concurrent edits are replayed next time
    mirror.set_meta("last_sync", start)
    return stats
