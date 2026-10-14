"""Sztuczna kamera do sprawdzania testów bez sprzętu (--zrodlo symulacja).

Generuje obraz w skali szarości z plamkami o profilu Gaussa, szumem odczytu
i zaokrągleniem do 8 bitów, tak jak z prawdziwej matrycy. Sceny:
  - "plamki": N diod w stałych miejscach (domyślnie),
  - "gwiazda": gwiazda 4 diod z konfiguracji, rzutowana z kamery o ogniskowej f,
  - "szachownica": szachownica w losowych pozach (do testu kalibracji).
Ustawia się je zmiennymi środowiskowymi, żeby nie mnożyć argumentów w testach:
  SYM_SCENA=plamki|gwiazda|szachownica, SYM_DIODY=2, SYM_ODLEGLOSC_M=2.0, SYM_F=521
"""

import os
import time

import cv2
import numpy as np


def plamka(obraz, x, y, amplituda, sigma):
    r = int(4 * sigma + 2)
    x0, y0 = int(x) - r, int(y) - r
    yy, xx = np.mgrid[y0:y0 + 2 * r + 1, x0:x0 + 2 * r + 1]
    g = amplituda * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma ** 2))
    h, w = obraz.shape
    xa, ya, xb, yb = max(0, x0), max(0, y0), min(w, x0 + 2 * r + 1), min(h, y0 + 2 * r + 1)
    if xa < xb and ya < yb:
        obraz[ya:yb, xa:xb] += g[ya - y0:yb - y0, xa - x0:xb - x0]


def macierz_K(f, w, h):
    return np.array([[f, 0, w / 2.0], [0, f, h / 2.0], [0, 0, 1.0]])


def rzut_gwiazdy(gwiazda_mm, f, w, h, odleglosc_m, obrot_deg=(20, -10, 30)):
    """Rzut punktów gwiazdy (mm) na obraz; gwiazda w odległości odleglosc_m przed kamerą."""
    rvec = np.radians(np.array(obrot_deg, float)).reshape(3, 1)
    tvec = np.array([[0.0], [0.0], [odleglosc_m * 1000.0]])
    pts, _ = cv2.projectPoints(np.array(gwiazda_mm, float), rvec, tvec, macierz_K(f, w, h), None)
    return pts.reshape(-1, 2)


class SymKamera:
    def __init__(self, nr, szerokosc, wysokosc, fps, kfg=None):
        self.nr = nr
        self.w, self.h, self.fps = szerokosc, wysokosc, fps
        self.kfg = kfg or {}
        self.ekspozycja, self.wzmocnienie = 40, 10
        self.scena = os.environ.get("SYM_SCENA", "plamki")
        self.rng = np.random.default_rng(1000 + nr)
        self.t_nast = time.monotonic()
        self.k = 0
        n = int(os.environ.get("SYM_DIODY", "1"))
        self.diody = [(self.w / 2 + 60 * (i - (n - 1) / 2), self.h / 2 + 10 * i) for i in range(n)]
        if self.scena == "gwiazda":
            f = float(os.environ.get("SYM_F", "521")) * self.w / 640.0
            z = float(os.environ.get("SYM_ODLEGLOSC_M", "2.0"))
            self.diody = [tuple(p) for p in rzut_gwiazdy(self.kfg["gwiazda_mm"], f, self.w, self.h, z)]
        if self.scena == "szachownica":
            self._przygotuj_szachownice()

    # --- interfejs jak w kamery.py ---
    def ustaw(self, ekspozycja=None, wzmocnienie=None):
        if ekspozycja is not None:
            self.ekspozycja = ekspozycja
        if wzmocnienie is not None:
            self.wzmocnienie = wzmocnienie

    def czytaj(self):
        # tempo klatek z drobnym rozrzutem i rzadkimi zgubionymi klatkami
        okres = 1.0 / self.fps
        self.t_nast += okres
        if self.rng.random() < 0.003:
            self.t_nast += okres
        teraz = time.monotonic()
        if self.t_nast > teraz:
            time.sleep(self.t_nast - teraz)
        else:
            self.t_nast = teraz
        self.k += 1
        t = time.monotonic() + self.rng.normal(0, 0.0004)
        if self.scena == "szachownica":
            return True, self._klatka_szachownicy(), t
        return True, self._klatka_plamek(), t

    def zamknij(self):
        pass

    # --- sceny ---
    def _klatka_plamek(self):
        img = self.rng.normal(6.0, 2.0, (self.h, self.w))
        jasnosc = min(1.0, self.ekspozycja / 40.0) * (1 + self.wzmocnienie / 20.0)
        for (x, y) in self.diody:
            # drobne drganie środka (szum matrycy, drgania powietrza), ok. 0,03 px
            dx, dy = self.rng.normal(0, 0.03, 2)
            plamka(img, x + dx, y + dy, 150 * jasnosc, 1.6)
        return np.clip(np.round(img), 0, 255).astype(np.uint8)

    def _przygotuj_szachownice(self):
        kol, wier = self.kfg.get("szachownica_rogi", [9, 6])
        bok = 40
        plansza = np.full(((wier + 3) * bok, (kol + 3) * bok), 230, np.uint8)
        for r in range(wier + 1):
            for c in range(kol + 1):
                if (r + c) % 2 == 0:
                    y, x = (r + 1) * bok, (c + 1) * bok
                    plansza[y:y + bok, x:x + bok] = 25
        self.plansza = plansza
        self.bok_planszy = bok
        f = float(os.environ.get("SYM_F", "521")) * self.w / 640.0
        self.K = macierz_K(f, self.w, self.h)
        self.dist = np.array([-0.12, 0.08, 0.0, 0.0, 0.0])
        # obraz z dystorsją w pikselu p = obraz idealny w punkcie undistort(p)
        yy, xx = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
        siatka = np.stack([xx.ravel(), yy.ravel()], axis=1).reshape(-1, 1, 2)
        idealne = cv2.undistortPoints(siatka, self.K, self.dist, P=self.K).reshape(self.h, self.w, 2)
        self.mapa = (idealne[..., 0].astype(np.float32), idealne[..., 1].astype(np.float32))

    def _klatka_szachownicy(self):
        # nowa poza co ~1,5 s, żeby test kalibracji mógł zebrać różne ujęcia
        nr_pozy = self.k // int(self.fps * float(os.environ.get("SYM_ZMIANA_S", "1.5")))
        rng = np.random.default_rng(nr_pozy)
        mm = self.kfg.get("szachownica_kwadrat_mm", 29.0)
        skala = mm / self.bok_planszy
        hp, wp = self.plansza.shape
        rvec = np.radians([rng.uniform(-30, 30), rng.uniform(-30, 30), rng.uniform(-15, 15)])
        z = rng.uniform(450, 900)
        tx = rng.uniform(-0.35, 0.35) * z * self.w / self.K[0, 0] - wp * skala / 2
        ty = rng.uniform(-0.3, 0.3) * z * self.h / self.K[1, 1] - hp * skala / 2
        rogi = np.array([[0, 0, 0], [wp * skala, 0, 0], [wp * skala, hp * skala, 0], [0, hp * skala, 0]], float)
        rogi -= [wp * skala / 2, hp * skala / 2, 0]
        R, _ = cv2.Rodrigues(rvec)
        rogi = rogi @ R.T + [tx + wp * skala / 2, ty + hp * skala / 2, z]
        obraz_rogi = (rogi @ self.K.T)
        obraz_rogi = obraz_rogi[:, :2] / obraz_rogi[:, 2:]
        H = cv2.getPerspectiveTransform(
            np.float32([[0, 0], [wp, 0], [wp, hp], [0, hp]]), np.float32(obraz_rogi))
        idealny = cv2.warpPerspective(self.plansza, H, (self.w, self.h), borderValue=8)
        img = cv2.remap(idealny, self.mapa[0], self.mapa[1], cv2.INTER_LINEAR).astype(np.float64)
        img += self.rng.normal(0, 2.0, img.shape)
        return np.clip(np.round(img), 0, 255).astype(np.uint8)
