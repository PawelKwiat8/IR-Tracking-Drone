"""Wspólne ustawienia testów: plik konfiguracja.json + argumenty z linii poleceń.

Kolejność (późniejsze nadpisuje wcześniejsze):
  1. konfiguracja.json             (w repo, wartości domyślne)
  2. konfiguracja_lokalna.json     (opcjonalny, Twoje ustawienia, nie trafia do repo)
  3. argumenty z linii poleceń
"""

import argparse
import json
import math
import os

KATALOG = os.path.dirname(os.path.abspath(__file__))
PLIK_KONFIGURACJI = os.path.join(KATALOG, "konfiguracja.json")
PLIK_LOKALNY = os.path.join(KATALOG, "konfiguracja_lokalna.json")
PLIK_MAPY = os.path.join(KATALOG, "mapa_kamer.json")
PLIK_INTRINSICS = os.path.join(KATALOG, "intrinsics.json")


def wczytaj_json(sciezka, domyslnie=None):
    if not os.path.exists(sciezka):
        return {} if domyslnie is None else domyslnie
    with open(sciezka, "r", encoding="utf-8") as f:
        return json.load(f)


def zapisz_json(sciezka, dane):
    with open(sciezka, "w", encoding="utf-8") as f:
        json.dump(dane, f, indent=4, ensure_ascii=False)


def wczytaj_konfiguracje():
    kfg = wczytaj_json(PLIK_KONFIGURACJI)
    kfg.update(wczytaj_json(PLIK_LOKALNY))
    return kfg


def parser(opis):
    """Parser z argumentami wspólnymi dla wszystkich testów."""
    p = argparse.ArgumentParser(description=opis)
    g = p.add_argument_group("kamera")
    g.add_argument("--zrodlo", choices=["auto", "v4l2", "pseyepy", "opencv", "symulacja"],
                   help="skąd brać obraz (domyślnie z konfiguracji: auto)")
    g.add_argument("--kamera", default=None,
                   help="numer logiczny kamery z mapa_kamer.json (np. 1) albo indeks urządzenia")
    g.add_argument("--szerokosc", type=int)
    g.add_argument("--wysokosc", type=int)
    g.add_argument("--fps", type=int)
    g.add_argument("--ekspozycja", type=int, help="0-255 (ov534)")
    g.add_argument("--wzmocnienie", type=int, help="0-63 (ov534)")
    g = p.add_argument_group("detekcja")
    g.add_argument("--prog", type=int, help="próg jasności 0-255 (0 = automatycznie)")
    g.add_argument("--min-pole", type=int)
    g.add_argument("--max-pole", type=int)
    p.add_argument("--bez-okna", action="store_true", help="bez podglądu (np. przez SSH)")
    return p


def polacz(args):
    """Zwraca słownik ustawień: konfiguracja nadpisana argumentami podanymi jawnie."""
    kfg = wczytaj_konfiguracje()
    for klucz in ("zrodlo", "szerokosc", "wysokosc", "fps", "ekspozycja", "wzmocnienie",
                  "prog", "min_pole", "max_pole"):
        wartosc = getattr(args, klucz, None)
        if wartosc is not None:
            kfg[klucz] = wartosc
    kfg["bez_okna"] = getattr(args, "bez_okna", False)
    return kfg


def ogniskowa(kfg, id_kamery=None):
    """Ogniskowa w px dla bieżącej rozdzielczości.

    Bierze fx z intrinsics.json (jeśli kamera była kalibrowana w tej rozdzielczości),
    a w przeciwnym razie wartość nominalną dla pozycji obiektywu, przeskalowaną do szerokości.
    Zwraca (f, skąd).
    """
    klucz = klucz_intrinsics(id_kamery, kfg)
    dane = wczytaj_json(PLIK_INTRINSICS)
    if klucz in dane:
        return float(dane[klucz]["K"][0][0]), "kalibracja " + klucz
    f640 = kfg["ogniskowa_nominalna_px"][str(kfg["pozycja_obiektywu"])]
    return f640 * kfg["szerokosc"] / 640.0, "nominalna (obiektyw %s°)" % kfg["pozycja_obiektywu"]


def klucz_intrinsics(id_kamery, kfg):
    return "kam%s_%dx%d_obj%s" % (id_kamery, kfg["szerokosc"], kfg["wysokosc"], kfg["pozycja_obiektywu"])


def fov_przekatna(f, szerokosc, wysokosc):
    return 2 * math.degrees(math.atan(math.hypot(szerokosc, wysokosc) / 2 / f))
