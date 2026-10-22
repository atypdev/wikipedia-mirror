"""Download (resumable) and stream-import a Wikimedia XML dump."""
import bz2
import os
import urllib.request
import xml.etree.ElementTree as ET

BASE = "https://dumps.wikimedia.org"
UA = "wikipedia-mirror/0.1 (https://github.com/atypdev/wikipedia-mirror)"


def dump_url(wiki="simplewiki"):
    return f"{BASE}/{wiki}/latest/{wiki}-latest-pages-articles.xml.bz2"


def download(url, dest, progress=None, opener=urllib.request.urlopen):
    """Download url to dest, resuming a partial '.part' file. Returns dest."""
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    headers = {"User-Agent": UA}
    if have:
        headers["Range"] = f"bytes={have}-"
    with opener(urllib.request.Request(url, headers=headers), timeout=60) as r:
        status = getattr(r, "status", 200)
        mode = "ab" if have and status == 206 else "wb"
        if mode == "wb":
            have = 0
        total = int(r.headers.get("Content-Length") or 0) + have
        with open(part, mode) as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                have += len(chunk)
                if progress:
                    progress(have, total)
    os.replace(part, dest)
    return dest


def _local(el):
    return el.tag.rsplit("}", 1)[-1]


def iter_pages(fileobj):
    """Yield (title, revid, timestamp, text) for non-redirect main-namespace pages."""
    for _, el in ET.iterparse(fileobj, events=("end",)):
        if _local(el) != "page":
            continue
        title = ns = None
        redirect = False
        revid = ts = None
        text = ""
        for c in el:
            t = _local(c)
            if t == "title":
                title = c.text
            elif t == "ns":
                ns = c.text
            elif t == "redirect":
                redirect = True
            elif t == "revision":
                for r in c:
                    rt = _local(r)
                    if rt == "id" and r.text:
                        revid = int(r.text)
                    elif rt == "timestamp":
                        ts = r.text
                    elif rt == "text":
                        text = r.text or ""
        if ns == "0" and title and not redirect \
                and not text.lstrip()[:9].upper().startswith("#REDIRECT"):
            yield title, revid, ts, text
        el.clear()


def import_dump(mirror, path, progress=None, batch=2000):
    """Import a (bz2 or plain) XML dump into the mirror. Returns page count."""
    opener = bz2.open if str(path).endswith(".bz2") else open
    n = 0
    with opener(path, "rb") as f:
        for title, revid, ts, text in iter_pages(f):
            mirror.upsert_page(title, revid, ts, text)
            n += 1
            if n % batch == 0:
                mirror.commit()
                if progress:
                    progress(n)
    mirror.commit()
    return n
