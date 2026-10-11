import os
import json
import time
import asyncio
import subprocess
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    CallbackQueryHandler, filters, ContextTypes
)
import google.generativeai as genai
import edge_tts
import yt_dlp

# ================= BOT TOKEN =================
# Railway Variables ထဲတွင် TELEGRAM_BOT_TOKEN တစ်ခုသာ ထည့်ရန်လိုသည်
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")

# User များ၏ API Key ကို သိမ်းဆည်းမည့် ဖိုင်
KEYS_FILE = "user_keys.json"
USER_SESSIONS = {}

def load_keys():
    if os.path.exists(KEYS_FILE):
        try:
            with open(KEYS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_key(user_id: int, api_key: str):
    keys = load_keys()
    keys[str(user_id)] = api_key
    with open(KEYS_FILE, "w") as f:
        json.dump(keys, f)

def get_user_key(user_id: int):
    keys = load_keys()
    return keys.get(str(user_id))

# ================= 1. START & KEY MANAGEMENT =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    has_key = get_user_key(user_id) is not None
    
    key_status = "✅ **ချိတ်ဆက်ပြီးပါပြီ (အသင့်သုံးနိုင်သည်)**" if has_key else "❌ **မထည့်ရသေးပါ (Key အရင်ပို့ပေးပါ)**"

    welcome_text = (
        "🎬 **Sigyi AI Recap & Dubbing Studio မှ ကြိုဆိုပါတယ်!**\n\n"
        f"🔑 **သင့် Gemini API Key အခြေအနေ:** {key_status}\n\n"
        "**အသုံးပြုပုံ အဆင့်ဆင့် -**\n"
        "၁။ သင့်ရဲ့ ကိုယ်ပိုင် **Gemini API Key** (`AIzaSy...` ဖြင့်စသော Key) ကို ဒီ Chat ထဲသို့ တိုက်ရိုက်ပို့ပေးပါ။\n"
        "   *(Key မရှိသေးပါက aistudio.google.com/app/apikey တွင် အခမဲ့ယူနိုင်ပါသည်)*\n"
        "၂။ Key ချိတ်ပြီးပါက **TikTok / YouTube / FB Link** သို့မဟုတ် **Video File** ပို့ပေးပါ။\n"
        "၃။ ကြိုက်နှစ်သက်ရာ **အသံ (Voice)** နဲ့ **Recap Style** ရွေးလိုက်တာနဲ့ Copyright လွတ် Video ပြန်ပို့ပေးပါမယ်!\n\n"
        "💡 *မှတ်ချက် - Key အသစ်ပြောင်းချင်လျှင် အချိန်မရွေး Key အသစ် ထပ်ပို့နိုင်ပါသည်။ `/mykey` ဖြင့် လက်ရှိ Key ကို စစ်နိုင်ပြီး `/delkey` ဖြင့် ပြန်ဖျက်နိုင်ပါသည်။*"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown", disable_web_page_preview=True)

async def check_my_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    key = get_user_key(user_id)
    if key:
        masked = key[:8] + "****************" + key[-4:]
        await update.message.reply_text(f"🔑 သင်လက်ရှိချိတ်ဆက်ထားသော Key မှာ -\n`{masked}` ဖြစ်ပါတယ်။", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ သင့်မှာ Gemini API Key မထည့်ရသေးပါ။ `AIzaSy...` ဖြင့်စသော Key ကို ပို့ပေးပါ။")

async def delete_my_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keys = load_keys()
    if str(user_id) in keys:
        del keys[str(user_id)]
        with open(KEYS_FILE, "w") as f:
            json.dump(keys, f)
        await update.message.reply_text("🗑️ သင့်ရဲ့ Gemini API Key ကို ဖျက်ပေးလိုက်ပါပြီ။")
    else:
        await update.message.reply_text("❌ ဖျက်ရန် Key မရှိပါ။")

# ================= 2. RECEIVE KEY, VIDEO OR LINK =================
async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""

    # ၁။ User က Gemini API Key (AIza... ဖြင့်စသောစာ) ပို့လာလျှင် သိမ်းပေးမည်
    if text.startswith("AIza") and len(text) > 30 and " " not in text:
        save_key(user_id, text)
        try:
            # လုံခြုံရေးအတွက် User ပို့လိုက်သော Key message ကို ဖျက်ပေးမည်
            await update.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=user_id,
            text="✅ **သင့်ရဲ့ Gemini API Key ကို အောင်မြင်စွာ ချိတ်ဆက်ပြီးပါပြီ!**\n\n🎬 အခု စတင်ပြီး Video File သို့မဟုတ် Video Link ပို့နိုင်ပါပြီ။",
            parse_mode="Markdown"
        )
        return

    # ၂။ Video သို့မဟုတ် Link ပို့လာချိန်တွင် API Key ရှိမရှိ အရင်စစ်မည်
    user_api_key = get_user_key(user_id)
    if not user_api_key:
        await update.message.reply_text(
            "⚠️ **သင့်ရဲ့ ကိုယ်ပိုင် Gemini API Key အရင်ထည့်ပေးရန် လိုအပ်ပါသည်!**\n\n"
            "၁။ [Google AI Studio](https://aistudio.google.com/app/apikey) သို့သွားပြီး Key ယူပါ။\n"
            "၂။ ရလာသော `AIzaSy...` ဖြင့်စသည့် Key ကို ဒီ Chat ထဲသို့ Copy ကူးပြီး ပို့ပေးပါ။",
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        return

    msg = await update.message.reply_text("⏳ Video ကို လက်ခံရယူနေပါတယ်...")
    input_path = f"raw_{user_id}.mp4"

    try:
        # Link ပို့လာလျှင် yt-dlp ဖြင့် ဒေါင်းမည်
        if text.startswith("http"):
            ydl_opts = {
                'format': 'mp4/best',
                'outtmpl': input_path,
                'overwrites': True,
                'quiet': True
            }
            await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).download([text]))
        
        # Video File တိုက်ရိုက်ပို့လာလျှင်
        elif update.message.video or update.message.document:
            video = update.message.video or update.message.document
            tg_file = await context.bot.get_file(video.file_id)
            await tg_file.download_to_drive(input_path)
        else:
            await msg.edit_text("❌ **API Key** (`AIzaSy...`) သို့မဟုတ် **Video File / Video Link** ပို့ပေးပါ။", parse_mode="Markdown")
            return

        USER_SESSIONS[user_id] = {"video_path": input_path, "voice": "my-MM-ThihaNeural"}

        # Voice ရွေးခိုင်းသည့် Button ပြမည်
        keyboard = [
            [
                InlineKeyboardButton("👦 ကိုသီဟ (Male)", callback_data="voice|my-MM-ThihaNeural"),
                InlineKeyboardButton("👩 မနီလာ (Female)", callback_data="voice|my-MM-NilarNeural")
            ]
        ]
        await msg.edit_text(
            "✅ Video ရရှိပါပြီ!\n\n🎙️ **အဆင့် (၁) - အသံ (Voice) ရွေးချယ်ပါ -**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    except Exception as e:
        await msg.edit_text(f"❌ Video ယူရာတွင် အမှားရှိနေပါသည်: {str(e)}")

# ================= 3. BUTTON SELECTION & GENERATE =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if user_id not in USER_SESSIONS:
        await query.edit_message_text("❌ Video အသစ် ပြန်ပို့ပေးပါ။")
        return

    user_api_key = get_user_key(user_id)
    if not user_api_key:
        await query.edit_message_text("❌ Gemini API Key မရှိပါ။ Key အရင်ပို့ပေးပါ။")
        return

    data = query.data.split("|")
    action, value = data[0], data[1]

    if action == "voice":
        USER_SESSIONS[user_id]["voice"] = value
        keyboard = [
            [InlineKeyboardButton("😎 လူငယ်အထာ (Street Slang)", callback_data="style|slang")],
            [InlineKeyboardButton("🎭 စိတ်လှုပ်ရှားဖွယ် (Drama Hook)", callback_data="style|drama")],
            [InlineKeyboardButton("⚡ အက်ရှင် အမြန် (Fast Recap)", callback_data="style|fast")]
        ]
        await query.edit_message_text(
            "🔥 **အဆင့် (၂) - ပြောမယ့် ပုံစံ (Recap Style) ရွေးချယ်ပါ -**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif action == "style":
        style = value
        voice = USER_SESSIONS[user_id]["voice"]
        input_video = USER_SESSIONS[user_id]["video_path"]
        output_audio = f"aud_{user_id}.mp3"
        output_video = f"final_{user_id}.mp4"

        try:
            await query.edit_message_text("🧠 **Step 1/3:** သင့် API Key ဖြင့် AI က Video ကိုကြည့်ပြီး မြန်မာ Script ရေးနေပါတယ်...", parse_mode="Markdown")
            script = await asyncio.to_thread(generate_script, input_video, style, user_api_key)

            await query.edit_message_text("🎙️ **Step 2/3:** မြန်မာအသံ (Voiceover) သွင်းနေပါတယ်...", parse_mode="Markdown")
            await generate_tts(script, voice, output_audio)

            await query.edit_message_text("🎬 **Step 3/3:** Copyright Bypass & Auto-Edit လုပ်နေပါတယ်...", parse_mode="Markdown")
            await asyncio.to_thread(render_video, input_video, output_audio, output_video)

            await query.edit_message_text("📤 Edit ပြီးသား Video ကို ပို့ပေးနေပါတယ်...")
            with open(output_video, "rb") as f:
                await context.bot.send_video(
                    chat_id=user_id,
                    video=f,
                    caption=f"✅ **Recap Studio Render ပြီးပါပြီ!**\n\n📝 **Script အကျဉ်း:**\n{script[:200]}...",
                    parse_mode="Markdown"
                )
            await query.delete_message()

        except Exception as e:
            await query.edit_message_text(
                f"❌ Error ဖြစ်သွားပါတယ်: {str(e)}\n\n"
                "💡 *(အကယ်၍ API Key အမှား သို့မဟုတ် Quota ပြည့်နေပါက Key အသစ်တစ်ခု ထပ်ပို့ပြီး ပြောင်းလဲနိုင်ပါသည်)*"
            )
        finally:
            for f in [input_video, output_audio, output_video]:
                if os.path.exists(f):
                    os.remove(f)
            USER_SESSIONS.pop(user_id, None)

# ================= AI & FFMPEG FUNCTIONS =================
def generate_script(video_path: str, style: str, api_key: str) -> str:
    # User တစ်ယောက်ချင်းစီ၏ API Key ကို အသုံးပြုခြင်း
    genai.configure(api_key=api_key)
    
    v_file = genai.upload_file(path=video_path)
    while v_file.state.name == "PROCESSING":
        time.sleep(3)
        v_file = genai.get_file(v_file.name)

    if v_file.state.name == "FAILED":
        raise Exception("Video ဖတ်ရှုမှု မအောင်မြင်ပါ။")

    style_prompts = {
        "slang": "TikTok မှာ လူငယ်တွေ အကြိုက် လူငယ်စကားပြော အထာကျကျ (Street Slang) ပုံစံနဲ့ အဖွင့်မှာ ဆွဲဆောင်မှုရှိတဲ့ Hook ထည့်ပြီး",
        "drama": "ကြည့်ရှုသူ စိတ်ဝင်စားသွားအောင် စိတ်လှုပ်ရှားဖွယ် ဒရာမာ Movie Recap ပုံစံနဲ့",
        "fast": "အချိန်တိုအတွင်း လိုရင်းထိထိမိမိ သိရမယ့် အက်ရှင် Movie Recap ပုံစံနဲ့"
    }

    prompt = (
        f"ဒီ Video ကို သေချာကြည့်ပြီး {style_prompts.get(style, '')} မြန်မာစကားပြော Voiceover Script ရေးပေးပါ။ "
        "Timestamp တွေ၊ အင်္ဂလိပ်စာတွေ၊ (BGM) လို ညွှန်ကြားချက်တွေ လုံးဝ မပါစေဘဲ "
        "အသံတန်းထွက်ဖတ်ရမယ့် မြန်မာစကားပြော စာသားသက်သက်ပဲ ရေးပေးပါ။"
    )
    model = genai.GenerativeModel("gemini-1.5-flash")
    res = model.generate_content([v_file, prompt])
    genai.delete_file(v_file.name)
    return res.text.strip()

async def generate_tts(text: str, voice: str, out_audio: str):
    comm = edge_tts.Communicate(text, voice, rate="+8%")
    await comm.save(out_audio)

def get_duration(path: str) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return float(res.stdout.strip())

def render_video(in_vid: str, in_aud: str, out_vid: str):
    v_dur = get_duration(in_vid)
    a_dur = get_duration(in_aud)
    pts = a_dur / v_dur

    vf = f"hflip,crop=iw*0.92:ih*0.92,scale=iw:ih,eq=contrast=1.06:saturation=1.12,setpts={pts}*PTS"
    cmd = [
        "ffmpeg", "-y", "-i", in_vid, "-i", in_aud,
        "-filter:v", vf,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-shortest", out_vid
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mykey", check_my_key))
    app.add_handler(CommandHandler("delkey", delete_my_key))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO | (filters.TEXT & ~filters.COMMAND), handle_input))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("🚀 Studio Bot (BYOK Mode) is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
    