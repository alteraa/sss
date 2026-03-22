# Echo Gain Adaptasyonu Notu

Bu doküman artık yalnızca tarihsel bağlam içindir. Projenin güncel ses mimarisi
`docs/LOCAL_AUDIO_AEC_ARCHITECTURE.md` içinde tanımlanan yerel AEC-first yapıdır.

## Bu not neden artık ana referans değil?

Önceki yaklaşımda yanlış interrupt sorununu azaltmak için `main.py` içinde
`speaking_echo_gain` benzeri heuristics tabanlı echo telafileri deneniyordu. Bu yöntem:

- hoparlörden gerçekten çıkan örneklerle mikrofon yakalamasını aynı akışta tutmuyordu
- echo baskılamayı asıl ses ön-uç yerine uygulama mantığında çözmeye çalışıyordu
- yüksek hoparlör ve yüksek mikrofon gain senaryolarında kırılgan kalabiliyordu

Güncel mimaride bu sınıf yaklaşım ana çözüm olmaktan çıkarıldı. Bunun yerine:

- mikrofon ve hoparlör aynı `sounddevice.Stream` içinde açılır
- TTS referansı doğrudan playback buffer'ından AEC reverse stream'e verilir
- interrupt kararı ham mikrofonda değil, AEC sonrası temizlenmiş sinyalde alınır

## Eski dal farkının anlamı

`main` ile `high-mic-level` arasındaki `speaking_echo_gain` adaptasyonu farkı, eski
heuristic tabanlı echo telafisinin bir varyasyonuydu. Bugün bu fark:

- mevcut mimarinin ana davranışını açıklamaz
- yeni tuning çalışmaları için birincil referans olarak kullanılmamalıdır

## Bu dosya ne zaman faydalı olabilir?

- Eski branch'lerdeki davranışı anlamak istenirse
- Heuristic tabanlı echo compensation denemelerinin neden terk edildiğini belgelemek için

## Güncel referanslar

- Ana mimari: `docs/LOCAL_AUDIO_AEC_ARCHITECTURE.md`
- Gelecek tuning işleri: `docs/FUTURE_DIRECTIONS.md`

