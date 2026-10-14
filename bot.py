import os
import re
import sys
import site
import json
import time
import shutil
import zipfile
import asyncio
import subprocess
import urllib.request
import urllib.parse
import logging
import base64
import wave
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

for pkg in [
    "pillow<10.0.0",
    "google-genai",
    "yt-dlp[default,curl-cffi]",
    "pytubefix",
    "btch-downloader",
    "gTTS",
    "python-telegram-bot",
]:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-U", pkg],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def setup_pot_server():
    try:
        pot_bin = "/tmp/bgutil-pot"
        if not os.path.exists(pot_bin):
            urllib.request.urlretrieve(
                "https://github.com/jim60105/bgutil-ytdlp-pot-provider-rs/releases/latest/download/bgutil-pot-linux-x86_64",
                pot_bin,
            )
            os.chmod(pot_bin, 0o755)
            z_p = "/tmp/pot_plugin.zip"
            urllib.request.urlretrieve(
                "https://github.com/jim60105/bgutil-ytdlp-pot-provider-rs/releases/latest/download/bgutil-ytdlp-pot-provider-rs.zip",
                z_p,
            )
            with zipfile.ZipFile(z_p, "r") as zf:
                zf.extractall(site.getsitepackages()[0])
        subprocess.Popen(
            [pot_bin, "server"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.environ["YT_DLP_POT_PROVIDER_URL"] = "http://127.0.0.1:4416"
    except Exception as e:
        logging.error(f"POT Server Setup Error: {e}")


setup_pot_server()

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from google import genai
from google.genai import types
import yt_dlp
from gtts import gTTS

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DB_FILE = "users.json"
SESSIONS, ACTIVE_TASKS = {}, {}

VOICES = [
    "Zephyr", "Charon", "Puck", "Kore", "Fenrir",
    "Aoede", "Leda", "Orus", "Callirrhoe", "Autonoe"
]

C1 = ("@moviezone336", "https://t.me/moviezone336", "📢 Channel 1 Join ရန်")
C2 = ("@color6777", "https://t.me/color6777", "📢 Channel 2 Join ရန်")
C3 = ("@sigyi89", "https://t.me/sigyi89", "📢 Channel 3 Join ရန်")
CHANNELS = [C1, C2, C3]

DEFAULT_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]
TTS_MODEL = "gemini-2.5-flash-preview-tts"


def safe_execution(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logging.error(f"Error in {getattr(func, '__name__', 'fn')}: {str(e)}")
        return None


def get_db():
    if os.path.exists(DB_FILE):
        def _read():
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return safe_execution(_read) or {}
    return {}


def save_db(db):
    def _write():
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f)
    safe_execution(_write)


def get_u(uid):
    db, k = get_db(), str(uid)
    d = db.get(k, {})
    keys = d.get("keys", []) or ([d["key"]] if d.get("key") else [])
    v = d.get("v", "Zephyr") if d.get("v") in VOICES else "Zephyr"
    if k not in db or "keys" not in d or d.get("v") not in VOICES:
        db[k] = {
            "keys": keys,
            "k_idx": d.get("k_idx", 0),
            "v": v,
            "f": d.get("f", True),
            "layout": d.get("layout", "frame"),
            "blur": d.get("blur", "auto"),
            "logo": d.get("logo", True),
            "verified": d.get("verified", False),
        }
        save_db(db)
    return db[k]


def set_u(uid, field, val):
    db, k = get_db(), str(uid)
    if k not in db:
        get_u(uid)
        db = get_db()
    db[k][field] = val
    save_db(db)


def cancel_user_task(uid):
    t = ACTIVE_TASKS.pop(uid, None)
    if t and not t.done():
        t.cancel()
    for f in os.listdir("."):
        if str(uid) in f and not f.startswith("logo_"):
            safe_execution(os.remove, f)
    SESSIONS.pop(uid, None)


def extract_keys(text):
    raw = re.split(r"[\s,;]+", text.strip())
    return [
        x.strip()
        for x in raw
        if len(x.strip()) >= 20
        and not x.startswith(("http", "/"))
        and (
            x.startswith(("AIza", "AQ."))
            or re.match(r"^[A-Za-z0-9_\-\.]{25,}$", x.strip())
        )
    ]


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
    rows.append([
        InlineKeyboardButton(
            "✅ Join ပြီးပါပြီ (Verify လုပ်မည်)", callback_data="verify|check"
        )
    ])
    return InlineKeyboardMarkup(rows)


def join_text():
    return (
        "🔒 Bot ကို အသုံးပြုရန် အောက်ပါ Channel (၃) ခုကို အရင် Join ပေးပါ -\n\n"
        "1️⃣ https://t.me/moviezone336\n"
        "2️⃣ https://t.me/color6777\n"
        "3️⃣ https://t.me/sigyi89\n\n"
        "✅ (၃) ခုလုံး Join ပြီးပါက အောက်ပါ Verify ခလုတ်ကို နှိပ်ပါ -"
    )


def main_kb():
    r1 = [KeyboardButton("🎬 Dashboard"), KeyboardButton("🔑 API Key")]
    r2 = [KeyboardButton("🎙️ Voice ရွေးရန်"), KeyboardButton("🖼️ Logo ပုံထည့်ရန်")]
    return ReplyKeyboardMarkup([r1, r2, [KeyboardButton("/start")]], resize_keyboard=True)


def cancel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 ရပ်တန့်မည် / ပြန်စမည် (/start)", callback_data="r|cancel")]
    ])


def key_menu_ui(u):
    keys = u.get("keys", [])
    lines = [f"{i+1}. {k[:6]}••••{k[-4:]}" for i, k in enumerate(keys[:10])]
    k_info = (
        f"✅ သိမ်းထားသော Key ({len(keys)}) ခု -\n" + "\n".join(lines)
        if keys
        else "❌ API Key မထည့်ရသေးပါ။"
    )
    txt = (
        f"🔑 GEMINI API KEY ROTATION စနစ်\n━━━━━━━━━━━━━━\n{k_info}\n\n"
        "💡 Key တစ်ခုချင်းဖြစ်စေ၊ အများကြီးကို Comma (,) ခြားပြီးဖြစ်စေ ပို့နိုင်ပါသည်။\n"
        "⚠️ Bot အလုပ်မလုပ်ပါက /start ကို နှိပ်ပါ။"
    )
    kb = [[
        InlineKeyboardButton(
            "🌐 Google AI Studio မှ Key ယူရန်",
            url="https://aistudio.google.com/app/apikey",
        )
    ]]
    if keys:
        kb.append([InlineKeyboardButton("🗑️ Key အားလုံး ဖျက်မည်", callback_data="m|clrkeys")])
    kb.append([InlineKeyboardButton("🔙 Dashboard သို့ ပြန်သွားရန်", callback_data="m|dash")])
    return txt, InlineKeyboardMarkup(kb)


def voice_menu_ui(u):
    cur = u.get("v", "Zephyr")
    txt = (
        f"🎙️ Gemini AI Voice (၁၀) မျိုး ရွေးချယ်ရန်\n"
        f"လက်ရှိအသံ - 🌟 {cur}\n━━━━━━━━━━━━━━"
    )
    kb, row = [], []
    for v in VOICES:
        row.append(
            InlineKeyboardButton(
                f"{'🟢' if cur==v else '⚪'} 🌟 {v}", callback_data=f"v|{v}"
            )
        )
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("🔙 Dashboard သို့ ပြန်သွားရန်", callback_data="m|dash")])
    return txt, InlineKeyboardMarkup(kb)


def dash_ui(u, uid):
    k_cnt = len(u.get("keys", []))
    kt = f"✅ ({k_cnt}) ခု ချိတ်ပြီး" if k_cnt > 0 else "❌ မရှိသေးပါ"
    v_lbl = f"🌟 {u.get('v', 'Zephyr')}"
    lay = "📱 Blur Frame" if u.get("layout", "frame") == "frame" else "📲 Full Screen"
    bm = {
        "auto": "🎯 Auto-Detect",
        "low": "အောက်ခြေ",
        "mid": "အလယ်အောက်",
        "high": "အလယ်",
        "off": "OFF ❌",
    }
    b_txt = bm.get(u.get("blur", "auto"), "🎯 Auto-Detect")
    lg_t = (
        ("ON ✅" if u.get("logo", True) else "OFF ❌")
        if os.path.exists(f"logo_{uid}.jpg")
        else "ပုံမထည့်ရသေး"
    )
    fl_t = "ON ✅" if u.get("f", True) else "OFF ❌"

    r1 = [InlineKeyboardButton(f"🔑 API Keys: {kt}", callback_data="m|key")]
    r2 = [
        InlineKeyboardButton(f"🎙️ Voice: {v_lbl}", callback_data="m|vmenu"),
        InlineKeyboardButton(f"🖼️ {lay}", callback_data="m|lay"),
    ]
    r3 = [
        InlineKeyboardButton(f"🌫️ Blur: {b_txt}", callback_data="m|blur"),
        InlineKeyboardButton(f"🏷️ Logo: {lg_t}", callback_data="m|logo"),
    ]
    r4 = [InlineKeyboardButton(f"🪞 Flip + Filter + Crop: {fl_t}", callback_data="m|f")]

    txt = "⚡ SIGYI AI STUDIO PRO (FAST TEXT SCRIPT) ⚡\n━━━━━━━━━━━━━━\n"
    txt += f"• 🔑 API Keys: {kt} (Auto-Rotation ✅)\n"
    txt += f"• 🎙️ Voice: {v_lbl} (Gemini Native TTS ✅)\n"
    txt += f"• 🖼️ {lay} | 🌫️ Blur: {b_txt}\n"
    txt += "• 🎯 FFmpeg Speed & Audio Sync: Active ✅\n━━━━━━━━━━━━━━\n"
    txt += "📥 TikTok / YouTube / Rednote Link သို့မဟုတ် Video ပို့ပါ!\n"
    txt += "💡 (Bot အလုပ်မလုပ်ပါက /start ကို နှိပ်ပါ)"
    return txt, InlineKeyboardMarkup([r1, r2, r3, r4])


def is_valid_video(p):
if not os.path.exists(p) or os.path.getsize(p) < 10000:
        return False
    r = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0", p
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return "video" in r.stdout.lower()


def is_valid_audio(p):
    if not os.path.exists(p) or os.path.getsize(p) < 600:
        return False
    r = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0", p
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return "audio" in r.stdout.lower()


def save_stream_url(dl_url, vpath, ua, ref=""):
    try:
        safe_execution(os.remove, vpath)
        hdrs = {"User-Agent": ua, **({"Referer": ref} if ref else {})}
        req = urllib.request.Request(dl_url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=20) as r, open(vpath, "wb") as f:
            while chunk := r.read(65536):
                f.write(chunk)
        if is_valid_video(vpath):
            return True
    except Exception:
        pass
    safe_execution(os.remove, vpath)
    return False


def download_video(url, vpath):
    url = url.strip().rstrip("，。、！!?,.;:)>\"'")
    ua_m = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
    ua_d = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    safe_execution(os.remove, vpath)
    res_u = (
        safe_execution(
            lambda: urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": ua_m}), timeout=8
            ).geturl()
        )
        or url
    )

    if "tiktok.com" in url.lower() or "tiktok.com" in res_u.lower():
        for tu in ([url, res_u] if res_u != url else [url]):
            api1 = f"https://www.tikwm.com/api/?url={urllib.parse.quote(tu)}&hd=1"
            resp1 = (
                safe_execution(
                    lambda: json.loads(
                        urllib.request.urlopen(
                            urllib.request.Request(api1, headers={"User-Agent": ua_m}),
                            timeout=10,
                        ).read().decode()
                    )
                )
                or {}
            )
            d1 = resp1.get("data") or {}
            for fk in ["play", "hdplay", "wmplay"]:
                if pu := d1.get(fk):
                    pu = "https://www.tikwm.com" + pu if pu.startswith("/") else pu
                    if save_stream_url(pu, vpath, ua_m, "https://www.tikwm.com/"):
                        return True

            api2 = f"https://api.tiklydown.eu.org/api/download?url={urllib.parse.quote(tu)}"
            d2 = (
                safe_execution(
                    lambda: json.loads(
                        urllib.request.urlopen(
                            urllib.request.Request(api2, headers={"User-Agent": ua_d}),
                            timeout=10,
                        ).read().decode()
                    )
                )
                or {}
            ).get("video", {})
            if (pu2 := (d2.get("noWatermark") or d2.get("watermark"))) and save_stream_url(pu2, vpath, ua_d):
                return True

        ydl_opts = {
            "format": "best",
            "outtmpl": vpath,
            "quiet": True,
            "no_warnings": True,
            "http_headers": {"User-Agent": ua_m},
        }
        safe_execution(lambda: yt_dlp.YoutubeDL(ydl_opts).download([url]))
        if is_valid_video(vpath):
            return True

    ym = re.search(r"(?:shorts/|v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})", res_u) or re.search(
        r"(?:shorts/|v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})", url
    )
    if ym:
        vid_id = ym.group(1)
        clean_yt = f"https://www.youtube.com/watch?v={vid_id}"
        ydl_opts = {
            "format": "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
            "outtmpl": vpath,
            "quiet": True,
            "nocheckcertificate": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android_vr", "android", "ios", "web"],
                    "skip": ["hls", "dash"],
                }
            },
            "http_headers": {"User-Agent": ua_d},
        }
        if os.path.exists("cookies.txt"):
            ydl_opts["cookiefile"] = "cookies.txt"
        safe_execution(lambda: yt_dlp.YoutubeDL(ydl_opts).download([clean_yt]))
        if is_valid_video(vpath):
            return True

        from pytubefix import YouTube
        for cli in ["ANDROID_VR", "IOS", "WEB_EMBED", "MWEB"]:
            try:
                yt = YouTube(clean_yt, client=cli)
                st = (
                    yt.streams.filter(progressive=True, file_extension="mp4")
                    .order_by("resolution")
                    .desc()
                    .first()
                )
                if st and safe_execution(lambda: st.download(filename=vpath)) and is_valid_video(vpath):
                    return True
            except Exception:
                continue

        u_os = f"https://p.oceansaver.in/ajax/download.php?format=720&url={urllib.parse.quote(clean_yt)}"
        tid = (
            safe_execution(
                lambda: json.loads(
                    urllib.request.urlopen(
                        urllib.request.Request(u_os, headers={"User-Agent": ua_d}),
                        timeout=10,
                    ).read().decode()
                )
            )
            or {}
        ).get("id")
        for _ in range(7 if tid else 0):
            time.sleep(2)
            dl_u = (
                safe_execution(
                    lambda: json.loads(
                        urllib.request.urlopen(
                            urllib.request.Request(
                                f"https://p.oceansaver.in/ajax/progress.php?id={tid}",
                                headers={"User-Agent": ua_d},
                            ),
                            timeout=8,
                        ).read().decode()
                    )
                )
                or {}
            ).get("download_url")
            if dl_u and save_stream_url(dl_u, vpath, ua_d):
                return True

    ydl_g = {
        "format": "best[ext=mp4]/best",
        "outtmpl": vpath,
        "quiet": True,
        "nocheckcertificate": True,
    }
    if os.path.exists("cookies.txt"):
        ydl_g["cookiefile"] = "cookies.txt"
    safe_execution(lambda: yt_dlp.YoutubeDL(ydl_g).download([url]))
    return is_valid_video(vpath)


def clean_mm_text(t):
    t = re.sub(r"\([^)]*\)", "", t)
    t = re.sub(r"[*#_`~0-9:a-zA-Z\[\]()|•\-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def get_duration(file_path):
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", file_path
    ]
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, text=True, stderr=subprocess.PIPE, timeout=15
        )
        value = float(result.stdout.strip())
        return value if 0 < value < float("inf") else 0.0
    except Exception:
        return 0.0


def extract_keyframes(vpath, vdur, count=4):
    frames = []
    for i in range(count):
        ts = max(0.0, min(vdur - 0.1, (vdur / (count + 1)) * (i + 1)))
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-ss", f"{ts:.2f}", "-i", vpath,
            "-frames:v", "1", "-vf", "scale=360:-2",
            "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"
        ]
        try:
            r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            if r.returncode == 0 and len(r.stdout) > 500:
                frames.append(types.Part.from_bytes(data=r.stdout, mime_type="image/jpeg"))
        except Exception:
            pass
    return frames


def get_working_models(client):
    discovered = []
    try:
        for m in client.models.list():
            name = str(getattr(m, "name", "") or "").removeprefix("models/")
            low = name.lower()
            if not name or "2.0-flash" in low or any(
                x in low for x in ["embedding", "tts", "image", "veo", "aqa", "audio"]
            ):
                continue
            actions = [str(a).lower() for a in (getattr(m, "supported_actions", None) or [])]
            if actions and not any("generatecontent" in a for a in actions):
                continue
            if "flash" in low or "pro" in low:
                discovered.append(name)
    except Exception:
        pass
    ordered = []
    for pm in DEFAULT_MODELS:
        if not discovered or pm in discovered:
            ordered.append(pm)
    for dm in discovered:
        if dm not in ordered:
            ordered.append(dm)
    for fm in DEFAULT_MODELS:
        if fm not in ordered:
            ordered.append(fm)
    return ordered


def ai_generate_fast_script(uid, vpath, vdur):
    u = get_u(uid)
    keys = u.get("keys", [])
    if not keys:
        raise RuntimeError("API Key မရှိပါ။")
    start_idx = u.get("k_idx", 0) % len(keys)
    target_chars = max(80, int(vdur * 11.0))
    frames = extract_keyframes(vpath, vdur, count=4)
    p = (
        f"ပေးထားသော ဗီဒီယိုပုံရိပ်များကို ကြည့်ပြီး ဗီဒီယိုကြာချိန် ({int(vdur)} စက္ကန့်) နှင့် လိုက်ဖက်သော "
        f"TikTok Professional Movie Recap ဇာတ်လမ်းပြော မြန်မာစာသား စုစုပေါင်း မြန်မာစာလုံးရေ {target_chars} လုံးခန့်ကို "
        "အပိုအလိုမရှိဘဲ အတိုဆုံးရေးပေးပါ။ (လူနာမည်များ မြန်မာလိုသာရေးပါ၊ အင်္ဂလိပ်စာ၊ ကွင်းစကွင်းပိတ်နှင့် နှုတ်ဆက်စကား လုံးဝ မထည့်ပါနှင့်)"
    )
    contents = [*frames, p] if frames else p
    raw_txt, last_err = "", None
    for step_i in range(len(keys)):
        k_i = (start_idx + step_i) % len(keys)
        client = genai.Client(
            api_key=keys[k_i].strip(), http_options=types.HttpOptions(timeout=30000)
        )
        candidate_models = get_working_models(client)
        for m_name in candidate_models:
            try:
                res = client.models.generate_content(model=m_name, contents=contents)
                if res and res.text:
                    raw_txt = res.text
                    set_u(uid, "k_idx", k_i)
                    break
            except Exception as me:
                last_err = me
        if raw_txt:
            break
    if not raw_txt:
        raise RuntimeError(f"Gemini Fast Script Error: {str(last_err)[:250]}")
    return clean_mm_text(raw_txt)


def _write_pcm_or_riff(pcm, wav_path):
    if pcm[:4] == b"RIFF":
        with open(wav_path, "wb") as f:
            f.write(pcm)
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


def generate_gemini_audio(script_text, output_audio_path, uid, voice_name="Zephyr"):
    u = get_u(uid)
    keys = u.get("keys", [])
    if not keys:
        raise RuntimeError("API Key မရှိပါ။")
    g_voice = voice_name if voice_name in VOICES else "Zephyr"
    pvc = types.PrebuiltVoiceConfig(voice_name=g_voice)
    sc = types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=pvc))
    cfg = types.GenerateContentConfig(response_modalities=["AUDIO"], speech_config=sc)
    prompt = f"Read the following Burmese movie recap narration aloud naturally and steadily without adding extra words:\n\n{script_text}"
    start_idx = u.get("k_idx", 0) % len(keys)
    last_err = None
    for attempt in range(2):
        for step_i in range(len(keys)):
            k_i = (start_idx + step_i) % len(keys)
            client = genai.Client(
                api_key=keys[k_i].strip(), http_options=types.HttpOptions(timeout=45000)
            )
            try:
                safe_execution(os.remove, output_audio_path)
                res = client.models.generate_content(
                    model=TTS_MODEL, contents=prompt, config=cfg
                )
                pcm = _extract_tts_pcm(res) if res else b""
                if pcm and len(pcm) > 1000:
                    _write_pcm_or_riff(pcm, output_audio_path)
                    if is_valid_audio(output_audio_path):
                        set_u(uid, "k_idx", k_i)
                        return True
            except Exception as e:
                last_err = e
                err_u = str(e).upper()
                if "404" in err_u or "NOT_FOUND" in err_u:
                    continue
        if attempt < 1:
            time.sleep(3)
    raise RuntimeError(f"Gemini TTS Error: {str(last_err)[:250]}")


def process_video_and_audio(input_video, audio_file, final_output, uid=None, u=None, audio_speed=1.18):
    """Low-RAM FFmpeg TikTok render supporting Flip/Filter/Crop, Subtitle Blur, Frame/Full Layout, and Logo."""
    if not isinstance(audio_speed, (int, float)) or not (0.5 <= audio_speed <= 2.0):
        raise ValueError(f"audio_speed 0.5 မှ 2.0 ကြား ဖြစ်ရပါမယ်: {audio_speed}")

    u = u or {}
    vid_duration = get_duration(input_video)
    aud_duration = get_duration(audio_file)

    if vid_duration <= 0 or aud_duration <= 0:
        raise ValueError(f"Video/Audio duration မမှန်ပါ: video={vid_duration}, audio={aud_duration}")

    target_duration = aud_duration / float(audio_speed)
    if target_duration <= 0 or not (target_duration < float('inf')):
        raise ValueError(f"Target duration မမှန်ပါ: {target_duration}")

    desired_pts = target_duration / vid_duration
    video_pts = min(max(desired_pts, 0.75), 1.12)

    fx = ",hflip,crop=iw*0.94:ih*0.94,eq=contrast=1.04:saturation=1.08" if u.get("f", True) else ""

    # Pre-scale input width to max 720px early to save RAM on 1080p/4K source clips
    fc = [
        f"[0:v]scale='min(720,iw)':-2,setpts={video_pts:.8f}*PTS,fps=30,"
        f"tpad=stop_mode=clone:stop_duration={target_duration:.6f},"
        f"trim=duration={target_duration:.6f},setpts=PTS-STARTPTS{fx},setsar=1[v_prep]"
    ]

    cur_v = "v_prep"
    blur_mode = u.get("blur", "auto")
    blur_y_map = {"auto": "0.76", "low": "0.80", "mid": "0.68", "high": "0.52"}

    if blur_mode in blur_y_map:
        by = blur_y_map[blur_mode]
        fc.append(
            f"[{cur_v}]split[vb_main][vb_src];"
            f"[vb_src]crop=iw:ih*0.16:0:ih*{by},boxblur=10:1[vb_bar];"
            f"[vb_main][vb_bar]overlay=0:H*{by}[v_sub]"
        )
        cur_v = "v_sub"

    if u.get("layout", "frame") == "full":
        fc.append(f"[{cur_v}]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280[v_lay]")
    else:
        # Downscale background to 180x320 before blurring, then scale back to 720x1280 (saves ~70% RAM/CPU)
        fc.append(
            f"[{cur_v}]split[bg][fg];"
            f"[bg]scale=180:320:force_original_aspect_ratio=increase,crop=180:320,boxblur=6:1,scale=720:1280[bg_blur];"
            f"[fg]scale=720:1280:force_original_aspect_ratio=decrease[fg_scaled];"
            f"[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2:shortest=1[v_lay]"
        )

    cur_v = "v_lay"
    logo_path = f"logo_{uid}.jpg" if uid else ""
    use_logo = bool(u.get("logo", True) and logo_path and os.path.exists(logo_path))

    if use_logo:
        fc.append(f"[2:v]scale=130:-1[lg];[{cur_v}][lg]overlay=30:40,format=yuv420p[v]")
    else:
        fc.append(f"[{cur_v}]format=yuv420p[v]")

    fc.append(f"[1:a]atempo={float(audio_speed):.6f},aresample=async=1:first_pts=0[a]")

    filter_complex = ";".join(fc)
    inputs = ['-i', input_video, '-i', audio_file] + (['-i', logo_path] if use_logo else [])

    # -threads 1 and -filter_complex_threads 1 keep Railway container RAM usage minimal
    cmd = [
        'ffmpeg', '-hide_banner', '-y', '-loglevel', 'warning',
        '-filter_complex_threads', '1',
        *inputs,
        '-filter_complex', filter_complex,
        '-map', '[v]', '-map', '[a]', '-t', f'{target_duration:.6f}',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
        '-threads', '1', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart',
        final_output
    ]

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=600)
        if result.returncode != 0:
            logging.error(f"FFmpeg Stderr: {result.stderr}")
            tail = (result.stderr or "FFmpeg က အသေးစိတ် error မပြန်ပေးပါ။")[-2000:]
            raise RuntimeError(f"FFmpeg render failed (exit={result.returncode}): {tail}")

        if not os.path.exists(final_output) or os.path.getsize(final_output) <= 0:
            raise RuntimeError("FFmpeg output ဖိုင် မထွက်လာပါ။")

        return True
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("FFmpeg render အချိန်ကျော်သွားပါတယ်။ (Memory မလုံလောက်လို့ ဖြစ်နိုင်ပါတယ်)") from e
    except MemoryError:
        raise RuntimeError("Memory မလုံလောက်ပါ။ Railway Plan ကို Upgrade လုပ်ဖို့ လိုအပ်ပါတယ်။")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cancel_user_task(uid)
    u = get_u(uid)
    if not u.get("verified") or not (await check_joined(context.bot, uid)):
        set_u(uid, "verified", False)
        await update.message.reply_text(
            join_text(), reply_markup=join_kb(), disable_web_page_preview=True
        )
        return
    await update.message.reply_text(
        "👋 Sigyi Ai Studio မှ ကြိုဆိုပါတယ်! (Fast Script + FFmpeg Ready ✅)",
        reply_markup=main_kb(),
    )
    txt, kb = dash_ui(u, uid)
    await update.message.reply_text(txt, reply_markup=kb)


async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_u(uid)
    if not u.get("verified") or not (await check_joined(context.bot, uid)):
        set_u(uid, "verified", False)
        await update.message.reply_text(
            join_text(), reply_markup=join_kb(), disable_web_page_preview=True
        )
        return

    if update.message.photo:
        f = await context.bot.get_file(update.message.photo[-1].file_id)
        await f.download_to_drive(f"logo_{uid}.jpg")
        set_u(uid, "logo", True)
        txt, kb = dash_ui(get_u(uid), uid)
        await update.message.reply_text(
            "✅ Logo ပုံ သိမ်းဆည်းပြီးပါပြီ!\n\n" + txt, reply_markup=kb
        )
        return

    t = (update.message.text or "").strip()
    if t in ["🎬 Dashboard", "🔑 API Key", "🎙️ Voice ရွေးရန်", "🖼️ Logo ပုံထည့်ရန်"]:
        if t == "🖼️ Logo ပုံထည့်ရန်":
            await update.message.reply_text(
                "🖼️ ဘယ်ဘက်အပေါ်ထောင့်မှာ ထည့်ချင်တဲ့ Logo ပုံ (Photo) ကို ပို့ပေးပါ။"
            )
            return
        txt, kb = (
            dash_ui(u, uid)
            if t == "🎬 Dashboard"
            else (key_menu_ui(u) if t == "🔑 API Key" else voice_menu_ui(u))
        )
        await update.message.reply_text(txt, reply_markup=kb)
        return

    um = re.search(r"https?://[^\s，。、！!\"'<>]+", t)
    p_keys = extract_keys(t) if not um else []
    if p_keys:
        added, total = add_user_keys(uid, p_keys)
        safe_execution(lambda: asyncio.create_task(update.message.delete()))
        txt, kb = dash_ui(get_u(uid), uid)
        await context.bot.send_message(
            uid,
            f"✅ API Key ({added}) ခု အသစ်ထပ်ပေါင်းပြီး စုစုပေါင်း ({total}) ခု သိမ်းဆည်းပြီးပါပြီ!\n\n" + txt,
            reply_markup=kb,
        )
        return

    if not u.get("keys"):
        txt, kb = key_menu_ui(u)
        await update.message.reply_text(
            "🔒 Gemini API Key အရင်ထည့်ပေးပါ!\n\n" + txt, reply_markup=kb
        )
        return

    cancel_user_task(uid)
    msg = await update.message.reply_text(
        "⏳ [15%] Video ဆွဲယူနေပါတယ်...\n💡 (အကယ်၍ ရပ်နေပါက /start နှိပ်ပါ)",
        reply_markup=cancel_kb(),
    )
    vpath = f"in_{uid}.mp4"
    try:
        if um:
            ok = await asyncio.wait_for(
                asyncio.to_thread(download_video, um.group(0), vpath), timeout=120
            )
            if not ok:
                raise RuntimeError("Video Link ဒေါင်းယူ၍ မရပါ။")
        if not um and (update.message.video or update.message.document):
            v = update.message.video or update.message.document
            f = await context.bot.get_file(v.file_id)
            await f.download_to_drive(vpath)
        if not is_valid_video(vpath):
            await msg.edit_text(
                "❌ Video ဖိုင် မမှန်ကန်ပါ သို့မဟုတ် Video Link ပို့ပါ!\n💡 (Bot အလုပ်မလုပ်ပါက /start နှိပ်ပါ)"
            )
            return
        SESSIONS[uid] = vpath
        txt, kb = dash_ui(u, uid)
        btn = InlineKeyboardButton(
            f"🚀 START RENDER (🌟 {u['v']} | Fast Sync)", callback_data="r|go"
        )
        await msg.edit_text(
            "🎬 Video ရပြီ! စတင်ရန် START RENDER ကို နှိပ်ပါ -\n\n" + txt,
            reply_markup=InlineKeyboardMarkup(list(kb.inline_keyboard) + [[btn]]),
        )
    except Exception as e:
        err_m = str(e).strip() or type(e).__name__
        await msg.edit_text(
            f"❌ Download Error: {err_m}\n\n💡 Bot အလုပ်မလုပ်ပါက /start ကို နှိပ်ပါ။"
        )


async def run_render_job(q, context, uid):
    u, vpath = get_u(uid), SESSIONS.get(uid)
    sm_v, apath, opath = f"sm_{uid}.mp4", f"aud_{uid}.wav", f"out_{uid}.mp4"
    gemini_tmp = f"gemini_{uid}.wav"
    hint = "\n\n💡 ရပ်နေပါက /start နှိပ်ပြီး video ပြန်ပို့ပါ"
    stage = "စတင်နေပါသည်"
    try:
        if not vpath or not is_valid_video(vpath):
            raise RuntimeError("Input video မမှန်ကန်ပါ")
        vdur = min(max(1.0, get_duration(vpath)), 180.0)
        stage = "Gemini fast script generation"
        await q.edit_message_text(
            f"🔄 [30%] Video အရှည် ({int(vdur)}s) အတွက် TikTok Pro Recap ဇာတ်လမ်းကို အမြန်ဆုံး ထုတ်ယူနေပါသည်...{hint}",
            reply_markup=cancel_kb(),
        )
        script_text = await asyncio.wait_for(
            asyncio.to_thread(ai_generate_fast_script, uid, vpath, vdur), timeout=60
        )
        stage = "Gemini TTS voice generation"
        await q.edit_message_text(
            f"🔄 [60%] 🎙️ Gemini AI ({u['v']}) ဖြင့် အသံ ထုတ်ယူနေပါသည်...{hint}",
            reply_markup=cancel_kb(),
        )
        try:
            ok_a = await asyncio.wait_for(
                asyncio.to_thread(
                    generate_gemini_audio, script_text, gemini_tmp, uid, u["v"]
                ),
                timeout=180,
            )
            if not ok_a or not is_valid_audio(gemini_tmp):
                raise RuntimeError("Gemini TTS အသံထုတ်မရပါ။")
            os.replace(gemini_tmp, apath)
        except (asyncio.TimeoutError, Exception) as tts_err:
            logging.warning(f"Gemini TTS failed/timed out; switching to gTTS: {tts_err}")
            await q.edit_message_text(
                f"⚠️ Gemini TTS အချိန်ကြာနေသဖြင့် gTTS ဖြင့် အသံထုတ်နေပါသည်...{hint}",
                reply_markup=cancel_kb(),
            )
            safe_execution(os.remove, apath)
            await asyncio.to_thread(
                gTTS(text=script_text, lang="my", slow=False).save, apath
            )
            if not is_valid_audio(apath):
                raise RuntimeError("Gemini TTS နှင့် gTTS နှစ်မျိုးလုံး အသံမထုတ်နိုင်ပါ။")

        stage = "FFmpeg video/audio sync"
        await q.edit_message_text(
            f"🔄 [85%] FFmpeg ဖြင့် Video နှင့် အသံ ကွက်တိပေါင်းနေပါသည်...{hint}",
            reply_markup=cancel_kb(),
        )
        await asyncio.wait_for(
            asyncio.to_thread(
                process_video_and_audio, vpath, apath, opath, uid, get_u(uid)
            ),
            timeout=610,
        )
        if not is_valid_video(opath):
            raise RuntimeError("FFmpeg Render မအောင်မြင်ပါ။")

        await q.edit_message_text("📤 [98%] Video ပို့ပေးနေပါတယ်...")
        with open(opath, "rb") as vf:
            await context.bot.send_video(
                uid,
                vf,
                caption="✅ ပြီးပါပြီ။\nPowered by SiGyi Ai Studio",
                read_timeout=300,
                write_timeout=300,
            )
        await q.delete_message()
    except asyncio.CancelledError:
        pass
    except asyncio.TimeoutError:
        safe_execution(
            lambda: asyncio.create_task(
                q.edit_message_text(
                    f"❌ {stage} အဆင့်မှာ အချိန်ကျော်သွားပါတယ်။ /start နှိပ်ပြီး ပြန်စမ်းပေးပါ။"
                )
            )
        )
    except Exception as e:
        err = str(e).strip() or type(e).__name__
        safe_execution(
            lambda: asyncio.create_task(
                q.edit_message_text(
                    f"❌ {stage} Error: {err[:800]}\n\n💡 /start နှိပ်ပြီး ပြန်စမ်းပါ"
                )
            )
        )
    finally:
        ACTIVE_TASKS.pop(uid, None)
        SESSIONS.pop(uid, None)
        for p in [vpath, sm_v, apath, opath, gemini_tmp, opath + "_temp_aud.m4a"]:
            if p and os.path.exists(p):
                safe_execution(os.remove, p)


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
        await context.bot.send_message(
            uid,
            "🎉 Verify အောင်မြင်ပါပြီ! Sigyi Ai Studio ကို စတင်အသုံးပြုနိုင်ပါပြီ။",
            reply_markup=main_kb(),
        )
        txt, kb = dash_ui(get_u(uid), uid)
        await q.edit_message_text(txt, reply_markup=kb)
        return

    if cat == "r" and act == "cancel":
        cancel_user_task(uid)
        await q.answer("🛑 ရပ်တန့်လိုက်ပါပြီ!")
        txt, kb = dash_ui(get_u(uid), uid)
        await q.edit_message_text(
            "🛑 လုပ်ငန်းစဉ်ကို ရပ်တန့်ပြီး Reset လုပ်ပေးထားပါသည်။\n\n" + txt,
            reply_markup=kb,
        )
        return

    if not u.get("verified") or not (await check_joined(context.bot, uid)):
        set_u(uid, "verified", False)
        await q.answer("🔒 Channel (၃) ခုကို အရင် Join ပေးပါ!", show_alert=True)
        await q.edit_message_text(
            join_text(), reply_markup=join_kb(), disable_web_page_preview=True
        )
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

    if cat == "m" and act == "lay":
        set_u(uid, "layout", "full" if u.get("layout", "frame") == "frame" else "frame")
    elif cat == "m" and act == "blur":
        modes = ["auto", "low", "mid", "high", "off"]
        cur_b = u.get("blur", "auto")
        set_u(
            uid,
            "blur",
            modes[(modes.index(cur_b) + 1) % len(modes)] if cur_b in modes else "auto",
        )
    elif cat == "m" and act == "logo":
        set_u(uid, "logo", not u.get("logo", True))
    elif cat == "m" and act == "f":
        set_u(uid, "f", not u.get("f", True))

    if cat == "v" and act in VOICES:
        set_u(uid, "v", act)

    if cat in ["v", "m"]:
        u_new = get_u(uid)
        txt, kb = dash_ui(u_new, uid)
        rows = list(kb.inline_keyboard)
        if uid in SESSIONS and os.path.exists(SESSIONS[uid]):
            rows.append([
                InlineKeyboardButton(
                    f"🚀 START RENDER (🌟 {u_new['v']} | Fast Sync)",
                    callback_data="r|go",
                )
            ])
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(rows))
        return

    if cat == "r" and act == "go":
        if uid not in SESSIONS or not os.path.exists(SESSIONS[uid]):
            await q.edit_message_text(
                "⚠️ Video အသစ် ပြန်ပို့ပါ။ (Bot အလုပ်မလုပ်ပါက /start နှိပ်ပါ)"
            )
            return
        if not u.get("keys"):
            txt, kb = key_menu_ui(u)
            await q.edit_message_text(
                "🔒 API Key အရင်ထည့်ပေးပါ!\n\n" + txt, reply_markup=kb
            )
            return
        if (old_t := ACTIVE_TASKS.pop(uid, None)) and not old_t.done():
            old_t.cancel()
        ACTIVE_TASKS[uid] = asyncio.create_task(run_render_job(q, context, uid))


def main():
    if not TOKEN:
        raise RuntimeError("Railway Variables ထဲ TELEGRAM_BOT_TOKEN မသတ်မှတ်ရသေးပါ။")
    app = (
        Application.builder()
        .token(TOKEN)
        .concurrent_updates(True)
        .read_timeout(240)
        .write_timeout(240)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(
            filters.PHOTO
            | filters.VIDEO
            | filters.Document.VIDEO
            | (filters.TEXT & ~filters.COMMAND),
            handle_msg,
        )
    )
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.run_polling()


if __name__ == "__main__":
    main()