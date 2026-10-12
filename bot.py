import os, re, sys, json, time, wave, base64, shutil, struct, asyncio, subprocess, urllib.request, urllib.parse
from pathlib import Path

for pkg in ["edge-tts", "yt-dlp[default,curl-cffi]", "pytubefix", "btch-downloader", "gTTS"]:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", pkg], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from google import genai
from google.genai import types
import yt_dlp
import edge_tts
from gtts import gTTS

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DB_FILE = "users.json"
SESSIONS, ACTIVE_TASKS = {}, {}

EDGE_MAP = {"Thiha": "my-MM-ThihaNeural", "Nilar": "my-MM-NilarNeural"}
GEMINI_FALLBACK_MAP = {"Thiha": "Charon", "Nilar": "Zephyr"}
VOICES = ["Thiha", "Nilar", "Zephyr", "Charon", "Kore", "Puck", "Fenrir"]
CHANNELS = [("@moviezone336", "https://t.me/moviezone336", "📢 Channel 1 Join ရန်"), ("@color6777", "https://t.me/color6777", "📢 Channel 2 Join ရန်"), ("@sigyi89", "https://t.me/sigyi89", "📢 Channel 3 Join ရန်")]
MODELS = [x.strip().removeprefix("models/") for x in os.getenv("GEMINI_MODELS", "gemini-2.5-flash,gemini-2.0-flash").split(",") if x.strip() and "flash" in x.lower()]
MODELS = MODELS or ["gemini-2.5-flash", "gemini-2.0-flash"]
TTS_MODELS = ["gemini-2.5-flash-preview-tts", "gemini-3.1-flash-tts-preview"]

def try_run(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception:
        return None

def get_db():
    return (try_run(lambda: json.load(open(DB_FILE))) or {}) if os.path.exists(DB_FILE) else {}

def get_u(uid):
    db, k = get_db(), str(uid)
    d = db.get(k, {})
    keys = d.get("keys", []) or ([d["key"]] if d.get("key") else [])
    v = d.get("v", "Zephyr") if d.get("v") in VOICES else "Zephyr"
    if k not in db or "keys" not in d or d.get("v") not in VOICES:
        db[k] = {"keys": keys, "k_idx": d.get("k_idx", 0), "v": v, "f": d.get("f", True), "layout": d.get("layout", "frame"), "blur": d.get("blur", "auto"), "logo": d.get("logo", True), "verified": d.get("verified", False)}
        json.dump(db, open(DB_FILE, "w"))
    return db[k]

def set_u(uid, field, val):
    db, k = get_db(), str(uid)
    if k not in db:
        get_u(uid)
        db = get_db()
    db[k][field] = val
    json.dump(db, open(DB_FILE, "w"))

def cancel_user_task(uid):
    t = ACTIVE_TASKS.pop(uid, None)
    if t and not t.done():
        t.cancel()
    for f in os.listdir("."):
        if str(uid) in f and not f.startswith("logo_"):
            try_run(os.remove, f)
    SESSIONS.pop(uid, None)

def extract_keys(text):
    raw = re.split(r"[\s,;]+", text.strip())
    return [x.strip() for x in raw if len(x.strip()) >= 20 and not x.startswith(("http", "/")) and (x.startswith(("AIza", "AQ.")) or re.match(r"^[A-Za-z0-9_\-\.]{25,}$", x.strip()))]

def add_user_keys(uid, new_keys):
    cur = list(get_u(uid).get("keys", []))
    added = sum(1 for nk in new_keys if nk not in cur and not cur.append(nk))
    set_u(uid, "keys", cur)
    return added, len(cur)

async def check_joined(bot, uid):
    for ch_id, _, _ in CHANNELS:
        try:
            m = await bot.get_chat_member(chat_id=ch_id, user_id=uid)
            if m.status in ["left", "kicked"]:
                return False
        except Exception:
            continue
    return True

def join_kb():
    rows = [[InlineKeyboardButton(lbl, url=url)] for _, url, lbl in CHANNELS]
    rows.append([InlineKeyboardButton("✅ Join ပြီးပါပြီ (Verify လုပ်မည်)", callback_data="verify|check")])
    return InlineKeyboardMarkup(rows)

def join_text():
    return "🔒 Bot ကို အသုံးပြုရန် အောက်ပါ Channel (၃) ခုကို အရင် Join ပေးပါ -\n\n1️⃣ https://t.me/moviezone336\n2️⃣ https://t.me/color6777\n3️⃣ https://t.me/sigyi89\n\n✅ (၃) ခုလုံး Join ပြီးပါက အောက်ပါ Verify ခလုတ်ကို နှိပ်ပါ -"

def main_kb():
    return ReplyKeyboardMarkup([[KeyboardButton("🎬 Dashboard"), KeyboardButton("🔑 API Key")], [KeyboardButton("🎙️ Voice ရွေးရန်"), KeyboardButton("🖼️ Logo ပုံထည့်ရန်")], [KeyboardButton("/start")]], resize_keyboard=True)

def cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🛑 ရပ်တန့်မည် / ပြန်စမည် (/start)", callback_data="r|cancel")]])

def key_menu_ui(u):
    keys = u.get("keys", [])
    lines = [f"{i+1}. {k[:6]}••••{k[-4:]}" for i, k in enumerate(keys[:10])]
    k_info = f"✅ သိမ်းထားသော Key ({len(keys)}) ခု -\n" + "\n".join(lines) if keys else "❌ API Key မထည့်ရသေးပါ။"
    txt = f"🔑 GEMINI API KEY ROTATION စနစ်\n━━━━━━━━━━━━━━\n{k_info}\n\n💡 Key တစ်ခုချင်းဖြစ်စေ၊ အများကြီးကို Comma (,) သို့မဟုတ် တစ်ကြောင်းချင်းစီ ခြားပြီးဖြစ်စေ ပို့နိုင်ပါသည်။\n⚠️ Bot အလုပ်မလုပ်ပါက /start ကို နှိပ်ပါ။"
    kb = [[InlineKeyboardButton("🌐 Google AI Studio မှ Key ယူရန်", url="https://aistudio.google.com/app/apikey")]]
    if keys:
        kb.append([InlineKeyboardButton("🗑️ Key အားလုံး ဖျက်မည်", callback_data="m|clrkeys")])
    kb.append([InlineKeyboardButton("🔙 Dashboard သို့ ပြန်သွားရန်", callback_data="m|dash")])
    return txt, InlineKeyboardMarkup(kb)

def voice_menu_ui(u):
    cur = u.get("v", "Zephyr")
    txt = f"🎙️ အသံရွေးချယ်ရန် (Speed: 1.25x)\nလက်ရှိအသံ - 🌟 {cur}\n💡 (Thiha/Nilar မရပါက Google AI Zephyr/Charon သို့ အလိုအလျောက် ပြောင်းပေးပါမည်)\n━━━━━━━━━━━━━━"
    r1 = [InlineKeyboardButton(f"{'🟢' if cur=='Zephyr' else '⚪'} 🌟 Zephyr", callback_data="v|Zephyr"), InlineKeyboardButton(f"{'🟢' if cur=='Charon' else '⚪'} 🌟 Charon", callback_data="v|Charon")]
    r2 = [InlineKeyboardButton(f"{'🟢' if cur=='Kore' else '⚪'} 🌟 Kore", callback_data="v|Kore"), InlineKeyboardButton(f"{'🟢' if cur=='Puck' else '⚪'} 🌟 Puck", callback_data="v|Puck"), InlineKeyboardButton(f"{'🟢' if cur=='Fenrir' else '⚪'} 🌟 Fenrir", callback_data="v|Fenrir")]
    r3 = [InlineKeyboardButton(f"{'🟢' if cur=='Thiha' else '⚪'} 👨 Thiha", callback_data="v|Thiha"), InlineKeyboardButton(f"{'🟢' if cur=='Nilar' else '⚪'} 👩 Nilar", callback_data="v|Nilar")]
    r4 = [InlineKeyboardButton("🔙 Dashboard သို့ ပြန်သွားရန်", callback_data="m|dash")]
    return txt, InlineKeyboardMarkup([r1, r2, r3, r4])

def dash_ui(u, uid):
    k_cnt = len(u.get("keys", []))
    kt = f"✅ ({k_cnt}) ခု ချိတ်ပြီး" if k_cnt > 0 else "❌ မရှိသေးပါ"
    v_lbl = f"{u.get('v', 'Zephyr')} (1.25x)"
    lay = "📱 Blur Frame" if u["layout"] == "frame" else "📲 Full Screen"
    bm = {"auto": "🎯 Auto-Detect", "low": "အောက်ခြေ", "mid": "အလယ်အောက်", "high": "အလယ်", "off": "OFF ❌"}
    b_txt = bm.get(u["blur"], "🎯 Auto-Detect")
    lg_t = ("ON ✅" if u["logo"] else "OFF ❌") if os.path.exists(f"logo_{uid}.jpg") else "ပုံမထည့်ရသေး"
    fl_t = "ON ✅" if u["f"] else "OFF ❌"
    kb = [[InlineKeyboardButton(f"🔑 API Keys: {kt}", callback_data="m|key")], [InlineKeyboardButton(f"🎙️ Voice: {v_lbl}", callback_data="m|vmenu"), InlineKeyboardButton(f"🖼️ {lay}", callback_data="m|lay")], [InlineKeyboardButton(f"🌫️ Blur: {b_txt}", callback_data="m|blur"), InlineKeyboardButton(f"🏷️ Logo: {lg_t}", callback_data="m|logo")], [InlineKeyboardButton(f"🪞 Flip + Filter + Crop: {fl_t}", callback_data="m|f")]]
    txt = f"⚡ SIGYI AI STUDIO PRO (ULTRA HD) ⚡\n━━━━━━━━━━━━━━\n• 🔑 API Keys: {kt} (Auto-Rotation ✅)\n• 🤖 AI: Gemini Flash + Google AI TTS ✅\n• 🎙️ Voice: {v_lbl} | 📺 Ultra HD\n• 🖼️ {lay} | 🌫️ Blur: {b_txt}\n• 🎯 Scene-Locked Frame Sync: Active ✅\n━━━━━━━━━━━━━━\n📥 TikTok / YouTube / Rednote Link သို့မဟုတ် Video ပို့ပါ!\n💡 (Bot အလုပ်မလုပ်ပါက /start ကို နှိပ်ပါ)"
    return txt, InlineKeyboardMarkup(kb)

def is_valid_video(p):
    if not os.path.exists(p) or os.path.getsize(p) < 10000:
        return False
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", p], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return "video" in r.stdout.lower()

def is_valid_audio(p):
    if not os.path.exists(p) or os.path.getsize(p) < 600:
        return False
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", p], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return "audio" in r.stdout.lower()

def save_stream_url(dl_url, vpath, ua, ref=""):
    try:
        try_run(os.remove, vpath)
        hdrs = {"User-Agent": ua, **({"Referer": ref} if ref else {})}
        with urllib.request.urlopen(urllib.request.Request(dl_url, headers=hdrs), timeout=25) as r, open(vpath, "wb") as f:
            while chunk := r.read(65536):
                f.write(chunk)
        if is_valid_video(vpath):
            return True
    except Exception:
        pass
    try_run(os.remove, vpath)
    return False

def find_mp4(obj):
    if isinstance(obj, str) and obj.startswith("http") and not any(b in obj.lower() for b in [".mp3", ".m4a", ".jpg", ".png", ".webp", ".jpeg"]):
        return obj if any(x in obj.lower() for x in [".mp4", "video", "play", "stream", "xhscdn", "googlevideo", "tikcdn", "aweme"]) else None
    if isinstance(obj, dict):
        for k in ["play", "hdplay", "noWatermark", "video", "url", "download", "mp4", "url_list", "data", "result"]:
            if k in obj and (r := find_mp4(obj[k])):
                return r
        for v in obj.values():
            if r := find_mp4(v):
                return r
    if isinstance(obj, list):
        for item in obj:
            if r := find_mp4(item):
                return r
    return None

def yt_dlp_download(url, vpath, ua):
    base = vpath[:-4] + "_ydl" if vpath.lower().endswith(".mp4") else vpath + "_ydl"
    configs = [{}]
    low = url.lower()
    if "tiktok.com" in low:
        configs = [{"extractor_args": {"tiktok": {"app_name": "musically"}}}, {"extractor_args": {"tiktok": {"app_name": "trill"}}}, {}]
    elif "youtu" in low:
        configs = [{"extractor_args": {"youtube": {"player_client": ["android_vr"]}}}, {"extractor_args": {"youtube": {"player_client": ["ios"]}}}, {}]
    for i, extra in enumerate(configs):
        outbase = f"{base}{i}"
        for old in [x for x in os.listdir(".") if x.startswith(outbase)]:
            try_run(os.remove, old)
        opts = {"format": "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/b[ext=mp4]/b", "merge_output_format": "mp4", "outtmpl": f"{outbase}.%(ext)s", "quiet": True, "no_warnings": True, "noplaylist": True, "nocheckcertificate": True, "retries": 3, "fragment_retries": 3, "extractor_retries": 3, "socket_timeout": 25, "concurrent_fragment_downloads": 1, "force_ipv4": True, "http_headers": {"User-Agent": ua, "Referer": "https://www.tiktok.com/"}, **extra}
        try_run(lambda: yt_dlp.YoutubeDL(opts).download([url]))
        candidates = [x for x in os.listdir(".") if x.startswith(outbase + ".") and is_valid_video(x)]
        if candidates:
            try_run(os.remove, vpath)
            os.rename(sorted(candidates)[0], vpath)
            for extra_file in candidates[1:]:
                try_run(os.remove, extra_file)
            return True
    return False

def dl_vid(url, vpath):
    url = url.strip().rstrip("，。、！!?,.;:)>\"'")
    ua_m = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
    ua_d = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    try_run(os.remove, vpath)
    if any(host in url.lower() for host in ["tiktok.com", "youtu.be", "youtube.com"]):
        if yt_dlp_download(url, vpath, ua_d):
            return
    if "tiktok.com" in url:
        api1 = f"https://www.tikwm.com/api/?url={urllib.parse.quote(url)}"
        d1 = (try_run(lambda: json.loads(urllib.request.urlopen(urllib.request.Request(api1, headers={"User-Agent": ua_m}), timeout=15).read().decode())) or {}).get("data", {})
        for fk in ["play", "wmplay", "hdplay"]:
            pu = d1.get(fk)
            if pu:
                pu = "https://www.tikwm.com" + pu if pu.startswith("/") else pu
                if save_stream_url(pu, vpath, ua_m, "https://www.tikwm.com/") or (try_run(lambda: urllib.request.urlretrieve(pu, vpath)) and is_valid_video(vpath)):
                    return
        d2 = (try_run(lambda: json.loads(urllib.request.urlopen(urllib.request.Request(f"https://api.tiklydown.eu.org/api/download?url={urllib.parse.quote(url)}", headers={"User-Agent": ua_d}), timeout=15).read().decode())) or {}).get("video", {})
        if (pu2 := (d2.get("noWatermark") or d2.get("watermark"))) and save_stream_url(pu2, vpath, ua_d):
            return
        d3 = (try_run(lambda: json.loads(urllib.request.urlopen(urllib.request.Request("https://lovetik.com/api/ajax/search", data=urllib.parse.urlencode({"query": url}).encode(), headers={"User-Agent": ua_d, "Origin": "https://lovetik.com"}), timeout=15).read().decode())) or {}).get("links", [])
        for lk in d3:
            if (pu3 := lk.get("a")) and "mp3" not in (lk.get("t") or "").lower() and save_stream_url(pu3, vpath, ua_d, "https://lovetik.com/"):
                return
    if "xhslink.com" in url or "xiaohongshu.com" in url:
        for ua in [ua_d, ua_m]:
            req_x = urllib.request.Request(url, headers={"User-Agent": ua, "Cookie": "webBuild=4.36.0; xsecappid=xhs-pc-web;"})
            html = try_run(lambda: urllib.request.urlopen(req_x, timeout=15).read().decode("utf-8", "ignore")) or ""
            mk, mog, mm = re.search(r'"originVideoKey"\s*:\s*"([^"]+)"', html), re.search(r'<meta\s+(?:name|property)="og:video"\s+content="([^"]+)"', html), re.search(r'"masterUrl"\s*:\s*"([^"]+)"', html)
            mcdn = re.search(r'(https?://sns-video-[a-z0-9\-]+\.xhscdn\.com/[^"\'\s\\]+)', html)
            cands = ([f"https://sns-video-bd.xhscdn.com/{mk.group(1).replace(chr(92)+'u002F', '/')}", f"https://sns-video-hw.xhscdn.com/{mk.group(1).replace(chr(92)+'u002F', '/')}"] if mk else []) + [m.group(1) for m in [mog, mm, mcdn] if m]
            for vu in cands:
                vu = vu.replace("\\u002F", "/").replace("&amp;", "&")
                if save_stream_url(vu if vu.startswith("http") else "https:" + vu, vpath, ua, "https://www.xiaohongshu.com/"):
                    return
    ym = re.search(r"(?:shorts/|v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})", url)
    if ym:
        vid_id = ym.group(1)
        clean_yt = f"https://www.youtube.com/watch?v={vid_id}"
        for fmt in ["720", "480", "360"]:
            tid = (try_run(lambda: json.loads(urllib.request.urlopen(urllib.request.Request(f"https://p.oceansaver.in/ajax/download.php?format={fmt}&url={urllib.parse.quote(clean_yt)}", headers={"User-Agent": ua_d}), timeout=12).read().decode())) or {}).get("id")
            for _ in range(10 if tid else 0):
                time.sleep(2)
                dl_u = (try_run(lambda: json.loads(urllib.request.urlopen(urllib.request.Request(f"https://p.oceansaver.in/ajax/progress.php?id={tid}", headers={"User-Agent": ua_d}), timeout=10).read().decode())) or {}).get("download_url")
                if dl_u and save_stream_url(dl_u, vpath, ua_d):
                    return
        from pytubefix import YouTube
        for cli in ["ANDROID_VR", "IOS", "WEB_EMBED", "MWEB", "TV"]:
            yt = try_run(lambda: YouTube(clean_yt, client=cli))
            st = try_run(lambda: yt.streams.filter(progressive=True, file_extension="mp4").order_by("resolution").desc().first()) if yt else None
            if st and try_run(lambda: st.download(filename=vpath)) and is_valid_video(vpath):
                return
        for api in [f"https://pipedapi.kavin.rocks/streams/{vid_id}", f"https://inv.nadeko.net/api/v1/videos/{vid_id}"]:
            data = try_run(lambda: json.loads(urllib.request.urlopen(urllib.request.Request(api, headers={"User-Agent": ua_d}), timeout=10).read().decode())) or {}
            for s in (data.get("formatStreams") or data.get("videoStreams") or []):
                if (su := s.get("url")) and (s.get("videoOnly") is not True) and save_stream_url(su, vpath, ua_d):
                    return
        url = clean_yt
    if yt_dlp_download(url, vpath, ua_d):
        return
    import btch_downloader
    dl_u = try_run(lambda: find_mp4(asyncio.run(btch_downloader.xiaohongshu(url) if "xhs" in url or "xiaohongshu" in url else (btch_downloader.ttdl(url) if "tiktok" in url else (btch_downloader.youtube(url) if "youtu" in url else btch_downloader.aio(url))))))
    if dl_u and save_stream_url(dl_u, vpath, ua_d):
        return
    raise Exception("Video Link ဒေါင်းယူ၍ မရပါ။ (Bot အလုပ်မလုပ်ပါက /start နှိပ်ပါ)")

def clean_mm_text(t):
    t = re.sub(r"\([^)]*\)", "", t)
    t = re.sub(r"[*#_`~0-9:a-zA-Z\[\]()|•\-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def get_generate_models(client):
    discovered = []
    try:
        for model in client.models.list():
            name = str(getattr(model, "name", "") or "").removeprefix("models/")
            actions = [str(a).lower() for a in (getattr(model, "supported_actions", None) or [])]
            if not name or (actions and not any("generatecontent" in a for a in actions)):
                continue
            low = name.lower()
            if not any(term in low for term in ("embedding", "tts", "image", "veo", "aqa")) and "flash" in low:
                discovered.append(name)
    except Exception:
        return MODELS
    available = set(discovered)
    preferred = [m for m in MODELS if m in available]
    return preferred + [m for m in discovered if m not in preferred] or MODELS

def _try_models_with_file(client, model_candidates, uf, p, uid, k_i):
    last_err = None
    for m_name in model_candidates:
        try:
            res = client.models.generate_content(model=m_name, contents=[uf, p])
            if res and res.text:
                set_u(uid, "k_idx", k_i)
                return res.text, None
        except Exception as me:
            last_err = me
            if any(w in str(me).upper() for w in ["429", "RESOURCE_EXHAUSTED", "QUOTA", "API_KEY", "PERMISSION", "403"]):
                continue
    return "", last_err

def ai_frame_audio_translate(vpath, sm_v, uid, vdur, n_win):
    subprocess.run(["ffmpeg", "-y", "-threads", "2", "-i", vpath, "-t", f"{vdur:.2f}", "-vf", "fps=1,scale=280:-2", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35", "-c:a", "aac", "-ac", "1", "-ar", "16000", "-b:a", "28k", sm_v], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
    up_file = sm_v if (os.path.exists(sm_v) and os.path.getsize(sm_v) > 1000) else vpath
    u = get_u(uid)
    keys = u.get("keys", [])
    if not keys:
        raise Exception("API Key မရှိပါ။ Key အရင်ထည့်ပေးပါ။")
    start_idx = u.get("k_idx", 0) % len(keys)
    w_dur = vdur / n_win
    chars_w = max(65, int(w_dur * 15.2))
    win_desc = "၊ ".join([f"အပိုင်း {i+1} ({int(i*w_dur)}s မှ {int((i+1)*w_dur)}s)" for i in range(n_win)])
    p = f"ဒီ Video ဖိုင်ရဲ့ ရုပ်ပုံ (Frames) နဲ့ မူရင်းအသံ (Audio) နှစ်ခုလုံးကို သေချာကြည့်ရှုနားထောင်ပြီး အောက်ပါ အချိန်အပိုင်းအခြား ({n_win}) ပိုင်းအတိုင်း အတိအကျ ခွဲ၍ အပိုအလိုမရှိဘဲ Burmese Professional Movie Recap စကားပြောပုံစံဖြင့် ဘာသာပြန်ပေးပါ - {win_desc}\n\n"
    p += "အတိအကျ လိုက်နာရမည့် ဥပမာ အရေးအသားပုံစံ -\n"
    p += "အမျိုးသားတစ်ယောက်ဟာ လှေပေါ်မှာ ဓားနဲ့ ကစားနေရင်း မတော်တဆ အပေါက်ဖောက်မိသွားတဲ့အတွက် ရေတွေ စတင် စိမ့်ဝင်လာပါတယ်။ ရေတွေက သင်္ဘောကုန်းပတ်ပေါ်အထိ လျင်မြန်စွာ တက်လာချိန်မှာပဲ တခြားလှေတစ်စင်း ချဉ်းကပ်လာတာကို သူ မြင်လိုက်ရပါတယ်။ ||| သူက သူ့ခြေထောက်နဲ့ အပေါက်ကို အမြန်ဖုံးအုပ်ပြီး ဘာမှမဖြစ်သလို ဟန်ဆောင်လိုက်ပါတယ်။ ရုတ်တရက်ဆိုသလိုပဲ ကင်းလှည့်ရေယာဉ်တစ်စင်း သူတို့ရှေ့မှာ ပေါ်လာပါတယ်။ သူတို့တွေက ငါးဖမ်းသမားတွေလို ဟန်ဆောင်ကြပေမဲ့ ရန်သူခေါင်းဆောင်ကတော့ တစ်ခုခု လွဲနေတယ်လို့ သံသယဝင်သွားပြီး စစ်ဆေးဖို့အတွက် သူတို့လှေပေါ်ကို တက်လာပါတော့တယ်။ ||| ခေါင်းဆောင်က အန်နာ ဆီကို လျှောက်သွားပြီး ငါးမျှားတံကို ကောက်ကိုင်ကာ ငါးဖမ်းဟန်ဆောင်လိုက်ပါတယ်။ အန်နာက လျင်မြန်စွာ လှည့်လိုက်တဲ့အခါ ငါးမျှားတံက သူမလက်ထဲကနေ လွင့်စင်သွားခဲ့ပါတယ်။\n\n"
   p += f"စည်းကမ်းချက် - အပိုင်းတစ်ပိုင်းစီအတွက် အဲ့ဒီအချိန်အတွင်း မြင်ရကြားရသည့်အတိုင်း မြန်မာစာလုံးရေ {chars_w} လုံးခန့် ရေးပြီး အပိုင်းကြားတွင် ||| သင်္ကေတ ခြားပေးပါ။ လူနာမည်များကို မြန်မာလိုသာရေးပါ၊ အင်္ဂလိပ်စာလုံးနှင့် ကွင်းစကွင်းပိတ် လုံးဝ မထည့်ပါနှင့်။"
    raw_txt, last_err = "", None
    for step_i in range(len(keys)):
        k_i = (start_idx + step_i) % len(keys)
        client = genai.Client(api_key=keys[k_i].strip(), http_options=types.HttpOptions(timeout=40000))
        model_candidates = get_generate_models(client)
        uf = try_run(lambda: client.files.upload(file=up_file))
        if not uf:
            continue
        for _ in range(120):
            if getattr(getattr(uf, "state", None), "name", "") == "PROCESSING":
                time.sleep(1)
                uf = try_run(lambda: client.files.get(name=uf.name)) or uf
        if getattr(getattr(uf, "state", None), "name", "") == "PROCESSING":
            last_err = RuntimeError("Gemini video file is still processing after 120 seconds")
            try_run(lambda: client.files.delete(name=uf.name))
            continue
        raw_txt, err_one = _try_models_with_file(client, model_candidates, uf, p, uid, k_i)
        if err_one:
            last_err = err_one
        try_run(lambda: client.files.delete(name=uf.name))
        if raw_txt:
            break
    if not raw_txt:
        err_text = str(last_err or "Unknown Gemini API error")
        if any(w in err_text.upper() for w in ["429", "RESOURCE_EXHAUSTED", "QUOTA", "LIMIT: 0"]):
            raise Exception("Gemini API quota ပြည့်နေပါသည်။ Google AI Studio မှ Key အသစ်ထည့်ပြီး ပြန်စမ်းပေးပါ။")
        raise Exception(f"Gemini API Error: {err_text[:600]}")
    parts = [clean_mm_text(x) for x in raw_txt.split("|||") if len(clean_mm_text(x)) > 5]
    if len(parts) != n_win:
        full_c = clean_mm_text(raw_txt)
        sents = [s.strip() + "။" for s in full_c.split("။") if len(s.strip()) > 5] or [full_c]
        st = max(1, len(sents) / n_win)
        parts = [" ".join(sents[int(round(i*st)):max(int(round(i*st))+1, int(round((i+1)*st)) if i < n_win-1 else len(sents))]) or sents[-1] for i in range(n_win)]
    return parts

def _write_pcm_or_riff(pcm, wav_path):
    if pcm[:4] == b"RIFF":
        open(wav_path, "wb").write(pcm)
        return
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(pcm)

def _extract_tts_pcm(res):
    pcm = b""
    for part in res.candidates[0].content.parts:
        if getattr(part, "inline_data", None) and part.inline_data.data:
            d = part.inline_data.data
            pcm += base64.b64decode(d) if isinstance(d, str) else d
    return pcm

def _gemini_tts_call(text, g_voice, out_wav, uid, key_offset=0):
    u = get_u(uid)
    keys = u.get("keys", [])
    if not keys:
        return False
    start_idx = (u.get("k_idx", 0) + key_offset) % len(keys)
    pvc = types.PrebuiltVoiceConfig(voice_name=g_voice)
    cfg = types.GenerateContentConfig(response_modalities=["AUDIO"], speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=pvc)))
    prompt = f"Read the following Burmese narration aloud naturally and clearly in Burmese:\n\n{text}"
    for step_i in range(len(keys)):
        k_i = (start_idx + step_i) % len(keys)
        client = genai.Client(api_key=keys[k_i].strip(), http_options=types.HttpOptions(timeout=45000))
        for tm in TTS_MODELS:
            res = try_run(lambda: client.models.generate_content(model=tm, contents=prompt, config=cfg))
            pcm = try_run(lambda: _extract_tts_pcm(res)) if res else b""
            if pcm and len(pcm) > 800:
                _write_pcm_or_riff(pcm, out_wav)
                if is_valid_audio(out_wav):
                    set_u(uid, "k_idx", k_i)
                    return True
    return False

def _detect_silence_midpoints(wav_path):
    r = subprocess.run(["ffmpeg", "-i", wav_path, "-af", "silencedetect=n=-38dB:d=0.14", "-f", "null", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", r.stderr)]
    return [(s + e) / 2.0 for s, e in zip(starts, ends)]

def _gemini_single_call_and_slice(seg_scripts, g_voice, work, uid):
    joined_txt = "\n\n".join(clean_mm_text(s) or "အဲ့ဒီနောက်မှာတော့" for s in seg_scripts)
    raw_full = os.path.join(work, "g_full_raw.wav")
    clean_full = os.path.join(work, "g_full_125x.wav")
    if not _gemini_tts_call(joined_txt, g_voice, raw_full, uid, 0):
        return None
    af = "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,areverse,atempo=1.25,highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=24000,asetpts=PTS-STARTPTS"
    subprocess.run(["ffmpeg", "-y", "-i", raw_full, "-af", af, "-ac", "1", "-ar", "24000", clean_full], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if not is_valid_audio(clean_full):
        return None
    tot_dur = max(1.0, get_dur(clean_full))
    mids = _detect_silence_midpoints(clean_full)
    weights = [max(1, len(clean_mm_text(s))) for s in seg_scripts]
    tot_w = sum(weights) or 1
    cuts = [0.0]
    acc = 0.0
    for i in range(len(seg_scripts) - 1):
        acc += weights[i]
        expected_t = tot_dur * (acc / tot_w)
        near = [m for m in mids if abs(m - expected_t) <= max(1.8, tot_dur * 0.08) and m > cuts[-1] + 0.4]
        best_cut = min(near, key=lambda m: abs(m - expected_t)) if near else max(cuts[-1] + 0.4, expected_t)
        cuts.append(min(tot_dur - 0.3, best_cut))
    cuts.append(tot_dur)
    seg_wavs = []
    for i in range(len(seg_scripts)):
        sw = os.path.join(work, f"g_slice_{i}.wav")
        st_t, en_t = cuts[i], max(cuts[i] + 0.4, cuts[i + 1])
        subprocess.run(["ffmpeg", "-y", "-i", clean_full, "-ss", f"{st_t:.3f}", "-to", f"{en_t:.3f}", "-ac", "1", "-ar", "24000", sw], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if not is_valid_audio(sw):
            return None
        seg_wavs.append(sw)
    return seg_wavs

def _save_gtts_chunk(chunk, path):
    for attempt in range(3):
        try_run(os.remove, path)
        try_run(lambda: gTTS(text=chunk, lang="my", lang_check=False).save(path))
        if is_valid_audio(path):
            return True
        q = urllib.parse.quote(chunk)
        for host in ["translate.googleapis.com", "translate.google.com"]:
            u_g = f"https://{host}/translate_tts?ie=UTF-8&client=gtx&tl=my&q={q}"
            data = try_run(lambda: urllib.request.urlopen(urllib.request.Request(u_g, headers={"User-Agent": "Mozilla/5.0"}), timeout=12).read())
            if data:
                open(path, "wb").write(data)
            if is_valid_audio(path):
                return True
        time.sleep(1 + attempt)
    return False

def _google_tts_fallback(text, output_mp3, uid, seg_index):
    text = clean_mm_text(text).strip() or "အဲ့ဒီနောက်မှာတော့"
    if len(text) <= 150 and _save_gtts_chunk(text, output_mp3):
        return True
    chunks = [text[i:i + 120] for i in range(0, len(text), 120)]
    chunk_paths = []
    list_path = f"gt_list_{uid}_{seg_index}.txt"
    try:
        for idx, chunk in enumerate(chunks):
            c_path = f"gt_{uid}_{seg_index}_{idx}.mp3"
            chunk_paths.append(c_path)
            if not _save_gtts_chunk(chunk, c_path):
                return False
        open(list_path, "w", encoding="utf-8").write("".join("file '" + os.path.abspath(p).replace("'", "'\\''") + "'\n" for p in chunk_paths))
        r = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c:a", "libmp3lame", "-q:a", "4", output_mp3], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90)
        return r.returncode == 0 and is_valid_audio(output_mp3)
    finally:
        for path in chunk_paths + [list_path]:
            try_run(os.remove, path)

def _pace_and_concat_segments(raw_seg_wavs, work, out_a, vdur):
    n_win = max(1, len(raw_seg_wavs))
    w_dur = vdur / n_win
    slot_target = (vdur / 0.90) / n_win
    final_wavs, seg_durs = [], []
    for i, cw in enumerate(raw_seg_wavs):
        fw = os.path.join(work, f"fw_{i}.wav")
        raw_d = max(0.5, get_dur(cw))
        tempo_adj = max(0.92, min(1.08, raw_d / max(0.5, slot_target)))
        min_seg_d = w_dur * 1.01
        af_fit = f"atempo={tempo_adj:.4f},apad=whole_dur={min_seg_d:.3f},asetpts=PTS-STARTPTS"
        subprocess.run(["ffmpeg", "-y", "-i", cw, "-af", af_fit, "-ac", "1", "-ar", "24000", fw], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        use_w = fw if is_valid_audio(fw) else cw
        final_wavs.append(use_w)
        seg_durs.append(max(0.5, get_dur(use_w)))
    list_f = os.path.join(work, "concat.txt")
    Path(list_f).write_text("".join("file '" + os.path.abspath(w).replace("'", "'\\''") + "'\n" for w in final_wavs), encoding="utf-8")
    r = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_f, "-c:a", "aac", "-b:a", "160k", out_a], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
    if r.returncode != 0 or not is_valid_audio(out_a):
        raise RuntimeError("Narration audio concat failed")
    return seg_durs

async def build_free_synced_voice(seg_scripts, voice_key, out_a, uid, vdur):
    work = f"tts_{uid}_{int(time.time() * 1000)}"
    os.makedirs(work, exist_ok=True)
    try:
        raw_seg_wavs = []
        # 1. Try Thiha / Nilar (Edge-TTS at 1.25x) if selected
        if voice_key in EDGE_MAP:
            edge_v = EDGE_MAP[voice_key]
            edge_ok = True
            for i, script in enumerate(seg_scripts):
                text = clean_mm_text(script) or "အဲ့ဒီနောက်မှာတော့"
                raw = os.path.join(work, f"edge_{i}.mp3")
                cw = os.path.join(work, f"cw_{i}.wav")
                for attempt in range(2):
                    try_run(os.remove, raw)
                    try:
                        await asyncio.wait_for(edge_tts.Communicate(text=text, voice=edge_v, rate="+25%").save(raw), timeout=15)
                    except Exception:
                        try_run(lambda: subprocess.run([sys.executable, "-m", "edge_tts", "--voice", edge_v, "--rate=+25%", "--text", text, "--write-media", raw], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15))
                    if is_valid_audio(raw):
                        break
                if not is_valid_audio(raw):
                    edge_ok = False
                    break
                af = "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,areverse,highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=24000,asetpts=PTS-STARTPTS"
                subprocess.run(["ffmpeg", "-y", "-i", raw, "-af", af, "-ac", "1", "-ar", "24000", cw], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
                if not is_valid_audio(cw):
                    edge_ok = False
                    break
                raw_seg_wavs.append(cw)
            if edge_ok and len(raw_seg_wavs) == len(seg_scripts):
                return await asyncio.to_thread(_pace_and_concat_segments, raw_seg_wavs, work, out_a, vdur)

        # 2. Google AI Studio Natural TTS (Zephyr, Charon, Kore, Puck, Fenrir) at 1.25x Speed
        g_voice = GEMINI_FALLBACK_MAP.get(voice_key, voice_key if voice_key in VOICES else "Zephyr")
        sliced = await asyncio.to_thread(_gemini_single_call_and_slice, seg_scripts, g_voice, work, uid)
        if sliced and len(sliced) == len(seg_scripts):
            return await asyncio.to_thread(_pace_and_concat_segments, sliced, work, out_a, vdur)

        # 3. Per-segment Google AI Studio TTS with Multi-Key Rotation fallback
        raw_seg_wavs = []
        for i, script in enumerate(seg_scripts):
            text = clean_mm_text(script) or "အဲ့ဒီနောက်မှာတော့"
            raw_w = os.path.join(work, f"gseg_raw_{i}.wav")
            cw = os.path.join(work, f"gseg_cw_{i}.wav")
            ok_g = await asyncio.to_thread(_gemini_tts_call, text, g_voice, raw_w, uid, i)
            if not ok_g:
                raw_w = os.path.join(work, f"gtts_{i}.mp3")
                if not await asyncio.to_thread(_google_tts_fallback, text, raw_w, uid, i):
                    raise RuntimeError(f"TTS အသံထုတ်မရပါ (Segment {i + 1})")
            af = "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,areverse,atempo=1.25,highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=24000,asetpts=PTS-STARTPTS"
            subprocess.run(["ffmpeg", "-y", "-i", raw_w, "-af", af, "-ac", "1", "-ar", "24000", cw], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
            if not is_valid_audio(cw):
                raise RuntimeError(f"Audio conversion failed at segment {i + 1}")
            raw_seg_wavs.append(cw)
        return await asyncio.to_thread(_pace_and_concat_segments, raw_seg_wavs, work, out_a, vdur)
    finally:
        try_run(shutil.rmtree, work, True)

def detect_sub_band(iv, vdur, is_fr, uid):
    raw_f = f"subdet_{uid}.raw"
    w, h = 360, (410 if is_fr else 640)
    vf = f"fps=6/{max(2.0, vdur):.2f},crop=iw*0.92:ih*0.92:iw*0.04:ih*0.04,scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    subprocess.run(["ffmpeg", "-y", "-threads", "1", "-i", iv, "-vf", vf, "-frames:v", "6", "-f", "rawvideo", "-pix_fmt", "gray", raw_f], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    dy, dh = (950, 86) if is_fr else (1040, 92)
    if not os.path.exists(raw_f):
        return dy, dh
    data = open(raw_f, "rb").read()
    try_run(os.remove, raw_f)
    n_f = len(data) // (w * h)
    if n_f < 1:
        return dy, dh
    ys, ye, scores = int(h * 0.56), int(h * 0.96), [0.0] * h
    for f_i in range(n_f):
        b = f_i * w * h
        for y in range(ys, ye):
            ro = b + y * w
            hits = sum(1 for x in range(int(w * 0.15), int(w * 0.85), 2) if abs(data[ro + x] - data[ro + x - 2]) > 40)
            if hits > 8:
                scores[y] += hits
    by_i = max(range(ys, ye - 16), key=lambda y: sum(scores[y:y + 16]), default=-1)
    if by_i < 0 or sum(scores[by_i:by_i + 16]) < 25 * n_f:
        return dy, dh
    out_c = int((by_i + 8) * 2.0) + (230 if is_fr else 0)
    return max(240 if is_fr else 100, min((1050 - dh) if is_fr else (1240 - dh), out_c - int(dh * 0.46))), dh

def get_dur(p):
    if not p or not os.path.exists(p):
        raise FileNotFoundError(f"Media file not found: {p}")
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", p], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
    duration = try_run(lambda: float(r.stdout.strip())) or 0.0
    if r.returncode != 0 or duration <= 0:
        raise RuntimeError(f"Invalid media duration for {os.path.basename(p)}")
    return duration

def build_piecewise_pts(vdur, seg_durs):
    n, w_d = len(seg_durs), max(0.5, vdur / max(1, len(seg_durs)))
    ts = [i * w_d for i in range(n)]
    ss = [sum(seg_durs[:i]) for i in range(n)]
    sl = [d / w_d for d in seg_durs]
    ex = f"{ss[-1]:.4f}+(T-{ts[-1]:.4f})*{sl[-1]:.4f}"
    for i in range(n - 2, -1, -1):
        ex = f"if(lt(T,{ts[i+1]:.4f}),{ss[i]:.4f}+(T-{ts[i]:.4f})*{sl[i]:.4f},{ex})"
    return f"trim=duration={vdur:.3f},fps=30,settb=AVTB,setpts=PTS-STARTPTS,setpts='({ex})/TB',fps=30"

def edit_vid(iv, ia, ov, u, uid, vdur, seg_durs):
    out_dur = max(get_dur(ia), 1.0)
    is_fr, fl = (u.get("layout", "frame") == "frame"), (",hflip" if u.get("f") else "")
    adj = "crop=iw*0.92:ih*0.92:iw*0.04:ih*0.04,eq=contrast=1.08:brightness=0.02:saturation=1.14:gamma=1.03,hue=h=3,unsharp=3:3:0.65:3:3:0.0"
    pw_s = build_piecewise_pts(vdur, seg_durs)
    un_s = f"trim=duration={vdur:.3f},fps=30,setpts={out_dur/max(vdur,1.0):.4f}*(PTS-STARTPTS),fps=30"
    b_map = {"low": (950, 86), "mid": (880, 86), "high": (790, 86)} if is_fr else {"low": (1040, 92), "mid": (940, 92), "high": (830, 92)}
    by, bh = detect_sub_band(iv, vdur, is_fr, uid) if u.get("blur") == "auto" else b_map.get(u.get("blur"), (950, 86))
    by, bh = (int(by) // 2) * 2, max(64, (int(bh) // 2) * 2)
    kbps = min(3200, max(1000, int((42 * 8192) / out_dur) - 160))
    last_err = ""
    for sync_f in [pw_s, un_s]:
        try_run(os.remove, ov)
        fc = f"[0:v]{sync_f}{fl}[v0];" + (f"[v0]split=2[bgi][fgi];[bgi]scale=180:320:force_original_aspect_ratio=increase,crop=180:320,gblur=sigma=14,eq=brightness=-0.07,scale=720:1280[bg];[fgi]{adj},scale=720:820:force_original_aspect_ratio=increase:flags=lanczos,crop=720:820[fg];[bg][fg]overlay=0:230[v1]" if is_fr else f"[v0]{adj},scale=720:1280:force_original_aspect_ratio=increase:flags=lanczos,crop=720:1280[v1]")
        cur = "[v1]"
        if u.get("blur") != "off":
            fc += f";{cur}split=2[m1][m2];[m2]crop=640:{bh}:40:{by},gblur=sigma=26[bst];[m1][bst]overlay=40:{by}[v2]"
            cur = "[v2]"
        inputs, logo_p = ["-i", iv, "-i", ia], f"logo_{uid}.jpg"
        if u.get("logo") and os.path.exists(logo_p):
            inputs.extend(["-i", logo_p])
            ly = 165 if is_fr else 80
            fc += f";[2:v]scale=110:110[lg];{cur}[lg]overlay=12:{ly}[v3]"
            cur = "[v3]"
        fc += f";{cur}format=yuv420p[vout]"
        c = ["ffmpeg", "-y", "-threads", "2"] + inputs + ["-map_metadata", "-1", "-map_chapters", "-1", "-filter_complex", fc, "-map", "[vout]", "-map", "1:a:0", "-c:v", "libx264", "-preset", "superfast", "-crf", "19", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps*2}k", "-c:a", "copy", "-t", f"{out_dur:.2f}", "-fs", "47M", ov]
        r = subprocess.run(c, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=max(300, int(out_dur * 6)))
        if r.returncode == 0 and is_valid_video(ov):
            return
        last_err = r.stderr[-500:]
    raise RuntimeError(f"Render Error: {last_err}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cancel_user_task(uid)
    u = get_u(uid)
    if not u.get("verified") or not (await check_joined(context.bot, uid)):
        set_u(uid, "verified", False)
        await update.message.reply_text(join_text(), reply_markup=join_kb(), disable_web_page_preview=True)
        return
    await update.message.reply_text("👋 Sigyi Ai Studio မှ ကြိုဆိုပါတယ်! (System Ready ✅)", reply_markup=main_kb())
    txt, kb = dash_ui(u, uid)
    await update.message.reply_text(txt, reply_markup=kb)

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_u(uid)
    if not u.get("verified") or not (await check_joined(context.bot, uid)):
        set_u(uid, "verified", False)
        await update.message.reply_text(join_text(), reply_markup=join_kb(), disable_web_page_preview=True)
        return
    if update.message.photo:
        f = await context.bot.get_file(update.message.photo[-1].file_id)
        await f.download_to_drive(f"logo_{uid}.jpg")
        set_u(uid, "logo", True)
        txt, kb = dash_ui(get_u(uid), uid)
        await update.message.reply_text("✅ Logo ပုံ သိမ်းဆည်းပြီးပါပြီ!\n\n" + txt, reply_markup=kb)
        return
    t = (update.message.text or "").strip()
    if t in ["🎬 Dashboard", "🔑 API Key", "🎙️ Voice ရွေးရန်", "🖼️ Logo ပုံထည့်ရန်"]:
        if t == "🖼️ Logo ပုံထည့်ရန်":
            await update.message.reply_text("🖼️ ဘယ်ဘက်အပေါ်ထောင့်မှာ ထည့်ချင်တဲ့ Logo ပုံ (Photo) ကို ပို့ပေးပါ။")
            return
        txt, kb = dash_ui(u, uid) if t == "🎬 Dashboard" else (key_menu_ui(u) if t == "🔑 API Key" else voice_menu_ui(u))
        await update.message.reply_text(txt, reply_markup=kb)
        return
    um = re.search(r"https?://[^\s，。、！!\"'<>]+", t)
    p_keys = extract_keys(t) if not um else []
    if p_keys:
        added, total = add_user_keys(uid, p_keys)
        try_run(lambda: asyncio.create_task(update.message.delete()))
        txt, kb = dash_ui(get_u(uid), uid)
        await context.bot.send_message(uid, f"✅ API Key ({added}) ခု အသစ်ထပ်ပေါင်းပြီး စုစုပေါင်း ({total}) ခု သိမ်းဆည်းပြီးပါပြီ!\n\n" + txt, reply_markup=kb)
        return
    if not u.get("keys"):
        txt, kb = key_menu_ui(u)
        await update.message.reply_text("🔒 Gemini API Key အရင်ထည့်ပေးပါ!\n\n" + txt, reply_markup=kb)
        return
    cancel_user_task(uid)
    msg = await update.message.reply_text("⏳ [15%] Ultra HD Video ဆွဲယူနေပါတယ်...\n💡 (အကယ်၍ ရပ်နေပါက /start နှိပ်ပါ)", reply_markup=cancel_kb())
    vpath = f"in_{uid}.mp4"
    try:
        if um:
            await asyncio.wait_for(asyncio.to_thread(dl_vid, um.group(0), vpath), timeout=300)
        if not um and (update.message.video or update.message.document):
            v = update.message.video or update.message.document
            f = await context.bot.get_file(v.file_id)
            await f.download_to_drive(vpath)
        if not is_valid_video(vpath):
            await msg.edit_text("❌ Video ဖိုင် မမှန်ကန်ပါ သို့မဟုတ် Video Link ပို့ပါ!\n💡 (Bot အလုပ်မလုပ်ပါက /start နှိပ်ပါ)")
            return
        SESSIONS[uid] = vpath
        txt, kb = dash_ui(u, uid)
        btn = InlineKeyboardButton(f"🚀 START RENDER ({u['v']} 1.25x | Ultra HD)", callback_data="r|go")
        await msg.edit_text("🎬 Video ရပြီ! စတင်ရန် START RENDER ကို နှိပ်ပါ -\n\n" + txt, reply_markup=InlineKeyboardMarkup(list(kb.inline_keyboard) + [[btn]]))
    except Exception as e:
        err_m = str(e).strip() or type(e).__name__
        await msg.edit_text(f"❌ Download Error: {err_m}\n\n💡 Bot အလုပ်မလုပ်ပါက /start ကို နှိပ်ပါ။")

async def run_render_job(q, context, uid):
    u, vpath = get_u(uid), SESSIONS.get(uid)
    sm_v, apath, opath = f"sm_{uid}.mp4", f"aud_{uid}.m4a", f"out_{uid}.mp4"
    hint = "\n\n💡 ရပ်နေပါက /start နှိပ်ပြီး video ပြန်ပို့ပါ"
    stage = "စတင်နေပါသည်"
    try:
        if not vpath or not is_valid_video(vpath):
            raise RuntimeError("Input video မမှန်ကန်ပါ")
        source_duration = max(1.0, get_dur(vpath))
        vdur = min(source_duration, 180.0)
        n_win = max(3, min(8, int(round(vdur / 12.0))))
        stage = "Gemini scene analysis"
        await q.edit_message_text(f"🔄 [30%] Video Frame + မူရင်းအသံကို အပိုင်း ({n_win}) ပိုင်းခွဲ၍ အတိအကျ ဘာသာပြန်နေပါသည်...{hint}", reply_markup=cancel_kb())
        seg_scripts = await asyncio.wait_for(asyncio.to_thread(ai_frame_audio_translate, vpath, sm_v, uid, vdur, n_win), timeout=max(240, int(vdur * 3)))
        stage = "TTS voice generation"
        await q.edit_message_text(f"🔄 [60%] 🎙️ {u['v']} (1.25x Speed) အသံနှင့် Scene အချိန် ချိန်ညှိသွင်းနေပါသည်...{hint}", reply_markup=cancel_kb())
        seg_durs = await asyncio.wait_for(build_free_synced_voice(seg_scripts, u["v"], apath, uid, vdur), timeout=max(240, int(vdur * 3)))
        stage = "FFmpeg video/audio render"
        await q.edit_message_text(f"🔄 [85%] Ultra HD + Auto-Blur + Scene-Locked Frame Sync Render လုပ်နေပါသည်...{hint}", reply_markup=cancel_kb())
        await asyncio.wait_for(asyncio.to_thread(edit_vid, vpath, apath, opath, u, uid, vdur, seg_durs), timeout=max(360, int(vdur * 6)))
        await q.edit_message_text("📤 [98%] Ultra HD Video ပို့ပေးနေပါတယ်...")
        with open(opath, "rb") as vf:
            await context.bot.send_video(uid, vf, caption="Powered by SiGyi Ai Studio", read_timeout=300, write_timeout=300)
        await q.delete_message()
    except asyncio.CancelledError:
        pass
    except asyncio.TimeoutError:
        try_run(lambda: asyncio.create_task(q.edit_message_text(f"❌ {stage} အဆင့်မှာ အချိန်ကျော်သွားပါတယ်။ /start နှိပ်ပြီး ပြန်စမ်းပေးပါ။")))
    except Exception as e:
        err = str(e).strip() or type(e).__name__
        try_run(lambda: asyncio.create_task(q.edit_message_text(f"❌ {stage} Error: {err[:800]}\n\n💡 /start နှိပ်ပြီး ပြန်စမ်းပါ")))
    finally:
        ACTIVE_TASKS.pop(uid, None)
        SESSIONS.pop(uid, None)
        for p in [vpath, sm_v, apath, opath]:
            if p and os.path.exists(p):
                try_run(os.remove, p)

async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid, u = q.from_user.id, get_u(q.from_user.id)
    cat, act = q.data.split("|")
    if cat == "verify":
        if not (await check_joined(context.bot, uid)):
            await q.answer("❌ Channel (၃) ခုလုံးကို အရင် Join ပေးပါ!", show_alert=True)
            return
        set_u(uid, "verified", True)
        await q.answer("✅ Verify အောင်မြင်ပါပြီ!")
        await context.bot.send_message(uid, "🎉 Verify အောင်မြင်ပါပြီ! Sigyi Ai Studio ကို စတင်အသုံးပြုနိုင်ပါပြီ။", reply_markup=main_kb())
        txt, kb = dash_ui(get_u(uid), uid)
        await q.edit_message_text(txt, reply_markup=kb)
        return
    if cat == "r" and act == "cancel":
        cancel_user_task(uid)
        await q.answer("🛑 ရပ်တန့်လိုက်ပါပြီ!")
        txt, kb = dash_ui(get_u(uid), uid)
        await q.edit_message_text("🛑 လုပ်ငန်းစဉ်ကို ရပ်တန့်ပြီး Reset လုပ်ပေးထားပါသည်။\n\n" + txt, reply_markup=kb)
        return
    if not u.get("verified") or not (await check_joined(context.bot, uid)):
        set_u(uid, "verified", False)
        await q.answer("🔒 Channel (၃) ခုကို အရင် Join ပေးပါ!", show_alert=True)
        await q.edit_message_text(join_text(), reply_markup=join_kb(), disable_web_page_preview=True)
        return
    await q.answer()
    if cat == "m" and act in ["key", "vmenu"]:
        txt, kb = key_menu_ui(u) if act == "key" else voice_menu_ui(u)
        await q.edit_message_text(txt, reply_markup=kb)
        return
    if cat == "m" and act == "clrkeys":
        set_u(uid, "keys", [])
        set_u(uid, "k_idx", 0)
        txt, kb = key_menu_ui(get_u(uid))
        await q.edit_message_text(txt, reply_markup=kb)
        return
    if cat == "v" and act in VOICES:
        set_u(uid, "v", act)
    if cat == "m" and act in ["lay", "blur", "logo", "f"]:
        bm = ["auto", "low", "mid", "high", "off"]
        if act == "lay":
            set_u(uid, "layout", "full" if u["layout"] == "frame" else "frame")
        if act == "blur":
            set_u(uid, "blur", bm[(bm.index(u["blur"] if u["blur"] in bm else "auto") + 1) % len(bm)])
        if act == "logo":
            set_u(uid, "logo", not u["logo"])
        if act == "f":
            set_u(uid, "f", not u["f"])
    if cat in ["v", "m"]:
        u_new = get_u(uid)
        txt, kb = dash_ui(u_new, uid)
        rows = list(kb.inline_keyboard)
        if uid in SESSIONS and os.path.exists(SESSIONS[uid]):
            rows.append([InlineKeyboardButton(f"🚀 START RENDER ({u_new['v']} 1.25x | Ultra HD)", callback_data="r|go")])
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(rows))
        return
    if cat == "r" and act == "go":
        if uid not in SESSIONS or not os.path.exists(SESSIONS[uid]):
            await q.edit_message_text("⚠️ Video အသစ် ပြန်ပို့ပါ။ (Bot အလုပ်မလုပ်ပါက /start နှိပ်ပါ)")
            return
        if not u.get("keys"):
            txt, kb = key_menu_ui(u)
            await q.edit_message_text("🔒 API Key အရင်ထည့်ပေးပါ!\n\n" + txt, reply_markup=kb)
            return
        if (old_t := ACTIVE_TASKS.pop(uid, None)) and not old_t.done():
            old_t.cancel()
        ACTIVE_TASKS[uid] = asyncio.create_task(run_render_job(q, context, uid))

def main():
    if not TOKEN:
        raise RuntimeError("Railway Variables ထဲ TELEGRAM_BOT_TOKEN မသတ်မှတ်ရသေးပါ။")
    app = Application.builder().token(TOKEN).concurrent_updates(True).read_timeout(240).write_timeout(240).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.VIDEO | (filters.TEXT & ~filters.COMMAND), handle_msg))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
