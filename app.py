from flask import Flask, render_template
import whisper
import requests

app = Flask(__name__)

model = whisper.load_model("base")

@app.route("/")
def process_audio():
    file_path = "santosh.mp3"  # your local file

    # Step 1: Transcribe
    result = model.transcribe(file_path, language="hi")
    transcript = result["text"]

    # Step 2: Send to Ollama
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "llama3",
            "prompt": f"""
            Summarize this meeting and extract:
            1. Key points
            2. Action items
            3. Decisions

            Transcript:
            {transcript}
            """,
            "stream": False
        }
    )

    summary = response.json()["response"]

    # Send data to HTML
    return render_template("front.html", transcript=transcript, summary=summary)


if __name__ == "__main__":
    app.run(debug=True)