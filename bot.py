import os
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

# ================= API KEYS =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)

# User တစ်ယောက်ချင်းစီရဲ့ ရွေးချယ်မှုကို မှတ်ထားရန်
USER_SESSIONS = {}

# ================= 1. START COMMAND =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🎬 **AI Recap & Dubbing Studio မှ ကြိုဆိုပါတယ်!**\n\n"
        "အသုံးပြုပုံ အဆင့်ဆင့် -\n"
        "၁။ **TikTok / YouTube / FB Link** (သို့မဟုတ်) **Video File** တစ်ခု ပို့ပေးပါ။\n"
        "၂။ ကြိုက်နှစ်သက်ရာ **အသံ (Voice)** နဲ့ **Recap Style** ကို ခလုတ်နှိပ်ရွေးပါ။\n"
        "၃။ ခဏစောင့်ပြီးရင် TikTok တန်းတင်လို့ရတဲ့ Copyright လွတ် Video ရပါပြီ!"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

# ================= 2. RECEIVE VIDEO OR LINK =================
async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = await update.message.reply_text("⏳ Video ကို လက်ခံရယူနေပါတယ်...")
    input_path = f"raw_{user_id}.mp4"

    try:
        # Link ပို့လာလျှင် yt-dlp ဖြင့် ဒေါင်းမည်
        if update.message.text and update.message.text.startswith("http"):
            url = update.message.text.strip()
            ydl_opts = {
                'format': 'mp4/best',
                'outtmpl': input_path,
                'overwrites': True,
                'quiet': True
            }
            await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).download([url]))
        
        # Video File တိုက်ရိုက်ပို့လာလျှင်
        elif update.message.video or update.message.document:
            video = update.message.video or update.message.document
            tg_file = await context.bot.get_file(video.file_id)
            await tg_file.download_to_drive(input_path)
        else:
            await msg.edit_text("❌ Video ဖိုင် သို့မဟုတ် Video Link ပို့ပေးပါ။")
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

    data = query.data.split("|")
    action, value = data[0], data[1]

    # Voice ရွေးပြီးလျှင် Style ဆက်ရွေးခိုင်းမည်
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

    # Style ရွေးပြီးလျှင် စတင် Generate လုပ်မည်
    elif action == "style":
        style = value
        voice = USER_SESSIONS[user_id]["voice"]
        input_video = USER_SESSIONS[user_id]["video_path"]
        output_audio = f"aud_{user_id}.mp3"
        output_video = f"final_{user_id}.mp4"

        try:
            await query.edit_message_text("🧠 **Step 1/3:** AI က Video ကို ကြည့်ပြီး မြန်မာ Script ရေးနေပါတယ်...", parse_mode="Markdown")
            script = await asyncio.to_thread(generate_script, input_video, style)

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
            await query.edit_message_text(f"❌ Error: {str(e)}")
        finally:
            for f in [input_video, output_audio, output_video]:
                if os.path.exists(f):
                    os.remove(f)
            USER_SESSIONS.pop(user_id, None)

# ================= AI & FFMPEG FUNCTIONS =================
def generate_script(video_path: str, style: str) -> str:
    v_file = genai.upload_file(path=video_path)
    while v_file.state.name == "PROCESSING":
        time.sleep(3)
        v_file = genai.get_file(v_file.name)

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

    # Copyright Bypass: Flip + 8% Zoom Crop + Color Boost + Speed Sync
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
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO | (filters.TEXT & ~filters.COMMAND), handle_input))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("🚀 Studio Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
    