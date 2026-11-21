import streamlit as st
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
import subprocess
import re
import json
import os

st.set_page_config(page_title="AI Viral Clip Finder", page_icon="🎬", layout="centered")
st.title("🎬 Free AI Viral Clip Finder")
st.write("Paste a YouTube link to find the best moments for Shorts & Reels.")

with st.sidebar:
    st.header("Settings")
    default_key = st.secrets.get("GEMINI_API_KEY", "") if "GEMINI_API_KEY" in st.secrets else ""
    api_key = st.text_input("Gemini API Key (Free from AI Studio)", value=default_key, type="password")
    crop_vertical = st.checkbox("Auto-crop to 9:16 Vertical (Shorts/Reels)", value=True)
    st.caption("Get a free key at aistudio.google.com")

class ViralClip(BaseModel):
    title: str = Field(description="Catchy hook title for Shorts/Reels")
    start_seconds: int = Field(description="Start time in seconds")
    end_seconds: int = Field(description="End time in seconds (clip should be 25 to 60 seconds long)")
    virality_score: int = Field(description="Score from 1 to 10")
    reason: str = Field(description="Why this clip will go viral")

class ClipList(BaseModel):
    clips: list[ViralClip]

def extract_video_id(url):
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
    return match.group(1) if match else None

def format_time(seconds):
    mins, secs = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}" if hrs else f"{mins:02d}:{secs:02d}"

video_url = st.text_input("🔗 Paste YouTube Video Link:", placeholder="https://www.youtube.com/watch?v=...")

with st.expander("📝 Optional: Paste Transcript Manually (If YouTube blocks cloud IP)"):
    manual_transcript = st.text_area("Paste YouTube transcript here (Open video on YouTube → Description → Show transcript → Copy & Paste)", height=150)

if st.button("🔍 Find Viral Moments", type="primary"):
    if not api_key:
        st.error("Please enter your free Gemini API Key in the left sidebar first.")
    elif not video_url and not manual_transcript:
        st.error("Please paste a YouTube link or transcript.")
    else:
        client = genai.Client(api_key=api_key)
        models_to_try = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-4-hydrogen"]
        
        base_prompt = """
        Analyze this video and find the top 5 most viral, engaging moments suitable for YouTube Shorts and Instagram Reels.
        Rules:
        - Each clip MUST be between 25 and 60 seconds long.
        - Look for strong hooks, shocking facts, emotional stories, funny moments, or actionable advice.
        - Return accurate start_seconds and end_seconds.
        """

        with st.spinner("AI is analyzing the video for viral hooks..."):
            success = False
            last_error = None

            # Method A: If user pasted manual transcript, use it
            if manual_transcript.strip():
                contents_payload = f"{base_prompt}\n\nTranscript:\n{manual_transcript[:60000]}"
            else:
                # Method B: Try fetching transcript via API; if IP blocked, pass YouTube URL directly to Gemini
                video_id = extract_video_id(video_url)
                transcript_text = ""
                if video_id:
                    try:
                        ytt_api = YouTubeTranscriptApi()
                        transcript_list = ytt_api.list(video_id)
                        transcript = transcript_list.find_transcript(['en', 'hi', 'en-IN'])
                        fetched = transcript.fetch()
                        for entry in fetched:
                            transcript_text += f"[{int(entry.start)}s] {entry.text}\n"
                    except Exception:
                        transcript_text = ""

                if transcript_text:
                    contents_payload = f"{base_prompt}\n\nTranscript:\n{transcript_text[:60000]}"
                else:
                    # Pass YouTube link directly to Gemini multimodal video understanding
                    clean_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else video_url
                    contents_payload = [
                        types.Part.from_uri(file_uri=clean_url, mime_type="video/mp4"),
                        base_prompt
                    ]

            for model_name in models_to_try:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=contents_payload,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=ClipList,
                        ),
                    )
                    data = json.loads(response.text)
                    st.session_state["clips"] = data["clips"]
                    st.session_state["video_url"] = video_url
                    success = True
                    break
                except Exception as e:
                    last_error = e
                    continue

            if not success:
                st.error(f"Could not analyze video right now. Tip: Expand the 'Paste Transcript Manually' box above and paste the video's YouTube transcript for instant results! Details: {last_error}")

if "clips" in st.session_state:
    st.subheader("🔥 Suggested Viral Clips")
    for idx, clip in enumerate(st.session_state["clips"]):
        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"### {idx+1}. {clip['title']} (Score: {clip['virality_score']}/10)")
                st.write(f"**Timestamps:** `{format_time(clip['start_seconds'])}` → `{format_time(clip['end_seconds'])}` ({clip['end_seconds'] - clip['start_seconds']}s)")
                st.write(f"**Why it works:** {clip['reason']}")
            with col2:
                if st.button(f"✂️ Cut Clip #{idx+1}", key=f"cut_{idx}"):
                    with st.spinner("Downloading & cutting segment..."):
                        output_file = f"viral_clip_{idx+1}.mp4"
                        if os.path.exists(output_file):
                            os.remove(output_file)
                        
                        start_str = format_time(clip['start_seconds'])
                        end_str = format_time(clip['end_seconds'])
                        
                        cmd = [
                            "yt-dlp",
                            "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]",
                            "--download-sections", f"*{start_str}-{end_str}",
                            "--force-keyframes-at-cuts",
                            "-o", "temp_raw.mp4",
                            st.session_state["video_url"]
                        ]
                        subprocess.run(cmd, check=False)
                        
                        if os.path.exists("temp_raw.mp4"):
                            if crop_vertical:
                                ffmpeg_cmd = [
                                    "ffmpeg", "-y", "-i", "temp_raw.mp4",
                                    "-vf", "crop=ih*(9/16):ih",
                                    "-c:a", "copy", output_file
                                ]
                                subprocess.run(ffmpeg_cmd, check=False)
                                os.remove("temp_raw.mp4")
                            else:
                                os.rename("temp_raw.mp4", output_file)
                                
                        if os.path.exists(output_file):
                            with open(output_file, "rb") as f:
                                st.download_button(
                                    label="⬇️ Download MP4",
                                    data=f,
                                    file_name=output_file,
                                    mime="video/mp4",
                                    key=f"dl_{idx}"
                                )
                        else:
                            st.warning("YouTube blocked the direct server download on this shared IP. Use the exact timestamps above to cut it in CapCut or your video editor!")
