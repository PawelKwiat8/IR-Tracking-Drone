#!/usr/bin/env python3
"""Uruchamia wszystkie testy na kamerach symulowanych, żeby sprawdzić instalację bez sprzętu.

  python sprawdz_bez_kamer.py
Każdy test powinien skończyć się "ZALICZONY". Wyniki trafiają do testy/wyniki/ jak zwykle.
"""

import os
import subprocess
import sys

KAT = os.path.dirname(os.path.abspath(__file__))
PROBY = [
    ("Test 1: kamery i FPS", ["t1_kamery.py", "--czas", "3"], {"SYM_KAMERY": "4"}),
    ("Test 2: plamka, 2 diody", ["t2_plamka.py", "--diody", "2", "--czas", "3",
                                 "--odleglosc", "2", "--rozstaw", "233"], {"SYM_DIODY": "2"}),
    ("Test 3: zasięg", ["t3_zasieg.py", "--odleglosc", "2", "--opis", "symulacja", "--czas", "1"], {}),
    ("Test 4: kalibracja", ["t4_kalibracja.py", "--ujec", "20", "--nie-zapisuj"],
     {"SYM_SCENA": "szachownica", "SYM_ZMIANA_S": "0.4"}),
    ("Test 5: gwiazda", ["t5_gwiazda.py", "--czas", "3", "--odleglosc", "2"],
     {"SYM_SCENA": "gwiazda", "SYM_ODLEGLOSC_M": "2"}),
]

wszystko = True
for nazwa, argumenty, srodowisko in PROBY:
    env = dict(os.environ, **srodowisko)
    cmd = [sys.executable, os.path.join(KAT, argumenty[0])] + argumenty[1:] + ["--zrodlo", "symulacja", "--bez-okna"]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=KAT)
    wynik = "ZALICZONY" if ("ZALICZONY" in r.stdout and "NIE ZALICZONY" not in r.stdout) else "BŁĄD"
    wszystko &= wynik == "ZALICZONY"
    print("%-26s %s" % (nazwa, wynik))
    if wynik != "ZALICZONY":
        print(r.stdout[-1500:], r.stderr[-1500:])
print("\nWszystko działa." if wszystko else "\nCoś nie działa - patrz wyżej.")
sys.exit(0 if wszystko else 1)
