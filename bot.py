import os, re, sys, json, time, shutil, asyncio, subprocess, urllib.request, urllib.parse
from pathlib import Path

for pkg in ["edge-tts", "yt-dlp[default,curl-cffi]", "pytubefix", "btch-downloader", "gTTS"]:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", pkg], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from google import genai
from google.genai import types
import yt_dlp, edge_tts
from gtts import gTTS

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DB_FILE = "users.json"
SESSIONS, ACTIVE_TASKS = {}, {}
EDGE_MAP = {"Thiha": "my-MM-ThihaNeural", "Nilar": "my-MM-NilarNeural"}
VOICES = ["Thiha", "Nilar"]
C1 = ("@moviezone336", "https://t.me/moviezone336", "📢 Channel 1 Join ရန်")
C2 = ("@color6777", "https://t.me/color6777", "📢 Channel 2 Join ရန်")
C3 = ("@sigyi89", "https://t.me/sigyi89", "📢 Channel 3 Join ရန်")
CHANNELS = [C1, C2, C3]
RAW_M = os.getenv("GEMINI_MODELS", "gemini-2.5-flash,gemini-2.0-flash").split(",")
MODELS = [x.strip().removeprefix("models/") for x in RAW_M if x.strip() and "flash" in x.lower()] or ["gemini-2.5-flash", "gemini-2.0-flash"]

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
    v = d.get("v", "Thiha") if d.get("v") in VOICES else "Thiha"
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
    r1 = [KeyboardButton("🎬 Dashboard"), KeyboardButton("🔑 API Key")]
    r2 = [KeyboardButton("🎙️ Voice ရွေးရန်"), KeyboardButton("🖼️ Logo ပုံထည့်ရန်")]
    return ReplyKeyboardMarkup([r1, r2, [KeyboardButton("/start")]], resize_keyboard=True)

def cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🛑 ရပ်တန့်မည် / ပြန်စမည် (/start)", callback_data="r|cancel")]])

def key_menu_ui(u):
    keys = u.get("keys", [])
    lines = [f"{i+1}. {k[:6]}••••{k[-4:]}" for i, k in enumerate(keys[:10])]
    k_info = f"✅ သိမ်းထားသော Key ({len(keys)}) ခု -\n" + "\n".join(lines) if keys else "❌ API Key မထည့်ရသေးပါ။"
    txt = f"🔑 GEMINI API KEY ROTATION စနစ်\n━━━━━━━━━━━━━━\n{k_info}\n\n💡 Key တစ်ခုချင်းဖြစ်စေ၊ အများကြီးကို Comma (,) ခြားပြီးဖြစ်စေ ပို့နိုင်ပါသည်။\n⚠️ Bot အလုပ်မလုပ်ပါက /start ကို နှိပ်ပါ။"
    kb = [[InlineKeyboardButton("🌐 Google AI Studio မှ Key ယူရန်", url="https://aistudio.google.com/app/apikey")]]
    if keys:
        kb.append([InlineKeyboardButton("🗑️ Key အားလုံး ဖျက်မည်", callback_data="m|clrkeys")])
    kb.append([InlineKeyboardButton("🔙 Dashboard သို့ ပြန်သွားရန်", callback_data="m|dash")])
    return txt, InlineKeyboardMarkup(kb)

def voice_menu_ui(u):
    cur = u.get("v", "Thiha")
    txt = f"🎙️ မြန်မာ TTS အသံရွေးချယ်ရန် (Speed: 1.25x)\nလက်ရှိအသံ - {'👨 Thiha (Male)' if cur == 'Thiha' else '👩 Nilar (Female)'}\n━━━━━━━━━━━━━━"
    b1 = InlineKeyboardButton(f"{'🟢' if cur=='Thiha' else '⚪'} 👨 Thiha (Male)", callback_data="v|Thiha")
    b2 = InlineKeyboardButton(f"{'🟢' if cur=='Nilar' else '⚪'} 👩 Nilar (Female)", callback_data="v|Nilar")
    b3 = InlineKeyboardButton("🔙 Dashboard သို့ ပြန်သွားရန်", callback_data="m|dash")
    return txt, InlineKeyboardMarkup([[b1, b2], [b3]])

def dash_ui(u, uid):
    k_cnt = len(u.get("keys", []))
    kt = f"✅ ({k_cnt}) ခု ချိတ်ပြီး" if k_cnt > 0 else "❌ မရှိသေးပါ"
    v_lbl = f"{u.get('v', 'Thiha')} (1.25x)"
    lay = "📱 Blur Frame" if u["layout"] == "frame" else "📲 Full Screen"
    bm = {"auto": "🎯 Auto-Detect", "low": "အောက်ခြေ", "mid": "အလယ်အောက်", "high": "အလယ်", "off": "OFF ❌"}
    b_txt = bm.get(u["blur"], "🎯 Auto-Detect")
    lg_t = ("ON ✅" if u["logo"] else "OFF ❌") if os.path.exists(f"logo_{uid}.jpg") else "ပုံမထည့်ရသေး"
    fl_t = "ON ✅" if u["f"] else "OFF ❌"
    r1 = [InlineKeyboardButton(f"🔑 API Keys: {kt}", callback_data="m|key")]
    r2 = [InlineKeyboardButton(f"🎙️ Voice: {v_lbl}", callback_data="m|vmenu"), InlineKeyboardButton(f"🖼️ {lay}", callback_data="m|lay")]
    r3 = [InlineKeyboardButton(f"🌫️ Blur: {b_txt}", callback_data="m|blur"), InlineKeyboardButton(f"🏷️ Logo: {lg_t}", callback_data="m|logo")]
    r4 = [InlineKeyboardButton(f"🪞 Flip + Filter + Crop: {fl_t}", callback_data="m|f")]
    txt = f"⚡ SIGYI AI STUDIO PRO (ULTRA HD) ⚡\n━━━━━━━━━━━━━━\n• 🔑 API Keys: {kt} (Auto-Rotation ✅)\n• 🎙️ Voice: {v_lbl} (Free Google/Neural TTS)\n• 🖼️ {lay} | 🌫️ Blur: {b_txt}\n• 🎯 Scene-Locked Frame Sync: Active ✅\n━━━━━━━━━━━━━━\n📥 TikTok / YouTube / Rednote Link သို့မဟုတ် Video ပို့ပါ!\n💡 (Bot အလုပ်မလုပ်ပါက /start ကို နှိပ်ပါ)"
    return txt, InlineKeyboardMarkup([r1, r2, r3, r4])

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
        with urllib.request.urlopen(urllib.request.Request(dl_url, headers=hdrs), timeout=20) as r, open(vpath, "wb") as f:
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
    low = url.lower()
    configs = [{"extractor_args": {"tiktok": {"app_name": "musically"}}}, {}] if "tiktok.com" in low else ([{"extractor_args": {"youtube": {"player_client": ["android_vr"]}}}, {"extractor_args": {"youtube": {"player_client": ["ios"]}}}] if "youtu" in low else [{}])
    for i, extra in enumerate(configs):
        outbase = f"{base}{i}"
        for old in [x for x in os.listdir(".") if x.startswith(outbase)]:
            try_run(os.remove, old)
        opts = {"format": "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/b[ext=mp4]/b", "merge_output_format": "mp4", "outtmpl": f"{outbase}.%(ext)s", "quiet": True, "no_warnings": True, "noplaylist": True, "nocheckcertificate": True, "retries": 2, "fragment_retries": 2, "socket_timeout": 18, "force_ipv4": True, "http_headers": {"User-Agent": ua, "Referer": "https://www.tiktok.com/"}, **extra}
        try_run(lambda: yt_dlp.YoutubeDL(opts).download([url]))
        candidates = [x for x in os.listdir(".") if x.startswith(outbase + ".") and is_valid_video(x)]
        if candidates:
            try_run(os.remove, vpath)
            os.rename(sorted(candidates)[0], vpath)
            return True
    return False

def dl_vid(url, vpath):
    url = url.strip().rstrip("，。、！!?,.;:)>\"'")
    ua_m = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
    ua_d = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    try_run(os.remove, vpath)
    res_u = try_run(lambda: urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": ua_m}), timeout=8).geturl()) or url
    if "tiktok.com" in url or "tiktok.com" in res_u:
        for tu in ([url, res_u] if res_u != url else [url]):
            for _ in range(2):
                api1 = f"https://www.tikwm.com/api/?url={urllib.parse.quote(tu)}&hd=1"
                resp1 = try_run(lambda: json.loads(urllib.request.urlopen(urllib.request.Request(api1, headers={"User-Agent": ua_m}), timeout=12).read().decode())) or {}
                d1 = resp1.get("data") or {}
                for fk in ["play", "hdplay", "wmplay"]:
                    if pu := d1.get(fk):
                        pu = "https://www.tikwm.com" + pu if pu.startswith("/") else pu
                        if save_stream_url(pu, vpath, ua_m, "https://www.tikwm.com/"):
                            return
                if resp1.get("code") == -1:
                    time.sleep(1.2)
            api2 = f"https://api.tiklydown.eu.org/api/download?url={urllib.parse.quote(tu)}"
            d2 = (try_run(lambda: json.loads(urllib.request.urlopen(urllib.request.Request(api2, headers={"User-Agent": ua_d}), timeout=12).read().decode())) or {}).get("video", {})
            if (pu2 := (d2.get("noWatermark") or d2.get("watermark"))) and save_stream_url(pu2, vpath, ua_d):
                return
            req_lt = urllib.request.Request("https://lovetik.com/api/ajax/search", data=urllib.parse.urlencode({"query": tu}).encode(), headers={"User-Agent": ua_d, "Origin": "https://lovetik.com"})
            d3 = (try_run(lambda: json.loads(urllib.request.urlopen(req_lt, timeout=12).read().decode())) or {}).get("links", [])
            for lk in d3:
                if (pu3 := lk.get("a")) and "mp3" not in (lk.get("t") or "").lower() and save_stream_url(pu3, vpath, ua_d, "https://lovetik.com/"):
                    return
        if yt_dlp_download(url, vpath, ua_d):
            return
    if "xhslink.com" in url or "xiaohongshu.com" in res_u or "xiaohongshu.com" in url:
        for x_u in ([res_u, url] if res_u != url else [url]):
            for ua in [ua_d, ua_m]:
                req_x = urllib.request.Request(x_u, headers={"User-Agent": ua, "Cookie": "webBuild=4.36.0; xsecappid=xhs-pc-web;"})
                html = try_run(lambda: urllib.request.urlopen(req_x, timeout=12).read().decode("utf-8", "ignore")) or ""
                mk, mog, mm = re.search(r'"originVideoKey"\s*:\s*"([^"]+)"', html), re.search(r'<meta\s+(?:name|property)="og:video"\s+content="([^"]+)"', html), re.search(r'"masterUrl"\s*:\s*"([^"]+)"', html)
                mcdn = re.search(r'(https?://sns-video-[a-z0-9\-]+\.xhscdn\.com/[^"\'\s\\]+)', html)
                k_s = mk.group(1).replace("\\u002F", "/") if mk else ""
                cands = ([f"https://sns-video-bd.xhscdn.com/{k_s}", f"https://sns-video-hw.xhscdn.com/{k_s}"] if k_s else []) + [m.group(1) for m in [mog, mm, mcdn] if m]
                for vu in cands:
                    vu = vu.replace("\\u002F", "/").replace("&amp;", "&")
                    if save_stream_url(vu if vu.startswith("http") else "https:" + vu, vpath, ua, "https://www.xiaohongshu.com/"):
                        return
    ym = re.search(r"(?:shorts/|v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})", res_u) or re.search(r"(?:shorts/|v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})", url)
    if ym:
        vid_id = ym.group(1)
        clean_yt = f"https://www.youtube.com/watch?v={vid_id}"
        from pytubefix import YouTube
        for cli in ["ANDROID_VR", "IOS", "WEB_EMBED", "MWEB"]:
            try:
                yt = YouTube(clean_yt, client=cli)
                st = yt.streams.filter(progressive=True, file_extension="mp4").order_by("resolution").desc().first()
                if st and try_run(lambda: st.download(filename=vpath)) and is_valid_video(vpath):
                    return
                vs = yt.streams.filter(only_video=True).order_by("resolution").desc().first()
                aus = yt.streams.filter(only_audio=True).first()
                if vs and aus:
                    vf_t, af_t = f"v_{vid_id}.mp4", f"a_{vid_id}.m4a"
                    try_run(os.remove, vf_t); try_run(os.remove, af_t)
                    vs.download(filename=vf_t); aus.download(filename=af_t)
                    subprocess.run(["ffmpeg", "-y", "-i", vf_t, "-i", af_t, "-c:v", "copy", "-c:a", "aac", vpath], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
                    try_run(os.remove, vf_t); try_run(os.remove, af_t)
                    if is_valid_video(vpath):
                        return
            except Exception:
                continue
        if yt_dlp_download(clean_yt, vpath, ua_d):
            return
        u_os = f"https://p.oceansaver.in/ajax/download.php?format=720&url={urllib.parse.quote(clean_yt)}"
        tid = (try_run(lambda: json.loads(urllib.request.urlopen(urllib.request.Request(u_os, headers={"User-Agent": ua_d}), timeout=10).read().decode())) or {}).get("id")
        for _ in range(7 if tid else 0):
            time.sleep(2)
            u_pr = f"https://p.oceansaver.in/ajax/progress.php?id={tid}"
            dl_u = (try_run(lambda: json.loads(urllib.request.urlopen(urllib.request.Request(u_pr, headers={"User-Agent": ua_d}), timeout=8).read().decode())) or {}).get("download_url")
            if dl_u and save_stream_url(dl_u, vpath, ua_d):
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
    cmd_sm = ["ffmpeg", "-y", "-threads", "2", "-i", vpath, "-t", f"{vdur:.2f}", "-vf", "fps=1,scale=280:-2", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35", "-c:a", "aac", "-ac", "1", "-ar", "16000", "-b:a", "28k", sm_v]
    subprocess.run(cmd_sm, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
    up_file = sm_v if (os.path.exists(sm_v) and os.path.getsize(sm_v) > 1000) else vpath
    u = get_u(uid)
    keys = u.get("keys", [])
    if not keys:
        raise Exception("API Key မရှိပါ။ Key အရင်ထည့်ပေးပါ။")
    start_idx = u.get("k_idx", 0) % len(keys)
    w_dur = vdur / n_win
    chars_w = max(65, int(w_dur * 15.2))
    win_desc = "၊ ".join([f"အပိုင်း {i+1} ({int(i*w_dur)}s-{int((i+1)*w_dur)}s)" for i in range(n_win)])
    p = f"ဒီ Video ဖိုင်ရဲ့ ရုပ်ပုံနဲ့ မူရင်းအသံကို သေချာကြည့်ရှုနားထောင်ပြီး ({n_win}) ပိုင်းခွဲ၍ အပိုအလိုမရှိဘဲ Burmese Professional Movie Recap ပုံစံဖြင့် ဘာသာပြန်ပေးပါ - {win_desc}\n"
    p += "ဥပမာ အရေးအသားပုံစံ - အမျိုးသားတစ်ယောက်ဟာ လှေပေါ်မှာ ဓားနဲ့ ကစားနေရင်း မတော်တဆ အပေါက်ဖောက်မိသွားတဲ့အတွက် ရေတွေ စတင် စိမ့်ဝင်လာပါတယ်။ ||| "
    p += "သူက သူ့ခြေထောက်နဲ့ အပေါက်ကို အမြန်ဖုံးအုပ်ပြီး ဘာမှမဖြစ်သလို ဟန်ဆောင်လိုက်ပါတယ်။ ရန်သူခေါင်းဆောင်ကတော့ သံသယဝင်သွားပြီး စစ်ဆေးဖို့ သူတို့လှေပေါ်ကို တက်လာပါတော့တယ်။ ||| "
    p += "ခေါင်းဆောင်က အန်နာ ဆီကို လျှောက်သွားပြီး ငါးမျှားတံကို ကောက်ကိုင်ကာ ငါးဖမ်းဟန်ဆောင်လိုက်ပါတယ်။\n"
    p += f"စည်းကမ်းချက် - တစ်ပိုင်းစီအတွက် မြန်မာစာလုံးရေ {chars_w} လုံးခန့် ရေးပြီး အပိုင်းကြားတွင် ||| သင်္ကေတ ခြားပေးပါ။ အင်္ဂလိပ်စာနှင့် ကွင်းစကွင်းပိတ် လုံးဝ မထည့်ပါနှင့်။"
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
            last_err = RuntimeError("Gemini video file is still processing")
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
            raise Exception("Gemini API quota ပြည့်နေပါသည်။ Key အသစ်ထည့်ပြီး ပြန်စမ်းပေးပါ။")
        raise Exception(f"Gemini API Error: {err_text[:600]}")
    parts = [clean_mm_text(x) for x in raw_txt.split("|||") if len(clean_mm_text(x)) > 5]
    if len(parts) != n_win:
        full_c = clean_mm_text(raw_txt)
        sents = [s.strip() + "။" for s in full_c.split("။") if len(s.strip()) > 5] or [full_c]
        st = max(1, len(sents) / n_win)
        parts = [" ".join(sents[int(round(i*st)):max(int(round(i*st))+1, int(round((i+1)*st)) if i < n_win-1 else len(sents))]) or sents[-1] for i in range(n_win)]
    return parts

def _split_gtts_text(text, max_len=140):
    words = text.split()
    chunks, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= max_len:
            cur = (cur + " " + w).strip()
        else:
            if cur:
                chunks.append(cur)
            cur = w
    if cur:
        chunks.append(cur)
    out = []
    for c in (chunks or [text]):
        for i in range(0, len(c), max_len):
            out.append(c[i:i + max_len])
    return out

def _save_gtts_chunk(chunk, path):
    for attempt in range(3):
        try_run(os.remove, path)
        q = urllib.parse.quote(chunk)
        for host in ["translate.googleapis.com", "translate.google.com"]:
            u_g = f"https://{host}/translate_tts?ie=UTF-8&client=gtx&tl=my&q={q}"
            req = urllib.request.Request(u_g, headers={"User-Agent": "Mozilla/5.0"})
            data = try_run(lambda: urllib.request.urlopen(req, timeout=10).read())
            if data:
                open(path, "wb").write(data)
            if is_valid_audio(path):
                return True
        try_run(lambda: gTTS(text=chunk, lang="my", lang_check=False).save(path))
        if is_valid_audio(path):
            return True
        time.sleep(0.5 + attempt)
    return False

def _google_tts_segment(text, output_mp3, work, seg_index):
    text = clean_mm_text(text).strip() or "အဲ့ဒီနောက်မှာတော့"
    chunks = _split_gtts_text(text, 140)
    if len(chunks) == 1 and _save_gtts_chunk(chunks[0], output_mp3):
        return True
    chunk_paths = []
    list_path = os.path.join(work, f"gt_list_{seg_index}.txt")
    for idx, chunk in enumerate(chunks):
        c_path = os.path.join(work, f"gt_{seg_index}_{idx}.mp3")
        chunk_paths.append(c_path)
        if not _save_gtts_chunk(chunk, c_path):
            return False
    lines = ["file '" + os.path.abspath(p).replace("'", "'\\''") + "'\n" for p in chunk_paths]
    Path(list_path).write_text("".join(lines), encoding="utf-8")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c:a", "libmp3lame", "-q:a", "3", output_mp3]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=45)
    return r.returncode == 0 and is_valid_audio(output_mp3)

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
        subprocess.run(["ffmpeg", "-y", "-i", cw, "-af", af_fit, "-ac", "1", "-ar", "24000", fw], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
        use_w = fw if is_valid_audio(fw) else cw
        final_wavs.append(use_w)
        seg_durs.append(max(0.5, get_dur(use_w)))
    list_f = os.path.join(work, "concat.txt")
    lines = ["file '" + os.path.abspath(w).replace("'", "'\\''") + "'\n" for w in final_wavs]
    Path(list_f).write_text("".join(lines), encoding="utf-8")
    r = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_f, "-c:a", "aac", "-b:a", "160k", out_a], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90)
    if r.returncode != 0 or not is_valid_audio(out_a):
        raise RuntimeError("Narration audio concat failed")
    return seg_durs

async def build_free_synced_voice(seg_scripts, voice_key, out_a, uid, vdur):
    work = f"tts_{uid}_{int(time.time() * 1000)}"
    os.makedirs(work, exist_ok=True)
    try:
        edge_v = EDGE_MAP.get(voice_key, "my-MM-ThihaNeural")
        edge_wavs = []
        edge_all_ok = True
        for i, script in enumerate(seg_scripts):
            text = clean_mm_text(script) or "အဲ့ဒီနောက်မှာတော့"
            raw = os.path.join(work, f"edge_{i}.mp3")
            cw = os.path.join(work, f"edge_cw_{i}.wav")
            try:
                await asyncio.wait_for(edge_tts.Communicate(text=text, voice=edge_v, rate="+25%").save(raw), timeout=8)
            except Exception:
                pass
            if not is_valid_audio(raw):
                edge_all_ok = False
                break
            af = "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,areverse,highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=24000,asetpts=PTS-STARTPTS"
            subprocess.run(["ffmpeg", "-y", "-i", raw, "-af", af, "-ac", "1", "-ar", "24000", cw], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            if not is_valid_audio(cw):
                edge_all_ok = False
                break
            edge_wavs.append(cw)
        if edge_all_ok and len(edge_wavs) == len(seg_scripts):
            return await asyncio.to_thread(_pace_and_concat_segments, edge_wavs, work, out_a, vdur)
        gtts_wavs = []
        spd_f = "asetrate=24000*0.88,aresample=24000,atempo=1.42" if voice_key == "Thiha" else "atempo=1.25"
        for i, script in enumerate(seg_scripts):
            text = clean_mm_text(script) or "အဲ့ဒီနောက်မှာတော့"
            raw_g = os.path.join(work, f"gtts_{i}.mp3")
            cw_g = os.path.join(work, f"gtts_cw_{i}.wav")
            ok_g = await asyncio.to_thread(_google_tts_segment, text, raw_g, work, i)
            if not ok_g or not is_valid_audio(raw_g):
                raise RuntimeError(f"Google TTS အသံထုတ်မရပါ (Segment {i + 1})")
            af = f"silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,areverse,{spd_f},highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=24000,asetpts=PTS-STARTPTS"
            r = await asyncio.to_thread(subprocess.run, ["ffmpeg", "-y", "-i", raw_g, "-af", af, "-ac", "1", "-ar", "24000", cw_g], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            if r.returncode != 0 or not is_valid_audio(cw_g):
                await asyncio.to_thread(subprocess.run, ["ffmpeg", "-y", "-i", raw_g, "-af", "atempo=1.25", "-ac", "1", "-ar", "24000", cw_g], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            if not is_valid_audio(cw_g):
                raise RuntimeError(f"Audio conversion failed at segment {i + 1}")
            gtts_wavs.append(cw_g)
        return await asyncio.to_thread(_pace_and_concat_segments, gtts_wavs, work, out_a, vdur)
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
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", p]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
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
            await asyncio.wait_for(asyncio.to_thread(dl_vid, um.group(0), vpath), timeout=180)
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
        seg_scripts = await asyncio.wait_for(asyncio.to_thread(ai_frame_audio_translate, vpath, sm_v, uid, vdur, n_win), timeout=max(180, int(vdur * 2.5)))
        stage = "TTS voice generation"
        await q.edit_message_text(f"🔄 [60%] 🎙️ {u['v']} (1.25x Speed) အသံတစ်မျိုးတည်းဖြင့် ချိန်ညှိသွင်းနေပါသည်...{hint}", reply_markup=cancel_kb())
        seg_durs = await asyncio.wait_for(build_free_synced_voice(seg_scripts, u["v"], apath, uid, vdur), timeout=120)
        stage = "FFmpeg video/audio render"
        await q.edit_message_text(f"🔄 [85%] Ultra HD + Auto-Blur + Scene-Locked Frame Sync Render လုပ်နေပါသည်...{hint}", reply_markup=cancel_kb())
        await asyncio.wait_for(asyncio.to_thread(edit_vid, vpath, apath, opath, u, uid, vdur, seg_durs), timeout=max(300, int(vdur * 5)))
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