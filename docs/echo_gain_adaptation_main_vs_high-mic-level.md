# Echo Gain Adaptasyonu: `main` vs `high-mic-level`

Bu doküman, `main` ile `high-mic-level` dalları arasındaki `main.py` farklarını özetler. Farkın ana odağı, konuşma sırasında `speaking_echo_gain` değerinin **adaptif olarak yeniden tahmin edilmesi** (drift azaltma) davranışıdır.

## Kapsam

- Değişen dosya: `main.py`
- `main` dalı: Konuşma boyunca echo gain drift’ini azaltmak için adaptif güncelleme içerir.
- `high-mic-level` dalı: Bu adaptif güncelleme mantığını içermez (ilgili değişkenler ve hesap bloğu kaldırılmıştır).

## `main.py`’de yapılan değişiklikler

`main` dalında konuşma (SPEAKING) sırasında `speaking_echo_gain` güncellemesini destekleyen şu öğeler bulunuyordu; `high-mic-level` dalında bunlar kaldırılmıştır:

1. Adaptasyon için RMS örnek listeleri
- `speaking_echo_gain_adapt_mic_rms`
- `speaking_echo_gain_adapt_ref_rms`

2. Adaptasyon penceresi sabitleri (örnek sayısı limitleri)
- `ECHO_GAIN_ADAPT_MIN_POINTS`
- `ECHO_GAIN_ADAPT_MAX_POINTS`

3. Adaptif yeniden-tahmin (hesap) bloğu
- Sadece belirli koşullar sağlandığında,
  - `speaking_baseline_ready` = True
  - `best_ref_rms > 1e-6`
  - `energy_gate` ve `corr_gate` True
  - `best_err < ECHO_PRED_ERROR_THRESHOLD`
  koşullarının yanında `mic_rms_now` ile `best_ref_rms` değerleri biriktiriliyor;
  - Biriken pencerede nokta sayısı min/max aralığında olduğunda `speaking_echo_gain` yeniden hesaplanıyordu.

4. TTS geçişlerinde liste resetleri
- TTS başlarken / state değişimlerinde adaptasyon listelerinin temizlenmesine yönelik ek resetler vardı; `high-mic-level` dalında bu resetler de kaldırılmıştır.

## Davranışsal etki

- `main`: Konuşma boyunca “yankı benzeri” chunk’lar üzerinden `speaking_echo_gain` sürekli izlenip yeniden tahmin edildiği için, yüksek mic gain senaryolarında oluşabilen drift daha iyi telafi edilebilir.
- `high-mic-level`: Bu sürekli adaptasyon olmadığı için `speaking_echo_gain` daha statik kalır; bu da drift telafisini azaltabilir ama hesap/samplinga bağlı maliyet ve değişkenlik ihtimalini düşürür.

## Test önerisi (kısa)

- Robot konuşurken yanlış interrupt oranı (özellikle yüksek hoparlör seviyesi / yüksek mic gain durumlarında) karşılaştırılabilir.
- Loglarda `speaking_echo_gain` değişimi ve interrupt tetiklenme anındaki RMS/VAD/gate durumları izlenerek farkın yönü doğrulanabilir.

