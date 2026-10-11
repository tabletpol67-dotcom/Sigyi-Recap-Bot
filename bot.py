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
# Railway Variables ထဲက TELEGRAM_BOT_TOKEN ကို အလိုအလျောက် ဖတ်ပါမည်
# (အကယ်၍ တိုက်ရိုက်ထည့်ချင်ပါက "YOUR_TELEGRAM_BOT_TOKEN" နေရာတွင် အစားထိုးနိုင်သည်)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN").strip()

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
    keys[str(user_id)] = api_key.strip()
    with open(KEYS_FILE, "w") as f:
        json.dump(keys, f)

def get_user_key(user_id: int):
    keys = load_keys()
    return keys.get(str(user_id))

# ================= 1. START & KEY COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_key = get_user_key(user_id)
    
    if user_key:
        masked = user_key[:8] + "••••••••" + user_key[-4:]
        key_status = f"✅ ချိတ်ဆက်ပြီး (`{masked}`)"
    else:
        key_status = "❌ မထည့်ရသေးပါ (Key အရင်ပို့ပေးပါ)"

    welcome_text = (
        "🎬 **Sigyi AI Recap & Dubbing Studio (BYOK)**\n\n"
        f"🔑 **သင့် Gemini API Key:** {key_status}\n\n"
        "**အသုံးပြုပုံ အဆင့်ဆင့် -**\n"
        "၁။ သင့်ရဲ့ ကိုယ်ပိုင် **Gemini API Key** (`AIzaSy...` ဖြင့်စသော Key) ကို ဒီ Chat ထဲသို့ တိုက်ရိုက်ပို့ပေးပါ။\n"
        "   👉 [Key အခမဲ့ယူရန် နှိပ်ပါ](https://aistudio.google.com/app/apikey)\n"
        "၂။ Key ချိတ်ပြီးပါက **TikTok / YouTube / FB Link** သို့မဟုတ် **Video File** ပို့ပေးပါ။\n"
        "၃။ **Voice** နဲ့ **Recap Style** ရွေးလိုက်တာနဲ့ Copyright လွတ် Video ပြန်ပို့ပေးပါမယ်!\n\n"
        "⚙️ **Commands:**\n"
        "• `/mykey` - လက်ရှိ Key ကို စစ်ဆေးရန်\n"
        "• `/delkey` - လက်ရှိ Key ကို ဖျက်ရန်"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown", disable_web_page_preview=True)

async def set_key_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ `/setkey AIzaSy...` ပုံစံဖြင့် Key ပို့ပေးပါ သို့မဟုတ် Key ကို ရိုးရိုး Message အနေဖြင့် တိုက်ရိုက်ပို့ပါ။", parse_mode="Markdown")
        return
    
    key = context.args[0].strip()
    if not key.startswith("AIza") or len(key) < 30:
        await update.message.reply_text("❌ Gemini API Key ပုံစံ မမှန်ကန်ပါ။ `AIzaSy...` ဖြင့်စသော Key အမှန်ကို ပို့ပေးပါ။", parse_mode="Markdown")
        return

    save_key(user_id, key)
    try:
        await update.message.delete()
    except Exception:
        pass
    await context.bot.send_message(
        chat_id=user_id,
        text="✅ **သင့်ရဲ့ Gemini API Key ကို အောင်မြင်စွာ သိမ်းဆည်းပြီးပါပြီ!**\n\n🎬 အခု Video Link သို့မဟုတ် Video File ပို့နိုင်ပါပြီ။",
        parse_mode="Markdown"
    )

async def check_my_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    key = get_user_key(user_id)
    if key:
        masked = key[:8] + "****************" + key[-4:]
        await update.message.reply_text(f"🔑 သင်လက်ရှိချိတ်ဆက်ထားသော Key မှာ -\n`{masked}` ဖြစ်ပါတယ်။", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ သင့်မှာ Gemini API Key မထည့်ရသေးပါ။ `AIzaSy...` ဖြင့်စသော Key ကို ပို့ပေးပါ။", parse_mode="Markdown")

async def delete_my_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keys = load_keys()
    if str(user_id) in keys:
        del keys[str(user_id)]
        with open(KEYS_FILE, "w") as f:
            json.dump(keys, f)
        await update.message.reply_text("🗑️ သင့်ရဲ့ Gemini API Key ကို ဖျက်ပေးလိုက်ပါပြီ။ အသစ်ပြန်ပို့နိုင်ပါတယ်။")
    else:
        await update.message.reply_text("❌ ဖျက်ရန် Key မရှိပါ။")

# ================= 2. RECEIVE KEY, VIDEO OR LINK =================
async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""

    # ၁။ User က Gemini API Key (AIza... ဖြင့်စသောစာ) တိုက်ရိုက်ပို့လာလျှင် သိမ်းပေးမည်
    if text.startswith("AIza") and len(text) >= 30 and " " not in text:
        save_key(user_id, text)
        try:
            await update.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=user_id,
            text="✅ **သင့်ရဲ့ Gemini API Key ကို အောင်မြင်စွာ ချိတ်ဆက်ပြီးပါပြီ!**\n\n🎬 အခု စတင်ပြီး Video File သို့မဟုတ် TikTok/YouTube Link ပို့နိုင်ပါပြီ။",
            parse_mode="Markdown"
        )
        return

    # ၂။ Video သို့မဟုတ် Link ပို့လာချိန်တွင် User ၏ API Key ရှိမရှိ အရင်စစ်မည်
    user_api_key = get_user_key(user_id)
    if not user_api_key:
        await update.message.reply_text(
            "⚠️ **သင့်ရဲ့ ကိုယ်ပိုင် Gemini API Key အရင်ထည့်ပေးရန် လိုအပ်ပါသည်!**\n\n"
            "၁။ [Google AI Studio (နှိပ်ပါ)](https://aistudio.google.com/app/apikey) သို့သွားပြီး Key ယူပါ။\n"
            "၂။ ရလာသော `AIzaSy...` ဖြင့်စသည့် Key ကို ဒီ Chat ထဲသို့ Copy ကူးပြီး တိုက်ရိုက်ပို့ပေးပါ။",
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
            await msg.edit_text(
                "❌ ပို့လိုက်သော စာသားသည် API Key သို့မဟုတ် Video Link မဟုတ်ပါ။\n"
                "• API Key ဖြစ်ပါက `AIzaSy...` ဖြင့် စရပါမည်။\n"
                "• Link ဖြစ်ပါက `http...` ဖြင့် စရပါမည်။",
                parse_mode="Markdown"
            )
            return

        USER_SESSIONS[user_id] = {"video_path": input_path, "voice": "my-MM-ThihaNeural"}

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
        await msg.edit_text(f"❌ Video ဒေါင်းလုဒ်ဆွဲရာတွင် အမှားရှိနေပါသည်: {str(e)}")

# ================= 3. BUTTON SELECTION & GENERATE =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.
    