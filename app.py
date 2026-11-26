"""
Kosakata Video - server lokal pribadi.

Alur (mengikuti pola innovationmech/video-translate):
  video (upload / link) -> Whisper (faster-whisper, waktu per kata)
  -> Gemini / Ollama (gratis) atau Claude (terjemahan + kosakata + slang) -> kartu kata di atas video.

Jalankan:  python app.py   lalu buka http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import List

import anthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")

DATA = Path(os.getenv("DATA_DIR", BASE / "data"))
DATA.mkdir(parents=True, exist_ok=True)
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
# Penerjemah: "gemini" (gratis, pakai kunci), "ollama" (gratis, offline di komputer ini) atau "claude" (berbayar)
PROVIDER = (os.getenv("LLM_PROVIDER") or (
    "gemini" if (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    else "claude" if os.getenv("ANTHROPIC_API_KEY") else "ollama")).lower()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = os.getenv("CLAUDE_EFFORT", "medium")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")
BATCH = 15 if PROVIDER == "ollama" else 40  # kalimat per permintaan ke penerjemah

LANGUAGES = {
    "id": "Bahasa Indonesia", "en": "English", "ms": "Bahasa Melayu", "jv": "Basa Jawa",
    "su": "Basa Sunda", "zh": "中文 (Mandarin)", "ja": "日本語", "ko": "한국어",
    "ar": "العربية", "hi": "हिन्दी", "th": "ไทย", "vi": "Tiếng Việt", "tl": "Filipino",
    "es": "Español", "pt": "Português", "fr": "Français", "de": "Deutsch",
    "it": "Italiano", "nl": "Nederlands", "ru": "Русский", "uk": "Українська",
    "pl": "Polski", "tr": "Türkçe", "fa": "فارسی", "ur": "اردو", "bn": "বাংলা",
    "ta": "தமிழ்", "sv": "Svenska", "no": "Norsk", "da": "Dansk", "fi": "Suomi",
    "el": "Ελληνικά", "he": "עברית", "cs": "Čeština", "ro": "Română", "hu": "Magyar",
    "sw": "Kiswahili", "my": "မြန်မာ", "km": "ខ្មែរ",
}

# ---------------------------------------------------------------- privasi
security = HTTPBasic(auto_error=False)


def guard(cred: HTTPBasicCredentials | None = Depends(security)):
    """Tanpa APP_PASSWORD server hanya terbuka di komputer ini (127.0.0.1).
    Dengan APP_PASSWORD, setiap akses wajib login (username bebas)."""
    if not APP_PASSWORD:
        return
    if cred is None or not secrets.compare_digest(cred.password.encode(), APP_PASSWORD.encode()):
        raise HTTPException(401, "Butuh kata sandi", headers={"WWW-Authenticate": "Basic"})


app = FastAPI(title="Kosakata Video", dependencies=[Depends(guard)], docs_url=None, redoc_url=None)

# ---------------------------------------------------------------- pekerjaan
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()
_whisper: dict[str, object] = {}


def job_dir(jid: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{12}", jid):
        raise HTTPException(404)
    return DATA / jid


def set_job(jid: str, **kw):
    with LOCK:
        JOBS[jid].update(kw)
        meta = {k: v for k, v in JOBS[jid].items() if k != "result"}
    (DATA / jid / "meta.json").write_text(json.dumps(meta, ensure_ascii=False))


def download_link(url: str, out: Path, jid: str) -> Path:
    import yt_dlp

    def hook(d):
        tot = d.get("total_bytes") or d.get("total_bytes_estimate")
        if d.get("status") == "downloading" and tot:
            set_job(jid, progress=min(0.99, d.get("downloaded_bytes", 0) / tot))

    opts = {
        "outtmpl": str(out / "video.%(ext)s"),
        # satu file berisi gambar+suara, utamakan mp4 agar bisa diputar di browser
        "format": "best[ext=mp4][acodec!=none][vcodec!=none]/best[acodec!=none][vcodec!=none]/best",
        "noplaylist": True, "quiet": True, "no_warnings": True,
        "progress_hooks": [hook],
    }
    cookies = os.getenv("YTDLP_COOKIES_FROM_BROWSER")
    if cookies:  # mis. "chrome" untuk video Facebook/Instagram yang butuh login
        opts["cookiesfrombrowser"] = (cookies,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))
    title = info.get("title") or url
    set_job(jid, title=title[:120])
    return path


def transcribe(path: Path, model_name: str, lang: str | None, jid: str):
    from faster_whisper import WhisperModel

    if model_name not in _whisper:
        set_job(jid, stage="model", message=f"Memuat model suara Whisper '{model_name}' (unduh sekali saja)…")
        _whisper[model_name] = WhisperModel(model_name, device=WHISPER_DEVICE, compute_type="auto")
    model = _whisper[model_name]
    set_job(jid, stage="asr", message="Mendengarkan video…", progress=0)
    segments, info = model.transcribe(
        str(path), language=lang or None, word_timestamps=True, vad_filter=True, beam_size=5,
    )
    words, dur = [], max(info.duration, 1)
    for seg in segments:
        for w in seg.words or []:
            words.append({"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)})
        set_job(jid, progress=min(0.99, seg.end / dur))
    return words, info.language, info.duration


CJK = re.compile(r"[぀-ヿ一-鿿가-힯฀-๿]")


def to_sentences(words):
    sents, cur = [], None
    for i, w in enumerate(words):
        if not w["w"]:
            continue
        if cur is None:
            cur = {"text": "", "s": w["s"], "e": w["e"], "w0": i}
            sents.append(cur)
        sep = "" if (not cur["text"] or CJK.search(w["w"])) else " "
        cur["text"] += sep + w["w"]
        cur["e"], cur["w1"] = w["e"], i
        if re.search(r"[.!?。！？]['\")]?$", w["w"]) or len(cur["text"]) > 180:
            cur = None
    return sents


# ---------------------------------------------------------------- Claude
class SentenceOut(BaseModel):
    i: int
    translation: str


class VocabOut(BaseModel):
    term: str          # persis seperti di video; boleh frasa/idiom/slang multi-kata
    lemma: str         # bentuk dasar
    meaning: str       # arti singkat dalam bahasa target, sesuai konteks video
    pos: str           # jenis kata dalam bahasa target
    slang: bool        # True jika slang/gaul/informal/idiom
    note: str          # penjelasan slang/nuansa singkat dalam bahasa target ("" jika tidak perlu)
    sentence: int      # indeks kalimat tempat istilah ini muncul pertama kali


class Analysis(BaseModel):
    sentences: List[SentenceOut]
    vocab: List[VocabOut]


SYSTEM = """You are an expert interpreter and language teacher who builds vocabulary cards from video transcripts.
You know contemporary slang, internet speech, regional dialects, idioms and filler words in every major language.

For the numbered transcript sentences you receive:
1. Translate every sentence into the target language naturally, the way a native speaker would say it, keeping tone and slang (translate slang with an equivalent slang or casual phrase, never word-for-word). Fix obvious speech-recognition errors silently using context.
2. Extract the vocabulary worth learning: content words, phrasal verbs, idioms, collocations, slang, abbreviations and informal contractions (gonna, ain't, lowkey, no cap, bussin, 草, ㅋㅋ, anjir, etc.). Skip trivial function words (articles, pronouns, basic auxiliaries) unless used in a special way.
   - `term`: exactly as spoken in the transcript (lowercase unless a proper noun); multi-word expressions are one term.
   - `meaning`: the meaning in THIS context, in the target language, short (max ~6 words; up to 3 alternatives separated by commas).
   - `pos`: part of speech written in the target language.
   - `slang`: true for slang, informal speech, idioms, internet language, profanity or dialect.
   - `note`: for slang/idioms, one short sentence in the target language explaining the nuance or when people use it; otherwise "".
   - `sentence`: index of the sentence where it first appears.
   List each term once. Do not invent terms that are not in the transcript."""


class LLMError(RuntimeError):
    pass


PROVIDER_NAME = {"gemini": "Gemini", "ollama": "Ollama", "claude": "Claude"}.get(PROVIDER, PROVIDER)


def ask_gemini(user: str) -> Analysis:
    from google import genai
    from google.genai import errors, types

    client = genai.Client()  # membaca GEMINI_API_KEY
    cfg = types.GenerateContentConfig(system_instruction=SYSTEM, response_mime_type="application/json",
                                      response_schema=Analysis, temperature=0.2)
    for attempt in range(4):
        try:
            r = client.models.generate_content(model=GEMINI_MODEL, contents=user, config=cfg)
            break
        except errors.ClientError as e:
            if e.code == 429 and attempt < 3:  # batas gratis per menit: tunggu lalu coba lagi
                time.sleep(25 * (attempt + 1))
                continue
            if e.code == 429:
                raise LLMError("Batas gratis Gemini hari ini/menit ini tercapai. Coba lagi nanti.") from e
            if e.code in (400, 401, 403) and "key" in str(e).lower():
                raise LLMError("Kunci Gemini salah. Periksa GEMINI_API_KEY di file .env.") from e
            raise LLMError(f"Gemini error {e.code}: {e.message}") from e
        except errors.ServerError as e:
            if attempt < 3:
                time.sleep(10)
                continue
            raise LLMError(f"Server Gemini sedang sibuk ({e.code}). Coba lagi nanti.") from e
    if r.parsed is not None:
        return r.parsed
    try:
        return Analysis.model_validate_json(r.text or "")
    except Exception as e:  # noqa: BLE001
        raise LLMError("Gemini tidak mengembalikan hasil untuk bagian ini.") from e


def ask_ollama(user: str) -> Analysis:
    import urllib.error
    import urllib.request

    body = json.dumps({
        "model": OLLAMA_MODEL, "stream": False, "format": Analysis.model_json_schema(),
        "options": {"temperature": 0.2, "num_ctx": 8192},
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(OLLAMA_URL + "/api/chat", body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise LLMError(f"Model Ollama '{OLLAMA_MODEL}' belum diunduh. Jalankan: ollama pull {OLLAMA_MODEL}") from e
        raise LLMError(f"Ollama error {e.code}: {e.read()[:200]!r}") from e
    except (urllib.error.URLError, ConnectionError) as e:
        raise LLMError("Ollama belum berjalan. Pasang dari ollama.com, lalu jalankan: "
                       f"ollama pull {OLLAMA_MODEL}  — atau isi GEMINI_API_KEY (gratis) di .env.") from e
    try:
        return Analysis.model_validate_json(data["message"]["content"])
    except Exception as e:  # noqa: BLE001
        raise LLMError("Ollama tidak mengembalikan hasil yang valid. Coba model yang lebih besar.") from e


def ask_claude(user: str) -> Analysis:
    client = anthropic.Anthropic()
    resp = client.beta.messages.parse(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": CLAUDE_EFFORT},
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_format=Analysis,
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise LLMError("Claude menolak atau tidak mengembalikan hasil untuk bagian ini.")
    return resp.parsed_output


def ask_llm(user: str) -> Analysis:
    return {"gemini": ask_gemini, "ollama": ask_ollama, "claude": ask_claude}[PROVIDER](user)


def analyze(sents, src_lang: str, tgt: str, level: str, jid: str):
    tgt_name = LANGUAGES.get(tgt, tgt)
    out_s: dict[int, str] = {}
    vocab: dict[str, dict] = {}
    batches = [sents[i:i + BATCH] for i in range(0, len(sents), BATCH)]
    for bi, batch in enumerate(batches):
        set_job(jid, stage="llm", message=f"{PROVIDER_NAME} menerjemahkan & menyusun kosakata… ({bi + 1}/{len(batches)})",
                progress=bi / len(batches))
        start = bi * BATCH
        context = " ".join(s["text"] for s in sents[max(0, start - 3):start])
        lines = "\n".join(f"[{start + k}] {s['text']}" for k, s in enumerate(batch))
        user = (
            f"Source language (detected): {src_lang}\nTarget language: {tgt_name} ({tgt})\n"
            f"Learner level: {level}. Choose vocabulary that is useful for this level.\n"
            + (f"Previous context (do not translate): {context}\n" if context else "")
            + f"\nTranscript:\n{lines}"
        )
        res = ask_llm(user)
        for s in res.sentences:
            out_s[s.i] = s.translation
        for v in res.vocab:
            key = v.term.strip().lower()
            if key and key not in vocab:
                vocab[key] = v.model_dump()
    return out_s, list(vocab.values())


def norm(t: str) -> str:
    return re.sub(r"^[^\w']+|[^\w']+$", "", t.lower().replace("’", "'"))


def locate(vocab, words, sents):
    """Cari setiap kemunculan istilah (termasuk frasa) di daftar kata bertimestamp."""
    keys = [norm(w["w"]) for w in words]
    cjk_joined = "".join(keys)
    for v in vocab:
        parts = [norm(p) for p in v["term"].split()] or [norm(v["term"])]
        parts = [p for p in parts if p]
        occ = []
        if parts:
            n = len(parts)
            for i in range(len(keys) - n + 1):
                if keys[i:i + n] == parts:
                    occ.append({"s": words[i]["s"], "e": words[i + n - 1]["e"], "w": " ".join(w["w"] for w in words[i:i + n])})
            if not occ and CJK.search(v["term"]):  # bahasa tanpa spasi: cari di dalam token
                for i, k in enumerate(keys):
                    if parts[0] in k:
                        occ.append({"s": words[i]["s"], "e": words[i]["e"], "w": v["term"]})
        if not occ and 0 <= v.get("sentence", -1) < len(sents):  # cadangan: waktu kalimatnya
            s = sents[v["sentence"]]
            occ.append({"s": s["s"], "e": min(s["e"], s["s"] + 2), "w": v["term"]})
        v["occ"] = occ
        v["s"] = occ[0]["s"] if occ else 0
    vocab.sort(key=lambda v: v["s"])
    return vocab


def run_job(jid: str, src: Path | None, url: str | None, opts: dict):
    d = DATA / jid
    try:
        if url:
            set_job(jid, stage="download", message="Mengunduh video dari link…", progress=0)
            src = download_link(url, d, jid)
        set_job(jid, video=src.name)
        words, lang, dur = transcribe(src, opts["whisper"], opts["src"], jid)
        if not words:
            raise RuntimeError("Tidak ada ucapan yang terdengar di video ini.")
        sents = to_sentences(words)
        trans, vocab = analyze(sents, lang, opts["tgt"], opts["level"], jid)
        for i, s in enumerate(sents):
            s["tr"] = trans.get(i, "")
        vocab = locate(vocab, words, sents)
        result = {"lang": lang, "tgt": opts["tgt"], "duration": dur, "sentences": sents, "vocab": vocab}
        (d / "result.json").write_text(json.dumps(result, ensure_ascii=False))
        set_job(jid, stage="done", progress=1, message=f"Selesai: {len(vocab)} kosakata, "
                f"{sum(v['slang'] for v in vocab)} slang/idiom.")
    except LLMError as e:
        set_job(jid, stage="error", message=str(e))
    except anthropic.AuthenticationError:
        set_job(jid, stage="error", message="Kunci API Claude salah atau belum diisi di file .env (ANTHROPIC_API_KEY).")
    except anthropic.RateLimitError:
        set_job(jid, stage="error", message="Batas pemakaian Claude tercapai. Coba lagi beberapa menit lagi.")
    except anthropic.APIConnectionError:
        set_job(jid, stage="error", message="Tidak bisa terhubung ke Claude. Periksa koneksi internet.")
    except anthropic.APIStatusError as e:
        set_job(jid, stage="error", message=f"Claude error {e.status_code}: {e.message}")
    except Exception as e:  # noqa: BLE001
        msg = re.split(r" \(caused by|; please report", str(e))[0].replace("ERROR: ", "")
        if "login" in msg.lower() or "cookies" in msg.lower():
            msg += " — Untuk Facebook/Instagram pribadi, isi YTDLP_COOKIES_FROM_BROWSER=chrome di .env."
        set_job(jid, stage="error", message=msg[:500])


# ---------------------------------------------------------------- API
@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/api/config")
def config():
    return {"languages": LANGUAGES, "provider": PROVIDER_NAME,
            "model": {"gemini": GEMINI_MODEL, "ollama": OLLAMA_MODEL, "claude": CLAUDE_MODEL}.get(PROVIDER),
            "has_key": PROVIDER == "ollama" or bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
                                                    or os.getenv("ANTHROPIC_API_KEY"))}


@app.post("/api/jobs")
async def create_job(
    file: UploadFile | None = File(None), url: str = Form(""), tgt: str = Form("id"),
    src: str = Form(""), whisper: str = Form("small"), level: str = Form("menengah"),
):
    if not file and not url.strip():
        raise HTTPException(400, "Unggah video atau tempel link.")
    if url and not re.match(r"^https?://", url.strip()):
        raise HTTPException(400, "Link harus diawali http:// atau https://")
    if whisper not in {"tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"}:
        raise HTTPException(400, "Model Whisper tidak dikenal.")
    jid = uuid.uuid4().hex[:12]
    d = DATA / jid
    d.mkdir()
    path = None
    title = url.strip()
    if file:
        ext = (Path(file.filename or "").suffix or ".mp4").lower()[:6]
        path = d / f"video{ext}"
        with path.open("wb") as f:
            while chunk := await file.read(1 << 20):
                f.write(chunk)
        title = file.filename or "video"
    with LOCK:
        JOBS[jid] = {"id": jid, "title": title[:120], "stage": "queued", "message": "Menunggu…",
                     "progress": 0, "tgt": tgt, "created": time.time(), "video": path.name if path else None}
    set_job(jid)
    opts = {"tgt": tgt, "src": src or None, "whisper": whisper, "level": level}
    threading.Thread(target=run_job, args=(jid, path, url.strip() or None, opts), daemon=True).start()
    return {"id": jid}


def load_meta(jid: str) -> dict:
    if jid in JOBS:
        return JOBS[jid]
    m = job_dir(jid) / "meta.json"
    if not m.exists():
        raise HTTPException(404)
    meta = json.loads(m.read_text())
    if meta.get("stage") not in ("done", "error"):  # server sempat mati di tengah proses
        meta.update(stage="error", message="Proses terhenti karena server dimatikan. Ulangi.")
    return meta


@app.get("/api/jobs")
def list_jobs():
    out = []
    for m in DATA.glob("*/meta.json"):
        try:
            out.append(load_meta(m.parent.name))
        except Exception:  # noqa: BLE001
            pass
    return sorted(out, key=lambda j: -j.get("created", 0))[:50]


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    meta = dict(load_meta(jid))
    r = job_dir(jid) / "result.json"
    if meta.get("stage") == "done" and r.exists():
        meta["result"] = json.loads(r.read_text())
    return meta


@app.delete("/api/jobs/{jid}")
def delete_job(jid: str):
    import shutil
    d = job_dir(jid)
    if JOBS.get(jid, {}).get("stage") not in (None, "done", "error"):
        raise HTTPException(409, "Masih diproses.")
    shutil.rmtree(d, ignore_errors=True)
    JOBS.pop(jid, None)
    return {"ok": True}


@app.get("/api/jobs/{jid}/video")
def video(jid: str):
    meta = load_meta(jid)
    name = meta.get("video")
    if not name:
        raise HTTPException(404)
    return FileResponse(job_dir(jid) / Path(name).name)


if __name__ == "__main__":
    import uvicorn

    if HOST not in ("127.0.0.1", "localhost") and not APP_PASSWORD:
        raise SystemExit("HOST bukan 127.0.0.1: isi APP_PASSWORD di .env agar aplikasi tetap pribadi.")
    print(f"\n  Kosakata Video berjalan di  http://{'127.0.0.1' if HOST == '0.0.0.0' else HOST}:{PORT}\n")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
