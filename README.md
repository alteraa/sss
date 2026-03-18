# Interruptible SR - Sistem Dokümantasyonu ve Parametre Rehberi

## Sistem Nasıl Çalışır?

Bu sistem bir insanla sesli diyalog kurabilen bir robot yazılımıdır. Temel akış şu şekilde
işler:

1. Mikrofon sürekli dinlenir
2. İnsan konuşmaya başladığında ses kaydedilir
3. İnsan sustu anda kayıt durdurulur, ses metne çevrilir (SR/Whisper)
4. Metin bir yapay zeka modeline gönderilir (LLM/OpenAI)
5. Gelen cevap seslendirilir (TTS/OpenAI)
6. Robot konuşurken insan tekrar konuşursa robot sözünü keser ve dinlemeye geri döner

### Durum Makinesi (State Machine)

Ana döngü 4 durumdan oluşur ve **asla bloklanmaz** — mikrofon her durumda okunmaya
devam eder:

```
IDLE ──(insan konuşmaya başladı)──> LISTENING
LISTENING ──(insan sustu)──> PROCESSING
PROCESSING ──(cevap hazır)──> SPEAKING
PROCESSING ──(boş/geçersiz sonuç)──> IDLE
SPEAKING ──(TTS bitti veya interrupt)──> IDLE
```

**IDLE:** Sessiz ortam. Mikrofon verileri pre-speech buffer'a (`before_chunks`)
kaydedilir, ortam gürültü seviyesi (RMS baseline) güncellenir, VAD ile konuşma
başlangıcı aranır. Debounce mekanizması sayesinde anlık gürültüler göz ardı edilir.

**LISTENING:** İnsan konuşuyor. Ses verileri biriktirilir. Konuşma durduğunda belirli
bir sessizlik süresi beklenir ve kayıt tamamlanır.

**PROCESSING:** Arka plan thread'inde Whisper ile ses metne çevriliyor ve LLM'e
gönderiliyor. Bu sırada ana döngü mikrofon okumaya devam eder (veriyi atar), böylece
PyAudio buffer'ı taşmaz.

**SPEAKING:** TTS ses dosyası indirilip çalınıyor. Robot konuşurken mikrofon dinlenmeye
devam eder ve interrupt algılama aktiftir — insan konuşursa robot sözünü keser.

### Thread Yapısı

| Thread        | Görevi                                           |
| ------------- | ------------------------------------------------ |
| Main Thread   | Mikrofon okuma, state machine, interrupt algılama |
| Worker Thread | Whisper transcription + LLM API çağrısı          |
| TTS Thread    | OpenAI TTS indirme + ffplay ile ses çalma         |

### Interrupt Algılama Nasıl Çalışır?

Robot konuşmaya başlamadan hemen önce ortamın sessiz haldeki gürültü seviyesi (RMS
değeri) "dondurulur" (`freeze_baseline`). Robot konuşurken mikrofona gelen toplam ses
enerjisi bu dondurulmuş değerin belirli bir katını aşarsa **VE** aynı anda Silero VAD
modeli de ses algılarsa, bu durum "insan konuşuyor" olarak yorumlanır. Ardışık belirli
sayıda chunk bu koşulu sağlarsa interrupt tetiklenir.

---

## Parametre Referansı

### Ses Yakalama Parametreleri

Dosya: `utils.py`, `sr.py`

| Parametre     | Değer | Açıklama                                        |
| ------------- | ----- | ------------------------------------------------ |
| `SAMPLE_RATE` | 16000 | Örnekleme hızı (Hz). Silero VAD ve Whisper 16kHz gerektirir |
| `NUM_SAMPLES` | 1536  | Her chunk'taki örnek sayısı                      |
| `CHANNELS`    | 1     | Mono kanal                                       |
| `FORMAT`      | paInt16 | 16-bit integer ses formatı                     |

**Chunk süresi:** `NUM_SAMPLES / SAMPLE_RATE = 1536 / 16000 = 0.096 saniye ≈ 96ms`

Her ~96ms'de bir mikrofon okunur, VAD çalıştırılır ve durum makinesi güncellenir. Bu
değer sistemin tepki hızını belirler.

#### `NUM_SAMPLES` (Chunk Boyutu)

- **Azaltırsan (ör. 512):** Daha sık okuma → daha hızlı tepki, ama VAD doğruluğu
  düşer (çok kısa ses parçaları üzerinde VAD güvenilir çalışmaz). CPU kullanımı artar.
- **Artırırsan (ör. 4096):** VAD daha güvenilir ama tepki süresi artar (~256ms).
  Konuşma başlangıcı ve sonu daha geç algılanır.
- **Önerilen aralık:** 512–2048. Silero VAD 512 örneğe kadar destekler ama 1536
  iyi bir denge noktasıdır.

---

### Konuşma Algılama Parametreleri

Dosya: `utils.py`

#### `SPEAK_THRESHOLD` = 0.5

Silero VAD modelinin döndürdüğü güven değeri (0.0–1.0) bu eşiği aştığında "konuşma
var" kabul edilir. IDLE ve LISTENING durumlarında kullanılır.

- **Azaltırsan (ör. 0.3):** Daha hassas. Hafif sesler, uzak konuşmalar, TV sesi gibi
  ortam gürültüleri de konuşma olarak algılanır. Daha fazla yanlış pozitif (false
  positive).
- **Artırırsan (ör. 0.7):** Daha az duyarlı. Sadece net, yakın ve yüksek sesli
  konuşma algılanır. Fısıltı veya uzak konuşma kaçırılabilir.
- **Ortam gürültülü ise:** 0.55–0.65 arası dene.
- **Sessiz ortam ise:** 0.4–0.5 yeterli olur.

#### `DEBOUNCE_CHUNKS` = second_to_chunks(0.3) ≈ 3 chunk

IDLE durumundayken, ardışık kaç chunk boyunca VAD eşiğini geçmesi gerektiğini belirler.
Kapı çarpması, bardak sesi gibi çok kısa gürültülerin konuşma olarak algılanmasını
engeller.

- **Azaltırsan (ör. 1):** Daha hızlı tepki ama anlık gürültüler de kayıt başlatır.
- **Artırırsan (ör. 5, ~0.5sn):** Gürültüye karşı çok dayanıklı ama konuşma
  başlangıcında fark edilir gecikme oluşur. Kullanıcı robotun duymadığını
  düşünebilir.
- **Önerilen:** 2–4 chunk (0.2–0.4 saniye).

#### `BEFORE_CHUNKS` = second_to_chunks(0.8) ≈ 8 chunk

IDLE durumunda kaydedilen pre-speech buffer boyutu. Konuşma algılandığında, bu buffer
sayesinde konuşmanın başlangıcı (debounce öncesi sessiz kısım dahil) da kayda dahil
edilir.

- **Azaltırsan (ör. 3):** Konuşmanın ilk hecesi kesilmiş olabilir. Whisper eksik
  girdiyle çalışır.
- **Artırırsan (ör. 15, ~1.5sn):** Daha fazla ortam gürültüsü de kaydın başına
  eklenir. Whisper genelde bunu tolere eder ama gereksiz veri işlenir.
- **Önerilen:** 0.5–1.0 saniye arası.

#### `AFTER_CHUNKS` = second_to_chunks(0.5) ≈ 5 chunk

LISTENING durumundayken, konuşma durduktan sonra kaç chunk sessizlik bekleneceğini
belirler. Bu süre dolunca kayıt tamamlanır ve işleme gönderilir.

- **Azaltırsan (ör. 2, ~0.2sn):** Konuşma içindeki doğal duraklamalar bile "konuşma
  bitti" olarak algılanır. Cümle ortasında kesilme riski.
- **Artırırsan (ör. 10, ~1.0sn):** Cümle arası duraklamalar tolere edilir ama
  kullanıcının cümlesinin bittiğini anlamak daha uzun sürer. Toplam yanıt süresi
  artar.
- **Önerilen:** 0.4–0.8 saniye. Türkçe konuşmada cümle içi doğal duraklama
  genellikle 0.3sn'nin altındadır.

---

### Interrupt Algılama Parametreleri

Dosya: `utils.py`

Bu parametreler yalnızca **SPEAKING** durumunda, robot konuşurken insanın sözünü
kesmesini algılamak için kullanılır. İki koşul aynı anda sağlanmalıdır: RMS eşiği
**VE** VAD eşiği.

#### `INTERRUPT_RMS_MULTIPLIER` = 2.5

Dondurulmuş baseline RMS değerinin kaç katı aşılırsa interrupt için RMS koşulunun
sağlandığı kabul edilir.

Örnek: Baseline RMS = 100 ise, threshold = 100 × 2.5 = 250. Mikrofondaki anlık RMS
250'yi geçmelidir.

- **Azaltırsan (ör. 1.5):** Robot kendi sesinden dolayı kendi sözünü keser (echo
  problemi). Hoparlör sesi mikrofona döndüğünde bile interrupt tetiklenir.
- **Artırırsan (ör. 4.0):** Sadece çok yüksek sesle bağıranlar interrupt
  tetikleyebilir. Normal konuşma hacmiyle interrupt çalışmaz.
- **Echo problemi varsa:** 2.5–3.5 arası dene. Hoparlör ile mikrofon arasındaki
  mesafe ve hacim etkiler.
- **Echo yoksa (kulaklık vb.):** 1.5–2.0 yeterli.

#### `INTERRUPT_VAD_THRESHOLD` = 0.6

Robot konuşurken, interrupt tetiklemek için Silero VAD güven değerinin geçmesi gereken
eşik. `SPEAK_THRESHOLD`'dan bağımsız, sadece interrupt için kullanılır.

- **Azaltırsan (ör. 0.4):** Robotun kendi TTS sesi VAD tarafından insan sesi olarak
  algılanıp interrupt tetiklenebilir.
- **Artırırsan (ör. 0.8):** Sadece çok net, yakın mesafeden konuşma interrupt
  tetikler. Uzak konuşma veya hafif sesler göz ardı edilir.
- **Önerilen:** 0.5–0.7 arası. Echo'nun yoğunluğuna göre ayarla.

#### `INTERRUPT_HOLD` = 3

Interrupt tetiklenmesi için ardışık kaç chunk'ta hem RMS hem VAD koşulunun aynı anda
sağlanması gerektiğini belirler. Tek bir chunk bile koşulu sağlamazsa sayaç sıfırlanır.

- **Azaltırsan (ör. 1):** Anlık gürültü spike'ları bile interrupt tetikler. Çok
  hassas ve dengesiz.
- **Artırırsan (ör. 5, ~0.5sn):** İnsan en az ~0.5 saniye net konuşmalı ki interrupt
  tetiklensin. Gecikmeli tepki.
- **Önerilen:** 2–4 chunk. Çoğu durumda 3 iyi çalışır.

#### `INTERRUPT_GRACE_PERIOD` = 1.0 (saniye)

TTS ses çalmaya başladıktan sonra ilk N saniye boyunca interrupt algılama tamamen
devre dışıdır. Bu, TTS sesinin hoparlörden çıkıp mikrofona ulaşması ve ilk spike'ın
yanlış interrupt tetiklemesini önler.

- **Azaltırsan (ör. 0.3):** TTS'in ilk anındaki ses spike'ı interrupt tetikleyebilir.
  Robot ilk hecesinden sonra kendi sözünü keser.
- **Artırırsan (ör. 2.0):** İnsan ilk 2 saniye boyunca robotu kesemez. Doğal diyalog
  akışını bozar.
- **Önerilen:** 0.8–1.5 saniye. Hoparlör hacmine ve mikrofon hassasiyetine göre
  ayarla.

#### `BASELINE_WINDOW` = 40 chunk (~3.8 saniye)

IDLE durumunda rolling ortalama hesaplamak için kullanılan pencere boyutu. Bu pencere
üzerinden hesaplanan ortalama RMS, `freeze_baseline` çağrıldığında dondurulur.

- **Azaltırsan (ör. 10, ~1sn):** Baseline daha hızlı güncellenir ama anlık gürültü
  değişimlerine duyarlı olur. Kapı açılma sesi gibi olaylar baseline'ı bozar.
- **Artırırsan (ör. 100, ~10sn):** Daha kararlı baseline ama ortam gürültüsü
  değiştiğinde (ör. klima açıldı) uyum süresi artar.
- **Önerilen:** 30–60 chunk (3–6 saniye).

---

### Whisper (Speech Recognition) Parametreleri

Dosya: `sr.py`

Bu projede Whisper artık **yerel model** yerine **OpenAI Whisper API** ile
çalışır. VAD (Silero) hâlâ yerel olarak çalışır.

#### `model` = "whisper-1"

OpenAI Whisper modeli. Sunucu tarafında transkripsiyon yapılır.

#### `language` = "tr"

OpenAI Whisper'a hangi dilde transkripsiyon yapacağını belirtir. Dil belirtmek
otomatik algılamayı atlayıp doğruluk/genel süreyi iyileştirebilir.

#### `OPENAI_API_KEY`

API anahtarı `llm.py` üzerinden okunur (`OPENAI_API_KEY` ortam değişkeni). Anahtar
set edilmezse `transcribe()` boş metin döner.

---

### LLM Parametreleri

Dosya: `llm.py`

#### `OPENAI_MODEL` = "gpt-4.1-nano"

Kullanılan LLM modeli. Daha büyük modeller daha iyi yanıtlar verir ama daha yavaş
ve pahalıdır.

| Model          | Hız       | Kalite    | Maliyet |
| -------------- | --------- | --------- | ------- |
| gpt-4.1-nano   | En hızlı  | Temel     | En ucuz |
| gpt-4.1-mini   | Hızlı     | İyi       | Ucuz    |
| gpt-4.1        | Orta      | En iyi    | Pahalı  |

#### `max_tokens` = 60

LLM yanıtının maksimum token sayısı. Yaklaşık olarak Türkçede 1 token ≈ 3-4 karakter.
60 token ≈ 1-2 kısa cümle.

- **Azaltırsan (ör. 30):** Daha kısa ve hızlı yanıtlar ama cümleler yarıda
  kesilebilir.
- **Artırırsan (ör. 200):** Daha detaylı yanıtlar ama TTS süresi uzar, kullanıcı uzun
  süre dinlemek zorunda kalır. Robotik diyalogda kısa yanıtlar tercih edilir.
- **Önerilen:** 40–100 arası. Diyalog tarzına göre ayarla.

#### Mesaj Geçmişi Limiti = 10 mesaj

`messages` listesi 10'u aştığında baştan 2 mesaj (1 kullanıcı + 1 asistan) silinir.
Bu, context window'un dolmasını engeller ama eski bağlamın kaybına neden olur.

---

### TTS Parametreleri

Dosya: `tts.py`

#### `OPENAI_TTS_VOICE` = "nova"

OpenAI TTS ses karakteri. Seçenekler: `alloy`, `echo`, `fable`, `onyx`, `nova`,
`shimmer`.

- `nova`: Sıcak, doğal kadın sesi
- `onyx`: Derin, otoriter erkek sesi
- `alloy`: Nötr, dengeli ses
- Her ses farklı RMS profili üretir — ses değiştirirken interrupt parametrelerini
  yeniden kalibre etmen gerekebilir.

#### TTS Model = "tts-1"

`tts-1` düşük gecikmeli model, `tts-1-hd` daha kaliteli ama daha yavaş.
Robotik uygulama için `tts-1` önerilir.

---

### Drain Buffer Parametresi

Dosya: `main.py`

#### `drain_mic_buffer` count = 5

SPEAKING → IDLE geçişlerinde PyAudio buffer'ındaki eski (stale) ses verilerini
temizlemek için kaç chunk okunup atılacağını belirler.

- **Azaltırsan (ör. 1):** TTS'in son anlarına ait ses verileri hala buffer'da kalır.
  Bu, TTS kapanır kapanmaz robotun kendi sesini yeni bir konuşma olarak algılamasına
  neden olabilir.
- **Artırırsan (ör. 20, ~2sn):** Daha güvenli temizlik ama geçiş sırasında
  kullanıcının yeni konuşması da atılabilir.
- **Önerilen:** 3–8 chunk (0.3–0.8 saniye).

---

## Hızlı Kalibrasyon Senaryoları

### Senaryo: Robot kendi sözünü kesiyor (echo)
1. `INTERRUPT_RMS_MULTIPLIER` artır (2.5 → 3.0)
2. `INTERRUPT_VAD_THRESHOLD` artır (0.6 → 0.7)
3. `INTERRUPT_GRACE_PERIOD` artır (1.0 → 1.5)
4. `INTERRUPT_HOLD` artır (3 → 4)

### Senaryo: Ortam gürültüsü konuşma olarak algılanıyor
1. `SPEAK_THRESHOLD` artır (0.5 → 0.6)
2. `DEBOUNCE_CHUNKS` artır (3 → 5)

### Senaryo: Kullanıcı konuşuyor ama robot duymuyor
1. `SPEAK_THRESHOLD` azalt (0.5 → 0.4)
2. `DEBOUNCE_CHUNKS` azalt (3 → 2)

### Senaryo: Cümleler ortasından kesiliyor
1. `AFTER_CHUNKS` artır (5 → 8)

### Senaryo: Cevap vermesi çok uzun sürüyor
1. Daha kısa ses dosyası göndermek için `AFTER_CHUNKS` azalt (5 → 3)
2. `max_tokens` azalt (60 → 40)
3. Daha hızlı LLM modeli kullan

### Senaryo: İnsan robotu kesemiyor
1. `INTERRUPT_RMS_MULTIPLIER` azalt (2.5 → 2.0)
2. `INTERRUPT_VAD_THRESHOLD` azalt (0.6 → 0.5)
3. `INTERRUPT_HOLD` azalt (3 → 2)
4. `INTERRUPT_GRACE_PERIOD` azalt (1.0 → 0.7)
