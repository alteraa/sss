# Future Directions v2

Bu dokuman, projeyi mevcut `AEC-first` yerel ses mimarisinden daha moduler, embodied
ve agentic bir sisteme evrimsel olarak nasil yaklastirabilecegimizi anlatir.

Odak:

- tek seferde buyuk bir mimari gecis yapmak degil
- mevcut sistemi bozmadan kontrollu adimlarla ilerlemek
- kisa vadeli `controller + SR + LLM + TTS` ayrimini gelecekteki `core-first`
  sisteme basamak yapmak

## Temel ilke

Her fazda su sira korunmalidir:

1. mevcut davranisi bozma
2. servis ve moduller arasindaki sinirlari netlestir
3. event, cancel ve lifecycle mantigini merkezilestir
4. embodied ve multimodal genislemeleri ancak bundan sonra ekle

Kisa form:

- once `audio-first split`
- sonra `controller hardening`
- sonra `core-first orchestration`
- sonra `multimodal embodied expansion`

## Faz 1: Kisa vade

Tahmini sure:

- `2-6 hafta`

Hedef:

- mevcut sistemi bozmadan `controller + SR + LLM + TTS` ayrimini oturtmak

Yapilacaklar:

- `SR`, `LLM` ve `TTS` servis sinirlarini netlestir
- `turn_id`, `segment_id`, `session_id`, timeout ve stale discard kurallarini standartlastir
- `stream` ve `non-stream` akislarini kontrat seviyesinde tanimla
- playback, interrupt, `AEC` ve queue mantigini controller icinde tut
- ilk asamada `REST + SSE` ile ilerle
- su olcumleri ekle:
  - `SR latency`
  - `first token / first segment latency`
  - `first audio latency`
  - `interrupt reaction time`
  - stale result sayisi

Teslimatlar:

- calisan servislesmis konusma mimarisi
- test edilebilir `SR`, `LLM`, `TTS` arayuzleri
- mevcut ses davranisini koruyan controller

Basari olcutu:

- bugunku konusma deneyimi bozulmadan servis ayrimi tamamlanmis olmali

## Faz 2: Kisa-orta vade

Tahmini sure:

- `1-2 ay`

Hedef:

- controller'i gelecekteki embodied ve event-driven sisteme hazirlamak

Yapilacaklar:

- controller icinde daha net alt sorumluluklar tanimla
- ortak bir event semasi olustur
- `turn_id` yanina `interaction_id`, `task_id`, `action_id` gibi kavramlari eklemeye basla
- servis cagrilarini dogrudan is mantigindan ayir
- adapter mantigina gecis icin ilk soyutlamalari kur
- cancellation ve timeout mantigini daha merkezi hale getir

Teslimatlar:

- event-ready controller iskeleti
- servis bagimliliklarindan daha az etkilenmis orchestration yapisi
- ileride ses disi event eklenmesine uygun ilk controller refaktoru

Basari olcutu:

- yeni bir event tipi eklemek tum sistemi bozmadan mumkun olmali

## Faz 3: Orta vade

Tahmini sure:

- `2-4 ay`

Hedef:

- ilk gercek `core-first` mimariyi kurmak

Yapilacaklar:

- ust seviye ayrimi netlestir:
  - `Core`
  - `Adapters`
  - `Plugins`
  - `Services`
- `Embodied Event Controller` kavramini hayata gecir
- event router, priority/arbitration ve interaction state machine ekle
- action lifecycle ve multimodal cancel/preemption mantigini kur
- tool calling icin guvenli execution sinirlari tanimla
- semantic turn detection gibi ilk plugin uzantilarini dene

Teslimatlar:

- sadece konusma sistemi olmayan, event-driven bir runtime
- ses disi event'leri de orkestre edebilen bir cekirdek
- `Core + Adapters + Plugins + Services` ayriminin ilk somut surumu

Basari olcutu:

- sistem farkli event tiplerini ayni orchestration modeliyle yonetebilmeli

## Faz 4: Orta-uzun vade

Tahmini sure:

- `4-8 ay`

Hedef:

- embodied ve multimodal yetenekleri kontrollu sekilde eklemek

Yapilacaklar:

- vision servisini sisteme bagla
- timer ve scheduler eventlerini ekle
- sensor eventlerini ortak event modeline bagla
- embodied action layer kur
- `speech + gesture + gaze` koordinasyonunu baslat
- policy ve safety uzantilarini ekle
- RAG veya memory uzantilarini devreye al
- gerekiyorsa `REST` tabanli haberlesmeden daha dusuk latency'li IPC seceneklerine gec

Teslimatlar:

- multimodal embodied interaction runtime
- ses, algi, tool ve fiziksel aksiyonlari ayni interaction modeli icinde yoneten sistem

Basari olcutu:

- robot konusma, algi ve fiziksel davranisi birlikte koordine edebilmeli

## Faz 5: Uzun vade

Tahmini sure:

- `6-12 ay`

Hedef:

- sistemi uretim seviyesinde saglam, moduler ve optimize hale getirmek

Yapilacaklar:

- performans kritik parcalari native dile tasimayi degerlendir
- gerekirse `Realtime Audio Core` icin `Rust` veya `C++` hedefle
- streaming `SR/TTS` icin daha dusuk seviyeli IPC seceneklerini uygula
- capability discovery ve versioned contract mantigi ekle
- replay/debug ve failure recovery altyapisini guclendir
- supervision ve saglik kontrolu ekle
- uygunsa hibrit `speech-to-speech` response engine seceneklerini degerlendir

Teslimatlar:

- production-grade embodied agent runtime
- daha genis bir model ve plugin ekosistemine hazir platform

Basari olcutu:

- sistem buyuse bile mimari dagilmadan yeni capability'ler eklenebilmeli

## Onerilen siralama

Pratikte izlenmesi en saglikli yol:

1. `LOCAL_SERVICE_SPLIT_ARCHITECTURE` mimarisini uygula
2. controller'i icten modulerlestir
3. event ve lifecycle modelini genislet
4. `Core + Adapters + Plugins + Services` ayrimini hayata gecir
5. sonra multimodal ve embodied genislemeleri ekle

## Riskler

Asagidaki hatalar bu yol haritasini zayiflatir:

- kisa vadeli `controller + SR + LLM + TTS` yapisini nihai mimari gibi gormek
- servis endpoint'lerini bugunun ihtiyacina gore fazla dar tasarlamak
- cancellation ve stale-result mantigini her serviste farkli sekilde ele almak
- audio-first controller sinirini bozup playback veya interrupt mantigini dagitmak
- vision, tools veya embodied action eklerken merkezi event modelini atlamak

## Kisa sonuc

Bu yol haritasinin ana fikri sudur:

- once mevcut sistemi servislesmis ama guvenli hale getir
- sonra controller'i daha genel bir event-driven cekirdege donustur
- sonra embodied ve multimodal yetenekleri bu cekirdegin etrafina ekle

Boylece proje, ani bir mimari kirilim yasamadan gelecekteki daha buyuk sisteme
evrimsel olarak yaklasabilir.
