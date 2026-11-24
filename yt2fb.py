#!/usr/bin/env python3
"""yt2fb: يراقب قناتك على يوتيوب وينشر الفيديوهات الجديدة على صفحتك في فيسبوك (فوري أو مجدول).
بدون مكتبات خارجية. بايثون 3.8 أو أحدث.

الأوامر:
  python yt2fb.py check      (أو: فحص)  فحص الإعدادات والتوكن
  python yt2fb.py run        (أو: تشغيل)  ينشر الفيديوهات الجديدة فقط
  python yt2fb.py run --dry  (أو: تشغيل --تجربة)  تجربة بدون نشر فعلي
  python yt2fb.py latest     (أو: اخر)  ينشر آخر فيديو مرة واحدة (للتجربة الأولى)
"""
import json, os, random, sys, time, urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET

HERE = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")
STATE = os.path.join(HERE, "state.json")
GRAPH = "https://graph.facebook.com/v21.0"
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


def load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def fetch_videos(channel_id):
    url = "https://www.youtube.com/feeds/videos.xml?channel_id=" + channel_id
    with urllib.request.urlopen(url, timeout=30) as r:
        root = ET.fromstring(r.read())
    out = []
    for e in root.findall("a:entry", NS):
        out.append({
            "id": e.find("yt:videoId", NS).text,
            "title": e.find("a:title", NS).text,
            "published": e.find("a:published", NS).text,
        })
    return out  # الأحدث أولا


def graph_post(page_id, token, message, link, publish_at=None):
    data = {"message": message, "link": link, "access_token": token}
    if publish_at:
        data["published"] = "false"
        data["scheduled_publish_time"] = str(int(publish_at))
    req = urllib.request.Request(
        "%s/%s/feed" % (GRAPH, page_id),
        data=urllib.parse.urlencode(data).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit("خطأ من فيسبوك: " + e.read().decode("utf-8", "ignore"))


def build_message(cfg, v):
    t = random.choice(cfg["templates"])
    return t.format(title=v["title"])


def post_video(cfg, v, dry):
    link = "https://www.youtube.com/watch?v=" + v["id"]
    delay = int(cfg.get("delay_minutes", 0))
    when = None
    if delay >= 10:  # فيسبوك يشترط 10 دقائق على الأقل
        when = time.time() + delay * 60
    msg = build_message(cfg, v)
    print(("[تجربة] " if dry else "") + "نشر:", v["title"], "|", link,
          "| مجدول بعد %d دقيقة" % delay if when else "| فوري")
    if dry:
        print("   النص:", msg)
        return
    res = graph_post(cfg["page_id"], cfg["page_access_token"], msg, link, when)
    print("   تم. رقم البوست:", res.get("id"))
def main():
    alias = {"فحص": "check", "تشغيل": "run", "اخر": "latest", "آخر": "latest"}
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = alias.get(sys.argv[1], sys.argv[1])
    if cmd not in ("check", "run", "latest"):
        print(__doc__)
        return
    dry = "--dry" in sys.argv or "--تجربة" in sys.argv
    cfg = load_json(CONFIG, None)
    if not cfg:
        raise SystemExit("ملف config.json مش موجود. انسخ config.example.json إلى config.json وعدّله.")
    token = os.environ.get("FB_PAGE_TOKEN")
    if token:
        cfg["page_access_token"] = token
    videos = fetch_videos(cfg["youtube_channel_id"])
    if cmd == "check":
        print("القناة شغالة. آخر فيديو:", videos[0]["title"] if videos else "لا يوجد")
        url = "%s/%s?fields=name&access_token=%s" % (GRAPH, cfg["page_id"], cfg["page_access_token"])
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                print("الصفحة شغالة:", json.load(r).get("name"))
        except urllib.error.HTTPError as e:
            print("مشكلة في التوكن أو رقم الصفحة:", e.read().decode("utf-8", "ignore"))
        return
    if cmd == "latest":
        post_video(cfg, videos[0], dry)
        return
    state = load_json(STATE, None)
    if state is None:  # أول تشغيل: نسجل الموجود حاليا بدون نشر
        state = {"seen": [v["id"] for v in videos]}
        json.dump(state, open(STATE, "w"))
        print("أول تشغيل: سجلت %d فيديو قديم بدون نشر. الفيديوهات الجديدة بس هتتنشر." % len(videos))
        return
    new = [v for v in reversed(videos) if v["id"] not in state["seen"]]
    if not new:
        print("لا يوجد فيديو جديد.")
    for v in new:
        post_video(cfg, v, dry)
        if not dry:
            state["seen"].append(v["id"])
            json.dump(state, open(STATE, "w"))
        time.sleep(2)


if __name__ == "__main__":
    main()
