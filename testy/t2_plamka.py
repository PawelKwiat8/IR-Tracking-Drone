#!/usr/bin/env python3
"""TEST 2: plamka nieruchomej diody i szum jej środka (plan, kroki 1.1 i 1.5).

Najpierw podgląd z suwakami ekspozycji, wzmocnienia i progu: ustaw tak, żeby tło było
czarne, a plamka mała i nieprzepalona (szczyt < 255). Spacja zaczyna pomiar.

Co mierzy dla każdej diody (dioda i kamera nieruchome):
  - σx, σy: odchylenie standardowe położenia środka [px], σ = sqrt((σx² + σy²) / 2),
  - dryf: nachylenie prostej dopasowanej do x(t) i y(t) [px/min] (np. nagrzewanie),
  - średnicę plamki, szczyt jasności, liczbę przepalonych pikseli,
  - SNR = (szczyt - średnia tła) / odch. std tła,
  - wykrywalność (w ilu klatkach dioda była) i fałszywe plamki (nadmiarowe).
Przy kilku diodach także najmniejszy odstęp plamek w px (powinien być > 2 średnice).
Z --odleglosc: σ w mm (σ_mm = σ_px · Z / f). Z --odleglosc i --rozstaw przy 2 diodach:
ogniskowa z pomiaru f = odstęp_px · Z / rozstaw (sprawdza, która pozycja obiektywu: 521 czy 752 px).

Zaliczony, gdy: σ < 0,2 px, wykrywalność >= 99,5%, zero fałszywych plamek.

Przykłady:
  python t2_plamka.py --kamera 1
  python t2_plamka.py --kamera 1 --diody 2 --odleglosc 3.0 --rozstaw 100 --czas 30
Klawisze: spacja = start pomiaru, s = zapisz ustawienia do konfiguracja_lokalna.json, q = koniec.
"""

import math
import time

import cv2
import numpy as np

import kamery
import plamki
import ustawienia
from wyniki import Wyniki, ocena


def ustawianie(kam, kfg, n_diod):
    """Podgląd z suwakami. Zwraca False, gdy użytkownik wyszedł klawiszem q."""
    okno = "Test 2 - ustawienia (spacja = pomiar, s = zapisz, q = koniec)"
    cv2.namedWindow(okno)
    cv2.createTrackbar("Ekspozycja", okno, kfg["ekspozycja"], 255, lambda v: None)
    cv2.createTrackbar("Wzmocnienie", okno, kfg["wzmocnienie"], 63, lambda v: None)
    cv2.createTrackbar("Prog (0=auto)", okno, kfg["prog"], 255, lambda v: None)
    poprz = (kfg["ekspozycja"], kfg["wzmocnienie"])
    while True:
        e = cv2.getTrackbarPos("Ekspozycja", okno)
        g = cv2.getTrackbarPos("Wzmocnienie", okno)
        kfg["prog"] = cv2.getTrackbarPos("Prog (0=auto)", okno)
        if (e, g) != poprz:
            kam.ustaw(e, g)
            kfg["ekspozycja"], kfg["wzmocnienie"] = e, g
            poprz = (e, g)
        ok, img, _ = kam.czytaj()
        if not ok:
            continue
        pl, prog = plamki.znajdz_plamki(img, kfg["prog"], kfg["min_pole"], kfg["max_pole"])
        bg = plamki.tlo(img, pl)
        vis = plamki.rysuj(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), pl)
        kolor = (0, 255, 0) if len(pl) == n_diod else (0, 0, 255)
        cv2.putText(vis, "plamek %d (oczekiwane %d)  prog %d  tlo: sr %.1f, max %d" %
                    (len(pl), n_diod, prog, bg[0], bg[3]), (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, kolor, 1)
        for i, p in enumerate(pl[:6]):
            ost = "  PRZEPALONA" if p["przepalone"] else ""
            cv2.putText(vis, "%d: sr. %.1f px, szczyt %d%s" % (i + 1, p["srednica"], p["szczyt"], ost),
                        (10, 42 + 18 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        (0, 0, 255) if ost else (0, 255, 255), 1)
        cv2.imshow(okno, vis)
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            return False
        if k == ord("s"):
            lok = ustawienia.wczytaj_json(ustawienia.PLIK_LOKALNY)
            lok.update({"ekspozycja": e, "wzmocnienie": g, "prog": kfg["prog"]})
            ustawienia.zapisz_json(ustawienia.PLIK_LOKALNY, lok)
            print("Zapisano ekspozycja=%d, wzmocnienie=%d, prog=%d do konfiguracja_lokalna.json" % (e, g, kfg["prog"]))
        if k == ord(" "):
            cv2.destroyWindow(okno)
            return True


def dryf_px_na_min(t, v):
    if len(t) < 3:
        return 0.0
    a = np.polyfit(t - t[0], v, 1)[0]
    return a * 60.0


def main():
    p = ustawienia.parser(__doc__)
    p.add_argument("--diody", type=int, default=1, help="ile diod jest w kadrze")
    p.add_argument("--czas", type=float, default=30, help="czas pomiaru [s]")
    p.add_argument("--odleglosc", type=float, help="odległość diod od kamery [m] (miarką)")
    p.add_argument("--rozstaw", type=float, help="odległość między 2 diodami [mm] (suwmiarką)")
    args = p.parse_args()
    kfg = ustawienia.polacz(args)
    kam = kamery.otworz_jedna(kfg, args.kamera)

    if not kfg["bez_okna"]:
        if not ustawianie(kam, kfg, args.diody):
            kam.zamknij()
            return

    # punkty odniesienia: N najsilniejszych plamek z pierwszych klatek
    odn = None
    for _ in range(60):
        ok, img, _ = kam.czytaj()
        if not ok:
            continue
        pl, _ = plamki.znajdz_plamki(img, kfg["prog"], kfg["min_pole"], kfg["max_pole"])
        if len(pl) >= args.diody:
            odn = sorted([(q["x"], q["y"]) for q in pl[:args.diody]])
            break
    if odn is None:
        kam.zamknij()
        raise SystemExit("Nie widać %d plamek. Sprawdź diody, próg i ekspozycję (uruchom z podglądem)." % args.diody)

    wyn = Wyniki("t2_plamka", kfg)
    zapisz = wyn.csv("plamki.csv", ["t_s", "dioda", "x", "y", "pole", "srednica", "szczyt",
                                    "przepalone", "plamek_w_klatce", "tlo_sr", "tlo_std"])
    print("Pomiar %d s, nie ruszaj diod ani kamery..." % args.czas)
    dane = [[] for _ in odn]
    klatek, falszywe_klatki, falszywe_plamki = 0, 0, 0
    tla = []
    t0 = time.monotonic()
    okno = "Test 2 - pomiar"
    while time.monotonic() - t0 < args.czas:
        ok, img, t = kam.czytaj()
        if not ok:
            continue
        klatek += 1
        pl, prog = plamki.znajdz_plamki(img, kfg["prog"], kfg["min_pole"], kfg["max_pole"])
        bg = plamki.tlo(img, pl)
        tla.append(bg)
        przyp = plamki.przypisz(odn, pl, bramka=8.0)
        nadmiar = len(pl) - sum(q is not None for q in przyp)
        if nadmiar > 0:
            falszywe_klatki += 1
            falszywe_plamki += nadmiar
        for i, q in enumerate(przyp):
            if q is None:
                continue
            dane[i].append((t, q["x"], q["y"], q["srednica"], q["szczyt"], q["przepalone"]))
            zapisz(["%.6f" % t, i + 1, "%.4f" % q["x"], "%.4f" % q["y"], q["pole"], "%.2f" % q["srednica"],
                    q["szczyt"], q["przepalone"], len(pl), "%.2f" % bg[0], "%.2f" % bg[1]])
        if not kfg["bez_okna"] and klatek % 4 == 0:
            vis = plamki.rysuj(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), przyp)
            cv2.putText(vis, "POMIAR %.0f / %.0f s" % (time.monotonic() - t0, args.czas), (10, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            cv2.imshow(okno, vis)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    kam.zamknij()
    if not kfg["bez_okna"]:
        cv2.destroyAllWindows()

    f, skad_f = ustawienia.ogniskowa(kfg, kam.nazwa)
    bg = np.array(tla)
    bg_sr, bg_std = float(bg[:, 0].mean()), float(bg[:, 1].mean())
    wyn.wypisz("Kamera %s (%s), %dx%d @ %d, ekspozycja %d, wzmocnienie %d, próg %s" %
               (kam.nazwa, kam.zrodlo, kfg["szerokosc"], kfg["wysokosc"], kfg["fps"],
                kfg["ekspozycja"], kfg["wzmocnienie"], kfg["prog"] or "auto"))
    wyn.wypisz("Klatek: %d w %.1f s. Tło: średnia %.1f, odch. std %.2f, max %d" %
               (klatek, time.monotonic() - t0, bg_sr, bg_std, int(bg[:, 3].max())))
    if args.odleglosc:
        wyn.wypisz("Odległość %.2f m, ogniskowa do przeliczeń f = %.0f px (%s): 1 px = %.2f mm" %
                   (args.odleglosc, f, skad_f, args.odleglosc * 1000 / f))
    liczby = {"klatek": klatek, "tlo_sr": bg_sr, "tlo_std": bg_std, "diody": []}
    ok_all = True
    wyn.wypisz("\nDioda | wykryta |  σx [px] |  σy [px] |  σ [px] | dryf x/y [px/min] | średnica | szczyt | przepalone | SNR")
    for i, d in enumerate(dane):
        if len(d) < 10:
            wyn.wypisz("%5d | za mało klatek (%d)" % (i + 1, len(d)))
            ok_all = False
            continue
        a = np.array(d)
        sx, sy = a[:, 1].std(), a[:, 2].std()
        s = math.sqrt((sx ** 2 + sy ** 2) / 2)
        wykr = 100.0 * len(d) / klatek
        dx, dy = dryf_px_na_min(a[:, 0], a[:, 1]), dryf_px_na_min(a[:, 0], a[:, 2])
        snr = (a[:, 4].mean() - bg_sr) / max(bg_std, 1e-6)
        przep = float((a[:, 5] > 0).mean() * 100)
        ok = s < 0.2 and wykr >= 99.5
        ok_all &= ok
        wyn.wypisz("%5d | %6.1f%% | %8.3f | %8.3f | %7.3f | %+7.3f / %+7.3f | %5.1f px | %6.0f | %6.0f%% kl. | %.0f" %
                   (i + 1, wykr, sx, sy, s, dx, dy, a[:, 3].mean(), a[:, 4].mean(), przep, snr))
        rek = {"wykrywalnosc_proc": wykr, "sigma_x_px": sx, "sigma_y_px": sy, "sigma_px": s,
               "dryf_x_px_min": dx, "dryf_y_px_min": dy, "srednica_px": a[:, 3].mean(),
               "szczyt": a[:, 4].mean(), "przepalone_klatki_proc": przep, "snr": snr,
               "x_sr": a[:, 1].mean(), "y_sr": a[:, 2].mean()}
        if args.odleglosc:
            rek["sigma_mm"] = s * args.odleglosc * 1000 / f
            wyn.wypisz("        σ na odległości %.2f m: %.2f mm" % (args.odleglosc, rek["sigma_mm"]))
        if przep > 0:
            wyn.wypisz("        UWAGA: plamka przepalona - zmniejsz ekspozycję lub wzmocnienie.")
        liczby["diody"].append(rek)

    if len(liczby["diody"]) >= 2:
        sr = [(r["x_sr"], r["y_sr"]) for r in liczby["diody"]]
        odst = min(math.dist(sr[i], sr[j]) for i in range(len(sr)) for j in range(i + 1, len(sr)))
        sred = max(r["srednica_px"] for r in liczby["diody"])
        liczby["min_odstep_px"] = odst
        wyn.wypisz("\nNajmniejszy odstęp plamek: %.1f px (zalecane > 2 x średnica = %.1f px) -> %s" %
                   (odst, 2 * sred, "OK" if odst > 2 * sred else "ZA BLISKO, plamki mogą się zlewać"))
        if len(sr) == 2 and args.odleglosc and args.rozstaw:
            f_pom = odst * args.odleglosc * 1000 / args.rozstaw
            liczby["f_z_pomiaru_px"] = f_pom
            nom = {k: v * kfg["szerokosc"] / 640 for k, v in kfg["ogniskowa_nominalna_px"].items()}
            blizej = min(nom, key=lambda k: abs(nom[k] - f_pom))
            wyn.wypisz("Ogniskowa z pomiaru: f = %.1f px · %.0f mm / %.1f mm = %.0f px" %
                       (odst, args.odleglosc * 1000, args.rozstaw, f_pom))
            wyn.wypisz("   nominalnie: %s -> najbliżej pozycji obiektywu %s° (różnica %.0f%%)" %
                       (", ".join("%s° = %.0f px" % kv for kv in nom.items()), blizej,
                        100 * (f_pom - nom[blizej]) / nom[blizej]))
            wyn.wypisz("   (diody muszą być ustawione prostopadle do osi kamery, inaczej odstęp maleje)")

    liczby["falszywe_klatki"] = falszywe_klatki
    liczby["falszywe_plamki"] = falszywe_plamki
    wyn.wypisz("\nFałszywe plamki: %d w %d klatkach" % (falszywe_plamki, falszywe_klatki))
    ok_all &= falszywe_plamki == 0
    wyn.wypisz("Kryterium: σ < 0,2 px, wykrywalność >= 99,5%, brak fałszywych plamek.")
    wyn.wypisz("Wynik: %s" % ocena(ok_all))
    liczby["zaliczony"] = bool(ok_all)
    wyn.zakoncz(liczby)


if __name__ == "__main__":
    main()
