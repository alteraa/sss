# Interruptible Speech-to-Speech

Bu proje, yerel robot cihaz üzerinde çalışan Türkçe odaklı, kesilebilir bir sesli
diyalog sistemidir.

Sistem klasik zinciri korur:

1. Mikrofon sürekli dinlenir
2. Kullanıcı konuşmaya başladığında ses toplanır
3. Konuşma bitince ses `OpenAI Whisper` ile metne çevrilir
4. Metin `LLM`'e gönderilir
5. Yanıt `OpenAI TTS` ile üretilir
6. Robot konuşurken kullanıcı tekrar konuşursa robot sözü kesilip dinlemeye döner

## Projenin Şu Anki Hali

Bu proje artık eski `PyAudio + ffplay + heuristics` yaklaşımını değil, daha güçlü bir
yerel ses hattını kullanır:

- `sounddevice` ile aynı process içinde full-duplex input/output
- `aec-audio-processing` ile gerçek zamanlı `AEC + noise suppression`
- `Silero VAD` ile konuşma algılama
- konuşma başlangıcında ek `RMS + crest factor` kapısı
- TTS sonrası residual sesleri azaltmak için queue temizliği ve kısa ignore penceresi

Bu sayede yüksek hoparlör ve mikrofon seviyelerinde bile robotun kendi TTS sesini
insan konuşması sanma problemi ciddi biçimde azaltılmıştır.

## Durum Makinesi

Ana akış 4 durumdan oluşur:

```text
IDLE -> LISTENING -> PROCESSING -> SPEAKING
```

- `IDLE`: Temizlenmiş mikrofonda yeni konuşma başlangıcı aranır
- `LISTENING`: Kullanıcı konuşması toplanır
- `PROCESSING`: Whisper + LLM çağrısı yapılır
- `SPEAKING`: TTS çalınır, interrupt algılama aktiftir

## Temel Dosyalar

- `main.py`: state machine ve ana akış
- `audio_io.py`: `sounddevice` stream, AEC/NS ve ses queue yönetimi
- `tts.py`: TTS üretimi ve aynı process içinde playback
- `sr.py`: `Silero VAD` ve Whisper transcription
- `utils.py`: konuşma başlangıcı ve interrupt eşikleri
- `llm.py`: OpenAI chat çağrısı

## Kurulum Notu

Python `3.12+` önerilir.

`Silero VAD` için `torch` ve `torchaudio` uyumlu CPU wheel olarak kurulmalıdır.
Gerekli paketler `requirements.txt` içindedir.

## Minimum Gereksinimler

Bu uygulamanın şu anki çalışan hali için gerçekten gerekli parçalar:

### Python paketleri

- `numpy`
- `openai`
- `python-dotenv`
- `torch`
- `torchaudio`
- `sounddevice`
- `aec-audio-processing`

### Sistem / apt paketleri

- `ffmpeg`
- `python3.12`
- `python3.12-venv`
- `libportaudio2`
- `portaudio19-dev`

### Ortam değişkeni

- `OPENAI_API_KEY`

### Not

Şu anki aktif workflow için `pyrnnoise` ve `soundfile` zorunlu değildir.

## Detaylı Dokümanlar

- `docs/LOCAL_AUDIO_AEC_ARCHITECTURE.md`
  Yerel `AEC-first` ses mimarisi, neden bu yapıya geçildiği, tuning noktaları ve
  teknik notlar.

- `docs/chatgpt_app.md`
  ChatGPT benzeri sesli deneyimin mimari referansı ve tasarım motivasyonu.

- `docs/FUTURE_DIRECTIONS.md`
  Echo, interrupt ve ses işleme tarafında ileri geliştirme yönleri.

- `docs/GUIDE.md`
  Ses işleme, echo cancellation ve düşük gecikmeli interrupt davranışı için araştırma
  rehberi.

- `docs/echo_gain_adaptation_main_vs_high-mic-level.md`
  Eski echo gain yaklaşımına dair tarihsel notlar.

## Kısa Not

Bu README kısa tutuldu ve mevcut çalışan mimariyi özetler. Parametre detayları,
tasarım kararları ve tuning önerileri için öncelikli referans:

`docs/LOCAL_AUDIO_AEC_ARCHITECTURE.md`
