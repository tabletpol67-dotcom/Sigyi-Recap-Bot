import re; CODE = r"""
@0 import os, re, sys, site, json, time, wave, base64, shutil, zipfile, asyncio, subprocess, urllib.request, urllib.parse, logging
@0 from pathlib import Path
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
@0 VOICES = ["Zephyr", "Charon", "Kore", "Puck", "Fenrir"]
@0 C1 = ("@moviezone336", "https://t.me/moviezone336", "📢 Channel 1 Join ရန်")
@0 C2 = ("@color6777", "https://t.me/color6777", "📢 Channel 2 Join ရန်")
@0 C3 = ("@sigyi89", "https://t.me/sigyi89", "📢 Channel 3 Join ရန်")
@0 CHANNELS = [C1, C2, C3]
@0 RAW_M = os.getenv("GEMINI_MODELS", "gemini-2.5-flash,gemini-2.0-flash").split(",")
@0 MODELS = [x.strip().removeprefix("models/") for x in RAW_M if x.strip() and "flash" in x.lower()] or ["gemini-2.5-flash", "gemini-2.0-flash"]
@0 TTS_MODELS = ["gemini-2.5-flash-preview-tts", "gemini-3.1-flash-tts-preview"]
@0 def safe_execution(func, *args, **kwargs):
@1 try:
@2 return func(*args, **kwargs)
@1 except Exception as e:
@2 logging.error(f"Error in {func.__name__}: {str(e)}")
@2 return None
@0 def get_db():
@1 if os.path.exists(DB_FILE):
@2 return safe_execution(lambda: json.load(open(DB_FILE))) or {}
@1 return {}
@0 def get_u(uid):
@1 db, k = get_db(), str(uid)
@1 d = db.get(k, {})
@1 keys = d.get("keys", []) or ([d["key"]] if d.get("key") else [])
@1 v = d.get("v", "Zephyr") if d.get("v") in VOICES else "Zephyr"
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
@1 txt = f"🔑 GEMINI API KEY ROTATION စနစ်\n━━━━━━━━━━━━━━\n{k_info}\n\n"
@1 txt += "💡 Key တစ်ခုချင်းဖြစ်စေ၊ အများကြီးကို Comma (,) ခြားပြီးဖြစ်စေ ပို့နိုင်ပါသည်။\n"
@1 txt += "⚠️ Bot အလုပ်မလုပ်ပါက /start ကို နှိပ်ပါ။"
@1 kb = [[InlineKeyboardButton("🌐 Google AI Studio မှ Key ယူရန်", url="https://aistudio.google.com/app/apikey")]]
@1 if keys:
@2 kb.append([InlineKeyboardButton("🗑️ Key အားလုံး ဖျက်မည်", callback_data="m|clrkeys")])
@1 kb.append([InlineKeyboardButton("🔙 Dashboard သို့ ပြန်သွားရန်", callback_data="m|dash")])
@1 return txt, InlineKeyboardMarkup(kb)
@0 def voice_menu_ui(u):
@1 cur = u.get("v", "Zephyr")
@1 txt = f"🎙️ Google AI Voice ရွေးချယ်ရန် (Speed: 1.25x)\nလက်ရှိအသံ - 🌟 {cur}\n━━━━━━━━━━━━━━"
@1 r1 = [InlineKeyboardButton(f"{'🟢' if cur=='Zephyr' else '⚪'} 🌟 Zephyr (Female)", callback_data="v|Zephyr"), InlineKeyboardButton(f"{'🟢' if cur=='Charon' else '⚪'} 🌟 Charon (Male)", callback_data="v|Charon")]
@1 r2 = [InlineKeyboardButton(f"{'🟢' if cur=='Kore' else '⚪'} 🌟 Kore (Female)", callback_data="v|Kore"), InlineKeyboardButton(f"{'🟢' if cur=='Puck' else '⚪'} 🌟 Puck (Male)", callback_data="v|Puck")]
@1 r3 = [InlineKeyboardButton(f"{'🟢' if cur=='Fenrir' else '⚪'} 🌟 Fenrir (Deep Male)", callback_data="v|Fenrir")]
@1 r4 = [InlineKeyboardButton("🔙 Dashboard သို့ ပြန်သွားရန်", callback_data="m|dash")]
@1 return txt, InlineKeyboardMarkup([r1, r2, r3, r4])
@0 def dash_ui(u, uid):
@1 k_cnt = len(u.get("keys", []))
@1 kt = f"✅ ({k_cnt}) ခု ချိတ်ပြီး" if k_cnt > 0 else "❌ မရှိသေးပါ"
@1 v_lbl = f"🌟 {u.get('v', 'Zephyr')} (1.25x)"
@1 lay = "📱 Blur Frame" if u["layout"] == "frame" else "📲 Full Screen"
@1 bm = {"auto": "🎯 Auto-Detect", "low": "အောက်ခြေ", "mid": "အလယ်အောက်", "high": "အလယ်", "off": "OFF ❌"}
@1 b_txt = bm.get(u["blur"], "🎯 Auto-Detect")
@1 lg_t = ("ON ✅" if u["logo"] else "OFF ❌") if os.path.exists(f"logo_{uid}.jpg") else "ပုံမထည့်ရသေး"
@1 fl_t = "ON ✅" if u["f"] else "OFF ❌"
@1 kb = [
@2 [InlineKeyboardButton(f"🔑 API Keys: {kt}", callback_data="m|key")],
@2 [InlineKeyboardButton(f"🎙️ Voice: {v_lbl}", callback_data="m|vmenu"), InlineKeyboardButton(f"🖼️ {lay}", callback_data="m|lay")],
@2 [InlineKeyboardButton(f"🌫️ Blur: {b_txt}", callback_data="m|blur"), InlineKeyboardButton(f"🏷️ Logo: {lg_t}", callback_data="m|logo")],
@2 [InlineKeyboardButton(f"🪞 Flip + Filter + Crop: {fl_t}", callback_data="m|f")]
@1 ]
@1 txt = "⚡ SIGYI AI STUDIO PRO (ULTRA HD) ⚡\n━━━━━━━━━━━━━━\n"
@1 txt += f"• 🔑 API Keys: {kt} (Auto-Rotation ✅)\n"
@1 txt += "• 🤖 AI: Gemini Flash + Google AI TTS ✅\n"
@1 txt += f"• 🎙️ Voice: {v_lbl} | 📺 Ultra HD\n"
@1 txt += f"• 🖼️ {lay} | 🌫️ Blur: {b_txt}\n"
@1 txt += "• 🎯 Scene-Locked Frame Sync: Active ✅\n━━━━━━━━━━━━━━\n"
@1 txt += "📥 TikTok / YouTube / Rednote Link သို့မဟုတ် Video ပို့ပါ!\n"
@1 txt += "💡 (Bot အလုပ်မလုပ်ပါက /start ကို နှိပ်ပါ)"
@1 return txt, InlineKeyboardMarkup(kb)
@0 def is_valid_video(p):
@1 if not os.path.exists(p) or os.path.getsize(p) < 10000:
@2 return False
@1 cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", p]
@1 r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
@1 return "video" in r.stdout.lower()
@0 def is_valid_audio(p):
@1 if not os.path.exists(p) or os.path.getsize(p) < 600:
@2 return False
@1 cmd = ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", p]
@1 r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
@1 return "audio" in r.stdout.lower()
@0 def save_stream_url(dl_url, vpath, ua, ref=""):
@1 try:
@2 safe_execution(os.remove, vpath)
@2 hdrs = {"User-Agent": ua, **({"Referer": ref} if ref else {})}
@2 with urllib.request.urlopen(urllib.request.Request(dl_url, headers=hdrs), timeout=25) as r, open(vpath, "wb") as f:
@3 while chunk := r.read(65536):
@4 f.write(chunk)
@2 if is_valid_video(vpath):
@3 return True
@1 except Exception as e:
@2 logging.error(f"Download Stream Error: {e}")
@1 safe_execution(os.remove, vpath)
@1 return False
@0 def find_mp4(obj):
@1 if isinstance(obj, str) and obj.startswith("http"):
@2 if not any(b in obj.lower() for b in [".mp3", ".m4a", ".jpg", ".png", ".webp", ".jpeg"]):
@3 if any(x in obj.lower() for x in [".mp4", "video", "play", "stream", "xhscdn", "googlevideo", "tikcdn", "aweme"]):
@4 return obj
@2 return None
@1 if isinstance(obj, dict):
@2 for k in ["play", "hdplay", "noWatermark", "video", "url", "download", "mp4", "url_list", "data", "result"]:
@3 if k in obj and (r := find_mp4(obj[k])):
@4 return r
@2 for v in obj.values():
@3 if r := find_mp4(v):
@4 return r
@1 if isinstance(obj, list):
@2 for item in obj:
@3 if r := find_mp4(item):
@4 return r
@1 return None
@0 def download_youtube_ytdlp(url, vpath, ua):
@1 opts = {
@2 'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
@2 'outtmpl': vpath,
@2 'quiet': True, 'no_warnings': True, 'nocheckcertificate': True,
@2 'extractor_args': {'youtube': {'player_client': ['android', 'web', 'ios'], 'skip': ['hls', 'dash']}},
@2 'http_headers': {'User-Agent': ua, 'Accept-Language': 'en-US,en;q=0.9'}
@1 }
@1 if os.path.exists('cookies.txt'):
@2 opts['cookiefile'] = 'cookies.txt'
@1 try:
@2 safe_execution(os.remove, vpath)
@2 yt_dlp.YoutubeDL(opts).download([url])
@2 if is_valid_video(vpath): return True
@1 except Exception as e:
@2 logging.error(f"YT Download Error: {e}")
@1 return False
@0 def yt_dlp_fallback(url, vpath, ua):
@1 base = vpath[:-4] + "_ydl" if vpath.lower().endswith(".mp4") else vpath + "_ydl"
@1 configs = [{"extractor_args": {"tiktok": {"app_name": "musically"}}}, {}] if "tiktok.com" in url.lower() else [{}]
@1 for i, extra in enumerate(configs):
@2 outbase = f"{base}{i}"
@2 for old in [x for x in os.listdir(".") if x.startswith(outbase)]:
@3 safe_execution(os.remove, old)
@2 opts = {"format": "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/b[ext=mp4]/b", "merge_output_format": "mp4", "outtmpl": f"{outbase}.%(ext)s", "quiet": True, "no_warnings": True, "noplaylist": True, "nocheckcertificate": True, "retries": 2, "fragment_retries": 2, "socket_timeout": 18, "force_ipv4": True, "http_headers": {"User-Agent": ua, "Referer": "https://www.tiktok.com/"}, **extra}
@2 if os.path.exists('cookies.txt'):
@3 opts['cookiefile'] = 'cookies.txt'
@2 safe_execution(lambda: yt_dlp.YoutubeDL(opts).download([url]))
@2 candidates = [x for x in os.listdir(".") if x.startswith(outbase + ".") and is_valid_video(x)]
@2 if candidates:
@3 safe_execution(os.remove, vpath)
@3 os.rename(sorted(candidates)[0], vpath)
@3 for extra_file in candidates[1:]:
@4 safe_execution(os.remove, extra_file)
@3 return True
@1 return False
@0 def dl_vid(url, vpath):
@1 url = url.strip().rstrip("，。、！!?,.;:)>\"'")
@1 ua_m = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
@1 ua_d = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
@1 safe_execution(os.remove, vpath)
@1 res_u = safe_execution(lambda: urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": ua_m}), timeout=8).geturl()) or url
@1 if "youtu" in url.lower() or "youtu" in res_u.lower():
@2 if download_youtube_ytdlp(url, vpath, ua_d) or download_youtube_ytdlp(res_u, vpath, ua_d):
@3 return
@1 if "tiktok.com" in url or "tiktok.com" in res_u:
@2 for tu in ([url, res_u] if res_u != url else [url]):
@3 for _ in range(2):
@4 api1 = f"https://www.tikwm.com/api/?url={urllib.parse.quote(tu)}&hd=1"
@4 resp1 = safe_execution(lambda: json.loads(urllib.request.urlopen(urllib.request.Request(api1, headers={"User-Agent": ua_m}), timeout=12).read().decode())) or {}
@4 d1 = resp1.get("data") or {}
@4 for fk in ["play", "hdplay", "wmplay"]:
@5 if pu := d1.get(fk):
@6 pu = "https://www.tikwm.com" + pu if pu.startswith("/") else pu
@6 if save_stream_url(pu, vpath, ua_m, "https://www.tikwm.com/"):
@7 return
@4 if resp1.get("code") == -1:
@5 time.sleep(1.5)
@3 api2 = f"https://api.tiklydown.eu.org/api/download?url={urllib.parse.quote(tu)}"
@3 d2 = (safe_execution(lambda: json.loads(urllib.request.urlopen(urllib.request.Request(api2, headers={"User-Agent": ua_d}), timeout=12).read().decode())) or {}).get("video", {})
@3 if (pu2 := (d2.get("noWatermark") or d2.get("watermark"))) and save_stream_url(pu2, vpath, ua_d):
@4 return
@3 req_lt = urllib.request.Request("https://lovetik.com/api/ajax/search", data=urllib.parse.urlencode({"query": tu}).encode(), headers={"User-Agent": ua_d, "Origin": "https://lovetik.com"})
@3 d3 = (safe_execution(lambda: json.loads(urllib.request.urlopen(req_lt, timeout=12).read().decode())) or {}).get("links", [])
@3 for lk in d3:
@4 if (pu3 := lk.get("a")) and "mp3" not in (lk.get("t") or "").lower() and save_stream_url(pu3, vpath, ua_d, "https://lovetik.com/"):
@5 return
@2 if yt_dlp_fallback(url, vpath, ua_d):
@3 return
@1 if "xhslink.com" in url or "xiaohongshu.com" in res_u or "xiaohongshu.com" in url:
@2 for x_u in ([res_u, url] if res_u != url else [url]):
@3 for ua in [ua_d, ua_m]:
@4 req_x = urllib.request.Request(x_u, headers={"User-Agent": ua, "Cookie": "webBuild=4.36.0; xsecappid=xhs-pc-web;"})
@4 html = safe_execution(lambda: urllib.request.urlopen(req_x, timeout=12).read().decode("utf-8", "ignore")) or ""
@4 mk, mog, mm = re.search(r'"originVideoKey"\s*:\s*"([^"]+)"', html), re.search(r'<meta\s+(?:name|property)="og:video"\s+content="([^"]+)"', html), re.search(r'"masterUrl"\s*:\s*"([^"]+)"', html)
@4 mcdn = re.search(r'(https?://sns-video-[a-z0-9\-]+\.xhscdn\.com/[^"\'\s\\]+)', html)
@4 k_s = mk.group(1).replace("\\u002F", "/") if mk else ""
@4 cands = ([f"https://sns-video-bd.xhscdn.com/{k_s}", f"https://sns-video-hw.xhscdn.com/{k_s}"] if k_s else []) + [m.group(1) for m in [mog, mm, mcdn] if m]
@4 for vu in cands:
@5 vu = vu.replace("\\u002F", "/").replace("&amp;", "&")
@5 if save_stream_url(vu if vu.startswith("http") else "https:" + vu, vpath, ua, "https://www.xiaohongshu.com/"):
@6 return
@1 import btch_downloader
@1 dl_u = safe_execution(lambda: find_mp4(asyncio.run(btch_downloader.xiaohongshu(url) if "xhs" in url or "xiaohongshu" in url else (btch_downloader.ttdl(url) if "tiktok" in url else (btch_downloader.youtube(url) if "youtu" in url else btch_downloader.aio(url))))))
@1 if dl_u and save_stream_url(dl_u, vpath, ua_d):
@2 return
@1 if yt_dlp_fallback(url, vpath, ua_d):
@2 return
@1 raise Exception("Video Link ဒေါင်းယူ၍ မရပါ။ (Bot အလုပ်မလုပ်ပါက /start နှိပ်ပါ)")
@0 def clean_mm_text(t):
@1 t = re.sub(r"\([^)]*\)", "", t)
@1 t = re.sub(r"[*#_`~0-9:a-zA-Z\[\]()|•\-]", " ", t)
@1 return re.sub(r"\s+", " ", t).strip()
@0 def get_generate_models(client):
@1 discovered = []
@1 try:
@2 for model in client.models.list():
@3 name = str(getattr(model, "name", "") or "").removeprefix("models/")
@3 actions = [str(a).lower() for a in (getattr(model, "supported_actions", None) or [])]
@3 if not name or (actions and not any("generatecontent" in a for a in actions)):
@4 continue
@3 low = name.lower()
@3 if not any(term in low for term in ("embedding", "tts", "image", "veo", "aqa")) and "flash" in low:
@4 discovered.append(name)
@1 except Exception:
@2 return MODELS
@1 available = set(discovered)
@1 preferred = [m for m in MODELS if m in available]
@1 return preferred + [m for m in discovered if m not in preferred] or MODELS
@0 def _try_models_with_file(client, model_candidates, uf, p, uid, k_i):
@1 last_err = None
@1 for m_name in model_candidates:
@2 try:
@3 res = client.models.generate_content(model=m_name, contents=[uf, p])
@3 if res and res.text:
@4 set_u(uid, "k_idx", k_i)
@4 return res.text, None
@2 except Exception as me:
@3 last_err = me
@3 if any(w in str(me).upper() for w in ["429", "RESOURCE_EXHAUSTED", "QUOTA", "API_KEY", "PERMISSION", "403"]):
@4 continue
@1 return "", last_err
@0 def ai_frame_audio_translate(vpath, sm_v, uid, vdur, n_win):
@1 cmd_sm = ["ffmpeg", "-y", "-threads", "2", "-i", vpath, "-t", f"{vdur:.2f}", "-vf", "fps=1,scale=280:-2", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35", "-c:a", "aac", "-ac", "1", "-ar", "16000", "-b:a", "28k", sm_v]
@1 subprocess.run(cmd_sm, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
@1 up_file = sm_v if (os.path.exists(sm_v) and os.path.getsize(sm_v) > 1000) else vpath
@1 u = get_u(uid)
@1 keys = u.get("keys", [])
@1 if not keys:
@2 raise Exception("API Key မရှိပါ။ Key အရင်ထည့်ပေးပါ။")
@1 start_idx = u.get("k_idx", 0) % len(keys)
@1 w_dur = vdur / n_win
@1 chars_w = max(65, int(w_dur * 15.2))
@1 win_desc = "၊ ".join([f"အပိုင်း {i+1} ({int(i*w_dur)}s မှ {int((i+1)*w_dur)}s)" for i in range(n_win)])
@1 p = f"ဒီ Video ဖိုင်ရဲ့ ရုပ်ပုံနဲ့ အသံကို သေချာကြည့်ရှုနားထောင်ပြီး ({n_win}) ပိုင်း အတိအကျခွဲ၍ TikTok တွင် ခေတ်စားနေသော Burmese Professional Movie Recap စကားပြောပုံစံဖြင့် အပိုအလိုမရှိ တိကျစွာ ဘာသာပြန်ပေးပါ - {win_desc}\n\n"
@1 p += "📌 အရေးကြီးချက်များ -\n"
@1 p += "၁။ Video အစပိုင်းတွင် စကားမပြောဘဲ Intro / တေးဂီတ သီးသန့်ဖြစ်နေပါက ထိုအပိုင်းအတွက် စာမရေးဘဲ '---' ဟုသာ ချန်ထားပါ။\n"
@1 p += "၂။ အပို နှုတ်ဆက်စကားများ၊ အင်္ဂလိပ်စာနှင့် ကွင်းစကွင်းပိတ်များ လုံးဝ (လုံးဝ) မထည့်ပါနှင့်။\n"
@1 p += f"၃။ တစ်ပိုင်းစီအတွက် မြန်မာစာလုံးရေ {chars_w} လုံးခန့်သာ ရေးပြီး အပိုင်းကြားတွင် ||| သင်္ကေတ ခြားပေးပါ။\n"
@1 p += "ဥပမာ အရေးအသား - --- ||| အမျိုးသားတစ်ယောက်ဟာ လှေပေါ်မှာ ဓားနဲ့ ကစားနေရင်း မတော်တဆ အပေါက်ဖောက်မိသွားတဲ့အတွက် ရေတွေ စတင် စိမ့်ဝင်လာပါတယ်။ ရေတွေက သင်္ဘောကုန်းပတ်ပေါ်အထိ လျင်မြန်စွာ တက်လာချိန်မှာပဲ တခြားလှေတစ်စင်း ချဉ်းကပ်လာတာကို သူ မြင်လိုက်ရပါတယ်။ ||| "
@1 p += "သူက သူ့ခြေထောက်နဲ့ အပေါက်ကို အမြန်ဖုံးအုပ်ပြီး ဘာမှမဖြစ်သလို ဟန်ဆောင်လိုက်ပါတယ်။ ရုတ်တရက်ဆိုသလိုပဲ ကင်းလှည့်ရေယာဉ်တစ်စင်း သူတို့ရှေ့မှာ ပေါ်လာပါတယ်။ သူတို့တွေက ငါးဖမ်းသမားတွေလို ဟန်ဆောင်ကြပေမဲ့ ရန်သူခေါင်းဆောင်ကတော့ တစ်ခုခု လွဲနေတယ်လို့ သံသယဝင်သွားပြီး စစ်ဆေးဖို့အတွက် သူတို့လှေပေါ်ကို တက်လာပါတော့တယ်။\n"
@1 raw_txt, last_err = "", None
@1 for step_i in range(len(keys)):
@2 k_i = (start_idx + step_i) % len(keys)
@2 client = genai.Client(api_key=keys[k_i].strip(), http_options=types.HttpOptions(timeout=40000))
@2 model_candidates = get_generate_models(client)
@2 uf = safe_execution(lambda: client.files.upload(file=up_file))
@2 if not uf:
@3 continue
@2 for _ in range(120):
@3 if getattr(getattr(uf, "state", None), "name", "") == "PROCESSING":
@4 time.sleep(1)
@4 uf = safe_execution(lambda: client.files.get(name=uf.name)) or uf
@2 if getattr(getattr(uf, "state", None), "name", "") == "PROCESSING":
@3 last_err = RuntimeError("Gemini video file is still processing")
@3 safe_execution(lambda: client.files.delete(name=uf.name))
@3 continue
@2 raw_txt, err_one = _try_models_with_file(client, model_candidates, uf, p, uid, k_i)
@2 if err_one:
@3 last_err = err_one
@2 safe_execution(lambda: client.files.delete(name=uf.name))
@2 if raw_txt:
@3 break
@1 if not raw_txt:
@2 err_text = str(last_err or "Unknown Gemini API error")
@2 if any(w in err_text.upper() for w in ["429", "RESOURCE_EXHAUSTED", "QUOTA", "LIMIT: 0"]):
@3 raise Exception("Gemini API quota ပြည့်နေပါသည်။ Key အသစ်ထည့်ပြီး ပြန်စမ်းပေးပါ။")
@2 raise Exception(f"Gemini API Error: {err_text[:600]}")
@1 parts = []
@1 for x in raw_txt.split("|||"):
@2 if x.strip() == "---":
@3 parts.append("---")
@2 elif len(clean_mm_text(x)) > 5:
@3 parts.append(clean_mm_text(x))
@1 if len(parts) != n_win:
@2 full_c = clean_mm_text(raw_txt)
@2 sents = [s.strip() + "။" for s in full_c.split("။") if len(s.strip()) > 5] or [full_c]
@2 st = max(1, len(sents) / n_win)
@2 parts = [" ".join(sents[int(round(i*st)):max(int(round(i*st))+1, int(round((i+1)*st)) if i < n_win-1 else len(sents))]) or sents[-1] for i in range(n_win)]
@1 return parts
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
@0 def _gemini_tts_call(text, g_voice, out_wav, uid, key_offset=1):
@1 u = get_u(uid)
@1 keys = u.get("keys", [])
@1 if not keys:
@2 raise RuntimeError("API Key မရှိပါ။")
@1 start_idx = (u.get("k_idx", 0) + key_offset) % len(keys)
@1 pvc = types.PrebuiltVoiceConfig(voice_name=g_voice)
@1 sc = types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=pvc))
@1 cfg = types.GenerateContentConfig(response_modalities=["AUDIO"], speech_config=sc)
@1 prompt = f"Read this Burmese movie recap narration aloud naturally, smoothly, and clearly:\n\n{text}"
@1 last_err = None
@1 for round_i in range(2):
@2 for step_i in range(len(keys)):
@3 k_i = (start_idx + step_i) % len(keys)
@3 client = genai.Client(api_key=keys[k_i].strip(), http_options=types.HttpOptions(timeout=35000))
@3 for tm in TTS_MODELS:
@4 try:
@5 safe_execution(os.remove, out_wav)
@5 res = client.models.generate_content(model=tm, contents=prompt, config=cfg)
@5 pcm = _extract_tts_pcm(res) if res else b""
@5 if pcm and len(pcm) > 800:
@6 _write_pcm_or_riff(pcm, out_wav)
@6 if is_valid_audio(out_wav):
@7 set_u(uid, "k_idx", k_i)
@7 return True
@4 except Exception as e:
@5 last_err = e
@5 if "404" in str(e) or "NOT_FOUND" in str(e).upper():
@6 continue
@5 break
@2 if round_i == 0:
@3 time.sleep(4)
@1 raise RuntimeError(f"Google AI Studio TTS ({g_voice}) Quota ပြည့်နေပါသည် သို့မဟုတ် အသံထုတ်မရပါ ({str(last_err)[:250]})။")
@0 def _concat_tts_chunks(wav_files, work, out_a):
@1 list_f = os.path.join(work, "concat_list.txt")
@1 lines = ["file '" + os.path.abspath(w).replace("'", "'\\''") + "'\n" for w in wav_files]
@1 Path(list_f).write_text("".join(lines), encoding="utf-8")
@1 cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_f, "-c:a", "aac", "-b:a", "160k", out_a]
@1 r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90)
@1 if r.returncode != 0 or not is_valid_audio(out_a):
@2 raise RuntimeError("Concat Error: " + r.stderr[-200:])
@1 return [max(0.1, get_dur(w)) for w in wav_files]
@0 async def build_free_synced_voice(seg_scripts, voice_key, out_a, uid, vdur):
@1 work = f"tts_{uid}_{int(time.time() * 1000)}"
@1 os.makedirs(work, exist_ok=True)
@1 g_voice = voice_key if voice_key in VOICES else "Zephyr"
@1 raw_seg_wavs = []
@1 n_win = max(1, len(seg_scripts))
@1 w_dur = vdur / n_win
@1 try:
@2 for i, script in enumerate(seg_scripts):
@3 text = clean_mm_text(script)
@3 raw_w = os.path.join(work, f"gseg_raw_{i}.wav")
@3 cw = os.path.join(work, f"gseg_cw_{i}.wav")
@3 if not text or script.strip() == "---":
@4 subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{w_dur}", "-c:a", "pcm_s16le", cw], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
@4 raw_seg_wavs.append(cw)
@4 continue
@3 ok_g = await asyncio.to_thread(_gemini_tts_call, text, g_voice, raw_w, uid, i)
@3 if not ok_g or not is_valid_audio(raw_w):
@4 raise RuntimeError(f"Google AI Studio TTS အသံထုတ်မရပါ (Segment {i + 1})")
@3 af = "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,areverse,atempo=1.25,highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=24000,asetpts=PTS-STARTPTS"
@3 subprocess.run(["ffmpeg", "-y", "-i", raw_w, "-af", af, "-ac", "1", "-ar", "24000", cw], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
@3 if not is_valid_audio(cw):
@4 raise RuntimeError(f"Audio conversion failed at segment {i + 1}")
@3 raw_seg_wavs.append(cw)
@2 return await asyncio.to_thread(_concat_tts_chunks, raw_seg_wavs, work, out_a)
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
@0 def get_dur(p):
@1 if not p or not os.path.exists(p):
@2 raise FileNotFoundError(f"Media file not found: {p}")
@1 cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", p]
@1 r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
@1 duration = safe_execution(lambda: float(r.stdout.strip())) or 0.0
@1 if r.returncode != 0 or duration <= 0:
@2 raise RuntimeError(f"Invalid media duration for {os.path.basename(p)}")
@1 return duration
@0 def build_piecewise_pts(vdur, seg_durs):
@1 n = len(seg_durs)
@1 w_d = max(0.1, vdur / max(1, n))
@1 ts = [i * w_d for i in range(n)]
@1 ss = [sum(seg_durs[:i]) for i in range(n)]
@1 sl = [d / w_d for d in seg_durs]
@1 ex = f"{ss[-1]:.4f}+(T-{ts[-1]:.4f})*{sl[-1]:.4f}"
@1 for i in range(n - 2, -1, -1):
@2 ex = f"if(lt(T,{ts[i+1]:.4f}),{ss[i]:.4f}+(T-{ts[i]:.4f})*{sl[i]:.4f},{ex})"
@1 return f"setpts='({ex})/TB',fps=30"
@0 def edit_vid(iv, ia, ov, u, uid, vdur, seg_durs):
@1 audio_dur = max(get_dur(ia), 1.0)
@1 is_fr, fl = (u.get("layout", "frame") == "frame"), (",hflip" if u.get("f") else "")
@1 adj = "crop=iw*0.92:ih*0.92:iw*0.04:ih*0.04,eq=contrast=1.08:brightness=0.02:saturation=1.14:gamma=1.03,hue=h=3,unsharp=3:3:0.65:3:3:0.0"
@1 pw_s = build_piecewise_pts(vdur, seg_durs)
@1 un_s = f"setpts={audio_dur/max(vdur,1.0):.4f}*(PTS-STARTPTS),fps=30"
@1 b_map = {"low": (950, 86), "mid": (880, 86), "high": (790, 86)} if is_fr else {"low": (1040, 92), "mid": (940, 92), "high": (830, 92)}
@1 by, bh = detect_sub_band(iv, vdur, is_fr, uid) if u.get("blur") == "auto" else b_map.get(u.get("blur"), (950, 86))
@1 by, bh = (int(by) // 2) * 2, max(64, (int(bh) // 2) * 2)
@1 kbps = min(3200, max(1000, int((42 * 8192) / audio_dur) - 160))
@1 last_err = ""
@1 for sync_f in [pw_s, un_s]:
@2 safe_execution(os.remove, ov)
@2 fc = f"[0:v]{sync_f}{fl}[v0];"
@2 if is_fr:
@3 fc += "[v0]split=2[bgi][fgi];[bgi]scale=180:320:force_original_aspect_ratio=increase,crop=180:320,gblur=sigma=14,eq=brightness=-0.07,scale=720:1280[bg];"
@3 fc += f"[fgi]{adj},scale=720:820:force_original_aspect_ratio=increase:flags=lanczos,crop=720:820[fg];[bg][fg]overlay=0:230[v1]"
@2 else:
@3 fc += f"[v0]{adj},scale=720:1280:force_original_aspect_ratio=increase:flags=lanczos,crop=720:1280[v1]"
@2 cur = "[v1]"
@2 if u.get("blur") != "off":
@3 fc += f";{cur}split=2[m1][m2];[m2]crop=640:{bh}:40:{by},gblur=sigma=26[bst];[m1][bst]overlay=40:{by}[v2]"
@3 cur = "[v2]"
@2 inputs, logo_p = ["-i", iv, "-i", ia], f"logo_{uid}.jpg"
@2 if u.get("logo") and os.path.exists(logo_p):
@3 inputs.extend(["-i", logo_p])
@3 ly = 165 if is_fr else 80
@3 fc += f";[2:v]scale=110:110[lg];{cur}[lg]overlay=12:{ly}[v3]"
@3 cur = "[v3]"
@2 fc += f";{cur}format=yuv420p[vout]"
@2 c = ["ffmpeg", "-y", "-threads", "2"] + inputs + ["-map_metadata", "-1", "-map_chapters", "-1", "-filter_complex", fc, "-map", "[vout]", "-map", "1:a:0", "-c:v", "libx264", "-preset", "superfast", "-crf", "19", "-pix_fmt", "yuv420p", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps*2}k", "-c:a", "copy", "-shortest", "-fs", "47M", ov]
@2 r = subprocess.run(c, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=max(300, int(audio_dur * 6)))
@2 if r.returncode == 0 and is_valid_video(ov):
@3 return
@2 last_err = r.stderr[-500:]
@1 raise RuntimeError(f"Render Error: {last_err}")
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
@1 msg = await update.message.reply_text("⏳ [15%] Ultra HD Video ဆွဲယူနေပါတယ်...\n💡 (အကယ်၍ ရပ်နေပါက /start နှိပ်ပါ)", reply_markup=cancel_kb())
@1 vpath = f"in_{uid}.mp4"
@1 try:
@2 if um:
@3 await asyncio.wait_for(asyncio.to_thread(dl_vid, um.group(0), vpath), timeout=180)
@2 if not um and (update.message.video or update.message.document):
@3 v = update.message.video or update.message.document
@3 f = await context.bot.get_file(v.file_id)
@3 await f.download_to_drive(vpath)
@2 if not is_valid_video(vpath):
@3 await msg.edit_text("❌ Video ဖိုင် မမှန်ကန်ပါ သို့မဟုတ် Video Link ပို့ပါ!\n💡 (Bot အလုပ်မလုပ်ပါက /start နှိပ်ပါ)")
@3 return
@2 SESSIONS[uid] = vpath
@2 txt, kb = dash_ui(u, uid)
@2 btn = InlineKeyboardButton(f"🚀 START RENDER (🌟 {u['v']} 1.25x | Ultra HD)", callback_data="r|go")
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
@2 source_duration = max(1.0, get_dur(vpath))
@2 vdur = min(source_duration, 180.0)
@2 n_win = max(3, min(8, int(round(vdur / 12.0))))
@2 stage = "Gemini scene analysis"
@2 await q.edit_message_text(f"🔄 [30%] Video Frame + မူရင်းအသံကို အပိုင်း ({n_win}) ပိုင်းခွဲ၍ အတိအကျ ဘာသာပြန်နေပါသည်...{hint}", reply_markup=cancel_kb())
@2 seg_scripts = await asyncio.wait_for(asyncio.to_thread(ai_frame_audio_translate, vpath, sm_v, uid, vdur, n_win), timeout=max(180, int(vdur * 2.5)))
@2 stage = "TTS voice generation"
@2 await q.edit_message_text(f"🔄 [60%] 🎙️ Google AI ({u['v']} 1.25x) ဖြင့် အသံသွင်းနေပါသည်...{hint}", reply_markup=cancel_kb())
@2 seg_durs = await asyncio.wait_for(build_free_synced_voice(seg_scripts, u["v"], apath, uid, vdur), timeout=180)
@2 stage = "FFmpeg video/audio render"
@2 await q.edit_message_text(f"🔄 [85%] Ultra HD + Auto-Blur + Scene-Locked Frame Sync Render လုပ်နေပါသည်...{hint}", reply_markup=cancel_kb())
@2 await asyncio.wait_for(asyncio.to_thread(edit_vid, vpath, apath, opath, u, uid, vdur, seg_durs), timeout=max(300, int(vdur * 5)))
@2 await q.edit_message_text("📤 [98%] Ultra HD Video ပို့ပေးနေပါတယ်...")
@2 with open(opath, "rb") as vf:
@3 await context.bot.send_video(uid, vf, caption="Powered by SiGyi Ai Studio", read_timeout=300, write_timeout=300)
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
@3 rows.append([InlineKeyboardButton(f"🚀 START RENDER (🌟 {u_new['v']} 1.25x | Ultra HD)", callback_data="r|go")])
@2 await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(rows))
@2 return
@1 if cat == "r" and act == "go":
@2 if uid not in SESSIONS or not os.path.exists(SESSIONS[uid]):
@3 await q.edit_message_text("⚠️ Video အသစ် ပြန်ပို့ပါ။ (Bot အလုပ်မလုပ်ပါက /start နှိပ်ပါ)")
@3 return
@2 if not u.get("keys"):
@3 txt, kb = key_menu_ui(u)
@3 await q.edit_message_text("🔒 API Key အရင်ထည့်ပေးပါ!\n\n" + txt, reply_markup=kb)
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