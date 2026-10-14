"""Zapis surowych danych i podsumowań testów.

Każde uruchomienie testu tworzy folder testy/wyniki/<test>_<data>_<godzina>/ z:
  - plikami CSV z surowymi danymi (do przeliczenia później),
  - podsumowanie.json (liczby + ustawienia, z którymi test był robiony),
  - podsumowanie.txt (to samo, co test wypisał na ekran).
"""

import csv
import datetime
import json
import os
import platform

from ustawienia import KATALOG

KATALOG_WYNIKOW = os.path.join(KATALOG, "wyniki")


class Wyniki:
    def __init__(self, nazwa_testu, kfg):
        znacznik = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.folder = os.path.join(KATALOG_WYNIKOW, "%s_%s" % (nazwa_testu, znacznik))
        os.makedirs(self.folder, exist_ok=True)
        self.kfg = kfg
        self.linie = []
        self._pliki = {}

    def csv(self, nazwa, naglowek):
        """Zwraca funkcję dopisującą wiersz do pliku CSV."""
        sciezka = os.path.join(self.folder, nazwa)
        f = open(sciezka, "w", newline="", encoding="utf-8")
        w = csv.writer(f)
        w.writerow(naglowek)
        self._pliki[nazwa] = f
        return w.writerow

    def wypisz(self, tekst=""):
        print(tekst)
        self.linie.append(tekst)

    def zakoncz(self, liczby):
        for f in self._pliki.values():
            f.close()
        dane = {
            "wyniki": liczby,
            "ustawienia": self.kfg,
            "system": platform.platform(),
            "czas": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        with open(os.path.join(self.folder, "podsumowanie.json"), "w", encoding="utf-8") as f:
            json.dump(dane, f, indent=4, ensure_ascii=False, default=float)
        with open(os.path.join(self.folder, "podsumowanie.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(self.linie) + "\n")
        print("\nZapisano w: %s" % self.folder)


def ocena(warunek):
    return "ZALICZONY" if warunek else "NIE ZALICZONY"
