## 1. Temel soru: "Sistem kendini nasıl duymuyor?"

Bu sorunun cevabı **Acoustic Echo Cancellation (AEC)**'dir. Sistem TTS sesini hoparlörden çalarken aynı anda mikrofon da bu sesi yakalar. AEC, hoparlörden çıkan sinyali "referans" olarak alıp mikrofon sinyalinden matematiksel olarak çıkarır; böylece mikrofona giren ses sadece kullanıcının gerçek sesi kalır.

---

## 2. Katmanlar

### Katman 1 — Donanım & OS

iOS ve Android, mikrofon ile hoparlörü **ayrı donanım akışları** olarak yönetir. `AUGraph` (iOS) veya `AudioRecord/AudioTrack` (Android), 24 kHz PCM, mono, 20 ms'lik frame'ler üretir. İşletim sistemi, hoparlörden çıkan referans sinyali zaman damgasıyla birlikte AEC modülüne iletir — senkronizasyon bu noktada kurulur.

### Katman 2 — AEC3 (Acoustic Echo Cancellation)

Hoparlörden çıkan ses analiz edilerek, mikrofon tarafından kaydedilen sesten çıkarılır; bu işlem yazılım tarafından gerçek zamanlı yapılır.

Kullanılan teknoloji **WebRTC AEC3** (Chromium'un açık kaynak motoru) veya iOS/Android'in donanım AEC'sidir. AEC'nin temel prensibi, uzak referans sinyali ile tahmini eko arasındaki korelasyona dayanarak adaptif filtre parametrelerini güncellemek ve elde edilen tahmini eko değerini kayıt sinyalinden çıkarmaktır.

Gelişmiş AEC sistemleri bile başlangıç çıkışı ses sızıntısına sebep olabilir; bu yüzden minimum VAD segment uzunluğu ve volume smoothing uygulanır.

### Katman 3 — Voice Activity Detection (VAD): İki mod

OpenAI Realtime API iki farklı VAD modu sunar:

**Server VAD (varsayılan):** Ses aktivasyonu için 0.0-1.0 arası eşik değeri kullanılır; varsayılan 0.5'tir. `prefix_padding_ms` varsayılan değeri 300 ms olup konuşmanın başını kesmemeyi sağlar, `silence_duration_ms` ise varsayılan 500 ms süren sessizliğin konuşmanın bittiğini işaretler.

**Semantic VAD (yeni nesil):** Semantic VAD, kullanıcının söylediği kelimelere göre konuşmasını tamamlayıp tamamlamadığını değerlendiren bir semantic classifier kullanır. "ummm…" gibi sürünen bir ses daha uzun beklemeye yol açarken kesin bir cümle anında tur bitirimini tetikler. Eagerness seviyeleri: `low` için 8 sn, `medium` için 4 sn, `high` için 2 sn maksimum timeout uygulanır.

### Katman 4 — Kesme (Barge-in) Mantığı

Realtime API, VAD aktifken TTS konuşurken kullanıcı sesi tespit edildiğinde devam eden yanıtı iptal edip yeni bir yanıt oluşturur. Sunucu, o ana kadar kaç byte'lık sesin çalındığını bildiğinden, konuşma geçmişini tam o noktada budanmış haliyle saklar.

### Katman 5 — End-to-End Ses Modeli (GPT-4o Realtime)

Geleneksel ses asistanları kaydı durdurur, metne çevirir, LLM'den geçirir, TTS ile tekrar sese dönüştürür. GPT-4o ise doğrudan ham sesi anlayıp ham ses üretir; bu aradaki üç modelin gecikmesini ortadan kaldırır.

Realtime API, WebRTC veya SIP bağlantılarında akış sesi hem girdi hem çıktı olarak destekler; arka planda fonksiyon çağrısı yaparken konuşmayı sürdürebilir ve kesmeleri (opsiyonel VAD ile) yönetebilir.

### Katman 6 — Pipeline İptali & Bağlam Senkronizasyonu

Kesme gerçekleştiğinde iptal edilebilir pipeline'lar gerekir: ASR, LLM ve TTS bileşenlerinin tamamı anında durdurulur; istemci tarafı API'lar aracılığıyla ses buffer'ı flush edilir. Konuşma geçmişine sadece kullanıcının gerçekten duyduğu kısım eklenir; model bir sonraki yanıtı oluştururken tutarsız bir bağlamla başlamaz.

---

## 3. Kullanılan teknoloji yığını

| Katman | Teknoloji |
|---|---|
| Ses işleme | WebRTC AEC3, iOS AUGraph, Android AudioRecord |
| VAD | OpenAI Server VAD, Semantic VAD (GPT-4o tabanlı classifier) |
| Taşıma | WebSocket veya WebRTC (gpt-realtime API) |
| Gürültü azaltma | `near_field` / `far_field` noise reduction (Realtime API) |
| Ses formatı | 24 kHz PCM mono, 20 ms frame'ler |
| Açık kaynak alternatif | Pipecat (Python), LiveKit Agents, Silero VAD |

---

## 4. Neden "yüksek ses" senaryosunda bile çalışıyor?

AEC'nin temel prensibi, bilinen çıkış sesini giriş sinyalinden çıkarmadan önce VAD'ı çalıştırmaktır. Eğer sistem kendi sesiyle kendi VAD'ını tetiklerse sonsuz sahte kesme döngüsü oluşur; bu yüzden AEC, VAD'dan önce mutlaka uygulanmalıdır.

Yüksek hoparlör durumlarındaki güvenilirlik ise şu üç önlemden gelir: AEC'nin adaptif filtresi ses seviyesi değiştiğinde kendini yeniden kalibre eder; minimum VAD segment uzunluğu kısa süreli yansımaları filtreler; Semantic VAD ise salt enerji yerine anlama bakarak karar verir.