import cv2
import time
import numpy as np

def ir_led_tracker(index=2, width=320, height=240, fps=125):
    print(f"Inicjalizacja śledzenia diod IR na indeksie {index}...")
    
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    if not cap.isOpened():
        print(f"BŁĄD: Nie można otworzyć kamery.")
        return False

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)

    # Okno z suwakiem do progu jasności
    cv2.namedWindow('Parametry')
    cv2.createTrackbar('Prog Jasnosci', 'Parametry', 200, 255, lambda x: None)
    # Suwak do minimalnej wielkości diody (powierzchnia w pikselach)
    cv2.createTrackbar('Min Wielkosc', 'Parametry', 2, 50, lambda x: None)

    print("Tracker uruchomiony. Nacisnij 'q', aby zamknąć.")
    
    prev_time = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 1. Konwersja na odcienie szarości
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 2. Pobranie wartości z suwaków
        threshold_val = cv2.getTrackbarPos('Prog Jasnosci', 'Parametry')
        min_area = cv2.getTrackbarPos('Min Wielkosc', 'Parametry')

        # 3. Progowanie (izolacja najjaśniejszych punktów)
        _, thresh = cv2.threshold(gray, threshold_val, 255, cv2.THRESH_BINARY)

        # 4. Znajdowanie konturów (blobów)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        led_positions = []

        # 5. Analiza znalezionych punktów
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area >= min_area:
                # Obliczanie środka masy (momenty)
                M = cv2.moments(cnt)
                if M["m00"] != 0:
                    cX = int(M["m10"] / M["m00"])
                    cY = int(M["m01"] / M["m00"])
                    
                    led_positions.append((cX, cY))
                    
                    # Rysowanie okręgu wokół diody i jej współrzędnych
                    cv2.circle(frame, (cX, cY), 5, (0, 0, 255), -1)
                    cv2.putText(frame, f"({cX},{cY})", (cX + 10, cY - 10), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)

        # Wyświetlanie liczby wykrytych diod
        cv2.putText(frame, f"Wykryto diod: {len(led_positions)}", (10, height - 10), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # Obliczanie i wyświetlanie FPS
        curr_time = time.time()
        fps_display = 1 / (curr_time - prev_time) if prev_time != 0 else 0
        prev_time = curr_time
        cv2.putText(frame, f"FPS: {int(fps_display)}", (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        # Podgląd binarny (co widzi algorytm)
        cv2.imshow('Widok Binarny (Maska)', thresh)
        # Podgląd końcowy
        cv2.imshow('IR LED Tracker', frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    ir_led_tracker(index=2, width=320, height=240, fps=125)

