"""Wykrywanie plamek diod IR na obrazie w skali szarości.

Środek plamki = średnia położeń pikseli ważona (jasność - próg). Odjęcie progu sprawia,
że brzeg plamki (piksele ledwo nad progiem) prawie nie wpływa na wynik, a wynik jest
podpikselowy. To ta sama idea co "peak_threshold" w starym tune_detection.py, ale bez
dwóch dodatkowych parametrów do strojenia.
"""

import math

import cv2
import numpy as np


def prog_automatyczny(gray):
    """Połowa najjaśniejszego piksela, ale nie mniej niż 40."""
    return max(40, int(gray.max()) // 2)


def znajdz_plamki(gray, prog=0, min_pole=2, max_pole=400, maks_liczba=20):
    """Zwraca listę plamek (słowniki) posortowaną od najjaśniejszej sumy.

    Pola plamki:
      x, y       środek ważony jasnością [px]
      pole       liczba pikseli powyżej progu
      srednica   średnica koła o tym samym polu [px]
      szczyt     najjaśniejszy piksel (255 = przepalona)
      przepalone liczba pikseli = 255
      suma       suma (jasność - próg), miara "siły" plamki
    """
    if prog <= 0:
        prog = prog_automatyczny(gray)
    _, bw = cv2.threshold(gray, prog, 255, cv2.THRESH_BINARY)
    n, etykiety, stats, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
    plamki = []
    for i in range(1, n):
        pole = int(stats[i, cv2.CC_STAT_AREA])
        if pole < min_pole or pole > max_pole:
            continue
        x0, y0 = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP]
        w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        roi = gray[y0:y0 + h, x0:x0 + w].astype(np.float64)
        maska = etykiety[y0:y0 + h, x0:x0 + w] == i
        wagi = np.where(maska, roi - prog, 0.0)
        suma = wagi.sum()
        if suma <= 0:
            continue
        yy, xx = np.mgrid[0:h, 0:w]
        plamki.append({
            "x": x0 + (xx * wagi).sum() / suma,
            "y": y0 + (yy * wagi).sum() / suma,
            "pole": pole,
            "srednica": 2 * math.sqrt(pole / math.pi),
            "szczyt": int(roi[maska].max()),
            "przepalone": int((roi[maska] >= 255).sum()),
            "suma": float(suma),
        })
    plamki.sort(key=lambda p: p["suma"], reverse=True)
    return plamki[:maks_liczba], prog


def tlo(gray, plamki, margines=6):
    """Statystyki tła z pominięciem okolic plamek: (średnia, odch. std, 99,9 percentyl, max)."""
    maska = np.ones(gray.shape, bool)
    for p in plamki:
        r = int(p["srednica"] / 2 + margines)
        x, y = int(round(p["x"])), int(round(p["y"]))
        maska[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1] = False
    piks = gray[maska]
    if piks.size == 0:
        return 0.0, 0.0, 0.0, 0
    return float(piks.mean()), float(piks.std()), float(np.percentile(piks, 99.9)), int(piks.max())


def przypisz(punkty_odniesienia, plamki, bramka=8.0):
    """Przypisuje plamki do punktów odniesienia (najbliższa w promieniu bramki).

    Zwraca listę długości len(punkty_odniesienia): plamka albo None.
    Dla kilku diod przy nieruchomym obiekcie to wystarcza (zachłannie po odległości).
    """
    pary = []
    for i, (xr, yr) in enumerate(punkty_odniesienia):
        for j, p in enumerate(plamki):
            d = math.hypot(p["x"] - xr, p["y"] - yr)
            if d <= bramka:
                pary.append((d, i, j))
    pary.sort()
    wynik = [None] * len(punkty_odniesienia)
    uzyte = set()
    for d, i, j in pary:
        if wynik[i] is None and j not in uzyte:
            wynik[i] = plamki[j]
            uzyte.add(j)
    return wynik


def rysuj(obraz_bgr, plamki, kolor=(0, 0, 255), podpisy=True):
    for k, p in enumerate(plamki):
        if p is None:
            continue
        c = (int(round(p["x"])), int(round(p["y"])))
        cv2.circle(obraz_bgr, c, int(p["srednica"] / 2) + 5, kolor, 1)
        if podpisy:
            cv2.putText(obraz_bgr, "%d" % (k + 1), (c[0] + 8, c[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
    return obraz_bgr
