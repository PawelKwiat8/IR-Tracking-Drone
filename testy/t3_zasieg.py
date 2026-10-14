#!/usr/bin/env python3
"""TEST 3: zasięg i kąt świecenia diody (plan, krok 1.2).

Jedno uruchomienie = jeden punkt pomiarowy (odległość, kąt obrotu diody względem kamery).
Wynik dopisuje się do testy/wyniki/zasieg.csv, więc robisz serię:

  python t3_zasieg.py --kamera 1 --opis "850nm 3mm 50mA mat" --odleglosc 1 --kat 0
  python t3_zasieg.py --kamera 1 --opis "850nm 3mm 50mA mat" --odleglosc 1 --kat 30
  ... (kąty 0, 30, 60, 90; odległości 1, 2, 3, 4 m)
  python t3_zasieg.py --raport          # tabela ze wszystkich pomiarów

Kąt = o ile dioda jest obrócona od kierunku "prosto w kamerę" (przechył drona).
Dla każdego punktu: wykrywalność, szczyt jasności, średnica plamki, SNR, σ środka.
Punkt zaliczony, gdy wykrywalność >= 99% i SNR >= 10 (zapas na słabszą diodę i daleki róg pokoju).

Przy okazji wypisuje, ile pikseli dzielą na tej odległości najbliższe diody gwiazdy
(77,9 mm): odstęp_px = 77,9 mm · f / Z.
"""

import csv
import math
import os
import time

import numpy as np

import kamery
import plamki
import ustawienia
from wyniki import KATALOG_WYNIKOW

PLIK = os.path.join(KATALOG_WYNIKOW, "zasieg.csv")
POLA = ["data", "kamera", "opis", "odleglosc_m", "kat_deg", "ekspozycja", "wzmocnienie", "prog",
        "klatek", "wykrywalnosc_proc", "szczyt", "srednica_px", "snr", "sigma_px", "falszywe", "zaliczony"]


def gwiazda_min_odstep_mm(kfg):
    g = np.array(kfg["gwiazda_mm"])
    return min(np.linalg.norm(g[i] - g[j]) for i in range(len(g)) for j in range(i + 1, len(g)))


def pomiar(args, kfg):
    kam = kamery.otworz_jedna(kfg, args.kamera)
    for _ in range(10):  # niech ustawienia ekspozycji zadziałają
        kam.czytaj()
    rek, tla, falsz, klatek = [], [], 0, 0
    t0 = time.monotonic()
    while time.monotonic() - t0 < args.czas:
        ok, img, t = kam.czytaj()
        if not ok:
            continue
        klatek += 1
        pl, prog = plamki.znajdz_plamki(img, kfg["prog"], kfg["min_pole"], kfg["max_pole"])
        tla.append(plamki.tlo(img, pl))
        if pl:
            rek.append((pl[0]["x"], pl[0]["y"], pl[0]["szczyt"], pl[0]["srednica"]))
            falsz += len(pl) - 1
    kam.zamknij()
    bg = np.array(tla)
    bg_sr, bg_std = bg[:, 0].mean(), max(bg[:, 1].mean(), 1e-6)
    wykr = 100.0 * len(rek) / max(klatek, 1)
    if rek:
        a = np.array(rek)
        szczyt, sred = a[:, 2].mean(), a[:, 3].mean()
        snr = (szczyt - bg_sr) / bg_std
        sigma = math.sqrt((a[:, 0].var() + a[:, 1].var()) / 2)
    else:
        szczyt = sred = snr = sigma = 0.0
    zal = wykr >= 99.0 and snr >= 10 and falsz == 0
    f, skad = ustawienia.ogniskowa(kfg, kam.nazwa)
    odst = gwiazda_min_odstep_mm(kfg) * f / (args.odleglosc * 1000)
    print("Kamera %s, %s, Z = %.2f m, kąt %g°" % (kam.nazwa, args.opis, args.odleglosc, args.kat))
    print("  wykrywalność %.1f%%, szczyt %.0f, średnica %.1f px, SNR %.0f, σ %.3f px, fałszywe %d" %
          (wykr, szczyt, sred, snr, sigma, falsz))
    print("  najbliższe diody gwiazdy (%.1f mm) będą %.1f px od siebie (f = %.0f px, %s); średnica plamki %.1f px -> %s" %
          (gwiazda_min_odstep_mm(kfg), odst, f, skad, sred, "OK" if odst > 2 * sred else "ZA BLISKO"))
    print("  -> %s" % ("ZALICZONY" if zal else "NIE ZALICZONY"))
    os.makedirs(KATALOG_WYNIKOW, exist_ok=True)
    nowy = not os.path.exists(PLIK)
    with open(PLIK, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if nowy:
            w.writerow(POLA)
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), kam.nazwa, args.opis, args.odleglosc, args.kat,
                    kfg["ekspozycja"], kfg["wzmocnienie"], kfg["prog"], klatek, "%.1f" % wykr,
                    "%.0f" % szczyt, "%.2f" % sred, "%.1f" % snr, "%.4f" % sigma, falsz, int(zal)])
    print("Dopisano do %s" % PLIK)


def raport():
    if not os.path.exists(PLIK):
        raise SystemExit("Brak pomiarów (%s)." % PLIK)
    with open(PLIK, encoding="utf-8") as fh:
        wiersze = list(csv.DictReader(fh))
    for opis in sorted({w["opis"] for w in wiersze}):
        ww = [w for w in wiersze if w["opis"] == opis]
        odl = sorted({float(w["odleglosc_m"]) for w in ww})
        katy = sorted({float(w["kat_deg"]) for w in ww})
        print("\n%s   (komórka: wykrywalność %% / SNR; * = niezaliczony)" % opis)
        print("Z [m] | " + " | ".join("%11s" % ("%g°" % k) for k in katy))
        for z in odl:
            kom = []
            for k in katy:
                tr = [w for w in ww if float(w["odleglosc_m"]) == z and float(w["kat_deg"]) == k]
                if not tr:
                    kom.append("%11s" % "-")
                    continue
                w = tr[-1]  # ostatni pomiar w tym punkcie
                kom.append("%5.0f/%4.0f%s" % (float(w["wykrywalnosc_proc"]), float(w["snr"]),
                                             " " if w["zaliczony"] == "1" else "*"))
            print("%5g | " % z + " | ".join(kom))


def main():
    p = ustawienia.parser(__doc__)
    p.add_argument("--odleglosc", type=float, help="odległość diody od kamery [m]")
    p.add_argument("--kat", type=float, default=0, help="obrót diody od kierunku na kamerę [°]")
    p.add_argument("--opis", default="dioda", help="opis diody, np. '850nm 3mm 50mA mat'")
    p.add_argument("--czas", type=float, default=3, help="czas pomiaru w punkcie [s]")
    p.add_argument("--raport", action="store_true", help="tylko wypisz tabelę z zasieg.csv")
    args = p.parse_args()
    if args.raport:
        raport()
        return
    if args.odleglosc is None:
        p.error("podaj --odleglosc (albo --raport)")
    pomiar(args, ustawienia.polacz(args))


if __name__ == "__main__":
    main()
