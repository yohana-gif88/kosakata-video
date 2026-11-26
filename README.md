# Kosakata Video

Aplikasi pribadi untuk belajar kosakata dari video. Unggah video atau tempel link (Facebook, YouTube, TikTok, Instagram, X, dan lainnya). Setiap kosakata, idiom dan **slang** akan muncul di layar bersama artinya tepat saat diucapkan.

Alurnya mengikuti [innovationmech/video-translate](https://github.com/innovationmech/video-translate):

| Langkah | Alat |
|---|---|
| Ambil video dari link | `yt-dlp` |
| Transkripsi + waktu per kata | Whisper (`faster-whisper`, berjalan di komputer Anda) |
| Terjemahan kalimat, kosakata, slang & penjelasannya | **Gemini** (gratis) atau **Ollama** (gratis, offline); Claude opsional |
| Kartu kata di atas video, CSV, SRT, unduh video bersubtitle | Browser |

## Pribadi

Aplikasi berjalan di komputer Anda sendiri pada `http://127.0.0.1:8000`, jadi hanya Anda yang bisa membukanya. Video dan hasilnya disimpan di folder `data/` di komputer Anda. Dengan Gemini, hanya teks transkrip yang dikirim ke Google untuk diterjemahkan (catatan: data di paket gratis Gemini dapat dipakai Google untuk meningkatkan layanannya). Dengan Ollama, **tidak ada data yang keluar** dari komputer Anda.

## Cara menjalankan

1. Pasang **Python 3.10+** (centang *Add Python to PATH* di Windows).
2. Unduh repo ini (tombol **Code → Download ZIP**), lalu ekstrak.
3. Pilih penerjemah gratis:
   - **Gemini (disarankan):** buat kunci gratis di https://aistudio.google.com/apikey, lalu isi `GEMINI_API_KEY` di file `.env` (dibuat otomatis dari `.env.example` saat pertama dijalankan).
   - **Ollama (offline total):** pasang dari https://ollama.com, lalu jalankan `ollama pull qwen2.5:7b`. Biarkan `GEMINI_API_KEY` kosong.
4. Jalankan:
   - **Windows:** klik dua kali `start.bat`
   - **Mac/Linux:** `./start.sh`
5. Browser akan terbuka di `http://127.0.0.1:8000`.

Pertama kali dijalankan, paket Python dan model suara Whisper akan diunduh (beberapa menit).

## Biaya

Semua komponen gratis: Whisper dan yt-dlp berjalan di komputer Anda, Gemini memakai paket gratis (ada batas jumlah permintaan per menit/hari; aplikasi otomatis menunggu lalu mencoba lagi), dan Ollama sepenuhnya gratis.

## Tips

- **Model suara:** `small` seimbang; `large-v3-turbo` paling akurat dan cukup cepat bila ada GPU.
- **Video Facebook/Instagram yang butuh login:** isi `YTDLP_COOKIES_FROM_BROWSER=chrome` di `.env` (login dulu di Chrome).
- **Membuka dari HP di Wi-Fi yang sama:** set `HOST=0.0.0.0` dan `APP_PASSWORD=...` di `.env`, lalu buka `http://<IP-komputer>:8000`.
- 39 bahasa tujuan tersedia, bahasa video dideteksi otomatis.
