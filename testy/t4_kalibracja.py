#!/usr/bin/env python3
"""TEST 4: kalibracja wewnętrzna kamery z kontrolą jakości (plan, krok 1.6).

Czym różni się od starego calibrate_intrinsics.py:
  - ujęcia łapią się same, gdy szachownica stoi nieruchomo (bez rozmycia) i jest w nowym
    miejscu lub pod nowym kątem; spacja wymusza ujęcie,
  - na obrazie widać siatkę pokrycia kadru: rogi szachownicy muszą trafić też w brzegi i rogi
    kadru, bo tam dystorsja jest największa (brak tego = przeuczona dystorsja jak w starym pliku),
  - domyślnie k3 = 0 (PS3 Eye ma umiarkowaną dystorsję, a wolne k3 przy słabym pokryciu
    "ucieka" do wartości typu ±4, co było w starym intrinsics.json),
  - wypisuje błąd reprojekcji (całość i każde ujęcie), odrzuca ujęcia odstające (> 3 x mediana),
    podaje niepewność fx, fy, cx, cy, pole widzenia i porównanie z pozycją obiektywu (521/752 px),
  - sprawdza prostoliniowość: rzędy rogów po usunięciu dystorsji muszą leżeć na prostych,
  - zapisuje zdjęcia, więc kalibrację można przeliczyć: --z-folderu <folder z wyników>.

W podczerwieni: szachownica z drukarki LASEROWEJ (toner pochłania IR), oświetlona żarówką
halogenową / oświetlaczem IR; na czas kalibracji można podnieść ekspozycję (--ekspozycja 200).
Wymiary szachownicy: --rogi 9 6 (rogi WEWNĘTRZNE) i --kwadrat 29 (mm), domyślnie z konfiguracji.

Zaliczony, gdy: RMS < 0,5 px, >= 15 ujęć, pokrycie kadru >= 70%, niepewność fx < 0,5%.

  python t4_kalibracja.py --kamera 1 --ekspozycja 200
  python t4_kalibracja.py --z-folderu wyniki/t4_kalibracja_20261014_150000
Klawisze: spacja = ujęcie, c = licz kalibrację, q = koniec bez liczenia.
"""

import glob
import math
import os
import time

import cv2
import numpy as np

import kamery
import ustawienia
from wyniki import Wyniki, ocena

SIATKA = (8, 6)  # komórki pokrycia kadru (poziomo, pionowo)


def znajdz(gray, rogi, dokladnie=False):
    flagi = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE
    if not dokladnie:
        flagi += cv2.CALIB_CB_FAST_CHECK
    ok, c = cv2.findChessboardCorners(gray, tuple(rogi), flagi)
    if ok and dokladnie:
        c = cv2.cornerSubPix(gray, c, (5, 5), (-1, -1),
                             (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.01))
    return ok, c


def komorki(c, w, h):
    xy = c.reshape(-1, 2)
    kx = np.clip((xy[:, 0] / w * SIATKA[0]).astype(int), 0, SIATKA[0] - 1)
    ky = np.clip((xy[:, 1] / h * SIATKA[1]).astype(int), 0, SIATKA[1] - 1)
    return set(zip(kx.tolist(), ky.tolist()))


def zbieranie(kam, kfg, rogi, cel, folder):
    w, h = kfg["szerokosc"], kfg["wysokosc"]
    ujecia, pokryte = [], set()
    poprz, stabilne = None, 0
    okno = "Test 4 - kalibracja (spacja = ujecie, c = licz, q = koniec)"
    t_ost = 0
    while True:
        ok, img, t = kam.czytaj()
        if not ok:
            continue
        znal, c = znajdz(img, rogi)
        wymus = False
        if not kfg["bez_okna"]:
            vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            nak = vis.copy()
            for (kx, ky) in pokryte:
                cv2.rectangle(nak, (kx * w // SIATKA[0], ky * h // SIATKA[1]),
                              ((kx + 1) * w // SIATKA[0], (ky + 1) * h // SIATKA[1]), (0, 120, 0), -1)
            vis = cv2.addWeighted(nak, 0.35, vis, 0.65, 0)
            if znal:
                cv2.drawChessboardCorners(vis, tuple(rogi), c, znal)
            cv2.putText(vis, "ujec %d/%d  pokrycie %.0f%%  %s" %
                        (len(ujecia), cel, 100 * len(pokryte) / (SIATKA[0] * SIATKA[1]),
                         "trzymaj nieruchomo..." if znal else "brak szachownicy"),
                        (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.imshow(okno, vis)
            k = cv2.waitKey(1) & 0xFF
            if k == ord("q"):
                return None
            if k == ord("c"):
                break
            wymus = k == ord(" ")
        elif len(ujecia) >= cel:
            break
        if not znal:
            poprz, stabilne = None, 0
            continue
        ruch = np.abs(c - poprz).max() if poprz is not None else 99
        poprz = c
        stabilne = stabilne + 1 if ruch < 1.0 else 0
        if not (wymus or stabilne >= 5) or time.monotonic() - t_ost < 0.5:
            continue
        # nowe ujęcie tylko, jeśli różni się od zebranych (średnie przesunięcie rogów > 30 px)
        if not wymus and any(np.abs(c - u).mean() < 30 for u in ujecia):
            continue
        ok2, c2 = znajdz(img, rogi, dokladnie=True)
        if not ok2:
            continue
        ujecia.append(c2)
        pokryte |= komorki(c2, w, h)
        cv2.imwrite(os.path.join(folder, "ujecie_%03d.png" % len(ujecia)), img)
        t_ost = time.monotonic()
        stabilne = 0
        print("  ujęcie %d, pokrycie %.0f%%" % (len(ujecia), 100 * len(pokryte) / (SIATKA[0] * SIATKA[1])))
    return ujecia


def z_folderu(folder, rogi):
    ujecia, rozmiar = [], None
    for plik in sorted(glob.glob(os.path.join(folder, "ujecie_*.png"))):
        img = cv2.imread(plik, cv2.IMREAD_GRAYSCALE)
        rozmiar = img.shape[::-1]
        ok, c = znajdz(img, rogi, dokladnie=True)
        if ok:
            ujecia.append(c)
        else:
            print("  pomijam %s (nie znaleziono szachownicy)" % os.path.basename(plik))
    return ujecia, rozmiar


def kalibruj(ujecia, rogi, kwadrat, rozmiar, flagi):
    obj = np.zeros((rogi[0] * rogi[1], 3), np.float32)
    obj[:, :2] = np.mgrid[0:rogi[0], 0:rogi[1]].T.reshape(-1, 2) * kwadrat
    objs = [obj] * len(ujecia)
    rms, K, dist, rv, tv, std_wew, _, bledy = cv2.calibrateCameraExtended(
        objs, ujecia, rozmiar, None, None, flags=flagi)
    return rms, K, dist, rv, tv, std_wew.ravel(), bledy.ravel(), obj


def prostoliniowosc(ujecia, rogi, K, dist):
    """Średnie odchylenie rogów od prostej dopasowanej do każdego rzędu [px], przed i po korekcji."""
    def odchyl(pkt):
        wyn = []
        for c in pkt:
            c = c.reshape(rogi[1], rogi[0], 2)
            for rzad in c:
                sr = rzad.mean(0)
                _, _, vt = np.linalg.svd(rzad - sr)
                n = vt[1]
                wyn.append(np.abs((rzad - sr) @ n).max())
        return float(np.mean(wyn))
    po = [cv2.undistortPoints(c, K, dist, P=K) for c in ujecia]
    return odchyl(ujecia), odchyl(po)


def main():
    p = ustawienia.parser(__doc__)
    p.add_argument("--rogi", type=int, nargs=2, help="rogi wewnętrzne szachownicy, np. 9 6")
    p.add_argument("--kwadrat", type=float, help="bok kwadratu [mm]")
    p.add_argument("--ujec", type=int, default=25, help="docelowa liczba ujęć")
    p.add_argument("--pelna-dystorsja", action="store_true", help="licz też k3 (domyślnie k3 = 0)")
    p.add_argument("--z-folderu", help="przelicz kalibrację ze zdjęć zapisanych wcześniej")
    p.add_argument("--nie-zapisuj", action="store_true", help="nie zapisuj wyniku do intrinsics.json")
    args = p.parse_args()
    kfg = ustawienia.polacz(args)
    rogi = args.rogi or kfg["szachownica_rogi"]
    kwadrat = args.kwadrat or kfg["szachownica_kwadrat_mm"]

    wyn = Wyniki("t4_kalibracja", kfg)
    if args.z_folderu:
        ujecia, rozmiar = z_folderu(args.z_folderu, rogi)
        nazwa_kam = args.kamera or "?"
        if rozmiar:
            kfg["szerokosc"], kfg["wysokosc"] = rozmiar
    else:
        kam = kamery.otworz_jedna(kfg, args.kamera)
        nazwa_kam = kam.nazwa
        rozmiar = (kfg["szerokosc"], kfg["wysokosc"])
        print("Pokazuj szachownicę w różnych miejscach kadru (też w rogach) i pod różnymi kątami (do ok. 45°).")
        ujecia = zbieranie(kam, kfg, rogi, args.ujec, wyn.folder)
        kam.zamknij()
        if not kfg["bez_okna"]:
            cv2.destroyAllWindows()
        if ujecia is None:
            print("Przerwano.")
            return
    if len(ujecia) < 5:
        raise SystemExit("Za mało ujęć (%d)." % len(ujecia))

    flagi = 0 if args.pelna_dystorsja else cv2.CALIB_FIX_K3
    rms, K, dist, rv, tv, sd, bledy, obj = kalibruj(ujecia, rogi, kwadrat, rozmiar, flagi)
    med = float(np.median(bledy))
    odrzucone = [i + 1 for i, b in enumerate(bledy) if b > 3 * med]
    if odrzucone and len(ujecia) - len(odrzucone) >= 10:
        wyn.wypisz("Odrzucam ujęcia odstające (błąd > 3 x mediana %.3f px): %s" % (med, odrzucone))
        ujecia = [u for i, u in enumerate(ujecia) if i + 1 not in odrzucone]
        rms, K, dist, rv, tv, sd, bledy, obj = kalibruj(ujecia, rogi, kwadrat, rozmiar, flagi)

    w, h = rozmiar
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    pokr = set()
    for u in ujecia:
        pokr |= komorki(u, w, h)
    pokrycie = 100.0 * len(pokr) / (SIATKA[0] * SIATKA[1])
    fov = ustawienia.fov_przekatna(fx, w, h)
    nom = {k: v * w / 640.0 for k, v in kfg["ogniskowa_nominalna_px"].items()}
    blizej = min(nom, key=lambda k: abs(nom[k] - fx))
    przed, po = prostoliniowosc(ujecia, rogi, K, dist)
    d = dist.ravel()

    wyn.wypisz("Kamera %s, %dx%d, szachownica %dx%d rogów, kwadrat %.1f mm, ujęć %d" %
               (nazwa_kam, w, h, rogi[0], rogi[1], kwadrat, len(ujecia)))
    wyn.wypisz("Błąd reprojekcji RMS: %.3f px (ujęcia: min %.3f, mediana %.3f, max %.3f)" %
               (rms, bledy.min(), np.median(bledy), bledy.max()))
    wyn.wypisz("fx = %.1f ± %.1f px, fy = %.1f ± %.1f px (fx/fy = %.4f)" % (fx, sd[0], fy, sd[1], fx / fy))
    wyn.wypisz("cx = %.1f ± %.1f px, cy = %.1f ± %.1f px (środek kadru: %.0f, %.0f)" %
               (cx, sd[2], cy, sd[3], w / 2, h / 2))
    wyn.wypisz("dystorsja k1 = %.4f, k2 = %.4f, p1 = %.5f, p2 = %.5f, k3 = %.4f%s" %
               (d[0], d[1], d[2], d[3], d[4], "" if args.pelna_dystorsja else " (k3 stałe)"))
    wyn.wypisz("Pole widzenia po przekątnej: 2·atan(%.0f / %.1f) = %.1f°" % (math.hypot(w, h) / 2, fx, fov))
    wyn.wypisz("Obiektyw: %s -> najbliżej pozycji %s° (różnica %+.0f%%)" %
               (", ".join("%s° = %.0f px" % kv for kv in nom.items()), blizej, 100 * (fx - nom[blizej]) / nom[blizej]))
    wyn.wypisz("Pokrycie kadru: %.0f%% komórek siatki %dx%d" % (pokrycie, SIATKA[0], SIATKA[1]))
    wyn.wypisz("Prostoliniowość rzędów: przed korekcją %.3f px, po korekcji %.3f px" % (przed, po))

    ok = rms < 0.5 and len(ujecia) >= 15 and pokrycie >= 70 and sd[0] / fx < 0.005
    wyn.wypisz("Kryterium: RMS < 0,5 px, >= 15 ujęć, pokrycie >= 70%, niepewność fx < 0,5%.")
    wyn.wypisz("Wynik: %s" % ocena(ok))
    if abs(fx - nom[blizej]) / nom[blizej] > 0.1:
        wyn.wypisz("UWAGA: fx różni się o ponad 10%% od obu pozycji obiektywu. Sprawdź pierścień obiektywu "
                   "i wymiar kwadratu (--kwadrat).")

    zapisz = wyn.csv("bledy_ujec.csv", ["ujecie", "blad_rms_px"])
    for i, b in enumerate(bledy):
        zapisz([i + 1, "%.4f" % b])
    wynik = {"K": K.tolist(), "dist": d.tolist(), "rms_px": rms, "ujec": len(ujecia),
             "pokrycie_proc": pokrycie, "sd_fx_fy_cx_cy": sd[:4].tolist(), "fov_przekatna": fov,
             "rozdzielczosc": [w, h], "data": time.strftime("%Y-%m-%d %H:%M:%S"),
             "folder": wyn.folder, "zaliczony": bool(ok)}
    if not args.nie_zapisuj and nazwa_kam != "?":
        klucz = ustawienia.klucz_intrinsics(nazwa_kam, kfg)
        dane = ustawienia.wczytaj_json(ustawienia.PLIK_INTRINSICS)
        dane[klucz] = wynik
        ustawienia.zapisz_json(ustawienia.PLIK_INTRINSICS, dane)
        wyn.wypisz("Zapisano do intrinsics.json jako %s" % klucz)
    wyn.zakoncz(wynik)


if __name__ == "__main__":
    main()
