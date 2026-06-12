# Plan działania — śledzenie pozycji drona w pomieszczeniu

Dokument roboczy do pracy magisterskiej. Stan na: czerwiec 2026.

## 1. Gdzie jesteśmy

Zrealizowane (Etap 1 wg README):

- Dron 55 mm (brushed) z 3 aktywnymi markerami IR, sterowany przez most ESP32↔ESP32 (ESP-NOW) + MSP do FC.
- Zmodyfikowane kamery PS3 Eye (usunięty filtr IR-cut, filtr z dyskietki, korekta ostrości).
- Skrypty: kalibracja intrinsics, detekcja LED (`ir_led_tracker.py`), szkielet trackera multi-kamerowego (`mocap_tracker.py`, `mocap_visualizer.py`), most joysticka.

Brakuje: kalibracji extrinsics (pozycje kamer względem siebie), triangulacji 3D w czasie rzeczywistym, identyfikacji markerów (który LED jest który), zamkniętej pętli sterowania (PID pozycji), pomiarów dokładności i opóźnień.

## 2. Trzy ścieżki do wyboru

### Ścieżka A — klasyczny IR MoCap (kontynuacja, fundament)

Dokończenie tego, co już jest: triangulacja z ≥2 kamer, dopasowanie trójkąta markerów (pozycja + yaw), filtr Kalmana, PID, zawis i trajektoria. Wzorzec: projekt [Low-Cost-Mocap (jyjblrd)](https://github.com/jyjblrd/Low-Cost-Mocap) — dokładnie ta sama koncepcja (PS3 Eye + dyskietka + aktywne IR LED), opisany na [Hackaday](https://hackaday.com/2023/11/23/drone-motion-capture-the-open-source-way/) i [blogu autora](https://joshuabird.com/blog/post/mocap-drones). Warto przeczytać jego kod kalibracji extrinsics (bundle adjustment) zamiast wymyślać od zera.

- **Zalety:** największa szansa na działający system w terminie; precyzja rzędu pojedynczych cm; mierzalne wyniki.
- **Wady:** odtwórcze — istnieje open-source'owy odpowiednik, sama replikacja to za mało na mocną pracę magisterską.

### Ścieżka B — detekcja drona siecią neuronową (markerless, Twój pomysł)

Zamiast markerów IR: zwykłe kamery RGB + sieć detekcyjna (YOLOv8n/YOLO11n lub mniejsza) wykrywa drona na obrazie; pozycja 3D z triangulacji środków bounding boxów z ≥2 kamer. Uniwersalność = działa z **dowolnym** dronem bez modyfikacji sprzętowych — to jest dokładnie ta cecha, której nie ma żaden tani MoCap.

- **Zalety:** nowość, atrakcyjność naukowa, zero ingerencji w drona.
- **Wady:** niższa dokładność i większe opóźnienie niż IR; brak orientacji (yaw) z samego bounding boxa; potrzebny dataset; ryzyko, że pętla sterowania nie będzie stabilna.

### Ścieżka C — hybryda (REKOMENDOWANA): IR jako ground truth dla sieci

Połączenie A i B w jedną spójną narrację pracy. Kluczowy pomysł — **automatyczne etykietowanie**:

1. Dokańczasz system IR (ścieżka A) — on i tak jest potrzebny.
2. Obok zmodyfikowanych kamer stawiasz 1–2 **niemodyfikowane** PS3 Eye (RGB), skalibrowane względem systemu IR.
3. Podczas zwykłych lotów system IR zna pozycję 3D drona → rzutujesz ją na obraz kamer RGB → **każda klatka RGB dostaje etykietę (bounding box) za darmo, bez ręcznego oznaczania**.
4. Godzina latania = dziesiątki tysięcy oznaczonych klatek. Trenujesz YOLO na tym datasecie.
5. System IR służy potem jako **wzorzec odniesienia (ground truth)** do ilościowej oceny dokładności trackera neuronowego — masz gotowy rozdział badawczy: „IR vs NN: dokładność, opóźnienie, odporność".
6. Uniwersalność modelu weryfikujesz na pozostałych dwóch dronach (Air75, 5"), których model nie widział w treningu — idealny test generalizacji.

To jest realny wkład własny: *self-supervised pipeline do taniego pozyskiwania datasetów detekcji dronów + ilościowe porównanie markerowego i bezmarkerowego śledzenia na tym samym stanowisku*. Nie znalazłem taniego open-source'owego systemu, który to robi.

## 3. Wykorzystanie trzech dronów

| Dron | Rola |
|---|---|
| 55 mm brushed + ESP32/ESP-NOW | Główna platforma: pętla sterowania (IR), generowanie datasetu, wszystkie loty testowe |
| BetaFPV Air75 (ELRS) | Drugi obiekt: test generalizacji modelu NN (inna sylwetka), śledzenie 2 dronów naraz; opcjonalnie sterowanie z PC |
| 5" (ELRS) | Tylko jako obiekt do datasetu/testu generalizacji (inna skala); **nie latać nim w pętli w pomieszczeniu** |

Sterowanie Air75 z komputera (jeśli potrzebne do testów w pętli): moduł nadawczy ELRS (micro TX, ~100–150 zł) podpięty do PC przez UART + projekt [elrs-joystick-control](https://github.com/kaack/elrs-joystick-control) — PC udaje aparaturę i wysyła CRSF. Alternatywnie najtańsza aparatura ELRS i tryb trainer. To pozwala użyć tego samego mostka Pythonowego (`joystick_bridge.py` → CRSF zamiast ESP-NOW) i pokazać, że system pozycjonowania jest niezależny od łącza radiowego — kolejny argument za uniwersalnością.

## 4. Kreatywne pomysły do rozważenia (od najcenniejszych)

1. **Auto-labeling przez rzutowanie IR→RGB** — opisany wyżej; serce ścieżki C.
2. **Identyfikacja dronów przez mruganie LED** — PS3 Eye robi do 187 fps przy 320×240. Każdy dron mruga markerem z innym wzorem (kod czasowy) → system rozróżnia wiele dronów bez różnych geometrii markerów. Tanie rozwiązanie problemu multi-drone ID, rzadko spotykane w amatorskich MoCap.
3. **Fuzja z IMU (EKF)** — FC już wysyła telemetrię po MSP (`MSP_ATTITUDE`, `MSP_RAW_IMU`). Fuzja kamera+IMU wygładza pozycję między klatkami i ratuje przy chwilowej okluzji. Mocny rozdział inżynierski, mało kodu (filtr Kalmana ze stanem pozycja+prędkość).
4. **Dane syntetyczne (domain randomization)** — model 3D drona w Blenderze, rendering na losowych tłach → dotrenowanie modelu, by generalizował na drony, których fizycznie nie masz. Dobrze łączy się z testem na Air75/5".
5. **Sieć keypointów zamiast bounding boxa** — model wykrywa charakterystyczne punkty drona (silniki, kamera FPV) → PnP → pełne 6-DOF bez markerów. Ambitne rozszerzenie ścieżki B; etykiety keypointów też można generować automatycznie z systemu IR (znasz pozycje ramion z geometrii markerów).
6. **Efektowne demonstracje do obrony:**
   - *Light painting* — zdjęcie z długim naświetlaniem, dron z LED rysuje w powietrzu zadany kształt (bezpośredni, widowiskowy dowód dokładności trajektorii);
   - precyzyjne lądowanie na małej platformie / „dokowanie" (nawiązanie do zastosowań magazynowych z README);
   - lot dwóch dronów naraz (leader–follower: Air75 śledzony przez NN, 55 mm przez IR);
   - „klatka bezpieczeństwa" — wirtualne ściany: system odpycha drona od granic pokoju.
7. **Rzetelny pomiar opóźnienia end-to-end** — LED błyska → ile ms do reakcji w komendzie sterującej (pomiar oscyloskopem/drugą kamerą). W literaturze rzadko raportowane dla tanich systemów; łatwy, konkretny wynik do tabeli.
8. **Publikacja datasetu i modelu** (GitHub/HuggingFace, ONNX) — „uniwersalny, podczepialny pod dowolnego drona" moduł detekcji to dobry produkt pracy; istniejące datasety (np. [DroneDetect](https://ieee-dataport.org/documents/dronedetect-benchmark-uav-dataset-deep-learning-based-drone-detection)) są głównie outdoorowe/anty-dronowe, indoor-tracking to nisza.

## 5. Harmonogram (12 tygodni)

| Tydz. | Cel | Wynik |
|---|---|---|
| 1–2 | Kalibracja extrinsics (szachownica lub wodzenie markerem + bundle adjustment wzorem Low-Cost-Mocap); triangulacja 3D offline | Pozycja 3D statycznego markera, błąd < 2 cm |
| 3–4 | Tracking w czasie rzeczywistym: dopasowanie trójkąta, filtr Kalmana, wysyłka pozycji przez ESP-NOW; pomiar opóźnienia | Pozycja+yaw @ ≥30 Hz, znana latencja |
| 5–6 | Zamknięcie pętli: PID (x, y, z, yaw) na PC → komendy RC przez MSP; strojenie | **Stabilny zawis** (kamień milowy pracy) |
| 7 | Trajektorie (kwadrat, okrąg), zbieranie logów; demo light painting | Wykresy zadane vs rzeczywiste |
| 8 | Dołożenie kamer RGB, kalibracja względem IR, pipeline auto-labelingu | Dataset kilkadziesiąt tys. klatek |
| 9 | Trening YOLO (nano), eksport ONNX, triangulacja z detekcji NN | Tracker NN działający na żywo |
| 10 | Ewaluacja: NN vs IR (dokładność, latencja, fps); test generalizacji na Air75 i 5" | Tabele porównawcze — rdzeń badawczy |
| 11 | Eksperymenty bonusowe wg czasu: zawis na NN, multi-drone, mruganie LED, lądowanie precyzyjne | Materiał na rozdział „rozszerzenia" |
| 12 | Bufor + pisanie: metodologia, wyniki, wnioski | Komplet danych do pracy |

Zasada: **tygodnie 1–7 są obowiązkowe (ścieżka A daje gotową, obronną pracę), 8–11 to nadbudowa naukowa (ścieżka C)**. Jeśli coś się posypie, ucinasz od końca, nie od środka.

## 6. Ryzyka i decyzje

- **PID na brushed whoopie może oscylować** (słaba dynamika, dryf baterii) → zacząć od samego utrzymania wysokości (z), dopiero potem x/y; ew. tryb Angle z małymi wychyleniami.
- **2 kamery to minimum, 3–4 znacznie lepsze** (okluzje) — PS3 Eye są tanie, dokupić wcześniej; uwaga na przepustowość USB (osobne kontrolery/huby).
- **Czas treningu NN nie jest ryzykiem** (nano-modele trenują się w godziny na darmowym Colabie), ryzykiem jest jakość auto-etykiet → odfiltrować klatki z rozmyciem ruchu i niepewną triangulacją.
- **Nie konfigurować pętli sterowania dla 5"** w pomieszczeniu — tylko statyczne/ręczne nagrania do datasetu.
- Decyzja do podjęcia po tygodniu 6: czy NN ma tylko *mierzyć* pozycję (porównanie z IR — bezpieczne), czy też *sterować* dronem (efektowne, ale ryzykowne czasowo). Rekomendacja: najpierw pomiar, sterowanie jako bonus.

## 7. Źródła

- [jyjblrd/Low-Cost-Mocap](https://github.com/jyjblrd/Low-Cost-Mocap) + [dyskusja o modyfikacji PS3 Eye](https://github.com/jyjblrd/Low-Cost-Mocap/discussions/10) + [opis na blogu](https://joshuabird.com/blog/post/mocap-drones) + [Hackaday](https://hackaday.com/2023/11/23/drone-motion-capture-the-open-source-way/)
- [kaack/elrs-joystick-control](https://github.com/kaack/elrs-joystick-control) — sterowanie ELRS z PC (CRSF)
- [DroneDetect — benchmark dataset](https://ieee-dataport.org/documents/dronedetect-benchmark-uav-dataset-deep-learning-based-drone-detection)
- [YOLO-IHD — detekcja w czasie rzeczywistym na dronach indoor](https://pmc.ncbi.nlm.nih.gov/articles/PMC10857234/)
