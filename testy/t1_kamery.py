#!/usr/bin/env python3
"""TEST 1: wykrycie kamer, numery logiczne i rzeczywisty klatkaż (plan, kroki 0.2 i 0.3).

Co mierzy (wszystkie kamery naraz, każda w osobnym wątku):
  - rzeczywisty FPS każdej kamery = (liczba klatek - 1) / (czas ostatniej - czas pierwszej),
  - odstępy między klatkami: średni, rozrzut, najdłuższy,
  - zgubione klatki: odstęp dt liczony jako round(dt * FPS_nominalny) - 1 brakujących.
Zaliczony, gdy każda kamera ma FPS >= 95% nominalnego i zgubiła < 1% klatek.

Uruchomienie:
  python t1_kamery.py                 # 10 s pomiaru wszystkich kamer
  python t1_kamery.py --czas 30
  python t1_kamery.py --mapuj         # nadanie numerów 1-4: pokazujesz diodę kolejnym kamerom
  python t1_kamery.py --fps 50        # sprawdzenie innego klatkażu
Klawisz q w oknie podglądu kończy pomiar wcześniej.
"""

import os
import time

import cv2
import numpy as np

import kamery
import plamki
import ustawienia
from wyniki import Wyniki, ocena


def podglad(watki, kfg, napis=""):
    kafle = []
    for w in watki:
        if w.ostatnia is None:
            img = np.zeros((kfg["wysokosc"], kfg["szerokosc"]), np.uint8)
        else:
            img = w.ostatnia[0]
        bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        n = len(w.czasy)
        fps = (n - 1) / (w.czasy[-1] - w.czasy[0]) if n > 10 else 0
        cv2.putText(bgr, "Kamera %s  %.1f kl/s" % (w.k.nazwa, fps), (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(bgr, w.k.id_sprz[-38:], (10, kfg["wysokosc"] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
        kafle.append(cv2.resize(bgr, (320, 240)))
    while len(kafle) % 2:
        kafle.append(np.zeros_like(kafle[0]))
    wiersze = [np.hstack(kafle[i:i + 2]) for i in range(0, len(kafle), 2)]
    obraz = np.vstack(wiersze)
    if napis:
        cv2.putText(obraz, napis, (10, obraz.shape[0] - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    cv2.imshow("Test 1 - kamery", obraz)
    return cv2.waitKey(1) & 0xFF


def pomiar(args, kfg):
    kam = kamery.otworz_kamery(kfg)
    wyn = Wyniki("t1_kamery", kfg)
    wyn.wypisz("Źródło: %s, tryb %dx%d @ %d kl./s, czas %d s" %
               (kam[0].zrodlo, kfg["szerokosc"], kfg["wysokosc"], kfg["fps"], args.czas))
    for k in kam:
        wyn.wypisz("  kamera %s: %s (%s)" % (k.nazwa, k.id_sprz, k.opis))
    watki = [kamery.WatekKamery(k) for k in kam]
    for w in watki:
        w.start()
    t0 = time.monotonic()
    while time.monotonic() - t0 < args.czas:
        if not kfg["bez_okna"]:
            if podglad(watki, kfg, "pomiar: %.0f / %d s" % (time.monotonic() - t0, args.czas)) == ord("q"):
                break
        else:
            time.sleep(0.1)
    for w in watki:
        w.stop.set()
    for w in watki:
        w.join(timeout=2)
    for k in kam:
        k.zamknij()
    if not kfg["bez_okna"]:
        cv2.destroyAllWindows()

    zapisz = wyn.csv("klatki.csv", ["kamera", "nr_klatki", "t_s"])
    nominal = kfg["fps"]
    liczby, wszystkie_ok = {}, True
    wyn.wypisz("\nKamera | klatek |   FPS  | śr. dt [ms] | rozrzut dt [ms] | max dt [ms] | zgubione | jasność tła")
    for w in watki:
        t = np.array(w.czasy)
        for i, ti in enumerate(t):
            zapisz([w.k.nazwa, i, "%.6f" % ti])
        if len(t) < 3:
            wyn.wypisz("%6s | brak klatek (błędy odczytu: %d)" % (w.k.nazwa, w.bledy))
            wszystkie_ok = False
            continue
        dt = np.diff(t)
        fps = (len(t) - 1) / (t[-1] - t[0])
        zgub = int(np.clip(np.round(dt * nominal) - 1, 0, None).sum())
        proc = 100.0 * zgub / (len(t) + zgub)
        jasn = float(w.ostatnia[0].mean()) if w.ostatnia else 0.0
        ok = fps >= 0.95 * nominal and proc < 1.0
        wszystkie_ok &= ok
        wyn.wypisz("%6s | %6d | %6.2f | %11.2f | %15.2f | %11.1f | %4d (%.1f%%) | %.1f" %
                   (w.k.nazwa, len(t), fps, 1e3 * dt.mean(), 1e3 * dt.std(), 1e3 * dt.max(), zgub, proc, jasn))
        liczby[w.k.nazwa] = {"id_sprzetowe": w.k.id_sprz, "klatek": len(t), "fps": fps,
                             "dt_sr_ms": 1e3 * dt.mean(), "dt_std_ms": 1e3 * dt.std(),
                             "dt_max_ms": 1e3 * dt.max(), "zgubione": zgub, "zgubione_proc": proc,
                             "zaliczony": bool(ok)}
    wyn.wypisz("\nKryterium: FPS >= %.1f (95%% z %d) i zgubione < 1%%." % (0.95 * nominal, nominal))
    wyn.wypisz("Wynik: %s" % ocena(wszystkie_ok))
    if not wszystkie_ok:
        wyn.wypisz("Podpowiedź: każda kamera 640x480@60 to ok. 37 MB/s (640*480*2 B*60), a USB 2.0 daje"
                   " realnie ok. 40 MB/s na kontroler. Podłącz kamery do różnych kontrolerów USB"
                   " albo zejdź do 320x240 lub niższego FPS.")
    wyn.zakoncz(liczby)


def mapuj(args, kfg):
    """Nadaje numery logiczne: kamera, która widzi diodę, dostaje kolejny numer."""
    if os.path.exists(ustawienia.PLIK_MAPY):
        os.replace(ustawienia.PLIK_MAPY, ustawienia.PLIK_MAPY + ".bak")
        print("Stara mapa zapisana jako mapa_kamer.json.bak")
    kam = kamery.otworz_kamery(kfg)
    licznik = {k.id_sprz: [0, 0] for k in kam}   # [klatki z plamką, wszystkie]
    aktywne = {"wlaczone": False}

    def licz(k):
        def f(img, t):
            if aktywne["wlaczone"]:
                p, _ = plamki.znajdz_plamki(img, kfg["prog"], kfg["min_pole"], kfg["max_pole"])
                licznik[k.id_sprz][0] += 1 if p else 0
                licznik[k.id_sprz][1] += 1
        return f

    watki = [kamery.WatekKamery(k, licz(k)) for k in kam]
    for w in watki:
        w.start()
    mapa = {}
    print("\nWykryto %d kamer. Zakryj wszystkie diody/światła w polu widzenia." % len(kam))
    for nr in range(1, len(kam) + 1):
        input("\nTrzymaj zapaloną diodę przed kamerą z naklejką %d (tylko ona ma ją widzieć) i naciśnij ENTER..." % nr)
        for v in licznik.values():
            v[0] = v[1] = 0
        aktywne["wlaczone"] = True
        time.sleep(2.0)
        aktywne["wlaczone"] = False
        udzialy = {s: (a / b if b else 0) for s, (a, b) in licznik.items() if s not in mapa.values()}
        for s, u in udzialy.items():
            print("   %s: plamka w %.0f%% klatek" % (s, 100 * u))
        najl = max(udzialy, key=udzialy.get) if udzialy else None
        inne = [u for s, u in udzialy.items() if s != najl]
        if najl and udzialy[najl] > 0.5 and all(u < 0.2 for u in inne):
            mapa[str(nr)] = najl
            print(" -> kamera %d = %s" % (nr, najl))
        else:
            print(" -> niejednoznaczne (diodę widzi kilka kamer albo żadna). Pomijam numer %d." % nr)
    for w in watki:
        w.stop.set()
    for k in kam:
        k.zamknij()
    ustawienia.zapisz_json(ustawienia.PLIK_MAPY, mapa)
    print("\nZapisano %s:" % ustawienia.PLIK_MAPY)
    for nr, s in mapa.items():
        print("  %s -> %s" % (nr, s))
    if kam and kam[0].zrodlo == "v4l2":
        print("Numer jest przypisany do portu USB: nie przekładaj kamer między gniazdami.")
    elif kam:
        print("UWAGA: przy źródle %s ID zależy od kolejności wykrycia; po zmianie podłączenia "
              "uruchom --mapuj ponownie." % kam[0].zrodlo)


def main():
    p = ustawienia.parser(__doc__)
    p.add_argument("--czas", type=float, default=10, help="czas pomiaru [s]")
    p.add_argument("--mapuj", action="store_true", help="nadaj kamerom numery logiczne")
    args = p.parse_args()
    kfg = ustawienia.polacz(args)
    if args.mapuj:
        mapuj(args, kfg)
    else:
        pomiar(args, kfg)


if __name__ == "__main__":
    main()
