import cv2
import time
import os
import glob

# Wymuszenie X11 dla OpenCV, aby uniknąć ostrzeżeń Wayland
os.environ["QT_QPA_PLATFORM"] = "xcb"

def find_available_cameras():
    """Skanuje porty video i zwraca listę dostępnych kamer (indeks, ścieżka)."""
    available_cameras = []
    
    # 1. Skanowanie po ścieżkach /dev/video*
    paths = sorted(glob.glob("/dev/video*"))
    for path in paths:
        try:
            # Wyciągnij numer z nazwy (np. /dev/video0 -> 0)
            idx = int(path.replace("/dev/video", ""))
            
            # Próba otwarcia
            cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    available_cameras.append((idx, path))
                cap.release()
        except Exception:
            pass
            
    return available_cameras

def test_cameras(width=320, height=240, fps=125):
    print("--- SKANOWANIE KAMER ---")
    cameras = find_available_cameras()
    
    if not cameras:
        print("BŁĄD: Nie znaleziono żadnych kamer.")
        return

    print(f"Znaleziono {len(cameras)} działających kamer:")
    for idx, path in cameras:
        print(f"  - Indeks {idx}: {path}")

    # Otwieramy wszystkie znalezione kamery
    caps = []
    for idx, path in cameras:
        print(f"\nInicjalizacja kamery {idx} ({width}x{height} @ {fps} FPS)...")
        cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
        if cap.isOpened():
            # Próba ustawienia formatu MJPG (kompresja sprzętowa) - kluczowe dla wielu kamer!
            # PS3 Eye wspiera YUYV (nieskompresowany) i czasami MJPG (zależnie od sterownika)
            # Ale przy 640x480@60 YUYV zatyka USB.
            # Jeśli sterownik ov534 nie wspiera MJPG, musimy zmniejszyć FPS/rozdzielczość.
            
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_FPS, fps)
            
            # Wymuszenie pobrania klatki, żeby sprawdzić czy działa
            ret, _ = cap.read()
            if ret:
                caps.append((idx, cap))
                print(f"  [OK] Kamera {idx} otwarta.")
            else:
                print(f"  [!] Kamera {idx} otwarta, ale brak obrazu (Bandwidth issue?). Zamykanie.")
                cap.release()
        else:
            print(f"  [!] Nie udało się otworzyć kamery {idx}")

    if not caps:
        return

    print("\n--- TEST ROZPOCZĘTY ---")
    print("Naciśnij 'q', aby zakończyć.")

    # Utwórz okno wcześniej, aby dodać suwaki
    cv2.namedWindow('Multi-Camera Test', cv2.WINDOW_NORMAL)

    def update_cam_params(x=None):
        """Callback do aktualizacji parametrów kamer"""
        exp = cv2.getTrackbarPos('Exposure', 'Multi-Camera Test')
        gain = cv2.getTrackbarPos('Gain', 'Multi-Camera Test')
        
        for idx_c, _ in caps:
            # Używamy v4l2-ctl dla pewności (OpenCV czasem nie ogarnia flag PS3 Eye)
            # auto_exposure: 1 = Manual Mode
            os.system(f"v4l2-ctl -d /dev/video{idx_c} --set-ctrl=auto_exposure=1 > /dev/null 2>&1")
            os.system(f"v4l2-ctl -d /dev/video{idx_c} --set-ctrl=exposure={exp} > /dev/null 2>&1")
            # gain_automatic: 0 = Manual
            os.system(f"v4l2-ctl -d /dev/video{idx_c} --set-ctrl=gain_automatic=0 > /dev/null 2>&1")
            os.system(f"v4l2-ctl -d /dev/video{idx_c} --set-ctrl=gain={gain} > /dev/null 2>&1")

    # Dodaj suwaki
    cv2.createTrackbar('Exposure', 'Multi-Camera Test', 20, 255, update_cam_params)
    cv2.createTrackbar('Gain', 'Multi-Camera Test', 10, 63, update_cam_params)
    
    # Wywołaj raz, aby ustawić wartości początkowe
    update_cam_params()

    prev_time = time.time()
    
    while True:
        # Obliczanie FPS
        curr_time = time.time()
        dt = curr_time - prev_time
        prev_time = curr_time
        fps_real = 1.0 / dt if dt > 0 else 0

        frames_to_display = []
        
        for idx, cap in caps:
            ret, frame = cap.read()
            if ret:
                # Dodaj info na obrazie
                cv2.putText(frame, f"Cam {idx}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                cv2.putText(frame, f"{int(fps_real)} FPS", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                frames_to_display.append(frame)
            else:
                # Placeholder gdy błąd odczytu
                import numpy as np
                blank = np.zeros((height, width, 3), dtype=np.uint8)
                cv2.putText(blank, f"Cam {idx} ERROR", (10, height//2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
                frames_to_display.append(blank)

        # Łączenie obrazów
        if frames_to_display:
            import numpy as np
            # Jeśli mamy dużo kamer, układamy je w rzędzie (proste podejście)
            combined = np.hstack(frames_to_display)
            
            # Skalowanie okna, żeby było nieco większe (1.5x) ale mieściło się na ekranie
            scale_factor = 1.0
            if combined.shape[1] > 0:
                # Opcjonalnie powiększamy podgląd
                new_w = int(combined.shape[1] * scale_factor)
                new_h = int(combined.shape[0] * scale_factor)
                # combined = cv2.resize(combined, (new_w, new_h))
            
            cv2.namedWindow('Multi-Camera Test', cv2.WINDOW_NORMAL)
            cv2.imshow('Multi-Camera Test', combined)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Sprzątanie
    for _, cap in caps:
        cap.release()
    cv2.destroyAllWindows()
    print("Test zakończony.")

if __name__ == "__main__":
    # Domyślnie tryb wysokiej rozdzielczości (60 FPS)
    # Zmieniono na 640x480 @ 30 FPS aby zmaksymalizować jakość przy mniejszym obciążeniu USB
    # test_cameras(width=320, height=240, fps=120)
    test_cameras(width=640, height=480, fps=30)

