# GUIDE: Mevcut Yerel Ses Mimarisi Sonrası Araştırma Rehberi

Bu rehber, `docs/LOCAL_AUDIO_AEC_ARCHITECTURE.md` içinde tanımlanan yeni yerel ses
mimarisini baz alır. Yani bu proje artık "AEC nasıl eklenir?" aşamasında değildir;
`audio_io.py` içinde aynı process çalışan full-duplex akış, referans beslemeli AEC ve
temizlenmiş sinyal üstünden interrupt kararı zaten temel mimarinin parçasıdır.

Bu nedenle aşağıdaki başlıklar, eski araştırma planı yerine mevcut sistemi daha iyi
kalibre etmek ve sağlamlaştırmak için tutulur.

## Mevcut hedefler

1. AEC sonrası residual echo seviyesini farklı cihazlarda daha da azaltmak
2. Gerçek kullanıcı konuşmasını düşük gecikmeyle yakalayıp robotu güvenilir biçimde kesmek
3. CPU maliyetini ve callback tarafındaki yükü kontrol altında tutmak

## Bugünkü temel akış

- Mikrofon ve hoparlör aynı `sounddevice.Stream` içinde açılır
- TTS örnekleri `AudioIO` playback buffer'ına yazılır
- Aynı örnekler AEC için reverse/reference stream olarak kullanılır
- Mikrofon chunk'ları 10 ms frame'lere bölünerek `aec-audio-processing` ile işlenir
- `main.py` içindeki state machine ve interrupt mantığı ham mikrofonda değil,
  temizlenmiş sinyalde çalışır
- Konuşma başlangıcı ve interrupt kararları `utils.py` eşikleri ile gate edilir

## Araştırılabilecek Konular

### 1) Donanım ve gecikme kalibrasyonu

- `AUDIO_PROCESSOR_DELAY_MS` ayarının farklı hoparlör/mikrofon düzeneklerinde ölçülmesi
- `blocksize`, queue uzunluğu ve stream latency ayarlarının karşılaştırılması
- TTS başlangıcı, playback callback'i ve interrupt reaksiyonu arasındaki toplam gecikmenin ölçülmesi

### 2) AEC sonrası residual analizi

- AEC çıkışında kalan residual echo için RMS dağılımı çıkarılması
- Yüksek hoparlör seviyesi, yüksek mikrofon gain ve reverberant ortam varyasyonlarının ayrı test edilmesi
- Gerekirse ikinci aşama gürültü bastırma katmanı (`pyrnnoise` gibi) eklenmesinin değerlendirilmesi

### 3) Speech-start gating iyileştirmeleri

- `is_speech_start()` içindeki dinamik baseline davranışının farklı ortam gürültülerinde karşılaştırılması
- `MAX_START_CREST_FACTOR` ile transient filtrelemenin konuşma başlangıcını geciktirip geciktirmediğinin ölçülmesi
- Gerekirse konuşma-benzerlik için hafif ek özellikler denenmesi

### 4) Interrupt karar mantığı

- `InterruptDetector` için grace period, RMS multiplier ve hold parametrelerinin tuning'i
- `POST_TTS_IGNORE_CHUNKS` penceresinin residual echo ile gerçek kullanıcı başlangıcı arasındaki trade-off'a etkisi
- Yanlış pozitif ve gecikmeli kesme olaylarının ayrı etiketlenmesi

### 5) Dayanıklılık ve performans

- `sounddevice` callback yükünün izlenmesi
- Tekrarlayan `output underflow` oluşursa callback içindeki DSP yükünün hafifletilmesi
- Gerekirse AEC işinin callback dışına taşınacağı alternatif mimarinin prototiplenmesi

## Pratik çalışma sırası

### Aşama 0: Ölçümleme

1. Farklı hoparlör ve mikrofon seviyeleri için kısa bir test matrisi oluştur
2. Yanlış interrupt ve gecikmeli interrupt olaylarını ayrı logla
3. `rms`, `vad`, baseline ve hold sayaçlarını karşılaştır

### Aşama 1: Tuning

1. `AUDIO_PROCESSOR_DELAY_MS` için küçük bir sweep yap
2. `START_RMS_MULTIPLIER`, `MIN_START_RMS` ve `MAX_START_CREST_FACTOR` değerlerini ortam bazlı karşılaştır
3. `INTERRUPT_RMS_MULTIPLIER`, `INTERRUPT_HOLD` ve `INTERRUPT_GRACE_PERIOD` ayarlarını yeniden kalibre et

### Aşama 2: Sağlamlaştırma

1. Residual echo belirginse isteğe bağlı ek NS katmanını dene
2. Çok gürültülü ortamlarda ek speech classifier ihtiyacını değerlendir
3. Callback yükü artarsa processing thread ayrımı için prototip çıkar

## Başarı ölçütleri

- Robot konuşurken kendi TTS'inden kaynaklı yanlış interrupt nadir hale geliyor mu?
- Gerçek kullanıcı konuşması başladığında robot kabul edilebilir gecikmeyle kesiliyor mu?
- Uzun süreli çalışmada queue, stream ve callback davranışı stabil kalıyor mu?

## Not

Eski dökümanlardaki delay+gain subtraction, NLMS veya "AEC entegrasyonu planı" gibi
başlıklar artık bu proje için ilk adım önerisi değildir. Bunlar ancak mevcut
`LOCAL_AUDIO_AEC_ARCHITECTURE.md` mimarisi yetersiz kalırsa ileri optimizasyon veya
alternatif araştırma konusu olarak düşünülmelidir.

