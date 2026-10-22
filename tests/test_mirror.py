import io
import tempfile
import unittest
from datetime import datetime, timezone

from wikimirror import cli
from wikimirror.db import Mirror
from wikimirror.dump import import_dump
from wikimirror.update import TooOld, apply_updates

XML = """<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
<page><title>Cat</title><ns>0</ns><id>1</id><revision><id>10</id>
<timestamp>2026-10-01T00:00:00Z</timestamp><contributor><id>5</id></contributor>
<text>The cat is a small furry animal.</text></revision></page>
<page><title>Dog</title><ns>0</ns><id>2</id><revision><id>11</id>
<timestamp>2026-10-02T00:00:00Z</timestamp><text>Dogs bark loudly.</text></revision></page>
<page><title>Felis</title><ns>0</ns><id>3</id><redirect title="Cat"/><revision><id>12</id>
<timestamp>2026-10-02T00:00:00Z</timestamp><text>#REDIRECT [[Cat]]</text></revision></page>
<page><title>Talk:Cat</title><ns>1</ns><id>4</id><revision><id>13</id>
<timestamp>2026-10-03T00:00:00Z</timestamp><text>talk</text></revision></page>
</mediawiki>"""


def fake_api(changes, pages):
    def api(params):
        if params.get("list") == "recentchanges":
            return {"query": {"recentchanges": [{"title": t} for t in changes]}}
        out = []
        for t in params["titles"].split("|"):
            out.append(pages.get(t, {"title": t, "missing": True}))
        return {"query": {"pages": out}}
    return api


def page(title, revid, text):
    return {"title": title, "revisions": [{"revid": revid, "timestamp": "2026-10-10T00:00:00Z",
                                            "slots": {"main": {"content": text}}}]}


class Tests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.xml = self.d.name + "/d.xml"
        open(self.xml, "w").write(XML)
        self.m = Mirror(self.d.name + "/m.db")

    def test_import_and_search(self):
        self.assertEqual(import_dump(self.m, self.xml), 2)
        self.assertEqual(self.m.count(), 2)
        self.assertEqual(self.m.search("furry cats")[0]["title"], "Cat")
        self.assertEqual(self.m.search("bar")[0]["title"], "Dog")  # prefix
        self.assertEqual(self.m.search('"; DROP'), [])

    def test_update(self):
        import_dump(self.m, self.xml)
        now = datetime(2026, 10, 15, tzinfo=timezone.utc)
        api = fake_api(["Cat", "Dog", "Bird"], {
            "Cat": page("Cat", 10, "same"),
            "Dog": page("Dog", 99, "Dogs wag tails."),
            "Bird": page("Bird", 50, "Birds fly."),
        })
        s = apply_updates(self.m, api, since="2026-10-03T00:00:00Z", now=now)
        self.assertEqual(s, dict(added=1, updated=1, removed=0, unchanged=1))
        self.assertEqual(self.m.search("wag")[0]["title"], "Dog")
        self.assertEqual(self.m.search("bark"), [])
        s = apply_updates(self.m, fake_api(["Bird"], {}), now=now)
        self.assertEqual(s["removed"], 1)
        self.assertEqual(self.m.count(), 2)

    def test_too_old(self):
        with self.assertRaises(TooOld):
            apply_updates(self.m, fake_api([], {}), since="2020-01-01T00:00:00Z")

    def test_cli_notes(self):
        import_dump(self.m, self.xml)
        self.m.close()
        base = ["--home", self.d.name]
        # cli uses <home>/mirror.db
        import os
        os.replace(self.d.name + "/m.db", self.d.name + "/mirror.db")
        out = io.StringIO()
        cli.main(base + ["note", "add", "cat", "likes", "milk"], out)
        cli.main(base + ["show", "Cat"], out)
        cli.main(base + ["search", "bark"], out)
        v = out.getvalue()
        self.assertIn("likes milk", v)
        self.assertIn("Dog", v)


if __name__ == "__main__":
    unittest.main()
