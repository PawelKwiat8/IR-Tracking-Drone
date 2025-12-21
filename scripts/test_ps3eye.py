import cv2
import time

def test_camera(index=2, width=320, height=240, fps=125):
    print(f"Próba otwarcia kamery PS3 Eye na indeksie {index}...")
    print(f"Ustawienia: {width}x{height} @ {fps} FPS")
    
    # Inicjalizacja kamery
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    
    if not cap.isOpened():
        print(f"BŁĄD: Nie można otworzyć kamery na indeksie {index}.")
        return False

    # Konfiguracja PS3 Eye
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)

    print("Kamera uruchomiona. Nacisnij 'q', aby zamknąć.")
    
    prev_time = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Błąd podczas odbierania klatki.")
            break

        # Obliczanie FPS w czasie rzeczywistym
        curr_time = time.time()
        fps = 1 / (curr_time - prev_time) if prev_time != 0 else 0
        prev_time = curr_time

        # Wyświetlanie FPS na obrazie
        cv2.putText(frame, f"FPS: {int(fps)}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        
        # Wyświetlanie obrazu
        cv2.imshow('PS3 Eye Test', frame)

        # Wyjście po naciśnięciu 'q'
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("Test zakończony.")

if __name__ == "__main__":
    # PS3 Eye obsługuje:
    # - 640x480 max 60 FPS
    # - 320x240 max 187 FPS (stabilne 125 FPS)
    
    # Wybierz tryb:
    # test_camera(index=2, width=640, height=480, fps=60)  # Tryb wysokiej rozdzielczości
    test_camera(index=2, width=320, height=240, fps=125)   # Tryb wysokiego klatkażu

