[٢٥‏/١١، ٣:٣٠ م] Instinct: #!/usr/bin/env python3
# -*- coding: utf-8 -*-
# fb_comments.py - رد تلقائي على تعليقات صفحة فيسبوك
#
# الوضع الافتراضي "معاينة" (preview): مبيبعتش أي رد خالص، بس بيكتب
# الردود المقترحة في ملف PREVIEWS.md عشان تشوفها وتوافق عليها الأول.
#
# التفعيل الفعلي: أنشئ ملف comments_config.json في المستودع وحط فيه:
#   {"mode": "live"}
#
# قواعد الرد:
# - بنرد بس على التعليقات اللي ينفع معاها شكر أو دعاء (مدح، شكر، دعاء، تحية).
# - بنتخطى: الأسئلة، التعليقات اللي فيها روابط، الشكاوى أو النقد،
#   التعليقات الطويلة جداً، وأي تعليق مش واضح إن الشكر يناسبه.
# - منردش مرتين على نفس التعليق، ولا على نفس الشخص مرتين في نفس المنشور.
# - لو الصفحة ردت يدوياً على تعليق، منردش عليه تاني.
# - حد أقصى 10 ردود كل 15 دقيقة، وثانيتين بين كل رد والتاني.
#
# يعمل ببايثون القياسي فقط، بدون أي مكتبات خارجية.

import json
import os
import sys
import time
import zlib
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo

API = "https://graph.facebook.com/v23.0"
TOKEN = os.environ.get("FB_PAGE_TOKEN", "").strip()
STATE_FILE = "comments_state.json"
CONFIG_FILE = "config.json"          # فيه page_id (نفس ملف yt2fb)
MODE_FILE = "comments_config.json"   # اختياري: {"mode": "live"}
PREVIEW_FILE = "PREVIEWS.md"
CAIRO = ZoneInfo("Africa/Cairo")

MAX_REPLIES_PER_RUN = 10   # أقصى عدد ردود فعلية في المرة الواحدة
MAX_PREVIEWS = 10          # أقصى عدد معروض في ملف المعاينة
POSTS_TO_SCAN = 20
COMMENTS_PER_POST = 25
MAX_STORED = 2000

# عائلات ردود متنوعة حسب نوع التعليق - تقدر تعدلها براحتك
DUA_REPLIES = [
    "آمين يا رب، وجزاك الله خيراً يا {name} 🙏",
    "آمين، وربنا يسمع منك يا {name} ❤️",
    "يا رب آمين، بارك الله فيك يا {name} 🤲",
    "آمين يا {name}، ربنا يتقبل منا ومنك 🙏",
]
PRAISE_REPLIES = [
    "يا {name}، كلمتك أسعدتني، ربنا يبارك فيك ❤️",
    "تسلم يا {name} على كلامك الحلو 🙏",
    "ربنا يكرمك يا {name}، دعمك بيفرق معانا ❤️",
    "جزاك الله خيراً يا {name} على كلماتك الطيبة 🙏",
    "سعدت بكلامك يا {name}، شكراً ليك ❤️",
]
THANK_REPLIES = [
    "العفو يا {name}، ده واجبنا ❤️",
    "الشكر ليك يا {name} على المتابعة 🙏",
    "متشكرين ليك يا {name} ❤️",
]
GENERIC_REPLIES = [
    "شكراً على تفاعلك يا {name} ❤️",
    "يا {name}، متابعتك بتفرق معانا 🙏",
    "أهلاً بيك يا {name}، نورت الصفحة ❤️",
]
FAMILIES = {
    "dua": DUA_REPLIES,
    "praise": PRAISE_REPLIES,
    "thanks": THANK_REPLIES,
    "generic": GENERIC_REPLIES,
}

LINK_HINTS = ("http", "www.", ".com", ".net", ".org")
NEGATIVE_WORDS = ("سيئ", "سيئة", "وحش", "كذب", "كدب", "غلط", "خطأ", "حرام",
                  "زفت", "ممل", "أسوأ", "فاشل")
DUA_WORDS = ("آمين", "امين", "أمين", "اللهم", "يا رب", "جزاك الله",
             "بارك الله", "حفظك الله", "ربنا يحفظك", "صدق الله")
THANK_WORDS = ("شكرا", "شكراً", "متشكر", "ممنون", "تسلم", "يعطيك العافية")
PRAISE_WORDS = ("جميل", "جميلة", "رائع", "رائعة", "حلو", "ممتاز", "عظيم",
                "ماشاء الله", "ما شاء الله", "ماشاءالله", "مفيد", "استفدت",
                "كويس", "تحفة", "محترم", "الله ينور", "أحسنت", "احسنت")


def explain_error(body):
    try:
        err = json.loads(body).get("error", {})
        code = err.get("code")
        msg = err.get("message", "")
    except Exception:
        code, msg = None, body
    print("حدث خطأ من فيسبوك: %s (كود %s)" % (msg, code))
    if code == 190:
        print("السبب غالباً: الرمز انتهت صلاحيته. جدد الرمز وحدّث السر FB_PAGE_TOKEN في GitHub.")
    elif code == 10 or "permission" in str(msg).lower():
        print("السبب غالباً: إذن pages_manage_engagement ناقص في الرمز (مطلوب للإرسال الفعلي فقط).")
    sys.exit(1)


def api_get(path, params):
    params = dict(params)
    params["access_token"] = TOKEN
    url = API + path + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        explain_error(e.read().decode("utf-8", "replace"))
[٢٥‏/١١، ٣:٣٠ م] Instinct: def api_post(path, params):
    params = dict(params)
    params["access_token"] = TOKEN
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(API + path, data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        explain_error(e.read().decode("utf-8", "replace"))


def parse_time(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_mode():
    if os.path.exists(MODE_FILE):
        try:
            mode = json.load(open(MODE_FILE, encoding="utf-8")).get("mode", "")
            if mode == "live":
                return "live"
        except Exception:
            pass
    return "preview"


def first_name(full):
    if not full:
        return "صديقي"
    name = str(full).split()[0].strip()
    if 1 < len(name) <= 20:
        return name
    return "صديقي"


def classify(text):
    """يرجع (العائلة, None) لو الشكر مناسب، أو (None, سبب التخطي)."""
    t = (text or "").strip()
    low = t.lower()
    if not t:
        return (None, "تعليق فاضي")
    if any(h in low for h in LINK_HINTS):
        return (None, "فيه رابط")
    if "؟" in t or "?" in t:
        return (None, "سؤال يستاهل رد شخصي منك")
    if any(w in low for w in NEGATIVE_WORDS):
        return (None, "نقد أو شكوى، الأفضل ترد عليه بنفسك")
    if len(t) > 200:
        return (None, "تعليق طويل يستاهل رد شخصي منك")
    if any(w in t for w in DUA_WORDS):
        return ("dua", None)
    if any(w in t for w in THANK_WORDS):
        return ("thanks", None)
    if any(w in t for w in PRAISE_WORDS):
        return ("praise", None)
    if len(t) <= 120:
        return ("generic", None)
    return (None, "تعليق محايد طويل، الشكر الآلي مش مناسب")


def pick_reply(family, cid, name):
    templates = FAMILIES[family]
    idx = zlib.crc32(str(cid).encode("utf-8")) % len(templates)
    return templates[idx].format(name=name)


def main():
    if not TOKEN:
        print("خطأ: السر FB_PAGE_TOKEN مش موجود في بيئة التشغيل.")
        sys.exit(1)

    state = load_state()
    page_id = str(json.load(open(CONFIG_FILE, encoding="utf-8"))["page_id"])
    mode = load_mode()
    now = int(time.time())

    checkpoint = state.get("last_comment_check")
    first_run = not checkpoint
    if first_run:
        if mode == "live":
            # أول تشغيل فعلي: تسجيل نقطة البداية فقط، من غير رد على القديم
            state["last_comment_check"] = now
            state.setdefault("replied_ids", [])
            state.setdefault("replied_commenters", [])
            save_state(state)
            print("أول تشغيل فعلي: تم تسجيل نقطة البداية بدون رد على التعليقات القديمة.")
            return
        # أول تشغيل معاينة: نرجع 24 ساعة عشان تشوف أمثلة حقيقية فوراً
        checkpoint = now - 24 * 3600

    data = api_get("/" + page_id + "/posts", {
        "fields": "id,comments.order(reverse_chronological).limit(%d)"
                  "{id,created_time,from,message,comments.limit(10){from}}" % COMMENTS_PER_POST,
        "limit": str(POSTS_TO_SCAN),
    })

    replied_ids = set(state.get("replied_ids", []))
    replied_commenters = set(state.get("replied_commenters", []))
    candidates = []
    max_seen = checkpoint
[٢٥‏/١١، ٣:٣٠ م] Instinct: for post in data.get("data", []):
        post_id = post["id"]
        for c in post.get("comments", {}).get("data", []):
            try:
                ts = int(parse_time(c["created_time"]).timestamp())
            except Exception:
                continue
            if ts > max_seen:
                max_seen = ts
            if ts <= checkpoint:
                continue
            cid = c["id"]
            if cid in replied_ids:
                continue
            commenter = (c.get("from") or {}).get("id", "unknown")
            if commenter == page_id:
                continue  # تعليق الصفحة نفسها
            subs = c.get("comments", {}).get("data", [])
            if any((s.get("from") or {}).get("id") == page_id for s in subs):
                continue  # الصفحة ردت عليه يدوياً قبل كده
            if post_id + "_" + commenter in replied_commenters:
                continue  # ردينا على نفس الشخص في نفس المنشور
            name = first_name((c.get("from") or {}).get("name"))
            candidates.append((ts, post_id, cid, commenter, name,
                               (c.get("message") or "").strip()))

    candidates.sort(key=lambda x: x[0])  # الأقدم الأول
    state["last_comment_check"] = max_seen
[٢٥‏/١١، ٣:٣٠ م] Instinct: if mode == "preview":
        lines = []
        lines.append("# معاينة الردود التلقائية - لم يتم إرسال أي رد")
        lines.append("")
        lines.append("آخر فحص: %s بتوقيت القاهرة" % datetime.now(CAIRO).strftime("%Y-%m-%d %I:%M %p"))
        lines.append("")
        lines.append("## قواعد الرد")
        lines.append("")
        lines.append("- الرد بيتم بس على التعليقات اللي ينفع معاها شكر أو دعاء.")
        lines.append("- يتم تخطي: الأسئلة، الروابط، النقد أو الشكاوى، والتعليقات الطويلة، عشان ترد عليها بنفسك.")
        lines.append("- لا يتم الرد مرتين على نفس التعليق، ولا على نفس الشخص مرتين في نفس المنشور.")
        lines.append("- حد أقصى %d ردود كل 15 دقيقة." % MAX_REPLIES_PER_RUN)
        lines.append("")
        shown = 0
        skipped = 0
        for ts, post_id, cid, commenter, name, text in candidates:
            family, reason = classify(text)
            if family is None:
                skipped += 1
                if shown < MAX_PREVIEWS:
                    lines.append("⏭️ **%s**: \"%s\"" % (name, text[:80]))
                    lines.append("   - اتخطّى: %s." % reason)
                    lines.append("")
                continue
            if shown < MAX_PREVIEWS:
                reply = pick_reply(family, cid, name)
                lines.append("💬 **%s**: \"%s\"" % (name, text[:80]))
                lines.append("   - الرد المقترح: \"%s\"" % reply)
                lines.append("")
            shown += 1
        if not candidates:
            lines.append("مفيش تعليقات جديدة من آخر فحص.")
        else:
            lines.append("---")
            lines.append("الإجمالي: %d تعليق جديد - %d ليهم رد مقترح، %d اتخطّوا." % (len(candidates), shown, skipped))
            lines.append("")
            lines.append("لو الردود عجبتك، البرنامج يبدأ يبعت فعلاً بعد ما تنشئ ملف comments_config.json وفيه {\"mode\": \"live\"}.")
        # اكتب الملف بس لو فيه جديد أو الملف مش موجود (عشان منعملش حفظ فاضي كل 15 دقيقة)
        if candidates or not os.path.exists(PREVIEW_FILE):
            with open(PREVIEW_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            print("معاينة: تم كتابة %d رد مقترح في %s (لم يتم إرسال أي رد)." % (shown, PREVIEW_FILE))
        else:
            print("معاينة: مفيش تعليقات جديدة، الملف زي ما هو.")
    else:
        done = 0
        for ts, post_id, cid, commenter, name, text in candidates:
            if done >= MAX_REPLIES_PER_RUN:
                break
            family, reason = classify(text)
            if family is None:
                continue
            key = post_id + "_" + commenter
            if key in replied_commenters:
                continue
            api_post("/" + cid + "/comments", {"message": pick_reply(family, cid, name)})
            replied_ids.add(cid)
            replied_commenters.add(key)
            done += 1
            time.sleep(2)
        if done:
            print("تم الرد على %d تعليق جديد ✅" % done)
        else:
            print("مفيش تعليقات جديدة مناسبة للرد في الفحص ده.")

    state["replied_ids"] = list(replied_ids)[-MAX_STORED:]
    state["replied_commenters"] = list(replied_commenters)[-MAX_STORED:]
    save_state(state)


if __name__ == "__main__":
    main()
