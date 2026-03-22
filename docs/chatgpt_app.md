# ChatGPT Tarzı Sesli Uygulama Notları

Bu dosya genel ürün/mimari referansı içindir; `speech-to-speech` projesinin güncel
uygulama mimarisini tarif etmez. Bu repo için geçerli gerçek kaynak
`docs/LOCAL_AUDIO_AEC_ARCHITECTURE.md` dosyasıdır.

## Bu projede şu an ne kullanılıyor?

Mevcut proje:

- klasik `ASR -> LLM -> TTS` zinciri kullanır
- yerel mikrofon/hoparlör akışını `sounddevice` ile yönetir
- TTS referansını aynı process içinde AEC'e besler
- konuşma algısı için `Silero VAD` kullanır
- interrupt kararını temizlenmiş mikrofon sinyali üstünden verir

Bu nedenle aşağıdaki notlar, "genel olarak ChatGPT benzeri sesli uygulamalarda hangi
katmanlar olabilir?" sorusuna yöneliktir; repodaki aktif davranışın birebir özeti
olarak okunmamalıdır.

## 1. Temel prensip

Bir sesli sistemin kendi hoparlöründen çıkan sesi kullanıcı konuşması sanmaması için
temel ihtiyaç `Acoustic Echo Cancellation (AEC)` veya eşdeğer bir echo bastırma
katmanıdır. Kritik nokta, hoparlöre giden referans ses ile mikrofon yakalamasının
senkron tutulması ve konuşma kararlarının mümkün olduğunca temizlenmiş sinyalde
verilmesidir.

## 2. Olası katmanlar

### Katman 1 - Ses I/O

- Mikrofon ve hoparlör akışı
- Frame boyutu, latency ve buffer yönetimi
- Referans playback sinyalinin erişilebilir olması

### Katman 2 - Echo bastırma

- Yerel AEC
- İşletim sistemi veya donanım seviyesinde AEC
- Gerekirse ek noise suppression

### Katman 3 - Speech activity detection

- VAD tabanlı konuşma başlangıcı/bitişi
- Enerji, RMS ve benzeri ek gate'ler
- Grace period ve smoothing katmanları

### Katman 4 - Barge-in / interrupt

- Robot konuşurken kullanıcı konuşmasının güvenilir tespiti
- TTS iptali, playback stop ve queue temizliği
- Yanlış pozitif ile gecikmeli kesme arasındaki dengenin ayarlanması

### Katman 5 - Diyalog pipeline'ı

- `ASR -> LLM -> TTS` zinciri
- veya uçtan uca ses modeli kullanan alternatif mimariler

## 3. Bu repo için kısa eşleme

| İhtiyaç | Bu projedeki karşılığı |
|---|---|
| Ses I/O | `audio_io.py` içindeki full-duplex `sounddevice.Stream` |
| Echo bastırma | `aec-audio-processing` ile referanslı AEC |
| VAD | `sr.py` içindeki `Silero VAD` |
| Interrupt | `utils.py` + `main.py` |
| Diyalog akışı | `ASR -> LLM -> TTS` |

## 4. Neden bu ayrım önemli?

Genel sesli uygulama literatüründe WebRTC, mobil donanım AEC, Realtime API veya
uçtan uca ses modeli gibi farklı tasarımlar anlatılabilir. Ancak bu projede bugün
geçerli olan mimari:

- Realtime API tabanlı tam-duplex bulut ses oturumu değildir
- Semantic VAD kullanan sunucu tarafı bir akış değildir
- mobil işletim sistemi AEC'sine bağımlı değildir

Bu repo üzerinde çalışırken güncel davranış, tuning ve teknik kararlar için ana
referans daima `docs/LOCAL_AUDIO_AEC_ARCHITECTURE.md` olmalıdır.