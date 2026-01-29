import cv2
import time
import numpy as np
import os

# Wymuszenie X11 dla OpenCV, aby uniknąć ostrzeżeń Wayland
os.environ["QT_QPA_PLATFORM"] = "xcb"

def ir_led_tracker(width=640, height=480, fps=60):
    print("Szukanie kamer PS3 Eye...")
    
    caps = []
    # Szukamy kamer w zakresie od 0 do 12
    for idx in range(0, 13):
        if len(caps) >= 3:
            break
            
        cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
        if cap.isOpened():
            # Sprawdzamy czy to nie jest urządzenie metadanych (częste w PS3 Eye)
            ret, frame = cap.read()
            if ret:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                cap.set(cv2.CAP_PROP_FPS, fps)
                caps.append((idx, cap))
                print(f"Znaleziono i otwarto kamerę na indeksie {idx}")
            else:
                cap.release()
        else:
            cap.release()

    if not caps:
        print(f"BŁĄD: Nie znaleziono żadnej kamery zewnętrznej.")
        return False
    
    if len(caps) < 3:
        print(f"OSTRZEŻENIE: Znaleziono tylko {len(caps)} kamery.")

    # Okno z suwakami do parametrów (wspólne dla wszystkich kamer)
    cv2.namedWindow('Parametry')
    cv2.createTrackbar('Prog Jasnosci', 'Parametry', 200, 255, lambda x: None)
    cv2.createTrackbar('Min Wielkosc', 'Parametry', 2, 50, lambda x: None)

    print("Tracker uruchomiony. Nacisnij 'q', aby zamknąć.")
    
    prev_time = time.time()
    while True:
        # Obliczanie globalnego FPS dla pętli
        curr_time = time.time()
        dt = curr_time - prev_time
        prev_time = curr_time
        fps_val = 1.0 / dt if dt > 0 else 0

        threshold_val = cv2.getTrackbarPos('Prog Jasnosci', 'Parametry')
        min_area = cv2.getTrackbarPos('Min Wielkosc', 'Parametry')
        
        frames_to_display = []
        
        for idx, cap in caps:
            ret, frame = cap.read()
            if not ret:
                # Jeśli klatka nie została odczytana, dodaj czarny obraz jako placeholder
                frame = np.zeros((height, width, 3), dtype=np.uint8)
                cv2.putText(frame, f"Brak sygnalu (Cam {idx})", (10, height // 2), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            else:
                # 1. Konwersja na odcienie szarości
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                # 2. Progowanie (izolacja najjaśniejszych punktów)
                _, thresh = cv2.threshold(gray, threshold_val, 255, cv2.THRESH_BINARY)

                # 3. Znajdowanie konturów (blobów)
                contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                # 4. Analiza i filtrowanie punktów
                detected_leds = []
                for cnt in contours:
                    area = cv2.contourArea(cnt)
                    if area >= min_area:
                        M = cv2.moments(cnt)
                        if M["m00"] != 0:
                            cX = int(M["m10"] / M["m00"])
                            cY = int(M["m01"] / M["m00"])
                            detected_leds.append({"pos": (cX, cY), "area": area})

                # Sortowanie po wielkości (największe diody na początku) i wybór 3 najlepszych
                detected_leds = sorted(detected_leds, key=lambda x: x['area'], reverse=True)[:3]

                # 5. Rysowanie wybranych punktów
                for i, led in enumerate(detected_leds):
                    cX, cY = led["pos"]
                    # Różne kolory dla 3 diod, aby je odróżnić
                    color = [(0, 0, 255), (0, 255, 0), (255, 0, 0)][i]
                    cv2.circle(frame, (cX, cY), 5, color, -1)
                    cv2.putText(frame, f"L{i+1}:({cX},{cY})", (cX + 10, cY - 10), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)

                # Wyświetlanie informacji o kamerze i liczbie diod
                cv2.putText(frame, f"Kamera {idx} | Diod: {len(detected_leds)}/3", (10, height - 10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

                # Wyświetlanie FPS (globalny dla pętli)
                cv2.putText(frame, f"FPS: {int(fps_val)}", (10, 25), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            frames_to_display.append(frame)

        # Połączenie wszystkich obrazów poziomo w jedno okno
        if frames_to_display:
            combined_frame = np.hstack(frames_to_display)
            cv2.imshow('Multi-Camera IR Tracker', combined_frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    for idx, cap in caps:
        cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    ir_led_tracker(width=640, height=480, fps=60)
