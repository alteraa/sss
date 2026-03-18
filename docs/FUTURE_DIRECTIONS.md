# Future Directions

Bu doküman, `speech-to-speech` projesinde robotun hoparlörden kendi sesini mikrofondan duyup yanlış şekilde konuşmayı kesmesi (echo/feedback interrupt) sorununu çözmek ve gerçek-zamanlı (low-latency, düşük CPU) çalışmayı korumak için geliştirilebilecek yönleri toplar.

## Kısa Özet (Geçmişte Uygulananlar)

### Whisper geçişi
- Yerel Whisper modeli (`faster_whisper`) kaldırıldı.
- Transkripsiyon OpenAI Whisper API (`model="whisper-1"`, `language="tr"`) ile yapılıyor (`sr.py`).

### Silero VAD taşınması
- Silero VAD modeli Torch Hub üzerinden indiriliyor (`torch.hub.load(..., source="github")`).
- VAD giriş örnek boyutu uyumsuzluğu giderildi: 1536 örneklik chunk'lar 512 örneklik pencerelere bölünüp (son parça pad edilerek) confidence değerleri birleştiriliyor (`sr.py: vad_confidence`).

### ffplay sistem bağımlılığı
- `ffplay` bulunamadığı için FFmpeg/`ffplay` kurulumunun gerekli olduğu belirlendi (`tts.py`).

### Interrupt (robot konuşurken kesme) mimarisi
- `main.py` state machine: `IDLE -> LISTENING -> PROCESSING -> SPEAKING`.
- `SPEAKING` sırasında grace süresi sonrası mikrofon chunk'ları `InterruptDetector.update()` ile değerlendirilip `tts_player.stop()` çağrılıyor.

### Echo yanlış interrupt azaltma denemeleri
- `main.py`: `INTERRUPT_GRACE_PERIOD` boyunca interrupt detection kapatıldı; grace bitince baseline `freeze_baseline()` ile donduruldu.
- `utils.py`: `InterruptDetector.reset()` içinde rolling pencere temizlenerek baseline'in yanlış şekilde geçmiş düşük seviyelerle etkilenmesi önlendi.
- Eşik ayarları daha muhafazakar hale getirildi:
  - `INTERRUPT_RMS_MULTIPLIER`: 1.5 -> 2.5
  - `INTERRUPT_HOLD`: 2 -> 3
  - `INTERRUPT_GRACE_PERIOD`: 0.8 -> 1.0

## Problem Tanımı (Teknik Kök Neden)

- Hoparlör ses seviyesi yükseldikçe, TTS'den çıkan ses mikrofon sinyaline echo olarak yansır.
- Mevcut interrupt detektörü iki koşulu birlikte arıyor:
  - RMS enerji: `current_rms > frozen_baseline * INTERRUPT_RMS_MULTIPLIER`
  - VAD: `current_vad > INTERRUPT_VAD_THRESHOLD`
- Silero VAD hoparlör kaynaklı örüntülerde doygunluk/yanlış pozitif üretebildiğinde (`vad ~ 1.0`), RMS filtresi de echo nedeniyle sık sık tetiklenip `interrupt: human_speaking_while_robot` ortaya çıkıyor.

## Gerçek-zamanlı (Low-Latency) Uygun Yöntemler - Öncelik Sırasıyla

Aşağıdaki yöntemler gecikme ve hesaplama maliyeti açısından değerlendirilir. En ideali genellikle “echo’yu residual’e indirmek”tir; böylece VAD/RMS yanlış tetiklenmeyi azalır.

### 1) Referanslı Echo Subtraction (Delay + Gain) [En ideal/En düşük gecikme]

**Fikir:** Robotun hoparlörden çaldığı TTS sesi elinizde referans olarak var. Mikrofon sinyalinden uygun gecikmede ve ölçekle referansı çıkararak echo’yu bastırın.

- Gecikme tahmini: cross-correlation ile coarse delay.
- Ölçekleme: kısa zamanlı gain tahmini (ör. envelope tabanlı) veya sabit bir başlangıç kazancı.
- Çıkarma: `residual = mic - alpha * reference_delayed`
- Residual üzerinde mevcut `InterruptDetector` (veya daha basit bir RMS gate) çalıştırılır.

**Artılar**
- Hesaplama çok hafif (chunk başına delay slicing + çıkarma + küçük gate).
- VAD doygunluğuna rağmen RMS daha stabil hale gelebilir.

### 2) Kısa Taplı Adaptive Filter (NLMS/LMS tabanlı) [Hızlı ve sağlam]

**Fikir:** Delay+gain yetersizse, referans sinyalinden kısa FIR ile echo’yu daha iyi modelleyip çıkarmak.

- NLMS/LMS: 16–64 tap gibi kısa filtrelerle gerçek-zamanlı öğrenme.
- Güncelleme: her chunk başına veya her N frame.
- Reference olarak TTS oynatma sinyalini (mümkünse PCM) kullanmak gerekir.

**Artılar**
- Delay/jitter ve oda koşullarına daha dayanıklı.

### 3) WebRTC Audio Processing APM (AEC3/NS/Gain Control) [En güçlü ama entegrasyon maliyeti]

**Fikir:** WebRTC’nin C/C++ tabanlı AEC/NS bileşenlerini entegre etmek.

- AEC: echo cancellation (robot sesini mikrofon girişinden bastırır)
- NS: gürültü bastırma ile VAD/RMS stabilizasyonu
- AGC: seviye kontrol

**Artılar**
- Kalite genelde en iyisi.
- CPU düşük olabilir (native implementasyon).

**Eksiler**
- Python entegrasyonu/kurulum eforu olabilir.

### 4) Echo-Likelihood / Correlation gating (VAD’yi tamamlayıcı) [Düşük maliyet]

**Fikir:** Mikrofon chunk’ının referans (TTS) ile gecikme-alanında benzerliğini ölçün.

- Örnek: normalized cross-correlation veya enerji benzerlik skoru.
- Skor yüksekse “robot yankısı” olma ihtimali yüksektir => interrupt koşuluna ek bir kısıt koyun.

**Örnek kural fikri**
- Interrupt için:
  - RMS > threshold
  - VAD > threshold
  - VE `echo_likelihood < limit`

### 5) VAD/RMS kararını daha yankı-dirençli hale getirmek (post-processing)

Mevcut sistemde `vad_confidence` max pooling ile birleşiyor. Echo durumunda bu max değer doygunluğa gidiyorsa, daha yankı-dirençli birleştirme denenebilir:

- Max yerine average/trimmed-mean ile birleştirme
- VAD confidence zaman üzerinde medyan filtresi / EMA ile smoothing
- “Tek spike” bastırma: bir pencere içindeki varyans/enerji modülasyonu threshold’ları

Bu yöntemler ucuzdur; AEC ile birlikte en iyi sonucu verir.

### 6) Bant-kısıtlama / HPF (düşük maliyetli yardımcı)

- Echo bazı bantlarda daha baskın olabilir.
- Çok agresif olmadan:
  - Hafif HPF (örn. 70–120 Hz) ile düşük frekans enerji azalımı
  - Band-limited RMS ile threshold daha stabil hale getirilebilir

### 7) Speaker verification / Embedding (son karar mekanizması)

**Fikir:** Echo residual de VAD/RMS’i etkiliyorsa, “robot sesine benzer mi?” sorusunu embedding ile yanıtlayın.

- Robot/TTS referansından embedding çıkarılır.
- Mikrofon pencere embedding ile karşılaştırılır.
- Benzerlik yüksekse interrupt engellenebilir.

**Not:** Gerçek-zamanlı maliyet daha yüksek olabilir; yalnızca interrupt adayı oluştuğunda çalıştırmak daha doğru olur.

## Ölçüm ve Tuning Prosedürü (Önerilen)

### A) Gözlemlerle tuning
- `DEBUG rms=... baseline=... thr=... vad=...` logları kullanılarak:
  - interrupt’un RMS mi yoksa VAD mi ile tetiklendiği netleştirilmeli.

### B) Baseline hesap güvenilirliği
- Baseline rolling penceresinin reset esnasında temizlenmesi gibi önlemlerle baseline sızıntısı engellenmeli.

## Sonraki Adım Önerisi (En düşük eforla en yüksek etki)

1) TTS referansını elde edebiliyorsanız (PCM/WAV):
   - Önce delay+gain subtraction prototipi.
2) Ardından hata kalırsa:
   - NLMS ile kısa taplı adaptive filter.
3) En son olarak:
   - WebRTC APM ile AEC entegrasyonu.

