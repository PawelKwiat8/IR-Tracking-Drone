# Testy kamer PS3 Eye i znaczników IR

Nowy zestaw testów zastępujący testy z `scripts/`. Kolejność i kryteria są wzięte z planu pracy
(kroki 0.2–1.6 i 4.1–4.2). Każdy test:

- działa na Linuksie (V4L2) i Windows (pseyepy), a bez kamer w trybie symulacji,
- zapisuje surowe dane CSV ze znacznikami czasu i podsumowanie do `testy/wyniki/<test>_<data>/`,
- kończy się wynikiem **ZALICZONY / NIE ZALICZONY** z progiem z planu.

## Instalacja

```bash
pip install opencv-python numpy
```

- **Linux:** `sudo apt install v4l-utils` (ustawianie ekspozycji przez `v4l2-ctl`). Sterownik ov534 jest w jądrze.
- **Windows:** w Zadig przypisz sterownik WinUSB do „USB Camera-B4.09.24.1”, potem zainstaluj
  [pseyepy](https://github.com/bensondaled/pseyepy). Bez tego testy użyją zwykłego OpenCV, ale ekspozycja może się nie ustawiać.

Sprawdzenie bez kamer (wszystkie testy na sztucznych plamkach):

```bash
python testy/sprawdz_bez_kamer.py
```

## Kolejność

| Test | Krok planu | Co sprawdza | Zaliczony, gdy |
|---|---|---|---|
| `t1_kamery.py --mapuj` | 0.2 | nadaje kamerom numery 1–4: pokazujesz diodę kamerze z naklejką | – |
| `t1_kamery.py` | 0.3 | wszystkie kamery naraz: rzeczywisty FPS, odstępy klatek, zgubione klatki | FPS ≥ 95% nominalnego, zgubione < 1% |
| `t2_plamka.py` | 1.1, 1.5 | suwaki ekspozycji/wzmocnienia/progu, potem szum środka nieruchomej plamki, dryf, SNR, przepalenie | σ < 0,2 px, wykrywalność ≥ 99,5%, 0 fałszywych |
| `t2_plamka.py --diody 2 --odleglosc Z --rozstaw D` | 0.4 | ogniskowa z dwóch diod: f = odstęp_px · Z / D, czyli która pozycja obiektywu (521 / 752 px) | – (informacja) |
| `t3_zasieg.py` | 1.2 | seria punktów (odległość × kąt obrotu diody), tabela `--raport` | wykrywalność ≥ 99%, SNR ≥ 10 |
| `t4_kalibracja.py` | 1.6 | kalibracja wewnętrzna: auto-ujęcia, mapa pokrycia kadru, odrzucanie odstających, niepewności, prostoliniowość | RMS < 0,5 px, ≥ 15 ujęć, pokrycie ≥ 70%, niepewność fx < 0,5% |
| `t5_gwiazda.py` | 4.1, 4.2 | gwiazda 4 diod jedną kamerą: rozpoznanie diod (24 przypisania), poza, odległość | rozpoznanie stałe ≥ 99%, błąd < 1 px, zapas ≥ 3, Z zgodne z miarką do 5% |

Przykład pierwszej sesji z jedną kamerą i diodą na baterii:

```bash
cd testy
python t1_kamery.py --mapuj
python t1_kamery.py --czas 30
python t2_plamka.py --kamera 1                     # ustaw suwaki, s = zapisz, spacja = pomiar 30 s
python t2_plamka.py --kamera 1 --diody 2 --odleglosc 2.0 --rozstaw 100
python t3_zasieg.py --kamera 1 --opis "850nm 50mA mat" --odleglosc 3 --kat 60
python t4_kalibracja.py --kamera 1 --ekspozycja 200
python t5_gwiazda.py --kamera 1 --odleglosc 2.0
```

## Pliki

| Plik | Co to |
|---|---|
| `konfiguracja.json` | ustawienia domyślne: tryb kamery, ekspozycja, próg, szachownica, model gwiazdy (mm) |
| `konfiguracja_lokalna.json` | Twoje nadpisania (zapisuje je klawisz `s` w teście 2), nie trafia do repo |
| `mapa_kamer.json` | numer logiczny kamery → port USB (z `t1_kamery.py --mapuj`) |
| `intrinsics.json` | wyniki testu 4, klucz `kam<nr>_<szer>x<wys>_obj<pozycja obiektywu>` |
| `kamery.py`, `plamki.py`, `ustawienia.py`, `wyniki.py`, `symulacja.py` | wspólny kod |

Wspólne argumenty każdego testu: `--kamera`, `--zrodlo {auto,v4l2,pseyepy,opencv,symulacja}`,
`--szerokosc`, `--wysokosc`, `--fps`, `--ekspozycja`, `--wzmocnienie`, `--prog`, `--bez-okna`.

## Uwagi do starych danych

- `intrinsics.json` w katalogu głównym ma fx ≈ 850 px, czyli ok. 50° po przekątnej. PS3 Eye ma 75° (521 px) albo 56° (752 px).
  Duże i różne między kamerami k2, k3 wskazują na przeuczoną dystorsję (w symulacji ujęcia tylko ze środka kadru
  z wolnym k3 dają k3 ≈ −1,6 przy prawdziwym 0). Ogniskową sprawdź testem 2 z dwiema diodami albo testem 5 z miarką.
- `camera_calibration.json`: każda kamera ma |t| = 1 z `recoverPose`, a potem wspólną skalę, więc program zakłada
  równe odległości kamer 2 i 3 od kamery 1. Kalibracja zewnętrzna będzie osobnym testem (różdżka z dwiema diodami, bundle adjustment).
