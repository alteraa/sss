# Future Directions

Bu doküman, `docs/LOCAL_AUDIO_AEC_ARCHITECTURE.md` içinde tanımlanan yeni yerel ses
mimarisi sonrasında kalan teknik iyileştirme alanlarını toplar. Odak artık "AEC nasıl
eklenir?" değil, mevcut AEC-first yapıyı farklı cihaz ve ortam koşullarında daha
güvenilir hale getirmektir.

## Güncel durum özeti

- Ses I/O aynı process içinde `sounddevice.Stream` ile yürütülür
- TTS referansı doğrudan playback buffer'ından AEC reverse stream'e verilir
- Mikrofon tarafında `aec-audio-processing` ile temizlenmiş sinyal elde edilir
- `Silero VAD` ve RMS tabanlı gate'ler temizlenmiş sinyal üstünde çalışır
- `ffplay` tabanlı ayrı playback süreci artık aktif mimarinin parçası değildir

## Yakın vadeli teknik yönler

### 1) Cihaz bazlı AEC delay tuning

- `AUDIO_PROCESSOR_DELAY_MS` için farklı donanımlarda kısa sweep'ler yapılması
- Hoparlör-mikrofon yerleşimine göre en stabil aralığın dokümante edilmesi
- Gerekirse cihaz profili bazlı varsayılanlar tanımlanması

### 2) Residual echo azaltma

- TTS sonrası kısa residual patlamaların loglanması
- `POST_TTS_IGNORE_CHUNKS` ile gerçek kullanıcı başlangıcı arasındaki dengenin ölçülmesi
- Gerekirse AEC sonrası isteğe bağlı ikinci aşama noise suppression katmanının eklenmesi

### 3) Speech-start ve interrupt tuning

- `START_RMS_MULTIPLIER`, `MIN_START_RMS` ve `MAX_START_CREST_FACTOR` için ortam bazlı kalibrasyon
- `INTERRUPT_RMS_MULTIPLIER`, `INTERRUPT_VAD_THRESHOLD`, `INTERRUPT_HOLD` ve `INTERRUPT_GRACE_PERIOD` değerlerinin yeniden karşılaştırılması
- Yanlış pozitif ile geç kesme vakalarının ayrı ölçülmesi

### 4) Performans ve callback yükü

- Tekrarlayan `output underflow` görülürse callback içindeki iş yükünün profillenmesi
- AEC ve ek DSP maliyeti büyürse processing işinin ayrı thread'e taşınmasının değerlendirilmesi
- Uzun süreli çalışmada queue büyümesi ve gecikme birikiminin izlenmesi

## Orta vadeli seçenekler

### 1) İsteğe bağlı ek noise suppression

`pyrnnoise` şu an aktif akışın zorunlu parçası değildir. Residual echo veya ortam
gürültüsü belirli cihazlarda sorun çıkarıyorsa, AEC sonrası opsiyonel katman olarak
yeniden değerlendirilmesi mantıklıdır.

### 2) Daha güçlü speech/non-speech ayrımı

`Silero VAD` çoğu durumda yeterli olsa da çok gürültülü ortamlarda ek bir speech
classifier veya daha seçici post-processing katmanı düşünülebilir.

### 3) Cihaz/ortam profilleri

Farklı robot gövdeleri, hoparlör güçleri veya mikrofon yerleşimleri için:

- gain seviyesi
- delay ayarı
- interrupt eşikleri

ayrı preset'ler halinde tutulabilir.

## Artık birincil yol haritası olmayan başlıklar

Aşağıdaki konular bu repo için artık "ilk uygulanacak çözüm" değildir:

- `ffplay` tabanlı playback ile echo yönetimi
- saf delay+gain heuristic yaklaşımını ana çözüm yapmak
- AEC'i daha sonra entegre edilecek ayrı bir gelecek işi olarak görmek

Bu başlıklar ancak mevcut mimari yetersiz kalırsa alternatif deney veya ileri
optimizasyon olarak değerlendirilebilir.

## Önerilen çalışma sırası

1. Gerçek cihaz üstünde hoparlör/mikrofon seviye matrisi ile ölçüm al
2. `AUDIO_PROCESSOR_DELAY_MS` ve interrupt eşiklerini kalibre et
3. Residual echo devam ediyorsa opsiyonel ikinci aşama NS dene
4. Gerekirse daha ağır classifier veya thread ayrımı gibi yapısal adımlara geç

