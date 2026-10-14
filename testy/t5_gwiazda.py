#!/usr/bin/env python3
"""TEST 5: gwiazda 4 diod widziana jedną kamerą (pierwszy test znacznika, kroki 4.1-4.2 planu).

Nie potrzebuje jeszcze kalibracji zewnętrznej ani drugiej kamery. Dla każdej klatki:
  1. wykrywa 4 plamki,
  2. dla każdego z 24 przypisań plamka -> dioda liczy pozę gwiazdy (solvePnP, metoda IPPE
     dla punktów w jednej płaszczyźnie) i błąd reprojekcji,
  3. najlepsze przypisanie = rozpoznanie diod; zapas = błąd drugiego najlepszego / błąd najlepszego.
Mierzy: jak często widać 4 plamki, czy rozpoznanie jest stałe, błąd reprojekcji, zapas,
odległość Z gwiazdy od kamery (porównaj z miarką: --odleglosc) i jej rozrzut.

Rozpoznanie jedną kamerą jest słabsze niż dopasowanie w 3D po triangulacji (tam zapas 9 mm),
bo zależy od dokładności kalibracji wewnętrznej. Jeśli zapas jest mały (< 3), to ważny wniosek:
rozpoznanie trzeba robić w 3D, a nie z jednej kamery.

Model gwiazdy (mm) bierze z konfiguracja.json ("gwiazda_mm", z uchwyt_diod_ir.md).
Ogniskowa i dystorsja z intrinsics.json (test 4); bez kalibracji używa wartości nominalnej.

  python t5_gwiazda.py --kamera 1 --odleglosc 2.0 --czas 20
"""

import itertools
import math
import time

import cv2
import numpy as np

import kamery
import plamki
import ustawienia
from wyniki import Wyniki, ocena

PERMUTACJE = list(itertools.permutations(range(4)))


def model_kamery(kfg, nazwa):
    dane = ustawienia.wczytaj_json(ustawienia.PLIK_INTRINSICS)
    klucz = ustawienia.klucz_intrinsics(nazwa, kfg)
    if klucz in dane:
        return np.array(dane[klucz]["K"]), np.array(dane[klucz]["dist"]), "kalibracja " + klucz
    f, skad = ustawienia.ogniskowa(kfg, nazwa)
    K = np.array([[f, 0, kfg["szerokosc"] / 2], [0, f, kfg["wysokosc"] / 2], [0, 0, 1.0]])
    return K, np.zeros(5), skad + ", bez dystorsji"


def rozpoznaj(model, pkt_n):
    """pkt_n: 4 punkty znormalizowane (po usunięciu dystorsji, K = I).

    Zwraca listę (błąd_rms_w_jedn_znorm, permutacja, rvec, tvec) posortowaną rosnąco.
    permutacja[i] = numer diody modelu dla i-tej plamki.
    """
    wyniki = []
    for perm in PERMUTACJE:
        obj = model[list(perm)]
        n, rvs, tvs, bl = cv2.solvePnPGeneric(obj, pkt_n, np.eye(3), None, flags=cv2.SOLVEPNP_IPPE)
        for k in range(n):
            if tvs[k][2, 0] <= 0:
                continue
            proj, _ = cv2.projectPoints(obj, rvs[k], tvs[k], np.eye(3), None)
            e = math.sqrt(((proj.reshape(-1, 2) - pkt_n.reshape(-1, 2)) ** 2).sum(1).mean())
            wyniki.append((e, perm, rvs[k], tvs[k]))
    wyniki.sort(key=lambda w: w[0])
    return wyniki


def katy_eulera(rvec):
    R, _ = cv2.Rodrigues(rvec)
    roll = math.degrees(math.atan2(R[2, 1], R[2, 2]))
    pitch = math.degrees(math.asin(-max(-1, min(1, R[2, 0]))))
    yaw = math.degrees(math.atan2(R[1, 0], R[0, 0]))
    return roll, pitch, yaw


def main():
    p = ustawienia.parser(__doc__)
    p.add_argument("--czas", type=float, default=20, help="czas pomiaru [s]")
    p.add_argument("--odleglosc", type=float, help="zmierzona miarką odległość środka gwiazdy [m]")
    args = p.parse_args()
    kfg = ustawienia.polacz(args)
    model = np.array(kfg["gwiazda_mm"], dtype=np.float64)
    kam = kamery.otworz_jedna(kfg, args.kamera)
    K, dist, skad = model_kamery(kfg, kam.nazwa)
    f = K[0, 0]

    wyn = Wyniki("t5_gwiazda", kfg)
    zapisz = wyn.csv("gwiazda.csv", ["t_s", "plamek", "perm", "blad_px", "blad2_px", "zapas",
                                     "x_mm", "y_mm", "z_mm", "roll", "pitch", "yaw"])
    klatek, z4 = 0, 0
    rek = []
    t0 = time.monotonic()
    while time.monotonic() - t0 < args.czas:
        ok, img, t = kam.czytaj()
        if not ok:
            continue
        klatek += 1
        pl, _ = plamki.znajdz_plamki(img, kfg["prog"], kfg["min_pole"], kfg["max_pole"])
        vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if not kfg["bez_okna"] else None
        if len(pl) >= 4:
            z4 += 1
            # kolejność plamek od lewej do prawej, żeby przy nieruchomej gwieździe
            # ta sama dioda miała w każdej klatce ten sam numer plamki
            pl = sorted(pl[:4], key=lambda q: (q["x"], q["y"]))
            pkt = np.array([[q["x"], q["y"]] for q in pl], np.float64).reshape(-1, 1, 2)
            pkt_n = cv2.undistortPoints(pkt, K, dist)
            w = rozpoznaj(model, pkt_n)
            if w:
                e1 = w[0][0] * f
                # drugie najlepsze inne przypisanie (nie ta sama permutacja z drugim rozwiązaniem IPPE)
                e2 = next((x[0] * f for x in w[1:] if x[1] != w[0][1]), float("inf"))
                perm, rv, tv = w[0][1], w[0][2], w[0][3]
                r, pt, yw = katy_eulera(rv)
                rek.append((t, perm, e1, e2, tv.ravel(), (r, pt, yw)))
                zapisz(["%.6f" % t, len(pl), "".join(str(i + 1) for i in perm), "%.4f" % e1, "%.4f" % e2,
                        "%.2f" % (e2 / max(e1, 1e-9)), *("%.2f" % v for v in tv.ravel()),
                        "%.2f" % r, "%.2f" % pt, "%.2f" % yw])
                if vis is not None:
                    for i, q in enumerate(pl):
                        cv2.putText(vis, "D%d" % (perm[i] + 1), (int(q["x"]) + 6, int(q["y"]) - 6),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                    cv2.putText(vis, "Z = %.0f mm  blad %.2f px  zapas %.1f" % (tv[2, 0], e1, e2 / max(e1, 1e-9)),
                                (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        if vis is not None:
            plamki.rysuj(vis, pl, podpisy=False)
            cv2.imshow("Test 5 - gwiazda (q = koniec)", vis)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    kam.zamknij()
    if not kfg["bez_okna"]:
        cv2.destroyAllWindows()

    wyn.wypisz("Kamera %s, model kamery: f = %.0f px (%s)" % (kam.nazwa, f, skad))
    wyn.wypisz("Klatek: %d, z 4 plamkami: %d (%.1f%%)" % (klatek, z4, 100.0 * z4 / max(klatek, 1)))
    if not rek:
        wyn.wypisz("Brak klatek z 4 plamkami - sprawdź diody, próg (test 2) i czy gwiazda jest cała w kadrze.")
        wyn.zakoncz({"klatek": klatek, "z4": 0, "zaliczony": False})
        return
    perms = ["".join(str(i + 1) for i in r[1]) for r in rek]
    najcz = max(set(perms), key=perms.count)
    stalosc = 100.0 * perms.count(najcz) / len(perms)
    e1 = np.array([r[2] for r in rek])
    e2 = np.array([r[3] for r in rek])
    zapas = e2 / np.maximum(e1, 1e-9)
    tv = np.array([r[4] for r in rek])
    ang = np.array([r[5] for r in rek])
    zmed = float(np.median(tv[:, 2]))
    wyn.wypisz("Rozpoznanie (plamki od lewej -> numer diody): %s w %.1f%% klatek" % (najcz, stalosc))
    wyn.wypisz("Błąd reprojekcji najlepszego przypisania: mediana %.3f px, max %.3f px" % (np.median(e1), e1.max()))
    wyn.wypisz("Drugie najlepsze przypisanie: mediana %.2f px -> zapas (błąd 2. / błąd 1.) mediana %.1f, min %.1f" %
               (np.median(e2), np.median(zapas), zapas.min()))
    wyn.wypisz("Poza: Z = %.1f mm (σ %.2f mm), X σ %.2f mm, Y σ %.2f mm; roll/pitch/yaw = %.1f / %.1f / %.1f° (σ %.2f / %.2f / %.2f°)" %
               (zmed, tv[:, 2].std(), tv[:, 0].std(), tv[:, 1].std(), *ang.mean(0), *ang.std(0)))
    pkt_min = min(np.linalg.norm(model[i] - model[j]) for i in range(4) for j in range(i + 1, 4))
    wyn.wypisz("Najbliższe diody (%.1f mm) na tej odległości: %.1f px od siebie" % (pkt_min, pkt_min * f / zmed))
    liczby = {"klatek": klatek, "z4_proc": 100.0 * z4 / max(klatek, 1), "rozpoznanie": najcz,
              "stalosc_proc": stalosc, "blad_px_med": float(np.median(e1)), "zapas_med": float(np.median(zapas)),
              "zapas_min": float(zapas.min()), "z_mm_med": zmed, "z_sigma_mm": float(tv[:, 2].std())}
    if args.odleglosc:
        roz = zmed - args.odleglosc * 1000
        liczby["z_roznica_mm"] = roz
        wyn.wypisz("Z z kamery %.0f mm, z miarki %.0f mm: różnica %+.0f mm (%+.1f%%)%s" %
                   (zmed, args.odleglosc * 1000, roz, 100 * roz / (args.odleglosc * 1000),
                    " -> błąd skali sugeruje złą ogniskową" if abs(roz) > 0.05 * args.odleglosc * 1000 else ""))
    ok = stalosc >= 99 and np.median(e1) < 1.0 and np.median(zapas) >= 3
    kryt = "Kryterium: rozpoznanie stałe >= 99%, błąd < 1 px, zapas >= 3"
    if args.odleglosc:
        ok &= abs(liczby["z_roznica_mm"]) < 0.05 * args.odleglosc * 1000
        kryt += ", Z zgodne z miarką do 5%"
    liczby["zaliczony"] = bool(ok)
    wyn.wypisz(kryt + ".")
    wyn.wypisz("Wynik: %s" % ocena(ok))
    wyn.zakoncz(liczby)


if __name__ == "__main__":
    main()
