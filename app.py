import os, re, time, wave, asyncio, subprocess, json, hashlib, shutil, random, math, uuid
import gradio as gr
from google import genai
from google.genai import types
from pathlib import Path

# --- Constants & Settings ---
VOICES = ["my-MM-NilarNeural", "my-MM-ThihaNeural"]
VOICE_MAP = {name: name for name in VOICES}
VIDEO_SPEED = 0.9
VOICE_SPEED = 1.25
VIDEO_SYNC_ADVANCE = 0.04
MODELS = ["gemini-2.5-flash", "gemini-2.0-flash"]

def try_run(fn, *a, **kw):
    try: return fn(*a, **kw)
    except Exception: return None

def clean_mm_text(t):
    t = str(t or "")
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"\[(?:KEEP|TIME|SEGMENT):.*?\]", " ", t, flags=re.I | re.S)
    t = re.sub(r"[*#_`~|•]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def get_dur(p):
    if not p or not os.path.exists(p): return 0.0
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", p], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return try_run(lambda: float(r.stdout.strip())) or 0.0

def is_valid_audio(p):
    if not os.path.exists(p) or os.path.getsize(p) < 600: return False
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", p], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return "audio" in r.stdout.lower()

def is_valid_video(p):
    if not os.path.exists(p) or os.path.getsize(p) < 10000: return False
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", p], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return "video" in r.stdout.lower()

# --- AI Audio Translation ---
def ai_frame_audio_translate(vpath, api_key, vdur, n_win):
    job_id = str(uuid.uuid4())[:8]
    audio_path = f"srcaud_{job_id}.wav"
    extract_cmd = ["ffmpeg", "-y", "-threads", "2", "-i", vpath, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", audio_path]
    subprocess.run(extract_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    if not is_valid_audio(audio_path):
        raise RuntimeError("ဗီဒီယိုမှ အသံထုတ်ယူ၍ မရပါ။")

    # Gemini ASR Prompt
    prompt_asr = (
        "Transcribe the speech heard in this AUDIO file exactly, in its original language. "
        "Return ONLY valid JSON with schema: {\"segments\":[{\"start\":0.0,\"end\":2.5,\"text\":\"words\"}]}. "
        f"Split speech into chunks between 0 and {vdur:.2f} seconds. Do not analyze video."
    )
    
    client = genai.Client(api_key=api_key)
    uploaded = client.files.upload(file=audio_path)
    
    transcript_segments = []
    try:
        response = client.models.generate_content(model=MODELS[0], contents=[uploaded, prompt_asr])
        raw_asr = response.text.strip()
        raw_asr = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_asr, flags=re.I)
        data_asr = json.loads(raw_asr[raw_asr.find("{"):raw_asr.rfind("}")+1])
        
        for seg in data_asr.get("segments", []):
            txt = re.sub(r"\s+", " ", str(seg.get("text", "") or "")).strip()
            a, b = float(seg.get("start", 0)), float(seg.get("end", 0))
            a, b = max(0.0, min(vdur, a)), max(0.0, min(vdur, b))
            if txt and b > a:
                transcript_segments.append({"start": a, "end": b, "text": txt})
    except Exception as e:
        raise RuntimeError(f"Gemini Transcription အလုပ်မလုပ်ပါ (API Key မှန်ကန်မှုစစ်ဆေးပါ): {e}")
    finally:
        try_run(lambda: client.files.delete(name=uploaded.name))
        try_run(os.remove, audio_path)

    if not transcript_segments:
        raise RuntimeError("အသံထဲမှ စကားပြောစာသား မတွေ့ပါ။")

    window_dur = vdur / n_win
    buckets = [[] for _ in range(n_win)]
    for seg in transcript_segments:
        idx = min(n_win - 1, max(0, int(seg["start"] / max(0.001, window_dur))))
        buckets[idx].append(seg)
        
    active = []
    for i, bucket in enumerate(buckets):
        if not bucket: continue
        a, b = i * window_dur, min(vdur, (i + 1) * window_dur)
        source_text = " ".join(x["text"] for x in bucket).strip()
        if source_text:
            active.append({"source_start": a, "source_end": b, "transcript": source_text})

    chunks = [f"SEGMENT {i+1} [{item['source_start']:.2f}-{item['source_end']:.2f}s]\n{item['transcript']}" for i, item in enumerate(active)]
    prompt_trans = (
        "Translate the transcript segments below into natural, clear Burmese for voice-over. "
        "Return exactly one Burmese text per segment, separated by the literal delimiter |||. "
        "No numbering, timestamps, or commentary.\n\n" + "\n\n".join(chunks)
    )

    try:
        res = client.models.generate_content(model=MODELS[0], contents=prompt_trans)
        raw_txt = res.text.strip()
    except Exception as e:
        raise RuntimeError(f"Translation Error: {e}")

    translated = [clean_mm_text(x) for x in raw_txt.split("|||")]
    if len(translated) != len(active):
        raise RuntimeError("ဘာသာပြန် အပိုင်းအရေအတွက် မကိုက်ညီပါ။ ပြန်စမ်းပါ။")

    keep_ranges = [(item["source_start"], item["source_end"], i) for i, item in enumerate(active)]
    return {"scripts": translated, "keep_ranges": keep_ranges, "source_transcript": [x["transcript"] for x in active]}

# --- Edge TTS ---
def _edge_tts_to_wav(text, output_wav, voice_name):
    import edge_tts
    normalized_text = clean_mm_text(text) or "အဲ့ဒီနောက်မှာတော့"
    mp3_path = output_wav + ".mp3"
    
    async def _generate():
        communicate = edge_tts.Communicate(text=normalized_text, voice=voice_name, rate="+0%")
        await communicate.save(mp3_path)
        
    asyncio.run(_generate())
    subprocess.run(["ffmpeg", "-y", "-i", mp3_path, "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", output_wav], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try_run(os.remove, mp3_path)
    return True

async def build_free_synced_voice(seg_scripts, voice_key, out_a):
    voice = VOICE_MAP.get(voice_key, "my-MM-NilarNeural")
    work = f"tts_work_{uuid.uuid4().hex[:8]}"
    os.makedirs(work, exist_ok=True)
    wavs, seg_durs = [], []
    try:
        for i, script in enumerate(seg_scripts):
            raw = os.path.join(work, f"raw_{i}.wav")
            wav = os.path.join(work, f"seg_{i}.wav")
            wavs.append(wav)
            await asyncio.to_thread(_edge_tts_to_wav, script, raw, voice)
            
            lead_in = ",adelay=140" if i == 0 else ""
            af = f"atempo={VOICE_SPEED},highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=24000,asetpts=PTS-STARTPTS{lead_in}"
            subprocess.run(["ffmpeg", "-y", "-i", raw, "-af", af, "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", wav], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            seg_durs.append(max(0.05, get_dur(wav)))

        list_f = os.path.join(work, "concat.txt")
        Path(list_f).write_text("".join("file '" + os.path.abspath(w).replace("'", "'\\''") + "'\n" for w in wavs), encoding="utf-8")
        joined = os.path.join(work, "joined.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_f, "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1", joined], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["ffmpeg", "-y", "-i", joined, "-map_metadata", "-1", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out_a], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return seg_durs
    finally:
        try_run(shutil.rmtree, work, ignore_errors=True)

# --- FFmpeg Video Sync ---
def edit_vid(iv, ia, ov, layout, blur_setting, source_dur, seg_durs):
    audio_dur = max(0.1, get_dur(ia))
    target = max(0.1, audio_dur)
    is_fr = layout == "Frame (9:16)"
    
    weights = [max(0.05, float(x)) for x in seg_durs.get("audio_segment_durs", [])]
    ranges = seg_durs.get("keep_ranges", [(0.0, source_dur, 0)])
    if not weights: weights = [target]
    
    src_group = [0.0] * len(weights)
    for a, b, i in ranges:
        if 0 <= i < len(src_group) and b > a: src_group[i] += b - a
    if sum(src_group) < 0.1: src_group = [source_dur]; weights = [target]

    source_bounds, target_bounds = [0.0], [0.0]
    for x in src_group: source_bounds.append(source_bounds[-1] + x)
    wsum = sum(weights)
    for x in weights: target_bounds.append(target_bounds[-1] + target * x / wsum)

    expr = f"{target_bounds[-1]:.6f}+(T-{source_bounds[-2]:.6f})*{((target_bounds[-1]-target_bounds[-2])/max(0.001,source_bounds[-1]-source_bounds[-2])):.8f}"
    for i in range(len(src_group)-2, -1, -1):
        slope = (target_bounds[i+1]-target_bounds[i])/max(0.001,source_bounds[i+1]-source_bounds[i])
        expr = f"if(lt(T,{source_bounds[i+1]:.6f}),{target_bounds[i]:.6f}+(T-{source_bounds[i]:.6f})*{slope:.8f},{expr})"
    
    trim_nodes = []
    split_labels = "".join(f"[src{j}]" for j in range(len(ranges)))
    trim_nodes.append(f"[0:v]split={len(ranges)}{split_labels}")
    for j, (a, b, _) in enumerate(ranges):
        trim_nodes.append(f"[src{j}]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[cut{j}]")
    if len(ranges) == 1:
        trim_nodes.append("[cut0]null[rawv]")
    else:
        concat_inputs = "".join(f"[cut{j}]" for j in range(len(ranges)))
        trim_nodes.append(f"{concat_inputs}concat=n={len(ranges)}:v=1:a=0[rawv]")

    video_clock = ";".join(trim_nodes) + f";[rawv]settb=AVTB,setpts='({expr})/TB',fps=24,tpad=stop_mode=clone:stop_duration={target + 2.0:.6f},trim=duration={target:.6f},setpts=PTS-STARTPTS[v0]"
    
    adj = "crop=iw*0.92:ih*0.92:iw*0.04:ih*0.04,eq=contrast=1.08:brightness=0.02:saturation=1.14:gamma=1.03,hue=h=3"
    fc = f"{video_clock};"
    
    if is_fr:
        fc += f"[v0]split=2[bgi][fgi];[bgi]scale=180:320:force_original_aspect_ratio=increase,crop=180:320,gblur=sigma=18,eq=brightness=-0.07,scale=720:1280[bg];[fgi]{adj},scale=720:827:force_original_aspect_ratio=increase:flags=lanczos,crop=720:827[fg];[bg][fg]overlay=0:226[v1]"
    else:
        fc += f"[v0]{adj},scale=720:1280:force_original_aspect_ratio=increase:flags=lanczos,crop=720:1280[v1]"
        
    cur = "[v1]"
    by, bh = (950, 86) if is_fr else (1040, 92) # Default blur bounds
    if blur_setting != "Off":
        if blur_setting == "Low": by, bh = (950, 86) if is_fr else (1040, 92)
        elif blur_setting == "Mid": by, bh = (880, 86) if is_fr else (940, 92)
        elif blur_setting == "High": by, bh = (790, 86) if is_fr else (830, 92)
        fc += f";{cur}split=2[m1][m2];[m2]crop=480:{bh}:30:{by},gblur=sigma=26[bst];[m1][bst]overlay=30:{by}[vout]"
    else:
        fc += f";{cur}copy[vout]"

    fc += f";[1:a:0]asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0,apad,atrim=duration={target:.6f},asetpts=PTS-STARTPTS[aout]"
    
    kbps = max(900, min(4200, int((42 * 8192) / target) - 140))
    cmd = [
        "ffmpeg", "-y", "-threads", "2", "-i", iv, "-i", ia,
        "-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
        "-fps_mode", "cfr", "-r", "24", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "22", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps*2}k",
        "-c:a", "aac", "-b:a", "128k", "-t", f"{target:.3f}", "-movflags", "+faststart", ov
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

# --- Main Gradio Processing Logic ---
async def process_video_gradio(api_key, voice_choice, layout_choice, blur_choice, video_path):
    if not api_key: raise gr.Error("🔑 Gemini API Key ထည့်ရန် လိုအပ်ပါသည်။")
    if not video_path: raise gr.Error("📥 ဗီဒီယိုဖိုင် ထည့်ရန် လိုအပ်ပါသည်။")
    
    voice_key = "my-MM-NilarNeural" if "Nilar" in voice_choice else "my-MM-ThihaNeural"
    job_id = str(uuid.uuid4())[:8]
    sm_v = f"temp_vid_{job_id}.mp4"
    apath = f"temp_aud_{job_id}.wav"
    opath = f"output_{job_id}.mp4"
    
    shutil.copy2(video_path, sm_v)
    source_vdur = max(1.0, get_dur(sm_v))
    n_win = max(1, min(30, int(math.ceil(source_vdur / 4.5))))
    
    gr.Info("🔄 [1/3] Video မှ စကားပြောများကို မြန်မာလို ဘာသာပြန်နေပါသည်...")
    analysis = await asyncio.to_thread(ai_frame_audio_translate, sm_v, api_key, source_vdur, n_win)
    
    gr.Info("🎙️ [2/3] AI အသံဖြင့် ဇာတ်ကြောင်းပြန်ပြောနေပါသည်...")
    raw_durs = await build_free_synced_voice(analysis["scripts"], voice_key, apath)
    analysis["audio_segment_durs"] = raw_durs
    
    gr.Info("🎬 [3/3] အသံနှင့် Video ကို Frame အလိုက် Sync လုပ်၍ Render လုပ်နေပါသည်...")
    await asyncio.to_thread(edit_vid, sm_v, apath, opath, layout_choice, blur_choice, source_vdur, analysis)
    
        # Cleanup Temp Files
    for p in [sm_v, apath]:
        try_run(os.remove, p)
        
    gr.Info("✅ အောင်မြင်စွာ ဖန်တီးပြီးပါပြီ။ အောက်တွင် Download လုပ်နိုင်ပါသည်။")
    return opath
    
# --- Gradio UI Layout (Dark Theme) ---
custom_theme = gr.themes.Monochrome(
    primary_hue="slate", secondary_hue="gray", neutral_hue="zinc",
    font=[gr.themes.GoogleFont("Inter"), "sans-serif"]
)

with gr.Blocks(theme=custom_theme, title="Si Gyi Recap Studio") as app:
    gr.Markdown("<h1 style='text-align: center; margin-bottom: 0;'>🎬 Si Gyi Recap Studio (Web)</h1>")
    gr.Markdown("<p style='text-align: center; color: gray;'>API Key ထည့်ပြီး Video များကို AI ဖြင့် အလွယ်တကူ ပြင်ဆင်လိုက်ပါ။</p>")
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### ⚙️ ပြင်ဆင်ခြင်း (Settings)")
            api_key_input = gr.Textbox(label="🔑 Gemini API Key (BYOK)", placeholder="AIzaSy...", type="password")
            voice_select = gr.Dropdown(label="🎙️ အသံရွေးရန်", choices=["my-MM-NilarNeural (မိန်းကလေး)", "my-MM-ThihaNeural (ယောကျ်ားလေး)"], value="my-MM-NilarNeural (မိန်းကလေး)")
            with gr.Row():
                layout_select = gr.Dropdown(label="📱 အချိုးအစား", choices=["Frame (9:16)", "Full Screen"], value="Frame (9:16)")
                blur_select = gr.Dropdown(label="🌫️ Blur အနေအထား", choices=["Auto", "Low", "Mid", "High", "Off"], value="Auto")
            video_input = gr.Video(label="📥 ဗီဒီယိုဖိုင် ထည့်ရန် (Upload / Drag & Drop)")
            run_btn = gr.Button("🚀 Start Render (ဗီဒီယို ဖန်တီးမည်)", variant="primary", size="lg")

        with gr.Column(scale=1):
            gr.Markdown("### 📤 ရလဒ် (Output Video)")
            video_output = gr.Video(label="ပြီးစီးသွားသော ဗီဒီယို (Download ဆွဲနိုင်ပါသည်)", interactive=False)

    run_btn.click(
        fn=process_video_gradio,
        inputs=[api_key_input, voice_select, layout_select, blur_select, video_input],
        outputs=video_output
    )

if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7860)
