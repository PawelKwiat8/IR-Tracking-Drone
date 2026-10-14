"""Dostęp do kamer PS3 Eye na Linuksie i Windows, z jednym interfejsem.

Źródła obrazu:
  v4l2       Linux, wbudowany sterownik ov534. Ekspozycja i wzmocnienie przez v4l2-ctl
             (pakiet v4l-utils). Stały identyfikator kamery = port USB (/dev/v4l/by-path),
             więc numeracja nie zmienia się po restarcie, dopóki kamera siedzi w tym samym porcie.
  pseyepy    Windows/macOS, biblioteka pseyepy (libusb, na Windows sterownik WinUSB z Zadig).
             Pełna kontrola ekspozycji, wzmocnienia i 60 kl./s przy 640x480.
  opencv     zapas: zwykły cv2.VideoCapture (np. sterownik CL-Eye na Windows). Ustawienia
             ekspozycji mogą nie działać.
  symulacja  sztuczne plamki, do sprawdzenia programów bez kamer.

Każda kamera ma metody: czytaj() -> (ok, obraz_szary, t), ustaw(ekspozycja, wzmocnienie), zamknij().
t to czas klatki w sekundach z zegara time.monotonic() (jeden zegar dla wszystkich kamer).

Numery logiczne kamer (naklejki 1-4) są w mapa_kamer.json, tworzonym przez t1_kamery.py --mapuj.
"""

import glob
import os
import platform
import subprocess
import threading
import time

import cv2
import numpy as np

from ustawienia import PLIK_MAPY, wczytaj_json

SYSTEM = platform.system()


# ---------------------------------------------------------------- v4l2 (Linux)

def _v4l2_urzadzenia():
    """Lista (id_sprzetowe, /dev/videoN, nazwa) kamer do przechwytywania obrazu."""
    wynik = []
    for sciezka in sorted(glob.glob("/sys/class/video4linux/video*")):
        dev = "/dev/" + os.path.basename(sciezka)
        try:
            with open(os.path.join(sciezka, "name")) as f:
                nazwa = f.read().strip()
            with open(os.path.join(sciezka, "index")) as f:
                if f.read().strip() != "0":
                    continue  # węzły metadanych itp.
        except OSError:
            continue
        id_sprz = None
        for link in glob.glob("/dev/v4l/by-path/*"):
            if os.path.realpath(link) == os.path.realpath(dev) and "video-index0" in link:
                id_sprz = os.path.basename(link).replace("-video-index0", "")
        wynik.append((id_sprz or dev, dev, nazwa))
    ps3 = [u for u in wynik if "USB Camera-B4" in u[2]]
    return ps3 if ps3 else wynik


def _v4l2_ctl(dev, nazwa, wartosc):
    try:
        r = subprocess.run(["v4l2-ctl", "-d", dev, "--set-ctrl=%s=%d" % (nazwa, wartosc)],
                           capture_output=True, text=True, timeout=3)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class KameraV4L2:
    def __init__(self, id_sprz, dev, kfg):
        self.id_sprz, self.dev = id_sprz, dev
        self.cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise RuntimeError("nie można otworzyć %s" % dev)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, kfg["szerokosc"])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, kfg["wysokosc"])
        self.cap.set(cv2.CAP_PROP_FPS, kfg["fps"])
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok = _v4l2_ctl(dev, "auto_exposure", 1)            # 1 = ręcznie
        ok &= _v4l2_ctl(dev, "gain_automatic", 0)
        _v4l2_ctl(dev, "white_balance_automatic", 0)
        if not ok:
            print("[UWAGA] %s: v4l2-ctl nie zadziałał (zainstaluj v4l-utils). "
                  "Ekspozycja zostaje automatyczna." % dev)
        self.ustaw(kfg["ekspozycja"], kfg["wzmocnienie"])

    def ustaw(self, ekspozycja=None, wzmocnienie=None):
        if ekspozycja is not None:
            _v4l2_ctl(self.dev, "exposure", int(ekspozycja))
        if wzmocnienie is not None:
            _v4l2_ctl(self.dev, "gain", int(wzmocnienie))

    def czytaj(self):
        ok, klatka = self.cap.read()
        t_host = time.monotonic()
        if not ok:
            return False, None, t_host
        # OpenCV z V4L2 podaje czas bufora sterownika (CLOCK_MONOTONIC, ms) - dokładniejszy
        # od czasu odczytu, bo nie zależy od tego, kiedy program zdążył odebrać klatkę.
        t_ster = self.cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        t = t_ster if 0 < t_host - t_ster < 1.0 else t_host
        if klatka.ndim == 3:
            klatka = cv2.cvtColor(klatka, cv2.COLOR_BGR2GRAY)
        return True, klatka, t

    def zamknij(self):
        self.cap.release()


# ---------------------------------------------------------------- pseyepy (Windows/macOS)

class _PseyeWspolny:
    """pseyepy obsługuje wszystkie kamery jednym obiektem Camera."""
    obiekt = None
    blokada = threading.Lock()

    @classmethod
    def otworz(cls, kfg):
        if cls.obiekt is None:
            from pseyepy import Camera, cam_count
            n = cam_count()
            if n == 0:
                raise RuntimeError("pseyepy nie widzi kamer (sterownik WinUSB z Zadig?)")
            rozdz = Camera.RES_LARGE if kfg["szerokosc"] >= 640 else Camera.RES_SMALL
            cls.obiekt = Camera(list(range(n)), resolution=rozdz, fps=kfg["fps"], colour=False,
                                auto_gain=False, auto_whitebalance=False,
                                gain=kfg["wzmocnienie"], exposure=kfg["ekspozycja"])
        return cls.obiekt


def _pseyepy_urzadzenia():
    try:
        from pseyepy import cam_count
        n = cam_count()
    except Exception as e:  # brak biblioteki lub sterownika
        print("[INFO] pseyepy niedostępne: %s" % e)
        return []
    # pseyepy nie podaje portu USB, więc ID = numer w kolejności wykrycia.
    return [("pseye%d" % i, i, "PS3 Eye (pseyepy)") for i in range(n)]


class KameraPseye:
    def __init__(self, id_sprz, nr, kfg):
        self.id_sprz, self.nr = id_sprz, nr
        self.cam = _PseyeWspolny.otworz(kfg)

    def ustaw(self, ekspozycja=None, wzmocnienie=None):
        with _PseyeWspolny.blokada:
            if ekspozycja is not None:
                self.cam.exposure[self.nr] = int(ekspozycja)
            if wzmocnienie is not None:
                self.cam.gain[self.nr] = int(wzmocnienie)

    def czytaj(self):
        klatka, _ = self.cam.read(self.nr)
        return True, np.array(klatka, copy=True), time.monotonic()

    def zamknij(self):
        pass


# ---------------------------------------------------------------- OpenCV (zapas)

def _opencv_urzadzenia(maks=8):
    api = cv2.CAP_DSHOW if SYSTEM == "Windows" else cv2.CAP_ANY
    wynik = []
    for i in range(maks):
        cap = cv2.VideoCapture(i, api)
        if cap.isOpened() and cap.read()[0]:
            wynik.append(("cv%d" % i, i, "OpenCV indeks %d" % i))
        cap.release()
    return wynik


class KameraOpenCV:
    def __init__(self, id_sprz, nr, kfg):
        self.id_sprz = id_sprz
        api = cv2.CAP_DSHOW if SYSTEM == "Windows" else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(nr, api)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, kfg["szerokosc"])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, kfg["wysokosc"])
        self.cap.set(cv2.CAP_PROP_FPS, kfg["fps"])
        print("[UWAGA] źródło opencv: ekspozycja/wzmocnienie mogą nie działać, sprawdź obraz.")

    def ustaw(self, ekspozycja=None, wzmocnienie=None):
        if wzmocnienie is not None:
            self.cap.set(cv2.CAP_PROP_GAIN, wzmocnienie)

    def czytaj(self):
        ok, klatka = self.cap.read()
        t = time.monotonic()
        if ok and klatka.ndim == 3:
            klatka = cv2.cvtColor(klatka, cv2.COLOR_BGR2GRAY)
        return ok, klatka, t

    def zamknij(self):
        self.cap.release()


# ---------------------------------------------------------------- wybór źródła

def wybierz_zrodlo(kfg):
    z = kfg.get("zrodlo", "auto")
    if z != "auto":
        return z
    if SYSTEM == "Linux":
        return "v4l2"
    return "pseyepy" if _pseyepy_urzadzenia() else "opencv"


def lista_urzadzen(kfg, liczba_symulowanych=3):
    """[(id_sprzetowe, adres, nazwa)] dla wybranego źródła."""
    z = wybierz_zrodlo(kfg)
    if z == "v4l2":
        return _v4l2_urzadzenia()
    if z == "pseyepy":
        return _pseyepy_urzadzenia()
    if z == "opencv":
        return _opencv_urzadzenia()
    n = int(os.environ.get("SYM_KAMERY", liczba_symulowanych))
    return [("sym%d" % i, i, "kamera symulowana") for i in range(n)]


def _otworz(z, id_sprz, adres, kfg):
    if z == "v4l2":
        return KameraV4L2(id_sprz, adres, kfg)
    if z == "pseyepy":
        return KameraPseye(id_sprz, adres, kfg)
    if z == "opencv":
        return KameraOpenCV(id_sprz, adres, kfg)
    from symulacja import SymKamera
    k = SymKamera(adres, kfg["szerokosc"], kfg["wysokosc"], kfg["fps"], kfg)
    k.id_sprz = id_sprz
    k.ustaw(kfg["ekspozycja"], kfg["wzmocnienie"])
    return k


def mapa_kamer():
    """{numer_logiczny: id_sprzetowe} z mapa_kamer.json."""
    return {str(k): v for k, v in wczytaj_json(PLIK_MAPY).items()}


def otworz_kamery(kfg, ktore=None):
    """Otwiera kamery i nadaje im numery logiczne (atrybut .nazwa).

    ktore: None = wszystkie wykryte, albo lista numerów logicznych / indeksów, np. ["1"].
    Bez mapa_kamer.json numer logiczny = kolejność wykrycia (1, 2, ...), z ostrzeżeniem.
    """
    z = wybierz_zrodlo(kfg)
    urz = lista_urzadzen(kfg)
    if not urz:
        raise SystemExit("Nie znaleziono kamer (źródło: %s)." % z)
    mapa = mapa_kamer()
    po_sprz = {u[0]: u for u in urz}
    nazwy = {}
    if mapa:
        for nr, sprz in mapa.items():
            if sprz in po_sprz:
                nazwy[sprz] = nr
        brak = [nr for nr, s in mapa.items() if s not in po_sprz]
        if brak:
            print("[UWAGA] Kamery z mapy niepodłączone: %s" % ", ".join(sorted(brak)))
    else:
        print("[UWAGA] Brak mapa_kamer.json - numery wg kolejności wykrycia. "
              "Uruchom t1_kamery.py --mapuj.")
    wolny = 1
    for u in urz:
        if u[0] not in nazwy:
            while str(wolny) in nazwy.values():
                wolny += 1
            nazwy[u[0]] = ("?%d" % wolny) if mapa else str(wolny)
            wolny += 1
    kamery = []
    for u in sorted(urz, key=lambda u: nazwy[u[0]]):
        nazwa = nazwy[u[0]]
        if ktore is not None and nazwa not in [str(k) for k in ktore] and nazwa.lstrip("?") not in [str(k) for k in ktore]:
            continue
        k = _otworz(z, u[0], u[1], kfg)
        k.nazwa, k.zrodlo, k.opis = nazwa, z, u[2]
        kamery.append(k)
    if not kamery:
        raise SystemExit("Brak kamery o numerze %s. Wykryte: %s" % (ktore, sorted(nazwy.values())))
    return kamery


def otworz_jedna(kfg, numer):
    return otworz_kamery(kfg, None if numer is None else [numer])[0]


class WatekKamery(threading.Thread):
    """Czyta kamerę w osobnym wątku: zapisuje czasy wszystkich klatek i trzyma ostatnią."""

    def __init__(self, kamera, przetwarzaj=None):
        super().__init__(daemon=True)
        self.k = kamera
        self.przetwarzaj = przetwarzaj   # funkcja(obraz, t) wołana dla każdej klatki
        self.czasy = []
        self.bledy = 0
        self.ostatnia = None
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            ok, img, t = self.k.czytaj()
            if not ok:
                self.bledy += 1
                time.sleep(0.005)
                continue
            self.czasy.append(t)
            self.ostatnia = (img, t)
            if self.przetwarzaj:
                self.przetwarzaj(img, t)
