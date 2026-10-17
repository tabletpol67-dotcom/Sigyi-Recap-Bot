FROM python:3.10-slim

WORKDIR /app

# FFmpeg ကို Server ပေါ်တွင် သွင်းခြင်း
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Library များကို သွင်းခြင်း
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ဖိုင်များအားလုံးကို ကူးယူခြင်း
COPY . .

# Gradio အတွက် Port ဖွင့်ပေးခြင်း
EXPOSE 7860
ENV GRADIO_SERVER_NAME="0.0.0.0"

CMD ["python", "app.py"]
