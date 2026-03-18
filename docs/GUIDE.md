# GUIDE: Ses/Sinyal İşleme Araştırma Yol Haritası

Bu rehber; `speech-to-speech` projesiyle uyumlu şekilde, gerçek-zamanlı (low-latency) konuşma kesme (interrupt) davranışını iyileştirmek isteyen birinin araştırabileceği ses işleme ve sinyal işleme konularını toplar. Ayrıca pratik bir yol haritası içerir.

## Projeden yola çıkarak hedefler

1. **Robot hoparlörünün yankısı (echo/feedback) mikrofona yansıyınca yanlış interrupt’u azaltmak**
2. **İnsan konuşmasını gerçek zamanlı yakalayıp robotu gerektiğinde kesmek**
3. **Mümkün olan en az gecikme ve CPU maliyeti ile çalışmak**

Bu nedenle rehber, özellikle şu konulara öncelik verir:
- Echo giderme (AEC/echo subtraction)
- VAD / speech activity kararları
- Düşük maliyetli özellikler ve gating
- Ölçümleme, hata analizi ve tuning

## Araştırılabilecek Konular (Rehber)

### 1) Gerçek-zamanlı mimari ve gecikme analizi
- Buffering: `chunk` boyu, `frames_per_buffer`, kuyruk uzunlukları
- Latency bütçeleme: mikrofon giriş -> özellik -> karar -> TTS stop
- Jitter toleransı: delay/timing hatalarının interrupt kararına etkisi
- Kesme güvenliği: grace period mantığı ve “yanlış pozitif kesme” vs “gecikmeli kesme” trade-off

### 2) Echo/feedback probleminin çözümü (En kritik alan)

**2.1. Reference tabanlı echo subtraction**
- Delay tahmini (cross-correlation / GCC-PHAT)
- Gain/ölçek tahmini (envelope tabanlı, regresyon, adaptif)
- Residual üzerinde gate/VAD/RMS karar

**2.2. Adaptive filtering (NLMS/LMS)**
- Kısa FIR ile echo modelleme (16–64 tap hedefle)
- Step-size (mu) tuning: yakınsama/stabilite
- Sürekli öğrenme mi, aralıklı öğrenme mi? (TTS sırasında öğrenme + insan konuşmasında sabitleme)

**2.3. AEC sistemleri (WebRTC APM / benzeri)**
- C/C++ tabanlı AEC3/NS kombinasyonları
- Python entegrasyonu (en az “wrapper” eforuyla nasıl bağlanır?)
- Veri format uyumu (PCM, sample rate, mono/stereo dönüşümleri)

**2.4. Fiziksel katman etkileri**
- Hoparlör-mikrofon mesafesi ve yönlülük
- Oda akustiği (reverberation) etkisi
- Mikrofon gain/AGC, noise suppression ayarları

### 3) VAD ve Speech Activity Detection (Echo’ya dayanıklılık)
- Frame-level VAD vs chunk-level VAD
- VAD smoothing: EMA/median filtre ile tek-spike bastırma
- Max pooling yerine daha yankı-dirençli birleştirme (trimmed mean / percentile)
- VAD yerine/yanına **normalleştirilmiş enerji** veya kısa-time spectral “speech-likeness” ekleme

### 4) Interrupt decision (Sinyal tabanlı gating stratejileri)
- RMS gate: baseline (rolling average) nasıl tanımlanmalı?
- Baseline sızıntısı (TTS sırasında yanlış baseline güncellenmesi)
- Ek bir koşul: echo-likelihood / correlation gating
  - Reference ile gecikme-alanında benzerlik ölç (echo benzerliği yüksekse interrupt’u ağırlaştır)
- Hold/sayacın zaman ölçeği: “kaç chunk” gecikmeye dönüşüyor?

### 5) Düşük maliyetli ön-işleme (Ucuz ama etkili)
- Band sınırlama (HPF/LPF) ile yankı baskın bantlarını kısma
- Pre-emphasis / hafif spectral whitening (çok agresif olmadan)
- DC offset ve mikrofon doygunluğu (clip) kontrolü

### 6) Konuşmacı ayırma (Echo residual içinde “robot mu insan mı?”)
- Speaker embedding tabanlı doğrulama (ECAPA-TDNN benzeri)
- İnsan/robot ayrımı için:
  - embedding benzerliği eşiği
  - sadece interrupt adayı oluştuğunda çalıştırma (hesap maliyeti kontrollü)
- Çalışma modu:
  - robot konuşurken “robot embedding ile benzerlik yüksekse interrupt’u zayıflat”

## Yol Haritası (Pratik)

### Aşama 0: Ölçümleme ve Teşhis (1–2 gün)
1. Mevcut `DEBUG` çıktıları ile interrupt tetiklenme nedenini etiketle:
   - `rms` mi `vad` mi?
   - tetik anında baseline nedir?
2. “Yanlış kesme” ve “gecikmeli kesme” için olay zamanlarını logla.
3. Hedef metrikleri belirle:
   - yanlış interrupt oranı
   - insan konuşmasını kaç ms gecikmeyle kesiyor
   - CPU kullanımına dair yaklaşık gözlem

### Aşama 1: Echo’yu karar öncesinde azalt (2–5 gün)
1. TTS referansını nasıl kullanabileceğini araştır:
   - MP3’ten PCM üretmek mi?
   - ya da TTS akışını PCM olarak elde etmek mi?
2. En düşük eforla:
   - delay+gain ile kaba echo subtraction prototipi
3. Residual üzerinde mevcut RMS/VAD gating’i tekrar değerlendir.

### Aşama 2: Adaptive filtering ile sağlamlaştır (3–7 gün)
1. NLMS/LMS ile kısa FIR adaptif filtre dene.
2. Adım boyu (mu) ve tap sayısı için hızlı grid search yap.
3. TTS sırasında adapt et, insan konuşması anında filtreyi sabitlemeye çalış.

### Aşama 3: En yüksek kalite için AEC entegrasyonu (5–15 gün)
1. WebRTC APM AEC3/NS entegrasyon planı çıkar.
2. Gerekirse:
   - wrapper/stream format dönüşümleri
   - performans ölçümü
3. AEC sonrası VAD/RMS thresholds yeniden ayarlanır.

### Aşama 4: Robot vs insan ayrımı (Opsiyonel, daha pahalı ama güçlü) (5–20 gün)
1. Interrupt adayı olduğunda embedding/verification çalıştır.
2. Benzerlik eşiği ile “echo residual” kaynaklı yanlış kesmeleri azalt.
3. Bu aşamayı yalnızca AEC+gating yeterli gelmezse düşün.

## Başarı Ölçütleri (Kontrol listesi)

- Robot konuşurken (özellikle hoparlör yüksekken) yanlış interrupt sayısı belirgin düşüyor mu?
- Gerçek insan konuşması başladığında robot yine de kesilebiliyor mu?
- Aşırı hesap maliyeti yüzünden gecikme artıyor mu?

## Başlangıç Araştırma Konuları (Hızlı liste)
- Delay estimation: cross-correlation, GCC-PHAT
- Echo subtraction / residual speech activity detection
- NLMS/LMS kısa FIR adaptif filtre
- WebRTC APM (AEC3 + NS) entegrasyon stratejisi
- VAD smoothing / max yerine robust pooling
- Echo-likelihood veya reference correlation gating

