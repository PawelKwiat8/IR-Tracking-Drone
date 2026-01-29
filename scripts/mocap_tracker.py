import cv2
import time
import numpy as np
import os
import json
import multiprocessing as mp
from queue import Empty
try:
    from camera_utils import get_camera_id
except ImportError:
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from camera_utils import get_camera_id

# Wymuszenie X11 dla OpenCV (Linux)
os.environ["QT_QPA_PLATFORM"] = "xcb"

# --- KONFIGURACJA DRONA (Geometria LEDów) ---
# Zakładamy układ T lub trójkąt równoramienny.
# Wartości w metrach.
DRONE_CONFIG = {
    "arm_length": 0.12,  # Odległość boczna
    "tail_length": 0.18, # Odległość ogonowa
    "tolerance": 0.02    # Tolerancja błędu dopasowania (2cm)
}

class KalmanFilter3D:
    """Filtr Kalmana 3D jak w Low-Cost-Mocap - modeluje pozycję, prędkość i przyspieszenie"""
    def __init__(self, fps=60):
        state_dim = 9       # [x, y, z, vx, vy, vz, ax, ay, az]
        measurement_dim = 3  # [x, y, z]
        
        self.kalman = cv2.KalmanFilter(state_dim, measurement_dim)
        self.prev_time = time.time()
        self.prev_pos = np.zeros(3)
        self.initialized = False
        
        dt = 1.0 / fps
        
        # Macierz przejścia (model ruchu z przyspieszeniem)
        self.kalman.transitionMatrix = np.array([
            [1, 0, 0, dt, 0, 0, 0.5*dt**2, 0, 0],
            [0, 1, 0, 0, dt, 0, 0, 0.5*dt**2, 0],
            [0, 0, 1, 0, 0, dt, 0, 0, 0.5*dt**2],
            [0, 0, 0, 1, 0, 0, dt, 0, 0],
            [0, 0, 0, 0, 1, 0, 0, dt, 0],
            [0, 0, 0, 0, 0, 1, 0, 0, dt],
            [0, 0, 0, 0, 0, 0, 1, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 1]
        ], dtype=np.float32)
        
        # Macierz pomiaru (mierzymy tylko pozycję)
        self.kalman.measurementMatrix = np.zeros((3, 9), dtype=np.float32)
        self.kalman.measurementMatrix[0, 0] = 1
        self.kalman.measurementMatrix[1, 1] = 1
        self.kalman.measurementMatrix[2, 2] = 1
        
        # Szum procesu i pomiaru (jak w Low-Cost-Mocap)
        self.kalman.processNoiseCov = np.eye(state_dim, dtype=np.float32) * 1e-2
        self.kalman.measurementNoiseCov = np.eye(measurement_dim, dtype=np.float32) * 1e0
        
        self.kalman.statePost = np.zeros((9, 1), dtype=np.float32)
    
    def update(self, measurement):
        """Aktualizuje filtr nowym pomiarem i zwraca przefiltrowaną pozycję"""
        now = time.time()
        dt = now - self.prev_time
        self.prev_time = now
        
        # Aktualizuj macierz przejścia z aktualnym dt
        self.kalman.transitionMatrix[0, 3] = dt
        self.kalman.transitionMatrix[1, 4] = dt
        self.kalman.transitionMatrix[2, 5] = dt
        self.kalman.transitionMatrix[3, 6] = dt
        self.kalman.transitionMatrix[4, 7] = dt
        self.kalman.transitionMatrix[5, 8] = dt
        self.kalman.transitionMatrix[0, 6] = 0.5 * dt**2
        self.kalman.transitionMatrix[1, 7] = 0.5 * dt**2
        self.kalman.transitionMatrix[2, 8] = 0.5 * dt**2
        
        pos = np.array(measurement, dtype=np.float32).reshape(3, 1)
        
        if not self.initialized:
            self.kalman.statePost[:3] = pos
            self.prev_pos = pos.flatten()
            self.initialized = True
            return pos.flatten()
        
        # Oblicz prędkość z różnicy pozycji
        vel = ((pos.flatten() - self.prev_pos) / max(dt, 0.001)).astype(np.float32)
        self.prev_pos = pos.flatten()
        
        # Predict + Correct
        self.kalman.predict()
        
        # Korekta tylko pozycją (prędkość jest estymowana)
        self.kalman.correct(pos)
        
        # Zwróć przefiltrowaną pozycję
        return self.kalman.statePost[:3].flatten()
    
    def get_velocity(self):
        """Zwraca estymowaną prędkość"""
        return self.kalman.statePost[3:6].flatten()
    
    def reset(self):
        self.kalman.statePost = np.zeros((9, 1), dtype=np.float32)
        self.initialized = False

def set_v4l2_ctrl(idx, ctrl, value):
    """Pomocnicza funkcja do ustawiania parametrów V4L2"""
    # Używamy os.path.realpath, aby rozwiązać symlinki (np. /dev/video2)
    dev_path = os.path.realpath(f"/dev/video{idx}")
    # Nazwa urządzenia dla v4l2-ctl musi być fizyczna
    os.system(f"v4l2-ctl -d {dev_path} --set-ctrl={ctrl}={value} > /dev/null 2>&1")

def apply_blur(img, blur_type, blur_size):
    """Aplikuje wybrany typ blur"""
    if blur_size < 3:
        return img
    blur_size = blur_size if blur_size % 2 == 1 else blur_size + 1
    if blur_type == 0:  # Median
        return cv2.medianBlur(img, blur_size)
    elif blur_type == 1:  # Gaussian
        return cv2.GaussianBlur(img, (blur_size, blur_size), 0)
    elif blur_type == 2:  # Bilateral
        return cv2.bilateralFilter(img, blur_size, 75, 75)
    return img

def camera_worker(idx, width, height, fps, threshold_val, min_area, intrinsics_path, output_queue, stop_event, hw_exposure, hw_gain):
    """PROCES KAMERY: Pobiera obraz i wylicza punkty 2D (BEZ filtrowania - filtrowanie na poziomie 3D)."""
    
    # Wczytaj konfigurację detekcji z pliku
    detection_config_path = os.path.join(os.path.dirname(intrinsics_path), "detection_config.json")
    det_cfg = {
        "exposure": 120,
        "gain": 30,
        "threshold": 40,
        "blur_size": 3,
        "blur_type": 0,
        "min_area": 2,
        "max_area": 500,
        "peak_threshold": 0.7,
        "peak_power": 2.0,
    }
    if os.path.exists(detection_config_path):
        try:
            with open(detection_config_path, 'r') as f:
                loaded = json.load(f)
                det_cfg.update(loaded)
                print(f" [OK] Cam{idx}: Wczytano detection_config.json (exp={det_cfg['exposure']}, gain={det_cfg['gain']}, thr={det_cfg['threshold']})")
        except Exception as e:
            print(f" [WARN] Cam{idx}: Błąd wczytywania detection_config: {e}")
    
    # Ustawienia sprzętowe kamery
    set_v4l2_ctrl(idx, "auto_exposure", 1)  # Manual Mode
    set_v4l2_ctrl(idx, "gain_automatic", 0)
    set_v4l2_ctrl(idx, "white_balance_automatic", 0)
    set_v4l2_ctrl(idx, "exposure", det_cfg["exposure"])
    set_v4l2_ctrl(idx, "gain", det_cfg["gain"])
    
    cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    # Wczytaj intrinsics dla kamery
    K = np.array([[width, 0, width/2], [0, width, height/2], [0, 0, 1.0]], dtype=np.float32)
    dist = np.zeros(5, dtype=np.float32)
    cam_id = get_camera_id(f"/dev/video{idx}")
    if os.path.exists(intrinsics_path):
        try:
            with open(intrinsics_path, 'r') as f:
                data = json.load(f)
                if cam_id in data:
                    K = np.array(data[cam_id]['mtx'], dtype=np.float32)
                    dist = np.array(data[cam_id]['dist'], dtype=np.float32).flatten()
                elif f"cam_{idx}" in data:
                    K = np.array(data[f"cam_{idx}"]['mtx'], dtype=np.float32)
                    dist = np.array(data[f"cam_{idx}"]['dist'], dtype=np.float32).flatten()
        except:
            pass

    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret: 
            time.sleep(0.01)
            continue

        # Przetwarzanie obrazu z parametrów z pliku
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = apply_blur(gray, det_cfg["blur_type"], det_cfg["blur_size"])
        _, thresh = cv2.threshold(gray, det_cfg["threshold"], 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        leds = []
        for cnt in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
            area = cv2.contourArea(cnt)
            if area < det_cfg["min_area"] or area > det_cfg["max_area"]:
                continue
            
            # Weighted centroid (Sub-pixel accuracy)
            x, y, w, h = cv2.boundingRect(cnt)
            roi = gray[max(0,y-2):y+h+2, max(0,x-2):x+w+2].astype(np.float32)
            peak = float(np.max(roi))
            
            # Wytnij tło
            peak_thr = det_cfg.get("peak_threshold", 0.7)
            peak_pow = det_cfg.get("peak_power", 2.0)
            if peak_thr > 0 and peak_pow > 0:
                roi = np.maximum(roi - (peak * peak_thr), 0)
                roi = np.power(roi, peak_pow)
            
            if np.sum(roi) > 0:
                yy, xx = np.mgrid[0:roi.shape[0], 0:roi.shape[1]]
                local_x = np.sum(xx * roi) / np.sum(roi)
                local_y = np.sum(yy * roi) / np.sum(roi)
                cX = float(max(0,x-2)) + float(local_x)
                cY = float(max(0,y-2)) + float(local_y)
            else:
                M = cv2.moments(cnt)
                denom = M["m00"] if M["m00"] > 0 else 1.0
                cX, cY = float(M["m10"]/denom), float(M["m01"]/denom)

            if not np.isfinite(cX) or not np.isfinite(cY):
                continue

            # Undistort point
            pt = np.array([[[cX, cY]]], dtype=np.float32)
            undist_pt = cv2.undistortPoints(pt, K, dist, P=K)
            cX_u, cY_u = undist_pt[0][0]
            
            # BEZ FILTROWANIA 2D - surowe dane do triangulacji
            leds.append({
                "pos": (cX_u, cY_u),       # Undistorted (do triangulacji)
                "raw_pos": (cX, cY),       # Oryginalne (do kalibracji)
                "peak": peak
            })
            
            cv2.drawMarker(frame, (int(cX), int(cY)), (0, 255, 0), cv2.MARKER_CROSS, 15, 2)

        if output_queue.full():
            try: output_queue.get_nowait()
            except Empty: pass
        output_queue.put((idx, leds, cv2.resize(frame, (320, 240))))
    cap.release()

class MocapTracker:
    def __init__(self, width=640, height=480, fps=60):
        self.width, self.height, self.fps = width, height, fps
        self.processes, self.queues = [], []
        self.stop_event = mp.Event()
        
        # Parametry współdzielone
        self.threshold_val = mp.Value('i', 40)
        self.min_area = mp.Value('i', 2)
        self.hw_exposure = mp.Value('i', 120)
        self.hw_gain = mp.Value('i', 30)
        
        self.camera_poses = []
        self.camera_intrinsics = []
        self.camera_ids = []
        
        self.calibrated = False
        self.scale = 1.0
        
        # Transformacja Świata (Podłoga)
        self.world_R = np.eye(3, dtype=np.float32)
        self.world_t = np.zeros((3, 1), dtype=np.float32)
        
        self.calibration_file = "camera_calibration.json"
        self.intrinsics_file = "intrinsics.json"
        
        # Kalman Filter 3D dla drona (jak w Low-Cost-Mocap)
        self.kalman = KalmanFilter3D(fps)
        
        # Debug (logi w terminalu) — domyślnie wyłączone i throttlowane
        self.debug_mode = False
        self.debug_interval_s = 1.0
        self._debug_last_ts = 0.0

    def dbg(self, msg: str, interval_s: float | None = None):
        """Wypisuje debug w terminalu nie częściej niż co `interval_s`."""
        if not self.debug_mode:
            return
        interval = self.debug_interval_s if interval_s is None else float(interval_s)
        now = time.time()
        if now - self._debug_last_ts >= interval:
            print(msg)
            self._debug_last_ts = now

    def find_cameras(self):
        """Wyszukuje i inicjalizuje kamery."""
        print("Łączenie z kamerami PS3 Eye...")
        # Sprawdzamy indeksy od 0 do 10
        indices = []
        for i in range(11):
            if os.path.exists(f"/dev/video{i}"):
                cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
                if cap.isOpened():
                    ret, _ = cap.read()
                    if ret:
                        indices.append(i)
                        print(f" [+] Połączono: /dev/video{i}")
                    cap.release()
            if len(indices) >= 4: break
        
        if len(indices) < 2:
            print(" [ERROR] Wymagane minimum 2 kamery do działania systemu!")
            return False

        self.camera_ids = []
        for idx in indices:
            cam_id = get_camera_id(f"/dev/video{idx}")
            self.camera_ids.append(cam_id)
            print(f" [INFO] Kamera {idx} ID: {cam_id}")

            # Wczytaj intrinsics
            K = np.array([[600.0, 0, self.width/2], [0, 600.0, self.height/2], [0, 0, 1.0]], dtype=np.float32)
            if os.path.exists(self.intrinsics_file):
                try:
                    with open(self.intrinsics_file, 'r') as f:
                        data = json.load(f)
                        if cam_id in data:
                            K = np.array(data[cam_id]['mtx'], dtype=np.float32)
                        elif f"cam_{idx}" in data:
                            K = np.array(data[f"cam_{idx}"]['mtx'], dtype=np.float32)
                except: pass
            self.camera_intrinsics.append(K)
            
            # Start procesu
            q = mp.Queue(maxsize=2)
            p = mp.Process(target=camera_worker, args=(idx, self.width, self.height, self.fps, 
                                                     self.threshold_val, self.min_area, 
                                                     self.intrinsics_file, q, self.stop_event, 
                                                     self.hw_exposure, self.hw_gain))
            p.daemon = True
            p.start()
            self.processes.append(p)
            self.queues.append(q)
            
        self.load_calibration()
        return True

    def load_calibration(self):
        if not os.path.exists(self.calibration_file):
            return

        try:
            with open(self.calibration_file, 'r') as f:
                data = json.load(f)
                
                self.camera_poses = []
                
                # 1. Próba ładowania wg ID
                if 'camera_poses_map' in data and self.camera_ids:
                    poses_map = data['camera_poses_map']
                    loaded_any = False
                    for cid in self.camera_ids:
                        if cid in poses_map:
                            p = poses_map[cid]
                            self.camera_poses.append({'R': np.array(p['R']), 't': np.array(p['t'])})
                            loaded_any = True
                        else:
                            # Brak kalibracji dla tej kamery -> placeholder
                            self.camera_poses.append({'R': np.eye(3), 't': np.zeros((3,1))})
                    
                    if loaded_any:
                        print(" [OK] Wczytano kalibrację extrinsics (ID-based).")

                # 2. Fallback: stara lista sekwencyjna
                if not self.camera_poses and 'camera_poses' in data:
                    self.camera_poses = [{'R': np.array(p['R']), 't': np.array(p['t'])} for p in data['camera_poses']]
                    print(" [INFO] Wczytano kalibrację sekwencyjną (stary format).")

                self.calibrated = data.get('calibrated', False)
                self.scale = data.get('scale', 1.0)
                if 'world_R' in data:
                    self.world_R = np.array(data['world_R'], dtype=np.float32)
                    self.world_t = np.array(data['world_t'], dtype=np.float32)
                    # Jeśli ktoś wcześniej ustawił "podłogę" błędnie, world_t potrafi odlecieć
                    # na setki metrów i wtedy kamery znikają z wizualizacji. Zabezpieczenie:
                    try:
                        if float(np.max(np.abs(self.world_t))) > 50.0:
                            print(f" [WARN] world_t wygląda na uszkodzone (max|t|={float(np.max(np.abs(self.world_t))):.2f}). Resetuję world_t do 0.")
                            self.world_t = np.zeros((3, 1), dtype=np.float32)
                    except Exception:
                        pass
        except Exception as e:
            print(f"Błąd wczytywania kalibracji: {e}")

    def save_calibration(self):
        poses_map = {}
        for i, pose in enumerate(self.camera_poses):
            if i < len(self.camera_ids):
                poses_map[self.camera_ids[i]] = {
                    'R': pose['R'].tolist(),
                    't': pose['t'].tolist()
                }

        data = {
            'camera_poses': [{'R': p['R'].tolist(), 't': p['t'].tolist()} for p in self.camera_poses],
            'camera_poses_map': poses_map,
            'calibrated': bool(self.calibrated), 
            'scale': float(self.scale),
            'world_R': self.world_R.tolist(), 
            'world_t': self.world_t.tolist()
        }
        with open(self.calibration_file, 'w') as f: json.dump(data, f, indent=4)

    def triangulate_local(self, pts_2d):
        """Triangulacja DLT dla N kamer."""
        # pts_2d: lista [ (x,y) lub None, ... ]
        valid_indices = [i for i, p in enumerate(pts_2d) if p is not None]
        if len(valid_indices) < 2: 
            return None
            
        A = []
        for i in valid_indices:
            x, y = pts_2d[i]
            # Macierz projekcji P = K * [R|t]
            # Tutaj pts_2d są już UNDISTORTED i w pikselach, więc używamy K
            # Ale uwaga: calibrate_extrinsics używa recoverPose, który daje znormalizowane współrzędne?
            # NIE. recoverPose daje R, t.
            # W triangulacji budujemy macierz A.
            
            Ki = self.camera_intrinsics[i]
            # Skalujemy t translacją
            RT = np.hstack((self.camera_poses[i]['R'], self.camera_poses[i]['t'] * self.scale))
            P = Ki @ RT
            
            A.append(x * P[2,:] - P[0,:])
            A.append(y * P[2,:] - P[1,:])
            
        _, _, Vh = np.linalg.svd(np.array(A))
        X = Vh[-1]
        X = X / X[3] # Normalizacja jednorodna
        return X[:3].reshape(3, 1).astype(np.float32)

    def triangulate(self, pts_2d):
        p_local = self.triangulate_local(pts_2d)
        if p_local is None: return None
        # Transformacja do układu świata
        p_world = self.world_R @ p_local + self.world_t
        return p_world.flatten()

    def calibrate_extrinsics(self, snapshots):
        """
        Kalibracja pozycji kamer względem kamery 0.
        snapshots: lista snapshotów, gdzie snapshot to lista 'leds' z każdej kamery.
        """
        print(f"Rozpoczynam kalibrację na {len(snapshots)} klatkach...")
        
        if len(snapshots) < 8:
            print(" [ERROR] Za mało punktów. Wymagane min 8.")
            return False
            
        num_cams = len(self.processes)
        # Kamera 0 jest centrum układu
        self.camera_poses = [{'R': np.eye(3), 't': np.zeros((3, 1))}]
        
        K0 = self.camera_intrinsics[0]
        # Wczytaj dist dla kamery 0
        dist0 = np.zeros(5, dtype=np.float32)
        if os.path.exists(self.intrinsics_file):
            try:
                with open(self.intrinsics_file, 'r') as f:
                    data = json.load(f)
                    cam_id0 = self.camera_ids[0] if self.camera_ids else None
                    if cam_id0 and cam_id0 in data:
                        dist0 = np.array(data[cam_id0]['dist'], dtype=np.float32).flatten()
            except: pass
        
        # Dla każdej kamery i > 0, znajdź jej pozycję względem 0
        for i in range(1, num_cams):
            print(f"Kalibracja kamery {i}...")
            pts0 = []
            ptsi = []
            
            Ki = self.camera_intrinsics[i]
            # Wczytaj dist dla kamery i
            disti = np.zeros(5, dtype=np.float32)
            if os.path.exists(self.intrinsics_file):
                try:
                    with open(self.intrinsics_file, 'r') as f:
                        data = json.load(f)
                        cam_idi = self.camera_ids[i] if i < len(self.camera_ids) else None
                        if cam_idi and cam_idi in data:
                            disti = np.array(data[cam_idi]['dist'], dtype=np.float32).flatten()
                except: pass
            
            # Zbieranie par punktów (cam0, cam_i)
            for snap in snapshots:
                # Sprawdź czy obie kamery coś widzą w tej klatce
                leds0 = snap[0]
                ledsi = snap[i]
                
                # Używamy tylko najjaśniejszego punktu, zakładając że używamy 1 diody do kalibracji
                if leds0 and ledsi:
                    # Sortuj po jasności (peak)
                    led0 = sorted(leds0, key=lambda x: x['peak'], reverse=True)[0]
                    ledi = sorted(ledsi, key=lambda x: x['peak'], reverse=True)[0]
                    
                    # WAŻNE: Używamy raw_pos (oryginalne piksele z dystorsją) do kalibracji!
                    p0 = led0.get('raw_pos', led0['pos'])  # fallback dla kompatybilności
                    pi = ledi.get('raw_pos', ledi['pos'])
                    
                    pts0.append(p0)
                    ptsi.append(pi)
            
            if len(pts0) < 8:
                print(f" [WARN] Za mało wspólnych punktów między cam0 a cam{i} ({len(pts0)}). Pomięto.")
                # Dajemy identity jako fallback, ale system nie będzie działał poprawnie
                self.camera_poses.append({'R': np.eye(3), 't': np.zeros((3, 1))})
                continue
                
            pts0_np = np.array(pts0, dtype=np.float32)
            ptsi_np = np.array(ptsi, dtype=np.float32)
            
            # Undistort z PEŁNYMI parametrami (K i dist) -> znormalizowane współrzędne
            # To jest jedyny undistort - w camera_worker zapisujemy raw_pos
            pts0_norm = cv2.undistortPoints(pts0_np.reshape(-1,1,2), K0, dist0)
            ptsi_norm = cv2.undistortPoints(ptsi_np.reshape(-1,1,2), Ki, disti)
            
            # Oblicz Essential Matrix (używamy focal=1, pp=(0,0) bo punkty są znormalizowane)
            E, mask = cv2.findEssentialMat(ptsi_norm, pts0_norm, focal=1.0, pp=(0,0), 
                                           method=cv2.RANSAC, prob=0.999, threshold=0.001)
            
            if E is None:
                print(f" [WARN] Nie udało się obliczyć Essential Matrix dla kamery {i}. Pomięto.")
                self.camera_poses.append({'R': np.eye(3), 't': np.zeros((3, 1))})
                continue
            
            # Odzyskaj R i t (ptsi = R * pts0 + t)
            # Uwaga: recoverPose zwraca t znormalizowane (scale=1)
            _, R, t, _ = cv2.recoverPose(E, ptsi_norm, pts0_norm)
            
            self.camera_poses.append({'R': R, 't': t})
            print(f" [OK] Skalibrowano kamerę {i}. t={t.flatten()}")

        self.calibrated = True
        self.save_calibration()
        return True

    def find_points_3d(self, all_leds):
        """Znajduje punkty 3D na podstawie korespondencji z kamer."""
        if not self.calibrated:
            return []

        num_cams = len(self.processes)
        
        # Kandydaci: bierzemy max 3 punkty z każdej kamery
        candidates = []
        for i in range(num_cams):
            if all_leds[i]:
                # Sortuj po peak i weź 3
                s = sorted(all_leds[i], key=lambda x: x['peak'], reverse=True)[:3]
                candidates.append([l['pos'] for l in s])
            else:
                candidates.append([])
        
        points_3d = []
        
        # --- UPROSZCZONY ALGORYTM PAROWANIA ---
        # Zamiast skomplikowanej epipolarnej (która bywa zawodna przy szumach),
        # użyjemy prostej heurystyki:
        # Sprawdzamy wszystkie możliwe kombinacje punktów z kamer i wybieramy te,
        # które dają niski błąd reprojekcji po triangulacji.
        
        # Lista wszystkich kombinacji (dla 2 kamer to proste, dla 3 trochę więcej)
        # Przyjmujemy max 1 punkt na kamerę dla jednego punktu 3D (oczywiste)
        
        # 1. Znajdź kamerę "Primary" (najniższy indeks z punktami)
        primary_cam = -1
        for i in range(num_cams):
            if candidates[i]:
                primary_cam = i
                break
        
        if primary_cam == -1: 
            return []
        
        # DEBUG: Pokaż ile punktów jest w każdej kamerze
        # if any(len(c) > 0 for c in candidates):
        #     if self.debug_mode:
        #         print(f"[DEBUG] Kandydaci 2D: {[len(c) for c in candidates]}")
        
        # Dla każdego punktu w Primary Cam
        used_indices = {i: set() for i in range(num_cams)}
        
        for p_idx, p_start in enumerate(candidates[primary_cam]):
            best_match_group = [None] * num_cams
            best_match_group[primary_cam] = p_start
            best_err = 100.0 # Duży błąd początkowy
            found_match = False
            
            # Szukamy pasującego punktu w innych kamerach
            # (Metoda zachłanna - Greedy)
            
            current_group = [None] * num_cams
            current_group[primary_cam] = p_start
            
            # Sprawdź z każdą inną kamerą
            for other_cam in range(num_cams):
                if other_cam == primary_cam: continue
                if not candidates[other_cam]: continue
                
                # Znajdź najlepszy punkt w other_cam pasujący do current_group
                local_best_p = None
                local_min_err = 100.0 # Próg błędu reprojekcji (piksele) - zwiększony
                
                for other_p_idx, other_p in enumerate(candidates[other_cam]):
                    if other_p_idx in used_indices[other_cam]: continue
                    
                    test_group = list(current_group)
                    test_group[other_cam] = other_p
                    
                    # Szybka triangulacja
                    p3d_local = self.triangulate_local(test_group)
                    if p3d_local is not None:
                        err = self.reprojection_error(p3d_local, test_group)
                        # print(f"[DEBUG] Cam{other_cam} pt{other_p_idx} err={err:.1f}")
                        if err < local_min_err:
                            local_min_err = err
                            local_best_p = other_p
                
                if local_best_p is not None:
                    current_group[other_cam] = local_best_p
            
            # Sprawdź czy mamy min 2 kamery
            count = sum(1 for x in current_group if x is not None)
            if count >= 2:
                # Finalna weryfikacja
                p3d_local = self.triangulate_local(current_group)
                final_err = self.reprojection_error(p3d_local, current_group)
                
                # print(f"[DEBUG] Triangulacja: count={count}, err={final_err:.1f}, p3d={p3d_local.flatten() if p3d_local is not None else None}")
                if final_err < 100.0: # Akceptowalny błąd (zwiększony)
                    p3d_world = self.world_R @ p3d_local + self.world_t
                    points_3d.append(p3d_world.flatten())
                    # print(f"[DEBUG] Punkt 3D zaakceptowany: {p3d_world.flatten()}")
                    # Oznacz użyte (uproszczenie - zakładamy że punkt nie jest widoczny 2 razy)
                    # (To można ulepszyć, ale na start wystarczy)
        
        return points_3d

    def reprojection_error(self, p_local, pts_2d):
        """Liczy błąd reprojekcji (średnia odległość w pikselach)."""
        errs = []
        Xh = np.vstack([p_local, [[1.0]]])
        for i, pt in enumerate(pts_2d):
            if pt is None: continue
            
            Ki = self.camera_intrinsics[i]
            RT = np.hstack((self.camera_poses[i]['R'], self.camera_poses[i]['t'] * self.scale))
            P = Ki @ RT
            proj = P @ Xh
            z = proj[2,0]
            if z <= 0.001: return 1000.0 # Punkt za kamerą
            
            u, v = proj[0,0]/z, proj[1,0]/z
            dist = np.hypot(u - pt[0], v - pt[1])
            errs.append(dist)
            
        return np.mean(errs) if errs else 1000.0

    def locate_drone(self, points_3d):
        """Dopasowuje trójkąt LEDów drona do chmury punktów 3D."""
        if len(points_3d) < 3: return None, 0.0, 0.0
        
        best_center = None
        min_structure_err = 1e6
        best_hdg = 0.0
        
        # Brute-force po trójkach punktów
        n = len(points_3d)
        for i in range(n):
            for j in range(i+1, n):
                for k in range(j+1, n):
                    pts = [points_3d[i], points_3d[j], points_3d[k]]
                    
                    # Oblicz odległości między punktami
                    d1 = np.linalg.norm(pts[0]-pts[1])
                    d2 = np.linalg.norm(pts[1]-pts[2])
                    d3 = np.linalg.norm(pts[0]-pts[2])
                    ds = sorted([d1, d2, d3])
                    
                    # Oczekiwane odległości z configu:
                    # Typowy układ 3 LEDów na dronie to: 2 LEDy na ramionach (odległość między nimi = arm_length)
                    # oraz 1 LED "ogon" w równej odległości od obu ramion (dwie dłuższe krawędzie = tail_length).
                    # Czyli boki: [arm_length, tail_length, tail_length]
                    expected = sorted([
                        DRONE_CONFIG["arm_length"],
                        DRONE_CONFIG["tail_length"],
                        DRONE_CONFIG["tail_length"],
                    ])
                    err = abs(ds[0] - expected[0]) + abs(ds[1] - expected[1]) + abs(ds[2] - expected[2])
                    
                    if err < DRONE_CONFIG["tolerance"] * 3 and err < min_structure_err:
                        min_structure_err = err
                        best_center = np.mean(pts, axis=0)
                        
                        # Heading (Kierunek)
                        # Przyjmujemy: najkrótszy bok = ramiona (przód), punkt naprzeciwko = ogon (tył).
                        # Kierunek "przodu" to wektor od ogona do środka ramion.
                        if d1 == ds[0]:
                            p_arm1, p_arm2, p_tail = pts[0], pts[1], pts[2]
                        elif d2 == ds[0]:
                            p_arm1, p_arm2, p_tail = pts[1], pts[2], pts[0]
                        else:
                            p_arm1, p_arm2, p_tail = pts[0], pts[2], pts[1]

                        front_center = (p_arm1 + p_arm2) / 2.0
                        front_vec = front_center - p_tail
                        best_hdg = float(np.arctan2(front_vec[1], front_vec[0]))

        return best_center, best_hdg, min_structure_err

    def determine_scale(self, points_3d):
        """Ustala skalę świata na podstawie znanego wymiaru drona."""
        # Szukamy dwóch punktów oddalonych o znany najdłuższy wymiar drona (z configu)
        if len(points_3d) < 2: 
            print(f"[SCALE] Za mało punktów: {len(points_3d)}")
            return False
        
        max_d = 0
        for i in range(len(points_3d)):
            for j in range(i+1, len(points_3d)):
                d = np.linalg.norm(points_3d[i] - points_3d[j])
                if d > max_d: max_d = d
        
        print(f"[SCALE] Max odległość między punktami: {max_d:.4f}m")
        
        if max_d > 0.001: # Minimalna ochrona przed szumem (1mm)
            # Obliczamy nową skalę
            # max_d (w obecnej skali) powinno wynosić target_len (w metrach)
            target_len = float(max(DRONE_CONFIG["arm_length"], DRONE_CONFIG["tail_length"]))
            factor = target_len / max_d
            old_scale = self.scale
            self.scale *= factor
            print(f"[SCALE] Skala: {old_scale:.4f} -> {self.scale:.4f} (factor={factor:.4f})")
            self.save_calibration()
            return True
        print(f"[SCALE] Odległość za mała: {max_d:.4f}m < 0.001m")
        return False

    def set_floor(self, drone_pos, center_xy: bool = False):
        """Ustawia poziom podłogi: zeruje Z na wysokości drona (w układzie świata).
        Jeśli `center_xy=True`, dodatkowo centruje X/Y na dronie (ustawia drona w (0,0,0))."""
        if drone_pos is None: return False
        
        # UWAGA: `drone_pos` które tu dostajemy jest już w układzie świata
        # (bo `find_points_3d()` zwraca punkty po world_R/world_t), więc NIE wolno
        # go ponownie skalować ani mnożyć przez world_R.
        dp = np.array(drone_pos, dtype=np.float32).reshape(3, 1)
        if center_xy:
            self.world_t[0, 0] -= float(dp[0, 0])
            self.world_t[1, 0] -= float(dp[1, 0])
        dz = float(dp[2, 0])
        self.world_t[2, 0] -= dz

        mode = "CENTER_XY+Z" if center_xy else "Z_ONLY"
        print(f"[FLOOR] ({mode}) przesunięcie: dx={(-dp[0,0] if center_xy else 0):.3f}, dy={(-dp[1,0] if center_xy else 0):.3f}, dz={-dz:.3f} | world_t={self.world_t.flatten()}")
        
        self.save_calibration()
        return True

    def stop(self):
        self.stop_event.set()
        for p in self.processes: p.terminate()

def main():
    from mocap_visualizer import MocapVisualizer
    
    tracker = MocapTracker()
    if not tracker.find_cameras(): 
        return

    # Okno kontrolne – mniejsze, żeby paski były widoczne na ekranie
    cv2.namedWindow('Mocap Control', cv2.WINDOW_NORMAL)
    cv2.resizeWindow('Mocap Control', 1100, 700)
    cv2.createTrackbar('Threshold', 'Mocap Control', tracker.threshold_val.value, 255, lambda x: setattr(tracker.threshold_val, 'value', x))
    cv2.createTrackbar('Exposure', 'Mocap Control', tracker.hw_exposure.value, 255, lambda x: setattr(tracker.hw_exposure, 'value', x))
    
    viz = MocapVisualizer(None)
    
    # Bufory
    num_cams = len(tracker.processes)
    frames_buffer = [None] * num_cams
    leds_buffer = [[]] * num_cams
    calibration_snapshots = []
    
    print("\n--- INSTRUKCJA ---")
    print(" 'c' - zbierz punkt do kalibracji (wymaga widoczności w min. 2 kamerach)")
    print(" 'k' - OBLICZ kalibrację (gdy masz >8 punktów)")
    print(" 'g' - ustaw skalę (połóż drona i wciśnij)")
    print(" 'f' - ustaw podłogę (Z=0 na dronie)")
    print(" 'F' - ustaw podłogę + wycentruj (dron -> (0,0,0))")
    print(" 'd' - debug ON/OFF (log w terminalu co ~1s)")
    print(" 'r' - reset kalibracji")
    print("ESC - wyjście\n")

    while True:
        # 1. Odbiór danych z procesów
        for i, q in enumerate(tracker.queues):
            try:
                while not q.empty():
                    _, leds, frame = q.get_nowait()
                    frames_buffer[i] = frame
                    leds_buffer[i] = leds
            except: pass
            
        # Sprawdź czy mamy komplet klatek (do wyświetlania)
        if any(f is None for f in frames_buffer):
            time.sleep(0.01)
            continue
            
        # 2. Przetwarzanie 3D
        p3d = tracker.find_points_3d(leds_buffer)
        drone_pos, hdg, err = tracker.locate_drone(p3d)
        tracker.dbg(f"[DBG] 2D={[len(l) for l in leds_buffer]} Pts3D={len(p3d)} Drone={'OK' if drone_pos is not None else 'NONE'} Err={err:.3f} Scale={tracker.scale:.2f}", interval_s=1.0)
        
        # 3. Kalman Filter 3D
        viz_pos = None
        if drone_pos is not None:
            # Użyj nowego KalmanFilter3D
            viz_pos = tracker.kalman.update(drone_pos)
            
            viz.drone_pos = viz_pos
            viz.drone_heading = hdg
            viz.trajectory.append(viz_pos)
            
        # 4. Wizualizacja
        if tracker.calibrated:
            # Transformuj kamery do wyświetlania w układzie świata
            world_cams = []
            for p in tracker.camera_poses:
                # Wizualizator oczekuje extrinsics WORLD->CAM (OpenCV): x_cam = R * X_world + t
                # Mamy extrinsics w układzie lokalnym (S) + transformację świata: X_W = world_R * X_S + world_t
                # Po podstawieniu: R_W = R_S * world_R^T,  t_W = t_S - R_W * world_t
                R_w = p['R'] @ tracker.world_R.T
                t_scaled = p['t'] * tracker.scale
                t_w = t_scaled - (R_w @ tracker.world_t)
                world_cams.append({'R': R_w, 't': t_w})
            viz.camera_poses = world_cams
        
        # Sklejanie obrazu podglądu (zmniejszone, aby okno mieściło się na ekranie)
        preview_w = 280
        preview_h = 210  # proporcje 4:3
        resized_frames = [cv2.resize(f, (preview_w, preview_h)) for f in frames_buffer]
        cam_row = np.hstack(resized_frames)
        
        # Render 3D
        viz_img = viz.render()
        # Skalowanie wizualizacji do szerokości paska kamer
        target_w = cam_row.shape[1]
        scale_viz = target_w / viz_img.shape[1]
        viz_img_res = cv2.resize(viz_img, (target_w, int(viz_img.shape[0] * scale_viz)))
        
        # Info panel (niższy, aby nie wypychał okna)
        info_panel = np.zeros((80, target_w, 3), dtype=np.uint8)
        status_txt = "CALIBRATED" if tracker.calibrated else "NOT CALIBRATED"
        dbg_txt = "ON" if tracker.debug_mode else "OFF"
        cv2.putText(info_panel, f"System: {status_txt} | Pts3D: {len(p3d)} | Err: {err:.3f} | DBG: {dbg_txt}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0,255,0), 2)
        cv2.putText(info_panel, f"CalibPts: {len(calibration_snapshots)}/8 | Scale: {tracker.scale:.2f}", (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200,200,200), 1)
        if drone_pos is not None:
             cv2.putText(info_panel, f"Pos: {drone_pos[0]:.2f}, {drone_pos[1]:.2f}, {drone_pos[2]:.2f}", (400, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255), 1)

        final_frame = np.vstack([cam_row, viz_img_res, info_panel])
        cv2.imshow('Mocap Control', final_frame)
        
        # Obsługa klawiszy
        key = cv2.waitKey(1) & 0xFF
        if key == 27: break
        elif key == ord('c'):
            # Zbieranie punktu kalibracyjnego
            # Wymagamy, aby co najmniej 2 kamery widziały punkt
            visible_count = sum(1 for l in leds_buffer if l)
            if visible_count >= 2:
                # Kopiujemy aktualny stan ledów
                snapshot = [list(l) for l in leds_buffer]
                calibration_snapshots.append(snapshot)
                print(f" [+] Dodano punkt kalibracyjny ({len(calibration_snapshots)}).")
                # Mignięcie
                cv2.imshow('Mocap Control', 255 - final_frame)
                cv2.waitKey(50)
            else:
                print(" [!] Za mało widocznych punktów (min 2).")
        
        elif key == ord('k'):
            if len(calibration_snapshots) >= 8:
                tracker.calibrate_extrinsics(calibration_snapshots)
                calibration_snapshots = []
            else:
                print(" [!] Za mało punktów do kalibracji (min 8).")
        
        elif key == ord('g'):
            if tracker.determine_scale(p3d):
                print(f" [OK] Skala zaktualizowana: {tracker.scale}")
        
        elif key == ord('f'):
            if drone_pos is not None:
                tracker.set_floor(drone_pos, center_xy=False)

        elif key == ord('F'):
            if drone_pos is not None:
                tracker.set_floor(drone_pos, center_xy=True)

        elif key == ord('d'):
            tracker.debug_mode = not tracker.debug_mode
            print(f" [INFO] Debug: {'ON' if tracker.debug_mode else 'OFF'}")
        
        elif key == ord('r'):
            tracker.calibrated = False
            calibration_snapshots = []
            if os.path.exists(tracker.calibration_file):
                os.remove(tracker.calibration_file)
            print(" [INFO] Reset kalibracji.")

        # Sterowanie wizualizacją
        if key == ord('w'): viz.rot_x = min(89, viz.rot_x + 5)
        elif key == ord('x'): viz.rot_x = max(-89, viz.rot_x - 5)
        elif key == ord('q'): viz.rot_z -= 5
        elif key == ord('e'): viz.rot_z += 5
        elif key == ord('+'): viz.scale += 10
        elif key == ord('-'): viz.scale -= 10

    tracker.stop()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
