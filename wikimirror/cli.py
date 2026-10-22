"""Command line interface."""
import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .db import Mirror
from .dump import download, dump_url, import_dump
from .update import TooOld, api_url, apply_updates, http_api


def home_dir(arg=None):
    return Path(arg or os.environ.get("WIKIMIRROR_HOME") or Path.home() / ".wikimirror")


def open_mirror(args):
    h = home_dir(args.home)
    h.mkdir(parents=True, exist_ok=True)
    return Mirror(h / "mirror.db"), h


def _bar(done, total):
    if total:
        sys.stderr.write(f"\r{done / 1e6:.0f}/{total / 1e6:.0f} MB")
    else:
        sys.stderr.write(f"\r{done / 1e6:.0f} MB")
    sys.stderr.flush()


def cmd_download(args, out):
    m, h = open_mirror(args)
    url = args.url or dump_url(args.wiki)
    dest = str(h / os.path.basename(url))
    if not (args.reuse and os.path.exists(dest)):
        print(f"Downloading {url}", file=out)
        download(url, dest, progress=_bar)
        sys.stderr.write("\n")
    print("Importing…", file=out)
    n = import_dump(m, dest, progress=lambda n: sys.stderr.write(f"\r{n} pages"))
    m.set_meta("wiki", args.wiki)
    ts = m.max_timestamp()
    if ts:
        m.set_meta("last_sync", ts)
    m.optimize()
    if not args.keep:
        os.remove(dest)
    print(f"Imported {n} pages; mirror has {m.count()}.", file=out)


def cmd_update(args, out, api=None):
    m, _ = open_mirror(args)
    wiki = m.get_meta("wiki", args.wiki)
    api = api or (lambda p: http_api(api_url(wiki), p))
    try:
        s = apply_updates(m, api)
    except TooOld as e:
        print(f"Cannot update incrementally: {e}. Run `wikimirror download`.", file=out)
        return 1
    print("Update done: {added} added, {updated} updated, {removed} removed, "
          "{unchanged} unchanged.".format(**s), file=out)
    return 0


def cmd_search(args, out):
    m, _ = open_mirror(args)
    rows = m.search(" ".join(args.query), args.limit)
    if not rows:
        print("No results.", file=out)
    for r in rows:
        print(f"{r['title']}\n    {' '.join(r['snippet'].split())}", file=out)


def cmd_show(args, out):
    m, _ = open_mirror(args)
    title = " ".join(args.title)
    p = m.get_page(title)
    if not p:
        print(f"No page '{title}'. Similar: " +
              ", ".join(r["title"] for r in m.title_search(title, 5)), file=out)
        return 1
    print(f"# {p['title']}  (rev {p['revid']}, {p['timestamp']})\n", file=out)
    print(p["text"], file=out)
    for n in m.list_notes(p["title"]):
        print(f"\n[note #{n['id']} {n['created']}] {n['body']}", file=out)


def cmd_random(args, out):
    m, _ = open_mirror(args)
    p = m.random_page()
    print(p["title"] if p else "Mirror is empty.", file=out)


def cmd_stats(args, out):
    m, h = open_mirror(args)
    print(f"Pages: {m.count()}\nNotes: {len(m.list_notes())}\n"
          f"Last sync: {m.get_meta('last_sync', 'never')}\nDatabase: {m.path}", file=out)


def cmd_note(args, out):
    m, _ = open_mirror(args)
    if args.action == "add":
        if not args.title or not args.text:
            print("usage: note add TITLE TEXT", file=out)
            return 2
        p = m.get_page(args.title)
        nid = m.add_note(p["title"] if p else args.title, " ".join(args.text))
        print(f"Added note #{nid}", file=out)
    elif args.action == "list":
        for n in m.list_notes(args.title):
            print(f"#{n['id']} [{n['title']}] {n['body']}", file=out)
    else:
        if not args.title or not args.title.isdigit():
            print("usage: note delete ID", file=out)
            return 2
        ok = m.delete_note(int(args.title))
        print("Deleted." if ok else "No such note.", file=out)
        return 0 if ok else 1


def build_parser():
    p = argparse.ArgumentParser(prog="wikimirror", description=__doc__)
    p.add_argument("--home", help="data directory (default ~/.wikimirror or $WIKIMIRROR_HOME)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download", help="download & import the full dump")
    d.add_argument("--wiki", default="simplewiki", help="dump name (default simplewiki)")
    d.add_argument("--url", help="explicit dump URL")
    d.add_argument("--keep", action="store_true", help="keep the downloaded file")
    d.add_argument("--reuse", action="store_true", help="reuse an existing downloaded file")
    d.set_defaults(fn=cmd_download)
    u = sub.add_parser("update", help="fetch only pages changed since last sync")
    u.add_argument("--wiki", default="simplewiki")
    u.set_defaults(fn=cmd_update)
    s = sub.add_parser("search", help="full-text search")
    s.add_argument("query", nargs="+")
    s.add_argument("-n", "--limit", type=int, default=10)
    s.set_defaults(fn=cmd_search)
    sh = sub.add_parser("show", help="show a page and its notes")
    sh.add_argument("title", nargs="+")
    sh.set_defaults(fn=cmd_show)
    sub.add_parser("random", help="random page title").set_defaults(fn=cmd_random)
    sub.add_parser("stats", help="mirror statistics").set_defaults(fn=cmd_stats)
    n = sub.add_parser("note", help="note-taking: add | list | delete")
    n.add_argument("action", choices=["add", "list", "delete"])
    n.add_argument("title", nargs="?", help="page title (add/list) or note id (delete)")
    n.add_argument("text", nargs="*", help="note text")
    n.set_defaults(fn=cmd_note)
    return p


def main(argv=None, out=None):
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    return args.fn(args, out) or 0


if __name__ == "__main__":
    sys.exit(main())
