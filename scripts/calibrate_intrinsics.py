import cv2
import numpy as np
import os
import json
import glob
try:
    from camera_utils import get_camera_id
except ImportError:
    # Fallback if running from a different directory without installing as package
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from camera_utils import get_camera_id

def calibrate_camera(video_dev, board_shape=(9, 6), square_size=0.029):
    """
    board_shape: liczba wewnętrznych rogów (szerokość, wysokość)
    square_size: rozmiar kwadratu w metrach
    """
    cam_id = get_camera_id(video_dev)
    print(f"Kalibracja kamery: {video_dev} (ID: {cam_id})")
    
    objp = np.zeros((board_shape[0] * board_shape[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:board_shape[0], 0:board_shape[1]].T.reshape(-1, 2) * square_size

    objpoints = [] # punkty 3d w świecie
    imgpoints = [] # punkty 2d w obrazie

    # Otwórz kamerę używając ścieżki urządzenia
    # Upewnij się, że masz uprawnienia (np. sudo chmod 666 /dev/video*)
    cap = cv2.VideoCapture(video_dev, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    print("Naciśnij 'SPACE', aby przechwycić klatkę, 'q' aby zakończyć zbieranie.")

    count = 0
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret: break
        
        frame_idx += 1
        display = frame.copy()
        
        ret_chess = False
        corners = None
        
        # Szukaj co 5 klatek
        if frame_idx % 5 == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            ret_chess, corners = cv2.findChessboardCorners(gray, board_shape, 
                cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_FAST_CHECK + cv2.CALIB_CB_NORMALIZE_IMAGE)

        if ret_chess and corners is not None:
            cv2.drawChessboardCorners(display, board_shape, corners, ret_chess)

        cv2.putText(display, f"Zabrano: {count} klatek. SPACE-zapisz, Q-licz", (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(display, f"ID: {cam_id}", (10, 60), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        cv2.imshow(f"Kalibracja", display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord(' '):
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            ret_chess, corners = cv2.findChessboardCorners(gray, board_shape, None)
            
            if ret_chess:
                objpoints.append(objp)
                imgpoints.append(corners)
                count += 1
                print(f"Zapisano klatkę {count}")
                flash = frame.copy()
                flash[:] = (255, 0, 0)
                cv2.imshow(f"Kalibracja", flash)
                cv2.waitKey(100)
            else:
                print("BŁĄD: Nie znaleziono szachownicy w tej klatce!")
        elif key == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

    if count > 10:
        print("Obliczanie parametrów...")
        ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(objpoints, imgpoints, (640,480), None, None)
        return cam_id, mtx, dist
    else:
        print("Zbyt mało klatek (min. 10).")
        return None, None, None

def main():
    # Parametry Twojej szachownicy
    rows = 9 
    cols = 6
    square_size = 0.029
    
    # Wczytaj istniejące wyniki, jeśli są
    if os.path.exists("intrinsics.json"):
        with open("intrinsics.json", 'r') as f:
            results = json.load(f)
    else:
        results = {}
    
    # Znajdź dostępne kamery PS3 Eye (zazwyczaj videoX, gdzie X>0)
    print("Skanowanie kamer...")
    found_cams = glob.glob("/dev/video*")
    # Filtrujemy, bierzemy tylko te, które się otwierają
    valid_cams = []
    for cam in sorted(found_cams):
        # Pomiń, jeśli to nie jest urządzenie wideo (np. loopback) - proste sprawdzenie numeru
        try:
            num = int(cam.replace("/dev/video", ""))
            if num == 0: continue # Pomiń laptop
        except: continue
        
        cap = cv2.VideoCapture(cam)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                valid_cams.append(cam)
            cap.release()
            
    print(f"Znaleziono kamery do kalibracji: {valid_cams}")
    
    for cam_dev in valid_cams:
        cam_id = get_camera_id(cam_dev)
        if cam_id in results:
            print(f"\nKamera {cam_id} ({cam_dev}) już skalibrowana. Pominąć? [T/n]")
            if input().lower() != 'n':
                continue
                
        print(f"\n--- Kalibracja kamery: {cam_dev} ---")
        cid, mtx, dist = calibrate_camera(cam_dev, (rows, cols), square_size)
        
        if mtx is not None:
            results[cid] = {
                "mtx": mtx.tolist(),
                "dist": dist.tolist()
            }
            with open("intrinsics.json", "w") as f:
                json.dump(results, f, indent=4)
            print(f"Zapisano parametry dla {cid}")

    print("\nKalibracja zakończona. Plik 'intrinsics.json' zaktualizowany.")

if __name__ == "__main__":
    main()
