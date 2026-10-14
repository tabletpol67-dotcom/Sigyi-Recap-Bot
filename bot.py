import re; CODE = r"""
@0 import os, re, sys, site, json, time, wave, base64, shutil, zipfile, asyncio, subprocess, urllib.request, urllib.parse, logging
@0 from pathlib import Path
@0 from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
@0 logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
@0 for pkg in ["yt-dlp[default,curl-cffi]", "pytubefix", "btch-downloader"]:
@1 subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", pkg], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
@0 def setup_pot_server():
@1 try:
@2 pot_bin = "/tmp/bgutil-pot"
@2 if not os.path.exists(pot_bin):
@3 urllib.request.urlretrieve("https://github.com/jim60105/bgutil-ytdlp-pot-provider-rs/releases/latest/download/bgutil-pot-linux-x86_64", pot_bin)
@3 os.chmod(pot_bin, 0o755)
@3 z_p = "/tmp/pot_plugin.zip"
@3 urllib.request.urlretrieve("https://github.com/jim60105/bgutil-ytdlp-pot-provider-rs/releases/latest/download/bgutil-ytdlp-pot-provider-rs.zip", z_p)
@3 with zipfile.ZipFile(z_p, "r") as zf:
@4 zf.extractall(site.getsitepackages()[0])
@2 subprocess.Popen([pot_bin, "server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
@2 os.environ["YT_DLP_POT_PROVIDER_URL"] = "http://127.0.0.1:4416"
@1 except Exception as e:
@2 logging.error(f"POT Server Setup Error: {e}")
@0 setup_pot_server()
@0 from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
@0 from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
@0 from google import genai
@0 from google.genai import types
@0 import yt_dlp
@0 TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
@0 DB_FILE = "users.json"
@0 SESSIONS, ACTIVE_TASKS = {}, {}
@0 VOICES = ["Zephyr", "Charon", "Puck", "Kore", "Fenrir", "Aoede", "Leda", "Orus", "Callirrhoe", "Autonoe"]
@0 C1 = ("@moviezone336", "https://t.me/moviezone336", "📢 Channel 1 Join ရန်")
@0 C2 = ("@color6777", "https://t.me/color6777", "📢 Channel 2 Join ရန်")
@0 C3 = ("@sigyi89", "https://t.me/sigyi89", "📢 Channel 3 Join ရန်")
@0 CHANNELS = [C1, C2, C3]
@0 DEFAULT_MODELS = ["gemini-3.8-flash", "gemini-1.5-flash", "gemini-2.5-flash", "gemini-1.5-pro", "gemini-3-flash-preview", "gemini-3.1-flash-lite"]
@0 TTS_MODEL = "gemini-2.5-flash-preview-tts"
@0 def safe_execution(func, *args, **kwargs):
@1 try:
@2 return func(*args, **kwargs)
@1 except Exception as e:
@2 logging.error(f"Error in {getattr(func, '__name__', 'fn')}: {str(e)}")
@2 return None
@0 def get_db():
@1 if os.path.exists(DB_FILE):
@2 return safe_execution(lambda: json.load(open(DB_FILE))) or {}
@1 return {}
@0 def get_u(uid):
@1 db, k = get_db(), str(uid)
@1 d = db.get(k, {})
@1 keys = d.get("keys", []) or ([d["key"]] if d.get("key") else [])
@1 raw_v = d.get("v", "Zephyr")
@1 v = "Charon" if raw_v == "Thiha" else ("Zephyr" if raw_v == "Nilar" else (raw_v if raw_v in VOICES else "Zephyr"))
@1 if k not in db or "keys" not in d or d.get("v") not in VOICES:
@2 db[k] = {"keys": keys, "k_idx": d.get("k_idx", 0), "v": v, "f": d.get("f", True), "layout": d.get("layout", "frame"), "blur": d.get("blur", "auto"), "logo": d.get("logo", True), "verified": d.get("verified", False)}
@2 safe_execution(lambda: json.dump(db, open(DB_FILE, "w")))
@1 return db[k]
@0 def set_u(uid, field, val):
@1 db, k = get_db(), str(uid)
@1 if k not in db:
@2 get_u(uid)
@2 db = get_db()
@1 db[k][field] = val
@1 safe_execution(lambda: json.dump(db, open(DB_FILE, "w")))
@0 def cancel_user_task(uid):
@1 t = ACTIVE_TASKS.pop(uid, None)
@1 if t and not t.done():
@2 t.cancel()
@1 for f in os.listdir("."):
@2 if str(uid) in f and not f.startswith("logo_"):
@3 safe_execution(os.remove, f)
@1 SESSIONS.pop(uid, None)
@0 def extract_keys(text):
@1 raw = re.split(r"[\s,;]+", text.strip())
@1 return [x.strip() for x in raw if len(x.strip()) >= 20 and not x.startswith(("http", "/")) and (x.startswith(("AIza", "AQ.")) or re.match(r"^[A-Za-z0-9_\-\.]{25,}$", x.strip()))]
@0 def add_user_keys(uid, new_keys):
@1 cur = list(get_u(uid).get("keys", []))
@1 added = sum(1 for nk in new_keys if nk not in cur and not cur.append(nk))
@1 set_u(uid, "keys", cur)
@1 return added, len(cur)
@0 async def check_joined(bot, uid):
@1 for ch_id, _, _ in CHANNELS:
@2 try:
@3 m = await bot.get_chat_member(chat_id=ch_id, user_id=uid)
@3 if m.status in ["left", "kicked"]:
@4 return False
@2 except Exception:
@3 continue
@1 return True
@0 def join_kb():
@1 rows = [[InlineKeyboardButton(lbl, url=url)] for _, url, lbl in CHANNELS]
@1 rows.append([InlineKeyboardButton("✅ Join ပြီးပါပြီ (Verify လုပ်မည်)", callback_data="verify|check")])
@1 return InlineKeyboardMarkup(rows)
@0 def join_text():
@1 return "🔒 Bot ကို အသုံးပြုရန် အောက်ပါ Channel (၃) ခုကို အရင် Join ပေးပါ -\n\n1️⃣ https://t.me/moviezone336\n2️⃣ https://t.me/color6777\n3️⃣ https://t.me/sigyi89\n\n✅ (၃) ခုလုံး Join ပြီးပါက အောက်ပါ Verify ခလုတ်ကို နှိပ်ပါ -"
@0 def main_kb():
@1 r1 = [KeyboardButton("🎬 Dashboard"), KeyboardButton("🔑 API Key")]
@1 r2 = [KeyboardButton("🎙️ Voice ရွေးရန်"), KeyboardButton("🖼️ Logo ပုံထည့်ရန်")]
@1 return ReplyKeyboardMarkup([r1, r2, [KeyboardButton("/start")]], resize_keyboard=True)
@0 def cancel_kb():
@1 return InlineKeyboardMarkup([[InlineKeyboardButton("🛑 ရပ်တန့်မည် / ပြန်စမည် (/start)", callback_data="r|cancel")]])
@0 def key_menu_ui(u):
@1 keys = u.get("keys", [])
@1 lines = [f"{i+1}. {k[:6]}••••{k[-4:]}" for i, k in enumerate(keys[:10])]
@1 k_info = f"✅ သိမ်းထားသော Key ({len(keys)}) ခု -\n" + "\n".join(lines) if keys else "❌ API Key မထည့်ရသေးပါ။"
@1 txt = f"🔑 GEMINI API KEY ROTATION စနစ်\n━━━━━━━━━━━━━━\n{k_info}\n\n💡 Key တစ်ခုချင်းဖြစ်စေ၊ အများကြီးကို Comma (,) ခြားပြီးဖြစ်စေ ပို့နိုင်ပါသည်။\n⚠️ Bot အလုပ်မလုပ်ပါက /start ကို နှိပ်ပါ။"
@1 kb = [[InlineKeyboardButton("🌐 Google AI Studio မှ Key ယူရန်", url="https://aistudio.google.com/app/apikey")]]
@1 if keys:
@2 kb.append([InlineKeyboardButton("🗑️ Key အားလုံး ဖျက်မည်", callback_data="m|clrkeys")])
@1 kb.append([InlineKeyboardButton("🔙 Dashboard သို့ ပြန်သွားရန်", callback_data="m|dash")])
@1 return txt, InlineKeyboardMarkup(kb)
@0 def voice_menu_ui(u):
@1 cur = u.get("v", "Zephyr")
@1 txt = f"🎙️ Gemini AI Voice (၁၀) မျိုး ရွေးချယ်ရန် (Speed: 1.18x)\nလက်ရှိအသံ - 🌟 {cur}\n━━━━━━━━━━━━━━"
@1 kb, row = [], []
@1 for v in VOICES:
@2 row.append(InlineKeyboardButton(f"{'🟢' if cur==v else '⚪'} 🌟 {v}", callback_data=f"v|{v}"))
@2 if len(row) == 2:
@3 kb.append(row)
@3 row = []
@1 if row:
@2 kb.append(row)
@1 kb.append([InlineKeyboardButton("🔙 Dashboard သို့ ပြန်သွားရန်", callback_data="m|dash")])
@1 return txt, InlineKeyboardMarkup(kb)
@0 def dash_ui(u, uid):
@1 k_cnt = len(u.get("keys", []))
@1 kt = f"✅ ({k_cnt}) ခု ချိတ်ပြီး" if k_cnt > 0 else "❌ မရှိသေးပါ"
@1 v_lbl = f"🌟 {u.get('v', 'Zephyr')} (1.18x)"
@1 lay = "📱 Blur Frame" if u.get("layout", "frame") == "frame" else "📲 Full Screen"
@1 bm = {"auto": "🎯 Auto-Detect", "low": "အောက်ခြေ", "mid": "အလယ်အောက်", "high": "အလယ်", "off": "OFF ❌"}
@1 b_txt = bm.get(u.get("blur", "auto"), "🎯 Auto-Detect")
@1 lg_t = ("ON ✅" if u.get("logo", True) else "OFF ❌") if os.path.exists(f"logo_{uid}.jpg") else "ပုံမထည့်ရသေး"
@1 fl_t = "ON ✅" if u.get("f", True) else "OFF ❌"
@1 r1 = [InlineKeyboardButton(f"🔑 API Keys: {kt}", callback_data="m|key")]
@1 r2 = [InlineKeyboardButton(f"🎙️ Voice: {v_lbl}", callback_data="m|vmenu"), InlineKeyboardButton(f"🖼️ {lay}", callback_data="m|lay")]
@1 r3 = [InlineKeyboardButton(f"🌫️ Blur: {b_txt}", callback_data="m|blur"), InlineKeyboardButton(f"🏷️ Logo: {lg_t}", callback_data="m|logo")]
@1 r4 = [InlineKeyboardButton(f"🪞 Flip + Filter + Crop: {fl_t}", callback_data="m|f")]
@1 txt = "⚡ SIGYI AI STUDIO PRO (PERFECT CFR SYNC) ⚡\n━━━━━━━━━━━━━━\n"
@1 txt += f"• 🔑 API Keys: {kt} (Auto-Rotation ✅)\n"
@1 txt += "• 🤖 Model: gemini-3.8-flash / 1.5-flash (Auto ✅)\n"
@1 txt += f"• 🎙️ Voice: {v_lbl} (Pure Gemini TTS ✅)\n"
@1 txt += f"• 🖼️ {lay} | 🌫️ Blur: {b_txt}\n"
@1 txt += "• 🎯 CFR 30fps + 1.18x Audio Perfect Sync: Active ✅\n━━━━━━━━━━━━━━\n"
@1 txt += "📥 TikTok / YouTube / Rednote Link သို့မဟုတ် Video ပို့ပါ!\n"
@1 txt += "💡 (Bot အလုပ်မလုပ်ပါက /start ကို နှိပ်ပါ)"
@1 return txt, InlineKeyboardMarkup([r1, r2, r3, r4])
@0 def is_valid_video(p):
@1 if not os.path.exists(p) or os.path.getsize(p) < 10000:
@2 return False
@1 r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", p], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
@1 return "video" in r.stdout.lower()
@0 def is_valid_audio(p):
@1 if not os.path.exists(p) or os.path.getsize(p) < 600:
@2 return False
@1 r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", p], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
@1 return "audio" in r.stdout.lower()
@0 def save_stream_url(dl_url, vpath, ua, ref=""):
@1 try:
@2 safe_execution(os.remove, vpath)
@2 hdrs = {"User-Agent": ua, **({"Referer": ref} if ref else {})}
@2 with urllib.request.urlopen(urllib.request.Request(dl_url, headers=hdrs), timeout=20) as r, open(vpath, "wb") as f:
@3 while chunk := r.read(65536):
@4 f.write(chunk)
@2 if is_valid_video(vpath):
@3 return True
@1 except Exception:
@2 pass
@1 safe_execution(os.remove, vpath)
@1 return False
@0 def download_video(url, vpath):
@1 url = url.strip().rstrip("，。、！!?,.;:)>\"'")
@1 ua_m = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
@1 ua_d = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
@1 safe_execution(os.remove, vpath)
@1 res_u = safe_execution(lambda: urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": ua_m}), timeout=8).geturl()) or url
@1 if "tiktok.com" in url.lower() or "tiktok.com" in res_u.lower():
@2 for tu in ([url, res_u] if res_u != url else [url]):
@3 api1 = f"https://www.tikwm.com/api/?url={urllib.parse.quote(tu)}&hd=1"
@3 resp1 = safe_execution(lambda: json.loads(urllib.request.urlopen(urllib.request.Request(api1, headers={"User-Agent": ua_m}), timeout=10).read().decode())) or {}
@3 d1 = resp1.get("data") or {}
@3 for fk in ["play", "hdplay", "wmplay"]:
@4 if pu := d1.get(fk):
@5 pu = "https://www.tikwm.com" + pu if pu.startswith("/") else pu
@5 if save_stream_url(pu, vpath, ua_m, "https://www.tikwm.com/"):
@6 return True
@3 api2 = f"https://api.tiklydown.eu.org/api/download?url={urllib.parse.quote(tu)}"
@3 d2 = (safe_execution(lambda: json.loads(urllib.request.urlopen(urllib.request.Request(api2, headers={"User-Agent": ua_d}), timeout=10).read().decode())) or {}).get("video", {})
@3 if (pu2 := (d2.get("noWatermark") or d2.get("watermark"))) and save_stream_url(pu2, vpath, ua_d):
@4 return True
@2 ydl_opts = {'format': 'best', 'outtmpl': vpath, 'quiet': True, 'no_warnings': True, 'http_headers': {'User-Agent': ua_m}}
@2 safe_execution(lambda: yt_dlp.YoutubeDL(ydl_opts).download([url]))
@2 if is_valid_video(vpath):
@3 return True
@1 ym = re.search(r"(?:shorts/|v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})", res_u) or re.search(r"(?:shorts/|v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})", url)
@1 if ym:
@2 vid_id = ym.group(1)
@2 clean_yt = f"https://www.youtube.com/watch?v={vid_id}"
@2 ydl_opts = {'format': 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best', 'merge_output_format': 'mp4', 'outtmpl': vpath, 'quiet': True, 'nocheckcertificate': True, 'extractor_args': {'youtube': {'player_client': ['android_vr', 'android', 'ios', 'web'], 'skip': ['hls', 'dash']}}, 'http_headers': {'User-Agent': ua_d}}
@2 if os.path.exists('cookies.txt'):
@3 ydl_opts['cookiefile'] = 'cookies.txt'
@2 safe_execution(lambda: yt_dlp.YoutubeDL(ydl_opts).download([clean_yt]))
@2 if is_valid_video(vpath):
@3 return True
@2 from pytubefix import YouTube
@2 for cli in ["ANDROID_VR", "IOS", "WEB_EMBED", "MWEB"]:
@3 try:
@4 yt = YouTube(clean_yt, client=cli)
@4 st = yt.streams.filter(progressive=True, file_extension="mp4").order_by("resolution").desc().first()
@4 if st and safe_execution(lambda: st.download(filename=vpath)) and is_valid_video(vpath):
@5 return True
@3 except Exception:
@4 continue
@2 u_os = f"https://p.oceansaver.in/ajax/download.php?format=720&url={urllib.parse.quote(clean_yt)}"
@2 tid = (safe_execution(lambda: json.loads(urllib.request.urlopen(urllib.request.Request(u_os, headers={"User-Agent": ua_d}), timeout=10).read().decode())) or {}).get("id")
@2 for _ in range(7 if tid else 0):
@3 time.sleep(2)
@3 dl_u = (safe_execution(lambda: json.loads(urllib.request.urlopen(urllib.request.Request(f"https://p.oceansaver.in/ajax/progress.php?id={tid}", headers={"User-Agent": ua_d}), timeout=8).read().decode())) or {}).get("download_url")
@3 if dl_u and save_stream_url(dl_u, vpath, ua_d):
@4 return True
@1 ydl_g = {'format': 'best[ext=mp4]/best', 'outtmpl': vpath, 'quiet': True, 'nocheckcertificate': True}
@1 if os.path.exists('cookies.txt'):
@2 ydl_g['cookiefile'] = 'cookies.txt'
@1 safe_execution(lambda: yt_dlp.YoutubeDL(ydl_g).download([url]))
@1 return is_valid_video(vpath)
@0 def clean_mm_text(t):
@1 t = re.sub(r"\([^)]*\)", "", t)
@1 t = re.sub(r"[*#_`~0-9:a-zA-Z\[\]()|•\-]", " ", t)
@1 return re.sub(r"\s+", " ", t).strip()
@0 def get_duration(file_path):
@1 cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
@1 try:
@2 result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, stderr=subprocess.PIPE, timeout=15)
@2 return float(result.stdout.strip())
@1 except Exception:
@2 return 0.0
@0 def get_intro_silence(video_path):
@1 cmd = ['ffmpeg', '-t', '5', '-i', video_path, '-af', 'silencedetect=noise=-30dB:d=0.35', '-f', 'null', '-']
@1 r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
@1 st_m = re.search(r"silence_start:\s*([0-9.]+)", r.stderr)
@1 en_m = re.search(r"silence_end:\s*([0-9.]+)", r.stderr)
@1 if st_m and en_m and float(st_m.group(1)) <= 0.20:
@2 return min(2.5, max(0.0, float(en_m.group(1))))
@1 return 0.0
@0 def get_working_models(client):
@1 discovered = []
@1 try:
@2 for m in client.models.list():
@3 name = str(getattr(m, "name", "") or "").removeprefix("models/")
@3 low = name.lower()
@3 if not name or "2.0-flash" in low or any(x in low for x in ["embedding", "tts", "image", "veo", "aqa", "audio"]):
@4 continue
@3 actions = [str(a).lower() for a in (getattr(m, "supported_actions", None) or [])]
@3 if actions and not any("generatecontent" in a for a in actions):
@4 continue
@3 if "flash" in low or "pro" in low:
@4 discovered.append(name)
@1 except Exception:
@2 pass
@1 ordered = []
@1 for pm in DEFAULT_MODELS:
@2 if not discovered or pm in discovered:
@3 ordered.append(pm)
@1 for dm in discovered:
@2 if dm not in ordered:
@3 ordered.append(dm)
@1 for fm in DEFAULT_MODELS:
@2 if fm not in ordered:
@3 ordered.append(fm)
@1 return ordered
@0 def ai_frame_audio_translate(vpath, sm_v, uid, vdur, intro_delay):
@1 cmd_sm = ["ffmpeg", "-y", "-threads", "4", "-i", vpath, "-t", f"{vdur:.2f}", "-vf", "fps=1,scale=240:-2", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "36", "-c:a", "aac", "-ac", "1", "-ar", "16000", "-b:a", "24k", sm_v]
@1 subprocess.run(cmd_sm, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
@1 up_file = sm_v if (os.path.exists(sm_v) and os.path.getsize(sm_v) > 1000) else vpath
@1 u = get_u(uid)
@1 keys = u.get("keys", [])
@1 if not keys:
@2 raise RuntimeError("API Key မရှိပါ။ Key အရင်ထည့်ပေးပါ။")
@1 start_idx = u.get("k_idx", 0) % len(keys)
@1 speech_dur = max(4.0, vdur - intro_delay)
@1 target_chars = max(90, min(650, int(speech_dur * 11.2)))
@1 max_chars_cap = max(130, min(750, int(speech_dur * 13.0)))
@1 p = f"ဒီ Video ဖိုင်ရဲ့ ရုပ်ပုံ (Frames) နဲ့ မူရင်းအသံ (Audio) ကို သေချာကြည့်ရှုနားထောင်ပြီး အပိုအလိုမရှိဘဲ TikTok မှာ ခေတ်စားနေတဲ့ Burmese Professional Movie Recap စကားပြောပုံစံဖြင့် စာပိုဒ်တစ်ပိုဒ်တည်း ဘာသာပြန်ပေးပါ။\n"
@1 p += "ဥပမာ အရေးအသား - အမျိုးသားတစ်ယောက်ဟာ လှေပေါ်မှာ ဓားနဲ့ ကစားနေရင်း မတော်တဆ အပေါက်ဖောက်မိသွားတဲ့အတွက် ရေတွေ စတင် စိမ့်ဝင်လာပါတယ်။ သူက သူ့ခြေထောက်နဲ့ အပေါက်ကို အမြန်ဖုံးအုပ်ပြီး ဘာမှမဖြစ်သလို ဟန်ဆောင်လိုက်ပါတယ်။ ခေါင်းဆောင်က အန်နာ ဆီကို လျှောက်သွားပြီး ငါးမျှားတံကို ကောက်ကိုင်ကာ ငါးဖမ်းဟန်ဆောင်လိုက်ပါတယ်။\n"
@1 p += f"စည်းကမ်းချက် - Video အရှည် ({int(vdur)} စက္ကန့်) နှင့် ကွက်တိဖြစ်စေရန် စုစုပေါင်း မြန်မာစာလုံးရေ {target_chars} လုံးခန့်သာ (အများဆုံး {max_chars_cap} လုံးထက် မပိုရ) တိကျစွာ ရေးပေးပါ။ လူနာမည်များကို မြန်မာလိုသာရေးပါ၊ အင်္ဂလိပ်စာ၊ ကွင်းစကွင်းပိတ်နှင့် နှုတ်ဆက်စကား လုံးဝ မထည့်ပါနှင့်။"
@1 raw_txt, last_err = "", None
@1 for step_i in range(len(keys)):
@2 k_i = (start_idx + step_i) % len(keys)
@2 client = genai.Client(api_key=keys[k_i].strip())
@2 candidate_models = get_working_models(client)
@2 uf = safe_execution(lambda: client.files.upload(file=up_file))
@2 if not uf:
@3 continue
@2 for _ in range(45):
@3 if getattr(getattr(uf, "state", None), "name", "") == "PROCESSING":
@4 time.sleep(1)
@4 uf = safe_execution(lambda: client.files.get(name=uf.name)) or uf
@2 for m_name in candidate_models:
@3 try:
@4 res = client.models.generate_content(model=m_name, contents=[uf, p])
@4 if res and res.text:
@5 raw_txt = res.text
@5 set_u(uid, "k_idx", k_i)
@5 break
@3 except Exception as me:
@4 err_s = str(me).upper()
@4 if "404" in err_s or "NOT_FOUND" in err_s or "NO LONGER AVAILABLE" in err_s:
@5 continue
@4 last_err = me
@2 safe_execution(lambda: client.files.delete(name=uf.name))
@2 if raw_txt:
@3 break
@1 if not raw_txt:
@2 raise RuntimeError(f"Gemini Script Error: {str(last_err)[:350]}")
@1 cleaned = clean_mm_text(raw_txt)
@1 sents = [s.strip() + "။" for s in cleaned.split("။") if len(s.strip()) > 3]
@1 final_sents, cur_len = [], 0
@1 for s in sents:
@2 if cur_len + len(s) <= max_chars_cap or not final_sents:
@3 final_sents.append(s)
@3 cur_len += len(s)
@2 else:
@3 break
@1 return " ".join(final_sents) if final_sents else cleaned[:max_chars_cap]
@0 def _write_pcm_or_riff(pcm, wav_path):
@1 if pcm[:4] == b"RIFF":
@2 open(wav_path, "wb").write(pcm)
@2 return
@1 with wave.open(wav_path, "wb") as wf:
@2 wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(24000); wf.writeframes(pcm)
@0 def _extract_tts_pcm(res):
@1 pcm = b""
@1 for part in res.candidates[0].content.parts:
@2 if getattr(part, "inline_data", None) and part.inline_data.data:
@3 d = part.inline_data.data
@3 pcm += base64.b64decode(d) if isinstance(d, str) else d
@1 return pcm
@0 def _single_tts_worker(api_key, voice_name, text, out_wav):
@1 client = genai.Client(api_key=api_key)
@1 pvc = types.PrebuiltVoiceConfig(voice_name=voice_name)
@1 sc = types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=pvc))
@1 cfg = types.GenerateContentConfig(response_modalities=["AUDIO"], speech_config=sc)
@1 prompt = f"Read this Burmese narration aloud naturally and steadily without adding extra words:\n{text}"
@1 res = client.models.generate_content(model=TTS_MODEL, contents=prompt, config=cfg)
@1 pcm = _extract_tts_pcm(res) if res else b""
@1 if pcm and len(pcm) > 800:
@2 safe_execution(os.remove, out_wav)
@2 _write_pcm_or_riff(pcm, out_wav)
@2 return is_valid_audio(out_wav)
@1 return False
@0 def _call_gemini_tts_bounded(text, voice_name, out_wav, uid, key_offset=0):
@1 u = get_u(uid)
@1 keys = u.get("keys", [])
@1 if not keys:
@2 raise RuntimeError("API Key မရှိပါ။")
@1 g_voice = voice_name if voice_name in VOICES else "Zephyr"
@1 start_idx = (u.get("k_idx", 0) + key_offset) % len(keys)
@1 last_err = None
@1 for attempt in range(2):
@2 for step_i in range(len(keys)):
@3 k_i = (start_idx + step_i) % len(keys)
@3 ex = ThreadPoolExecutor(max_workers=1)
@3 fut = ex.submit(_single_tts_worker, keys[k_i].strip(), g_voice, text, out_wav)
@3 try:
@4 ok = fut.result(timeout=28)
@4 ex.shutdown(wait=False)
@4 if ok and is_valid_audio(out_wav):
@5 set_u(uid, "k_idx", k_i)
@5 return True
@3 except FuturesTimeout:
@4 ex.shutdown(wait=False)
@4 last_err = "Gemini TTS Server 28s Timeout"
@3 except Exception as e:
@4 ex.shutdown(wait=False)
@4 last_err = str(e)
@2 if attempt == 0:
@3 time.sleep(3)
@1 raise RuntimeError(f"Gemini TTS ({g_voice}) Error: {str(last_err)[:240]} (API Key Quota စစ်ပါ သို့မဟုတ် Key အသစ်ထပ်ထည့်ပါ)")
@0 def generate_gemini_narration(script_text, voice_name, out_a, uid):
@1 work = f"tts_{uid}_{int(time.time() * 1000)}"
@1 os.makedirs(work, exist_ok=True)
@1 try:
@2 sents = [s.strip() + "။" for s in script_text.split("။") if len(s.strip()) > 2]
@2 if len(script_text) <= 320 or len(sents) <= 2:
@3 chunks = [script_text]
@2 else:
@3 mid = max(1, len(sents) // 2)
@3 chunks = [" ".join(sents[:mid]), " ".join(sents[mid:])]
@2 wav_parts = []
@2 for idx, ch in enumerate(chunks):
@3 rw = os.path.join(work, f"part_{idx}.wav")
@3 cw = os.path.join(work, f"clean_{idx}.wav")
@3 _call_gemini_tts_bounded(ch, voice_name, rw, uid, idx + 1)
@3 af = "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,areverse,highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=24000,asetpts=PTS-STARTPTS"
@3 subprocess.run(["ffmpeg", "-y", "-i", rw, "-af", af, "-ac", "1", "-ar", "24000", cw], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
@3 wav_parts.append(cw if is_valid_audio(cw) else rw)
@2 if len(wav_parts) == 1:
@3 subprocess.run(["ffmpeg", "-y", "-i", wav_parts[0], "-c:a", "aac", "-b:a", "160k", out_a], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
@2 else:
@3 list_f = os.path.join(work, "concat.txt")
@3 Path(list_f).write_text("".join(f"file '{os.path.abspath(w)}'\n" for w in wav_parts), encoding="utf-8")
@3 subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_f, "-c:a", "aac", "-b:a", "160k", out_a], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
@2 if not is_valid_audio(out_a):
@3 raise RuntimeError("Audio encode failed")
@2 return True
@1 finally:
@2 safe_execution(shutil.rmtree, work, True)
@0 def detect_sub_band(iv, vdur, is_fr, uid):
@1 raw_f = f"subdet_{uid}.raw"
@1 w, h = 360, (410 if is_fr else 640)
@1 vf = f"fps=6/{max(2.0, vdur):.2f},crop=iw*0.92:ih*0.92:iw*0.04:ih*0.04,scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
@1 subprocess.run(["ffmpeg", "-y", "-threads", "1", "-i", iv, "-vf", vf, "-frames:v", "6", "-f", "rawvideo", "-pix_fmt", "gray", raw_f], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
@1 dy, dh = (950, 86) if is_fr else (1040, 92)
@1 if not os.path.exists(raw_f):
@2 return dy, dh
@1 data = open(raw_f, "rb").read()
@1 safe_execution(os.remove, raw_f)
@1 n_f = len(data) // (w * h)
@1 if n_f < 1:
@2 return dy, dh
@1 ys, ye, scores = int(h * 0.56), int(h * 0.96), [0.0] * h
@1 for f_i in range(n_f):
@2 b = f_i * w * h
@2 for y in range(ys, ye):
@3 ro = b + y * w
@3 hits = sum(1 for x in range(int(w * 0.15), int(w * 0.85), 2) if abs(data[ro + x] - data[ro + x - 2]) > 40)
@3 if hits > 8:
@4 scores[y] += hits
@1 by_i = max(range(ys, ye - 16), key=lambda y: sum(scores[y:y + 16]), default=-1)
@1 if by_i < 0 or sum(scores[by_i:by_i + 16]) < 25 * n_f:
@2 return dy, dh
@1 out_c = int((by_i + 8) * 2.0) + (230 if is_fr else 0)
@1 return max(240 if is_fr else 100, min((1050 - dh) if is_fr else (1240 - dh), out_c - int(dh * 0.46))), dh
@0 def render_perfect_sync(video_path, audio_path, output_path, u, uid, intro_delay=0.0, audio_speed=1.18):
@1 vid_dur = min(max(1.0, get_duration(video_path)), 180.0)
@1 aud_dur = get_duration(audio_path)
@1 if vid_dur == 0 or aud_dur == 0:
@2 raise RuntimeError("Video သို့မဟုတ် Audio ဖိုင် ပျက်နေပါသည်။")
@1 eff_speed = audio_speed
@1 new_aud_dur = intro_delay + (aud_dur / eff_speed)
@1 max_allowed_dur = vid_dur * 1.18
@1 min_allowed_dur = vid_dur * 0.92
@1 if new_aud_dur > max_allowed_dur:
@2 eff_speed = min(1.38, aud_dur / max(1.0, max_allowed_dur - intro_delay))
@2 new_aud_dur = intro_delay + (aud_dur / eff_speed)
@1 elif new_aud_dur < min_allowed_dur:
@2 eff_speed = max(1.05, aud_dur / max(1.0, min_allowed_dur - intro_delay))
@2 new_aud_dur = intro_delay + (aud_dur / eff_speed)
@1 video_pts_factor = new_aud_dur / vid_dur if vid_dur > 0 else 1.0
@1 is_fr, fl = (u.get("layout", "frame") == "frame"), (",hflip" if u.get("f") else "")
@1 adj = "crop=iw*0.92:ih*0.92:iw*0.04:ih*0.04,eq=contrast=1.08:brightness=0.02:saturation=1.14:gamma=1.03,hue=h=3,unsharp=3:3:0.65:3:3:0.0"
@1 b_map = {"low": (950, 86), "mid": (880, 86), "high": (790, 86)} if is_fr else {"low": (1040, 92), "mid": (940, 92), "high": (830, 92)}
@1 by, bh = detect_sub_band(video_path, vid_dur, is_fr, uid) if u.get("blur") == "auto" else b_map.get(u.get("blur"), (950, 86))
@1 by, bh = (int(by) // 2) * 2, max(64, (int(bh) // 2) * 2)
@1 v_filt = f"trim=duration={vid_dur:.3f},setpts={video_pts_factor:.6f}*(PTS-STARTPTS),fps=30"
@1 fc = f"[0:v]{v_filt}{fl}[v0];"
@1 if is_fr:
@2 fc += f"[v0]split=2[bgi][fgi];[bgi]scale=180:320:force_original_aspect_ratio=increase,crop=180:320,gblur=sigma=14,eq=brightness=-0.07,scale=720:1280[bg];[fgi]{adj},scale=720:820:force_original_aspect_ratio=increase:flags=lanczos,crop=720:820[fg];[bg][fg]overlay=0:230[v1]"
@1 else:
@2 fc += f"[v0]{adj},scale=720:1280:force_original_aspect_ratio=increase:flags=lanczos,crop=720:1280[v1]"
@1 cur = "[v1]"
@1 if u.get("blur") != "off":
@2 fc += f";{cur}split=2[m1][m2];[m2]crop=640:{bh}:40:{by},gblur=sigma=26[bst];[m1][bst]overlay=40:{by}[v2]"
@2 cur = "[v2]"
@1 inputs, logo_p = ["-i", video_path, "-i", audio_path], f"logo_{uid}.jpg"
@1 if u.get("logo") and os.path.exists(logo_p):
@2 inputs.extend(["-i", logo_p])
@2 ly = 165 if is_fr else 80
@2 fc += f";[2:v]scale=110:110[lg];{cur}[lg]overlay=12:{ly}[v3]"
@2 cur = "[v3]"
@1 delay_ms = int(intro_delay * 1000)
@1 a_filt = f"atempo={eff_speed:.4f},adelay={delay_ms}|{delay_ms},asetpts=PTS-STARTPTS" if delay_ms > 150 else f"atempo={eff_speed:.4f},asetpts=PTS-STARTPTS"
@1 fc += f";{cur}format=yuv420p[v];[1:a]{a_filt}[a]"
@1 safe_execution(os.remove, output_path)
@1 cmd = ["ffmpeg", "-y", "-threads", "4"] + inputs + ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "superfast", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", "-fs", "47M", output_path]
@1 r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=max(240, int(new_aud_dur * 4)))
@1 if r.returncode != 0 or not is_valid_video(output_path):
@2 raise RuntimeError(f"Render Error: {r.stderr[-500:]}")
@1 return True
@0 async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
@1 uid = update.effective_user.id
@1 cancel_user_task(uid)
@1 u = get_u(uid)
@1 if not u.get("verified") or not (await check_joined(context.bot, uid)):
@2 set_u(uid, "verified", False)
@2 await update.message.reply_text(join_text(), reply_markup=join_kb(), disable_web_page_preview=True)
@2 return
@1 await update.message.reply_text("👋 Sigyi Ai Studio မှ ကြိုဆိုပါတယ်! (System Ready ✅)", reply_markup=main_kb())
@1 txt, kb = dash_ui(u, uid)
@1 await update.message.reply_text(txt, reply_markup=kb)
@0 async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
@1 uid = update.effective_user.id
@1 u = get_u(uid)
@1 if not u.get("verified") or not (await check_joined(context.bot, uid)):
@2 set_u(uid, "verified", False)
@2 await update.message.reply_text(join_text(), reply_markup=join_kb(), disable_web_page_preview=True)
@2 return
@1 if update.message.photo:
@2 f = await context.bot.get_file(update.message.photo[-1].file_id)
@2 await f.download_to_drive(f"logo_{uid}.jpg")
@2 set_u(uid, "logo", True)
@2 txt, kb = dash_ui(get_u(uid), uid)
@2 await update.message.reply_text("✅ Logo ပုံ သိမ်းဆည်းပြီးပါပြီ!\n\n" + txt, reply_markup=kb)
@2 return
@1 t = (update.message.text or "").strip()
@1 if t in ["🎬 Dashboard", "🔑 API Key", "🎙️ Voice ရွေးရန်", "🖼️ Logo ပုံထည့်ရန်"]:
@2 if t == "🖼️ Logo ပုံထည့်ရန်":
@3 await update.message.reply_text("🖼️ ဘယ်ဘက်အပေါ်ထောင့်မှာ ထည့်ချင်တဲ့ Logo ပုံ (Photo) ကို ပို့ပေးပါ။")
@3 return
@2 txt, kb = dash_ui(u, uid) if t == "🎬 Dashboard" else (key_menu_ui(u) if t == "🔑 API Key" else voice_menu_ui(u))
@2 await update.message.reply_text(txt, reply_markup=kb)
@2 return
@1 um = re.search(r"https?://[^\s，。、！!\"'<>]+", t)
@1 p_keys = extract_keys(t) if not um else []
@1 if p_keys:
@2 added, total = add_user_keys(uid, p_keys)
@2 safe_execution(lambda: asyncio.create_task(update.message.delete()))
@2 txt, kb = dash_ui(get_u(uid), uid)
@2 await context.bot.send_message(uid, f"✅ API Key ({added}) ခု အသစ်ထပ်ပေါင်းပြီး စုစုပေါင်း ({total}) ခု သိမ်းဆည်းပြီးပါပြီ!\n\n" + txt, reply_markup=kb)
@2 return
@1 if not u.get("keys"):
@2 txt, kb = key_menu_ui(u)
@2 await update.message.reply_text("🔒 Gemini API Key အရင်ထည့်ပေးပါ!\n\n" + txt, reply_markup=kb)
@2 return
@1 cancel_user_task(uid)
@1 msg = await update.message.reply_text("⏳ [15%] Video ဆွဲယူနေပါတယ်...\n💡 (အကယ်၍ ရပ်နေပါက /start နှိပ်ပါ)", reply_markup=cancel_kb())
@1 vpath = f"in_{uid}.mp4"
@1 try:
@2 if um:
@3 ok = await asyncio.wait_for(asyncio.to_thread(download_video, um.group(0), vpath), timeout=120)
@3 if not ok:
@4 raise RuntimeError("Video Link ဒေါင်းယူ၍ မရပါ။")
@2 if not um and (update.message.video or update.message.document):
@3 v = update.message.video or update.message.document
@3 f = await context.bot.get_file(v.file_id)
@3 await f.download_to_drive(vpath)
@2 if not is_valid_video(vpath):
@3 await msg.edit_text("❌ Video ဖိုင် မမှန်ကန်ပါ သို့မဟုတ် Video Link ပို့ပါ!\n💡 (Bot အလုပ်မလုပ်ပါက /start နှိပ်ပါ)")
@3 return
@2 SESSIONS[uid] = vpath
@2 txt, kb = dash_ui(u, uid)
@2 btn = InlineKeyboardButton(f"🚀 START RENDER (🌟 {u['v']} 1.18x | Perfect Sync)", callback_data="r|go")
@2 await msg.edit_text("🎬 Video ရပြီ! စတင်ရန် START RENDER ကို နှိပ်ပါ -\n\n" + txt, reply_markup=InlineKeyboardMarkup(list(kb.inline_keyboard) + [[btn]]))
@1 except Exception as e:
@2 err_m = str(e).strip() or type(e).__name__
@2 await msg.edit_text(f"❌ Download Error: {err_m}\n\n💡 Bot အလုပ်မလုပ်ပါက /start ကို နှိပ်ပါ။")
@0 async def run_render_job(q, context, uid):
@1 u, vpath = get_u(uid), SESSIONS.get(uid)
@1 sm_v, apath, opath = f"sm_{uid}.mp4", f"aud_{uid}.m4a", f"out_{uid}.mp4"
@1 hint = "\n\n💡 ရပ်နေပါက /start နှိပ်ပြီး video ပြန်ပို့ပါ"
@1 stage = "စတင်နေပါသည်"
@1 try:
@2 if not vpath or not is_valid_video(vpath):
@3 raise RuntimeError("Input video မမှန်ကန်ပါ")
@2 vdur = min(max(1.0, get_duration(vpath)), 180.0)
@2 intro_delay = get_intro_silence(vpath)
@2 stage = "Gemini scene analysis"
@2 await q.edit_message_text(f"🔄 [30%] Video အရှည် ({int(vdur)}s) နှင့် ကွက်တိ TikTok Pro Recap Script ရေးသားနေပါသည်...{hint}", reply_markup=cancel_kb())
@2 script_text = await asyncio.wait_for(asyncio.to_thread(ai_frame_audio_translate, vpath, sm_v, uid, vdur, intro_delay), timeout=90)
@2 stage = "Gemini TTS voice generation"
@2 await q.edit_message_text(f"🔄 [60%] 🎙️ Gemini AI ({u['v']}) ဖြင့် အသံသွင်းနေပါသည်...{hint}", reply_markup=cancel_kb())
@2 await asyncio.wait_for(asyncio.to_thread(generate_gemini_narration, script_text, u["v"], apath, uid), timeout=95)
@2 stage = "FFmpeg video/audio render"
@2 await q.edit_message_text(f"🔄 [85%] CFR 30fps + 1.18x Audio Perfect Sync Render လုပ်နေပါသည်...{hint}", reply_markup=cancel_kb())
@2 await asyncio.wait_for(asyncio.to_thread(render_perfect_sync, vpath, apath, opath, u, uid, intro_delay, 1.18), timeout=max(240, int(vdur * 4)))
@2 await q.edit_message_text("📤 [98%] Ultra HD Video ပို့ပေးနေပါတယ်...")
@2 with open(opath, "rb") as vf:
@3 await context.bot.send_video(uid, vf, caption="✅ ပြီးပါပြီ။\nPowered by SiGyi Ai Studio", read_timeout=300, write_timeout=300)
@2 await q.delete_message()
@1 except asyncio.CancelledError:
@2 pass
@1 except asyncio.TimeoutError:
@2 safe_execution(lambda: asyncio.create_task(q.edit_message_text(f"❌ {stage} အဆင့်မှာ အချိန်ကျော်သွားပါတယ်။ /start နှိပ်ပြီး ပြန်စမ်းပေးပါ။")))
@1 except Exception as e:
@2 err = str(e).strip() or type(e).__name__
@2 safe_execution(lambda: asyncio.create_task(q.edit_message_text(f"❌ {stage} Error: {err[:800]}\n\n💡 /start နှိပ်ပြီး ပြန်စမ်းပါ")))
@1 finally:
@2 ACTIVE_TASKS.pop(uid, None)
@2 SESSIONS.pop(uid, None)
@2 for p in [vpath, sm_v, apath, opath]:
@3 if p and os.path.exists(p):
@4 safe_execution(os.remove, p)
@0 async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
@1 q = update.callback_query
@1 uid, u = q.from_user.id, get_u(q.from_user.id)
@1 cat, act = q.data.split("|")
@1 if cat == "verify":
@2 if not (await check_joined(context.bot, uid)):
@3 await q.answer("❌ Channel (၃) ခုလုံးကို အရင် Join ပေးပါ!", show_alert=True)
@3 return
@2 set_u(uid, "verified", True)
@2 await q.answer("✅ Verify အောင်မြင်ပါပြီ!")
@2 await context.bot.send_message(uid, "🎉 Verify အောင်မြင်ပါပြီ! Sigyi Ai Studio ကို စတင်အသုံးပြုနိုင်ပါပြီ။", reply_markup=main_kb())
@2 txt, kb = dash_ui(get_u(uid), uid)
@2 await q.edit_message_text(txt, reply_markup=kb)
@2 return
@1 if cat == "r" and act == "cancel":
@2 cancel_user_task(uid)
@2 await q.answer("🛑 ရပ်တန့်လိုက်ပါပြီ!")
@2 txt, kb = dash_ui(get_u(uid), uid)
@2 await q.edit_message_text("🛑 လုပ်ငန်းစဉ်ကို ရပ်တန့်ပြီး Reset လုပ်ပေးထားပါသည်။\n\n" + txt, reply_markup=kb)
@2 return
@1 if not u.get("verified") or not (await check_joined(context.bot, uid)):
@2 set_u(uid, "verified", False)
@2 await q.answer("🔒 Channel (၃) ခုကို အရင် Join ပေးပါ!", show_alert=True)
@2 await q.edit_message_text(join_text(), reply_markup=join_kb(), disable_web_page_preview=True)
@2 return
@1 await q.answer()
@1 if cat == "m" and act in ["key", "vmenu"]:
@2 txt, kb = key_menu_ui(u) if act == "key" else voice_menu_ui(u)
@2 await q.edit_message_text(txt, reply_markup=kb)
@2 return
@1 if cat == "m" and act == "clrkeys":
@2 set_u(uid, "keys", [])
@2 set_u(uid, "k_idx", 0)
@2 txt, kb = key_menu_ui(get_u(uid))
@2 await q.edit_message_text(txt, reply_markup=kb)
@2 return
@1 if cat == "v" and act in VOICES:
@2 set_u(uid, "v", act)
@1 if cat == "m" and act in ["lay", "blur", "logo", "f"]:
@2 bm = ["auto", "low", "mid", "high", "off"]
@2 if act == "lay":
@3 set_u(uid, "layout", "full" if u["layout"] == "frame" else "frame")
@2 if act == "blur":
@3 set_u(uid, "blur", bm[(bm.index(u["blur"] if u["blur"] in bm else "auto") + 1) % len(bm)])
@2 if act == "logo":
@3 set_u(uid, "logo", not u["logo"])
@2 if act == "f":
@3 set_u(uid, "f", not u["f"])
@1 if cat in ["v", "m"]:
@2 u_new = get_u(uid)
@2 txt, kb = dash_ui(u_new, uid)
@2 rows = list(kb.inline_keyboard)
@2 if uid in SESSIONS and os.path.exists(SESSIONS[uid]):
@3 rows.append([InlineKeyboardButton(f"🚀 START RENDER (🌟 {u_new['v']} 1.18x | Perfect Sync)", callback_data="r|go")])
@2 await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(rows))
@2 return
@1 if cat == "r" and act == "go":
@2 if uid not in SESSIONS or not os.path.exists(SESSIONS[uid]):
@3 await q.edit_message_text("⚠️ Video အသစ် ပြန်ပို့ပါ။ (Bot အလုပ်မလုပ်ပါက /start နှိပ်ပါ)")
@3 return
@2 if (old_t := ACTIVE_TASKS.pop(uid, None)) and not old_t.done():
@3 old_t.cancel()
@2 ACTIVE_TASKS[uid] = asyncio.create_task(run_render_job(q, context, uid))
@0 def main():
@1 if not TOKEN:
@2 raise RuntimeError("Railway Variables ထဲ TELEGRAM_BOT_TOKEN မသတ်မှတ်ရသေးပါ။")
@1 app = Application.builder().token(TOKEN).concurrent_updates(True).read_timeout(240).write_timeout(240).build()
@1 app.add_handler(CommandHandler("start", start))
@1 app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.VIDEO | (filters.TEXT & ~filters.COMMAND), handle_msg))
@1 app.add_handler(CallbackQueryHandler(cb_handler))
@1 app.run_polling()
@0 if __name__ == "__main__":
@1 main()
"""; exec(compile("\n".join("    "*int(m[1])+m[2] for l in CODE.splitlines() if (m:=re.match(r"^\s*@(\d)\s(.*)$",l))),"bot.py","exec"),globals())