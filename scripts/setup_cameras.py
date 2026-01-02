import cv2
import time
import os
import json
import glob
import sys

CAMERA_MAP_FILE = "camera_map.json"

def get_connected_cameras():
    """Zwraca listę aktywnych urządzeń wideo (rozwiązane ścieżki)"""
    cameras = set()
    for path in glob.glob("/dev/video*"):
        try:
            real_path = os.path.realpath(path)
            # Ignorujmy urządzenia, których nie da się otworzyć (np. metadane)
            if not os.access(real_path, os.R_OK):
                continue
            cameras.add(real_path)
        except:
            pass
    return cameras

def main():
    print("=================================================")
    print("   KREATOR KONFIGURACJI KAMER (LOGICZNE ID)")
    print("=================================================")
    print("Ten skrypt pozwoli Ci przypisać logiczne numery (1, 2, ...)")
    print("do fizycznych kamer, niezależnie od portu USB.")
    print("Używaj tego po zmianie portów lub komputera.")
    print("-------------------------------------------------")
    
    # 1. Poproś o odłączenie wszystkich kamer PS3 Eye
    print("\nKROK 1: Odłącz WSZYSTKIE kamery PS3 Eye od komputera.")
    print("Zostaw tylko wbudowaną kamerę (jeśli masz).")
    input("Naciśnij ENTER, gdy gotowe...")
    
    base_cameras = get_connected_cameras()
    print(f"Wykryto {len(base_cameras)} urządzeń bazowych (np. laptopa).")
    
    mapping = {}
    
    while True:
        cam_num = len(mapping) + 1
        print(f"\nKROK 2: Podłącz kamerę, którą oznaczyłeś numerem {cam_num}.")
        print("(Upewnij się, że podłączasz do portu, który działa!)")
        print("Czekam na wykrycie nowej kamery...")
        
        found_new = None
        # Pętla oczekiwania na nowe urządzenie
        for _ in range(60): # 30 sekund czekania
            current_cameras = get_connected_cameras()
            new_cams = current_cameras - base_cameras
            
            if new_cams:
                # Znaleziono nową!
                found_new = list(new_cams)[0] # Bierzemy pierwszą nową
                # Znajdź jej dev path (np. /dev/video2)
                # Musimy przeszukać /dev/video*, żeby znaleźć to co wskazuje na found_new
                dev_path = None
                for path in glob.glob("/dev/video*"):
                    if os.path.realpath(path) == found_new:
                        dev_path = path
                        break
                
                print(f" [SUKCES] Wykryto nową kamerę: {dev_path}")
                mapping[f"cam_{cam_num}"] = dev_path
                base_cameras.add(found_new) # Dodaj do znanych, żeby szukać kolejnej
                break
            
            time.sleep(0.5)
            
        if not found_new:
            print(" [TIMEOUT] Nie wykryto nowej kamery w ciągu 30 sekund.")
            retry = input("Czy chcesz spróbować ponownie? [t/n]: ").lower()
            if retry != 't':
                break
        else:
            more = input(f"Kamera nr {cam_num} skonfigurowana. Czy chcesz dodać kolejną? [T/n]: ").lower()
            if more == 'n':
                break

    print("\n-------------------------------------------------")
    print("Podsumowanie mapowania:")
    for cid, path in mapping.items():
        print(f"  {cid} -> {path}")
        
    if mapping:
        with open(CAMERA_MAP_FILE, 'w') as f:
            json.dump(mapping, f, indent=4)
        print(f"\nZapisano mapowanie do {CAMERA_MAP_FILE}.")
        print("Możesz teraz uruchomić kalibrację lub tracker.")
    else:
        print("\nNie skonfigurowano żadnych kamer.")

if __name__ == "__main__":
    main()

