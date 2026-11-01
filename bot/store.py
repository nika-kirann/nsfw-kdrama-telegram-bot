"""Tiny JSON store for series, episodes, requests and schedules (ported idea from heaven-bot's db.py,
simplified: one JSON file, atomic writes). Seeded with built-in spicy series on first run."""
import json
import time
from pathlib import Path

from .content.series_seed import SEED


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.on_save = None  # set to storage.schedule_flush for channel-DB mirroring
        if path.exists():
            self.d = json.loads(path.read_text())
        else:
            self.d = {"next_id": 1, "series": {}, "requests": [], "schedules": [], "channel_posts": {}}
            for s in SEED:
                self.add_series(**s)
        self._migrate()
        self.save()

    def _migrate(self):
        """Old format had prose 'text' episodes -> convert to watch-link stubs."""
        for s in self.d["series"].values():
            for e in s["episodes"]:
                if "links" not in e:
                    e.pop("text", None); e["links"] = []; e.setdefault("title", f"Episode {e['n']}")
                elif isinstance(e["links"], dict):  # {label: url} -> [{q,url,kind}]
                    e["links"] = [{"q": ("HD" if k == "Watch" else k), "url": u, "kind": "part"} for k, u in e["links"].items()]

    def set_episode_links(self, sid, n, links, title=None):
        e = self.get(sid)["episodes"][n - 1]
        e["links"] = [dict(l) for l in links]
        if title:
            e["title"] = title
        e["added"] = time.time(); self.get(sid)["updated"] = time.time()
        self.save()

    def apply_links(self, sid, eps, total=None):
        """eps = {n: [(q, url, kind)]} from parse_quality_links. Creates episodes up to max(n, total);
        replaces links of each episode given. Returns sorted episode numbers touched."""
        s = self.get(sid)
        top = max([*eps, total or 0, len(s["episodes"])])
        while len(s["episodes"]) < top:
            self.add_episode(sid, [], save=False)
        for n, ls in eps.items():
            e = s["episodes"][n - 1]
            e["links"] = [{"q": q, "url": u, "kind": k} for q, u, k in ls]; e["added"] = time.time()
        s["updated"] = time.time()
        self.save()
        return sorted(eps)

    def save(self, flush=True):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d, ensure_ascii=False, indent=1))
        tmp.replace(self.path)
        if flush and self.on_save:
            self.on_save()

    # --- series ---
    def add_series(self, title, synopsis="", tags=(), status="Ongoing", heat=3, episodes=(), poster=None):
        sid = str(self.d["next_id"]); self.d["next_id"] += 1
        self.d["series"][sid] = {"id": int(sid), "title": title, "synopsis": synopsis, "tags": list(tags),
                                 "status": status, "heat": heat, "poster": poster, "created": time.time(),
                                 "updated": time.time(), "episodes": []}
        for _ in range(episodes if isinstance(episodes, int) else len(episodes)):
            self.add_episode(int(sid), {}, save=False)
        self.save()
        return self.get(int(sid))

    def get(self, sid):
        return self.d["series"].get(str(sid))

    def find(self, ref: str):
        ref = ref.strip()
        if ref.isdigit():
            return self.get(int(ref))
        for s in self.d["series"].values():
            if s["title"].lower() == ref.lower():
                return s
        hits = [s for s in self.d["series"].values() if ref.lower() in s["title"].lower()]
        return hits[0] if len(hits) == 1 else None

    def add_episode(self, sid, links, title=None, save=True):
        """Episode = title + watch links [{"q": "720p", "url": ..., "kind": "part"|"mirror"}].
        Empty links = stub (shown as 'link coming soon')."""
        s = self.get(sid)
        n = len(s["episodes"]) + 1
        s["episodes"].append({"n": n, "title": title or f"Episode {n}", "links": [dict(l) for l in links], "added": time.time()})
        s["updated"] = time.time()
        if save:
            self.save()
        return len(s["episodes"])

    def update(self, sid, **kw):
        self.get(sid).update(kw, updated=time.time()); self.save()

    def delete(self, sid):
        self.d["series"].pop(str(sid), None); self.save()

    def listing(self, status=None, tag=None, query=None, order="updated"):
        out = list(self.d["series"].values())
        if status:
            out = [s for s in out if s["status"] == status]
        if tag:
            out = [s for s in out if tag in s["tags"]]
        if query:
            q = query.lower()
            out = [s for s in out if q in s["title"].lower() or q in " ".join(s["tags"]).lower() or q in s["synopsis"].lower()]
        return sorted(out, key=lambda s: s[order] if order != "title" else s["title"], reverse=order != "title")

    def top_tags(self, n=10):
        c = {}
        for s in self.d["series"].values():
            for t in s["tags"]:
                c[t] = c.get(t, 0) + 1
        return sorted(c.items(), key=lambda x: -x[1])[:n]

    # --- misc ---
    def add_request(self, uid, text):
        self.d["requests"].append({"uid": uid, "text": text, "at": time.time()}); self.save()
        return len(self.d["requests"])

    def set_channel_post(self, sid, msg_id):
        self.d["channel_posts"][str(sid)] = msg_id; self.save()

    def channel_post(self, sid):
        return self.d["channel_posts"].get(str(sid))

    def new_eps_since(self, ts):
        return [(s, e) for s in self.d["series"].values() for e in s["episodes"] if e["added"] >= ts]

    # --- posters ---
    def poster_input(self, s):
        """Return something send_photo accepts (file_id/URL or open file), or None for text fallback."""
        p = s.get("poster")
        if not p:
            return None
        if p.startswith(("http://", "https://")) or not p.startswith("/"):
            return p
        path = Path(p)
        return path.read_bytes() if path.exists() else None
