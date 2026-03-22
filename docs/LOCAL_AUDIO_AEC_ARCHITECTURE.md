# Local Audio AEC Architecture

Bu doküman, `speech-to-speech` projesinde yapılan yerel ses mimarisi dönüşümünü
özetler. Amaç, aynı cihaz üzerinde çalışan robotta hoparlör sesi ve mikrofon gain'i
yüksek olsa bile sistemin kendi TTS sesini gerçek kullanıcı konuşması sanmamasıdır.

## Hedef

Eski yaklaşımda sistem:

- mikrofonu `PyAudio` ile okuyordu,
- TTS sesini `ffplay` ile ayrı process içinde çalıyordu,
- robot konuşurken oluşan yankıyı büyük ölçüde sonradan heuristics ile bastırmaya
  çalışıyordu.

Bu yapı çalışsa da yüksek hoparlör ve mikrofon seviyelerinde robot kendi sesini
duyup yanlış interrupt üretebiliyordu.

Yeni hedef:

- klasik `ASR -> LLM -> TTS` zincirini korumak,
- ama ses ön-uç katmanını `AEC-first` hale getirmek,
- aynı process içinde senkron playback/capture yapmak,
- interrupt kararını ham mikrofonda değil, temizlenmiş sinyal üzerinde vermek.

## Yeni Mimari

Yeni mimarinin merkezinde `audio_io.py` bulunur.

Akış:

1. Mikrofon ve hoparlör aynı `sounddevice.Stream` içinde açılır.
2. Hoparlöre gönderilen TTS örnekleri `reverse stream` olarak `aec-audio-processing`
   modülüne verilir.
3. Mikrofondan gelen chunk'lar 10 ms frame'lere bölünür.
4. Her frame için:
   - `process_reverse_stream()`
   - `process_stream()`
   çağrılır.
5. Ortaya çıkan temizlenmiş ses chunk'ları ana state machine'e queue üzerinden verilir.
6. `main.py` artık konuşma algılama ve interrupt kararlarını bu temizlenmiş sinyal
   üzerinde verir.

Kritik dosyalar:

- `audio_io.py`: full-duplex input/output, AEC/NS, queue yönetimi
- `tts.py`: TTS üretimi ve aynı process içinde playback başlatma
- `main.py`: durum makinesi, ASR/LLM/TTS akışı, interrupt mantığı
- `sr.py`: Silero VAD + Whisper transcription
- `utils.py`: speech-start gating, interrupt gating, temel eşikler

## Neden `ffplay` Kaldırıldı?

`ffplay` ayrı process içinde oynattığı için:

- hoparlörden gerçekten ne zaman hangi sample çıktığını kesin bilmek zorlaşıyordu,
- playback ile microphone capture zaman ekseni tam uyuşmuyordu,
- güçlü AEC için gereken referans sinyal zinciri zayıf kalıyordu.

Yeni yapıda TTS çıktısı WAV/PCM örneklerine dönüştürülüp doğrudan `AudioIO`
playback buffer'ına yazılır. Böylece AEC modülü tam olarak çalınan referans sesle
çalışır.

## TTS Akışı

`tts.py` içindeki `TTSPlayer` şu şekilde çalışır:

1. OpenAI TTS ile MP3 üretir.
2. `ffmpeg` ile bunu `16 kHz mono PCM WAV` formatına çevirir.
3. WAV içindeki örnekleri `numpy int16` olarak okur.
4. `audio_io.start_playback(ref)` ile hoparlör akışına verir.

Bu tasarımın önemli etkisi:

- TTS referansı artık AEC için doğrudan kullanılabilir,
- konuşma bitiminde playback state merkezi olarak kapanır,
- TTS sonrası residual sesleri kontrol etmek kolaylaşır.

## Mikrofon Tarafındaki Yeni Karar Mantığı

Sistem artık yalnızca "bir ses geldi" diye `hear` moduna geçmez. `IDLE -> LISTENING`
geçişi için `utils.py` içinde daha seçici bir `is_speech_start()` filtresi vardır.

Bu filtre üç koşul arar:

- VAD eşiği geçilmeli
- RMS, dinamik baseline'a göre yeterince yüksek olmalı
- sinyal çok impulsive olmamalı

Son madde özellikle önemlidir. Parmak şıklatma, alkış, kısa darbe, masa vurma gibi
sesler genelde konuşmaya göre çok daha yüksek crest factor üretir. Bu nedenle
`crest_factor()` tabanlı bir transient filtresi eklenmiştir.

## Interrupt Mantığı

Robot konuşurken interrupt kararı için ana kural şudur:

- TTS başladıktan hemen sonra kısa bir grace period vardır
- bu sürede yalnızca baseline toplanır
- grace sonrası `InterruptDetector` temizlenmiş mikrofonda:
  - RMS yükselişi
  - VAD pozitifliği
  - ardışık hold
  ile karar verir

Yani interrupt artık robotun ham yankısına göre değil, AEC sonrası kalan sinyale göre
çalışır.

## TTS Sonrası Yanlış Tetikleri Azaltmak İçin Eklenen Önlemler

TTS bittikten sonra bazen residual echo veya queue içinde kalan eski chunk'lar
yanlış `hear` başlatabiliyordu. Bunu azaltmak için:

- `audio_io.clear_input_queue()` eklendi
- playback başlarken ve biterken input queue temizleniyor
- `main.py` içinde `POST_TTS_IGNORE_CHUNKS` kadar kısa bir ignore penceresi var
- bu pencere boyunca sistem baseline toplamaya devam ediyor ama yeni konuşma
  başlatmıyor

## VAD Kararı

Projede tek workflow olarak `Silero VAD` kullanılır.

Notlar:

- `Silero VAD` için `torch` ve `torchaudio` uyumlu CPU wheel olarak kurulmalıdır
- `torchaudio` yanlış wheel ile kurulursa `libtorchaudio.so` yüklenmeyebilir
- bu projede doğrulanmış kurulum çifti:
  - `torch==2.10.0+cpu`
  - `torchaudio==2.10.0+cpu`

Önerilen kurulum:

```bash
uv pip install --python .venv/bin/python --index-url https://download.pytorch.org/whl/cpu "torch==2.10.0+cpu" "torchaudio==2.10.0+cpu"
```

## Gerekli Paketler

`requirements.txt` içindeki ana paketler:

- `torch`
- `torchaudio`
- `sounddevice`
- `aec-audio-processing`
- `numpy`
- `openai`
- `python-dotenv`

Varsayılan kurulum artık yalnızca aktif workflow'ta kullanılan paketleri içerir.

Eklenebilecek özellik notları:

- `pyrnnoise`: AEC sonrasına opsiyonel ikinci aşama noise suppression katmanı olarak yeniden eklenebilir
- `soundfile`: ileride dosya tabanlı ses debug/export veya offline analiz araçları gerekirse eklenebilir

## `output underflow` Notu

`sounddevice` açılışında zaman zaman tekil `output underflow` logları görülebilir.
Bu genellikle stream startup anında output buffer prime edilmeden önce oluşan kısa bir
durumdur.

Bunu azaltmak için:

- stream `latency="high"` ile açılır
- startup sırasında playback yokken gelen tekil output underflow logları filtrelenir
- gerçek tekrar eden callback sorunları yine loglanır

Eğer underflow sürekli hale gelirse:

- callback içinde yapılan DSP işinin hafifletilmesi,
- AEC işinin callback dışına taşınması,
- blocksize ve latency tuning
değerlendirilmelidir.

## Şu Anki Güçlü Sonuç

Bu mimari değişikliğinin en önemli kazanımı:

- mikrofon ve hoparlör seviyesi çok yüksek olsa bile sistemin kendi TTS sesini
  kullanıcı konuşması sanma oranı ciddi şekilde düşmüştür

Pratikte bu, robot üzerinde "yüksek gain altında kendi kendini kesmeme" hedefini
başarmıştır.

## Bilinen Sınırlamalar

- `aec-audio-processing` stream delay ayarı (`AUDIO_PROCESSOR_DELAY_MS`) ortama göre
  ince ayar isteyebilir
- farklı hoparlör/mikrofon donanımlarında en iyi sonuç için eşikler yeniden
  kalibre edilebilir
- `Silero VAD` konuşma algısında güçlüdür ama çok gürültülü ortamlarda tek başına
  yeterli olmayabilir; gerekirse ek bir speech classifier katmanı düşünülebilir
- `pyrnnoise` henüz aktif akışa dahil edilmemiştir

## Tuning İçin Ana Parametreler

`audio_io.py`

- `AUDIO_PROCESSOR_DELAY_MS`
- `AUDIO_PROCESSOR_FRAME_SIZE`

`utils.py`

- `SPEAK_THRESHOLD`
- `START_RMS_MULTIPLIER`
- `MIN_START_RMS`
- `MAX_START_CREST_FACTOR`
- `INTERRUPT_RMS_MULTIPLIER`
- `INTERRUPT_VAD_THRESHOLD`
- `INTERRUPT_HOLD`
- `INTERRUPT_GRACE_PERIOD`

`main.py`

- `POST_TTS_IGNORE_CHUNKS`

## Önerilen Sonraki Teknik Adımlar

1. Gerçek cihaz üstünde farklı hoparlör ve mikrofon seviyeleri için kısa bir test
   matrisi çıkar
2. `AUDIO_PROCESSOR_DELAY_MS` için 40 / 60 / 80 ms karşılaştır
3. `pyrnnoise` katmanını isteğe bağlı ikinci aşama olarak değerlendir
4. Uzun vadede callback içindeki iş yükü artarsa AEC işini ayrı processing thread'e
   taşı
