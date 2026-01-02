#!/usr/bin/env python3
"""
Narzędzie do strojenia parametrów detekcji punktów IR.
Pozwala na żywo dostosować wszystkie parametry i zapisać konfigurację.
"""

import cv2
import numpy as np
import os
import json
import sys
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from camera_utils import get_camera_id

os.environ["QT_QPA_PLATFORM"] = "xcb"

# Ścieżka do pliku konfiguracji (w głównym katalogu projektu)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
CONFIG_FILE = os.path.join(PROJECT_DIR, "detection_config.json")

# Domyślne wartości parametrów
DEFAULT_CONFIG = {
    # Parametry sprzętowe kamery
    "exposure": 120,
    "gain": 30,
    
    # Przetwarzanie obrazu
    "threshold": 40,
    "blur_size": 3,          # Rozmiar blur (1=brak, 3, 5, 7...)
    "blur_type": 0,          # 0=median, 1=gaussian, 2=bilateral
    
    # Morfologia (opcjonalna)
    "morph_open": 0,         # Rozmiar operacji opening (usuwa szum)
    "morph_close": 0,        # Rozmiar operacji closing (łączy bliskie punkty)
    
    # Filtrowanie konturów
    "min_area": 2,
    "max_area": 500,
    "min_circularity": 0.0,  # 0-1, 1=idealny okrąg
    
    # Centroid weighting
    "peak_threshold": 0.7,   # % peak do odcięcia tła w ROI
    "peak_power": 2.0,       # Potęga do wzmocnienia jasnych pikseli
    
    # Stabilizacja (One Euro Filter) - WAŻNE dla końcowej stabilności!
    # mincutoff: niższy = więcej wygładzania (wolniejsza reakcja)
    # beta: niższy = mniej reakcji na szybkie zmiany (stabilniejsze, ale laguje)
    "filter_mincutoff": 0.5,   # 0.001-2.0, zalecane 0.3-1.0
    "filter_beta": 0.01,       # 0.0-0.5, zalecane 0.01-0.1
}

def set_v4l2_ctrl(idx, ctrl, value):
    """Ustawia parametr V4L2 kamery"""
    dev_path = os.path.realpath(f"/dev/video{idx}")
    os.system(f"v4l2-ctl -d {dev_path} --set-ctrl={ctrl}={value} > /dev/null 2>&1")

def apply_blur(img, blur_type, blur_size):
    """Aplikuje wybrany typ blur"""
    if blur_size < 3:
        return img
    
    # Upewnij się że rozmiar jest nieparzysty
    blur_size = blur_size if blur_size % 2 == 1 else blur_size + 1
    
    if blur_type == 0:  # Median
        return cv2.medianBlur(img, blur_size)
    elif blur_type == 1:  # Gaussian
        return cv2.GaussianBlur(img, (blur_size, blur_size), 0)
    elif blur_type == 2:  # Bilateral (zachowuje krawędzie)
        return cv2.bilateralFilter(img, blur_size, 75, 75)
    return img

def apply_morphology(img, open_size, close_size):
    """Aplikuje operacje morfologiczne"""
    if open_size > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_size, open_size))
        img = cv2.morphologyEx(img, cv2.MORPH_OPEN, kernel)
    
    if close_size > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_size, close_size))
        img = cv2.morphologyEx(img, cv2.MORPH_CLOSE, kernel)
    
    return img

class OneEuroFilter:
    """Filtr stabilizujący pozycję - redukuje szum bez dużego opóźnienia"""
    def __init__(self, freq, mincutoff=1.0, beta=0.0, dcutoff=1.0):
        self.freq = max(1.0, freq)  # Min 1 Hz
        self.mincutoff = max(0.01, mincutoff)  # Min 0.01
        self.beta = max(0.001, beta)  # Min 0.001
        self.dcutoff = max(0.01, dcutoff)  # Min 0.01
        self.x_prev = None
        self.dx_prev = 0

    def alpha(self, cutoff):
        cutoff = max(0.01, cutoff)  # Zabezpieczenie
        tau = 1.0 / (2 * np.pi * cutoff)
        te = 1.0 / self.freq
        return 1.0 / (1.0 + tau / te)

    def filter(self, x):
        if self.x_prev is None:
            self.x_prev = x
            return x
        dx = (x - self.x_prev) * self.freq
        edx = self.alpha(self.dcutoff) * dx + (1 - self.alpha(self.dcutoff)) * self.dx_prev
        cutoff = max(0.01, self.mincutoff + self.beta * abs(edx))
        a = self.alpha(cutoff)
        x_res = a * x + (1 - a) * self.x_prev
        self.x_prev = x_res
        self.dx_prev = edx
        return x_res
    
    def update_params(self, mincutoff, beta):
        self.mincutoff = max(0.01, mincutoff)
        self.beta = max(0.001, beta)

def detect_leds(gray, thresh_img, config):
    """Wykrywa LEDy z pełną konfiguracją"""
    contours, _ = cv2.findContours(thresh_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    leds = []
    for cnt in sorted(contours, key=cv2.contourArea, reverse=True)[:10]:
        area = cv2.contourArea(cnt)
        
        # Filtrowanie po wielkości
        if area < config["min_area"] or area > config["max_area"]:
            continue
        
        # Filtrowanie po okrągłości
        if config["min_circularity"] > 0:
            perimeter = cv2.arcLength(cnt, True)
            if perimeter > 0:
                circularity = 4 * np.pi * area / (perimeter * perimeter)
                if circularity < config["min_circularity"]:
                    continue
        
        # Weighted centroid (Sub-pixel accuracy)
        x, y, w, h = cv2.boundingRect(cnt)
        roi = gray[max(0,y-2):y+h+2, max(0,x-2):x+w+2].astype(np.float32)
        peak = float(np.max(roi))
        
        # Wytnij tło
        threshold_val = peak * config["peak_threshold"]
        roi = np.maximum(roi - threshold_val, 0)
        roi = np.power(roi, config["peak_power"])
        
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
        
        if np.isfinite(cX) and np.isfinite(cY):
            leds.append({
                "pos": (cX, cY),
                "area": area,
                "peak": peak
            })
    
    return leds

class TuningGUI:
    def __init__(self, camera_indices):
        self.camera_indices = camera_indices
        self.caps = []
        self.config = DEFAULT_CONFIG.copy()
        
        # Wczytaj zapisaną konfigurację
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    saved = json.load(f)
                    # Konwertuj typy - trackbary wymagają int
                    for key, val in saved.items():
                        if key in self.config:
                            # Zachowaj typ z DEFAULT_CONFIG
                            default_type = type(self.config[key])
                            if default_type == int:
                                self.config[key] = int(val)
                            elif default_type == float:
                                self.config[key] = float(val)
                            else:
                                self.config[key] = val
                    print(f"[OK] Wczytano konfigurację z {CONFIG_FILE}")
                    print(f"    Parametry: Exp={self.config['exposure']}, Gain={self.config['gain']}, Thr={self.config['threshold']}, Blur={self.config['blur_size']}")
            except Exception as e:
                print(f"[WARN] Błąd wczytywania konfiguracji: {e}")
        
        # Historia pozycji dla stabilności
        self.position_history = [{} for _ in camera_indices]
        self.history_length = 30
        
        # Statystyki do porównywania
        self.stats_history = {
            'raw': [],      # Historia stabilności surowej
            'filtered': [], # Historia stabilności filtrowanej
        }
        self.stats_max_samples = 300  # ~5 sekund przy 60fps
        self.test_mode = False
        self.test_start_time = None
        self.test_results = []
        
        # Filtry One Euro dla każdej kamery (max 10 punktów)
        # Proste podejście: sortujemy punkty po X i przypisujemy do indeksów
        self.filters = []
        for _ in camera_indices:
            cam_filters = {
                'x': [OneEuroFilter(60, max(0.01, self.config["filter_mincutoff"]), max(0.001, self.config["filter_beta"])) for _ in range(10)],
                'y': [OneEuroFilter(60, max(0.01, self.config["filter_mincutoff"]), max(0.001, self.config["filter_beta"])) for _ in range(10)]
            }
            self.filters.append(cam_filters)
        
        # Tryb wyświetlania
        self.show_filtered = True  # Przełącznik: filtrowane vs surowe
        
        # Flaga blokująca callbacki podczas inicjalizacji
        self.initializing = True
        
        self.setup_cameras()
        self.setup_gui()
        
        self.initializing = False
    
    def setup_cameras(self):
        """Inicjalizuje kamery"""
        for idx in self.camera_indices:
            # Ustaw tryb manualny
            set_v4l2_ctrl(idx, "auto_exposure", 1)
            set_v4l2_ctrl(idx, "gain_automatic", 0)
            set_v4l2_ctrl(idx, "white_balance_automatic", 0)
            
            cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 60)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.caps.append(cap)
            
            # Ustaw początkowe wartości
            set_v4l2_ctrl(idx, "exposure", self.config["exposure"])
            set_v4l2_ctrl(idx, "gain", self.config["gain"])
    
    def setup_gui(self):
        """Tworzy okno z suwakami"""
        cv2.namedWindow('IR Tuning', cv2.WINDOW_NORMAL)
        cv2.resizeWindow('IR Tuning', 1400, 900)
        
        # Parametry sprzętowe
        cv2.createTrackbar('Exposure', 'IR Tuning', self.config["exposure"], 255, self.on_exposure)
        cv2.createTrackbar('Gain', 'IR Tuning', self.config["gain"], 255, self.on_gain)
        
        # Przetwarzanie
        cv2.createTrackbar('Threshold', 'IR Tuning', self.config["threshold"], 255, self.on_trackbar)
        cv2.createTrackbar('Blur Size', 'IR Tuning', self.config["blur_size"], 15, self.on_trackbar)
        cv2.createTrackbar('Blur Type (0=Med,1=Gaus,2=Bil)', 'IR Tuning', self.config["blur_type"], 2, self.on_trackbar)
        
        # Morfologia
        cv2.createTrackbar('Morph Open', 'IR Tuning', self.config["morph_open"], 10, self.on_trackbar)
        cv2.createTrackbar('Morph Close', 'IR Tuning', self.config["morph_close"], 10, self.on_trackbar)
        
        # Filtrowanie konturów
        cv2.createTrackbar('Min Area', 'IR Tuning', self.config["min_area"], 100, self.on_trackbar)
        cv2.createTrackbar('Max Area', 'IR Tuning', self.config["max_area"], 2000, self.on_trackbar)
        cv2.createTrackbar('Min Circularity x100', 'IR Tuning', int(self.config["min_circularity"]*100), 100, self.on_trackbar)
        
        # Centroid
        cv2.createTrackbar('Peak Threshold x100', 'IR Tuning', int(self.config["peak_threshold"]*100), 100, self.on_trackbar)
        cv2.createTrackbar('Peak Power x10', 'IR Tuning', int(self.config["peak_power"]*10), 50, self.on_trackbar)
        
        # Filtr stabilizacji (One Euro)
        cv2.createTrackbar('Filter MinCutoff x100', 'IR Tuning', int(self.config["filter_mincutoff"]*100), 200, self.on_filter)
        cv2.createTrackbar('Filter Beta x1000', 'IR Tuning', int(self.config["filter_beta"]*1000), 500, self.on_filter)
    
    def on_exposure(self, val):
        if hasattr(self, 'initializing') and self.initializing:
            return
        self.config["exposure"] = val
        for idx in self.camera_indices:
            set_v4l2_ctrl(idx, "exposure", val)
    
    def on_gain(self, val):
        if hasattr(self, 'initializing') and self.initializing:
            return
        self.config["gain"] = val
        for idx in self.camera_indices:
            set_v4l2_ctrl(idx, "gain", val)
    
    def on_trackbar(self, val):
        if hasattr(self, 'initializing') and self.initializing:
            return
        # Odczytaj wszystkie wartości z trackbarów
        self.config["threshold"] = cv2.getTrackbarPos('Threshold', 'IR Tuning')
        self.config["blur_size"] = cv2.getTrackbarPos('Blur Size', 'IR Tuning')
        self.config["blur_type"] = cv2.getTrackbarPos('Blur Type (0=Med,1=Gaus,2=Bil)', 'IR Tuning')
        self.config["morph_open"] = cv2.getTrackbarPos('Morph Open', 'IR Tuning')
        self.config["morph_close"] = cv2.getTrackbarPos('Morph Close', 'IR Tuning')
        self.config["min_area"] = cv2.getTrackbarPos('Min Area', 'IR Tuning')
        self.config["max_area"] = cv2.getTrackbarPos('Max Area', 'IR Tuning')
        self.config["min_circularity"] = cv2.getTrackbarPos('Min Circularity x100', 'IR Tuning') / 100.0
        self.config["peak_threshold"] = cv2.getTrackbarPos('Peak Threshold x100', 'IR Tuning') / 100.0
        self.config["peak_power"] = cv2.getTrackbarPos('Peak Power x10', 'IR Tuning') / 10.0
    
    def on_filter(self, val):
        if hasattr(self, 'initializing') and self.initializing:
            return
        # Odczytaj parametry filtra z minimalnymi wartościami (unikamy dzielenia przez 0)
        self.config["filter_mincutoff"] = max(0.01, cv2.getTrackbarPos('Filter MinCutoff x100', 'IR Tuning') / 100.0)
        self.config["filter_beta"] = max(0.001, cv2.getTrackbarPos('Filter Beta x1000', 'IR Tuning') / 1000.0)
        
        # Aktualizuj istniejące filtry
        for cam_filters in self.filters:
            for f in cam_filters['x']:
                f.update_params(self.config["filter_mincutoff"], self.config["filter_beta"])
            for f in cam_filters['y']:
                f.update_params(self.config["filter_mincutoff"], self.config["filter_beta"])
    
    def calculate_stability(self, cam_idx, leds, filtered=False):
        """Oblicza stabilność punktów (odchylenie standardowe pozycji)"""
        history = self.position_history[cam_idx]
        stabilities = []
        
        for i, led in enumerate(leds[:5]):  # Max 5 punktów
            key = f"{i}_{'f' if filtered else 'r'}"
            pos = led["pos"]
            
            if key not in history:
                history[key] = []
            
            history[key].append(pos)
            if len(history[key]) > self.history_length:
                history[key].pop(0)
            
            if len(history[key]) >= 3:
                positions = np.array(history[key])
                std_x = np.std(positions[:, 0])
                std_y = np.std(positions[:, 1])
                stability = np.sqrt(std_x**2 + std_y**2)
                stabilities.append(stability)
        
        return np.mean(stabilities) if stabilities else 0.0
    
    def calculate_filtered_stability(self, cam_idx, filtered_positions):
        """Oblicza stabilność filtrowanych pozycji"""
        history = self.position_history[cam_idx]
        stabilities = []
        
        for i, (fx, fy) in enumerate(filtered_positions[:5]):
            key = f"{i}_filt"
            
            if key not in history:
                history[key] = []
            
            history[key].append((fx, fy))
            if len(history[key]) > self.history_length:
                history[key].pop(0)
            
            if len(history[key]) >= 3:
                positions = np.array(history[key])
                std_x = np.std(positions[:, 0])
                std_y = np.std(positions[:, 1])
                stability = np.sqrt(std_x**2 + std_y**2)
                stabilities.append(stability)
        
        return np.mean(stabilities) if stabilities else 0.0
    
    def update_stats(self, raw_stab, filt_stab):
        """Aktualizuje historię statystyk"""
        self.stats_history['raw'].append(raw_stab)
        self.stats_history['filtered'].append(filt_stab)
        
        # Ogranicz długość
        if len(self.stats_history['raw']) > self.stats_max_samples:
            self.stats_history['raw'].pop(0)
            self.stats_history['filtered'].pop(0)
    
    def get_stats_summary(self):
        """Zwraca podsumowanie statystyk"""
        if len(self.stats_history['raw']) < 10:
            return None
        
        raw = np.array(self.stats_history['raw'])
        filt = np.array(self.stats_history['filtered'])
        
        return {
            'raw_mean': np.mean(raw),
            'raw_std': np.std(raw),
            'raw_max': np.max(raw),
            'raw_p95': np.percentile(raw, 95),
            'filt_mean': np.mean(filt),
            'filt_std': np.std(filt),
            'filt_max': np.max(filt),
            'filt_p95': np.percentile(filt, 95),
            'improvement': (np.mean(raw) - np.mean(filt)) / np.mean(raw) * 100 if np.mean(raw) > 0 else 0,
            'samples': len(raw)
        }
    
    def process_frame(self, frame, cam_idx):
        """Przetwarza pojedynczą klatkę"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Blur
        blurred = apply_blur(gray, self.config["blur_type"], self.config["blur_size"])
        
        # Threshold
        _, thresh = cv2.threshold(blurred, self.config["threshold"], 255, cv2.THRESH_BINARY)
        
        # Morfologia
        thresh = apply_morphology(thresh, self.config["morph_open"], self.config["morph_close"])
        
        # Detekcja
        leds = detect_leds(gray, thresh, self.config)
        
        # WAŻNE: Sortuj punkty po X żeby były spójne między klatkami
        leds = sorted(leds, key=lambda p: p["pos"][0])[:10]
        
        # Oblicz stabilność (surowa)
        stability_raw = self.calculate_stability(cam_idx, leds, filtered=False)
        
        # Wizualizacja
        display = frame.copy()
        filtered_positions = []
        
        for i, led in enumerate(leds):  # Max 10 punktów (już posortowane)
            raw_x, raw_y = led["pos"]
            
            # Używaj filtra o tym samym indeksie (punkty posortowane po X)
            fx = self.filters[cam_idx]['x'][i]
            fy = self.filters[cam_idx]['y'][i]
            
            # Sprawdź czy filtr jest "rozgrzany" (ma poprzednią wartość)
            filter_ready = fx.x_prev is not None
            
            # Filtruj pozycję
            filt_x = fx.filter(raw_x)
            filt_y = fy.filter(raw_y)
            
            # Dodaj do listy tylko jeśli filtr jest gotowy
            if filter_ready:
                filtered_positions.append((filt_x, filt_y))
            
            # Różnica między surową a filtrowaną
            diff = np.sqrt((raw_x - filt_x)**2 + (raw_y - filt_y)**2) if filter_ready else 0
            
            # Kolor zależny od jasności (peak)
            peak = led["peak"]
            if peak > 200:
                raw_color = (0, 0, 255)  # Czerwony = prześwietlony
            elif peak > 100:
                raw_color = (0, 200, 0)  # Zielony = OK
            else:
                raw_color = (0, 255, 255)  # Żółty = słaby
            
            # Rysuj SUROWĄ pozycję (mały krzyżyk)
            cv2.drawMarker(display, (int(raw_x), int(raw_y)), raw_color, cv2.MARKER_CROSS, 12, 1)
            
            # Rysuj FILTROWANĄ pozycję tylko gdy filtr jest gotowy
            if filter_ready:
                cv2.circle(display, (int(filt_x), int(filt_y)), 8, (0, 255, 0), 2)
                
                # Linia między nimi
                if diff > 0.5:
                    cv2.line(display, (int(raw_x), int(raw_y)), (int(filt_x), int(filt_y)), (255, 255, 0), 1)
                
                # Info o punkcie
                cv2.putText(display, f"P:{peak:.0f} d:{diff:.1f}", (int(filt_x)+12, int(filt_y)), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)
            else:
                # Punkt nowy - pokaż tylko info
                cv2.putText(display, f"P:{peak:.0f} NEW", (int(raw_x)+12, int(raw_y)), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 165, 255), 1)
        
        # Oblicz stabilność filtrowaną
        stability_filt = self.calculate_filtered_stability(cam_idx, filtered_positions) if filtered_positions else 0.0
        
        # Aktualizuj statystyki
        self.update_stats(stability_raw, stability_filt)
        
        # Info ogólne - duża liczba punktów żeby było widać miganie
        pts_color = (0, 255, 0) if len(leds) >= 3 else (0, 0, 255)  # Czerwony gdy za mało punktów
        cv2.putText(display, f"CAM{cam_idx+1} Pts:{len(leds)}", 
                   (display.shape[1]-150, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, pts_color, 2)
        cv2.putText(display, f"RAW:{stability_raw:.2f}px | FILT:{stability_filt:.2f}px", 
                   (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
        
        # Legenda
        cv2.putText(display, "Cross=RAW | Circle=FILTERED", 
                   (10, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1)
        
        # Thresh preview (mały)
        thresh_small = cv2.resize(thresh, (160, 120))
        thresh_color = cv2.cvtColor(thresh_small, cv2.COLOR_GRAY2BGR)
        display[0:120, 0:160] = thresh_color
        
        return display, len(leds), stability_raw, stability_filt
    
    def start_test(self):
        """Rozpoczyna test 5-sekundowy"""
        self.test_mode = True
        self.test_start_time = time.time()
        # Wyczyść statystyki przed testem
        self.stats_history = {'raw': [], 'filtered': []}
        print("\n[TEST] Rozpoczęto test 5-sekundowy. Nie ruszaj drona!")
    
    def finish_test(self):
        """Kończy test i pokazuje wyniki"""
        self.test_mode = False
        stats = self.get_stats_summary()
        if stats:
            result = {
                'config': self.config.copy(),
                'stats': stats,
                'timestamp': time.strftime("%H:%M:%S")
            }
            self.test_results.append(result)
            
            print("\n" + "="*60)
            print(f"  TEST ZAKOŃCZONY - {stats['samples']} próbek")
            print("="*60)
            print(f"  RAW (surowe):      avg={stats['raw_mean']:.3f}px  p95={stats['raw_p95']:.3f}px  max={stats['raw_max']:.3f}px")
            print(f"  FILTERED:          avg={stats['filt_mean']:.3f}px  p95={stats['filt_p95']:.3f}px  max={stats['filt_max']:.3f}px")
            print(f"  POPRAWA:           {stats['improvement']:.1f}%")
            print("="*60)
            
            if len(self.test_results) > 1:
                print(f"\n  Poprzednie testy ({len(self.test_results)-1}):")
                for i, r in enumerate(self.test_results[:-1]):
                    s = r['stats']
                    print(f"    [{r['timestamp']}] raw={s['raw_mean']:.2f} filt={s['filt_mean']:.2f} ({s['improvement']:.0f}%)")
            print()
    
    def clear_stats(self):
        """Czyści statystyki"""
        self.stats_history = {'raw': [], 'filtered': []}
        if hasattr(self, '_filtered_history'):
            self._filtered_history = {}
        print("[INFO] Statystyki wyczyszczone")
    
    def save_config(self):
        """Zapisuje konfigurację do pliku"""
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=4)
        print(f"\n[SAVED] Konfiguracja zapisana do {CONFIG_FILE}")
        print("Parametry:")
        for k, v in self.config.items():
            print(f"  {k}: {v}")
    
    def run(self):
        """Główna pętla"""
        print("\n" + "="*60)
        print("  NARZĘDZIE DO STROJENIA DETEKCJI IR")
        print("="*60)
        print("Klawisze:")
        print("  's' - ZAPISZ konfigurację")
        print("  'r' - RESET do domyślnych")
        print("  '1','2','3' - pokaż tylko kamerę N")
        print("  'a' - pokaż wszystkie kamery")
        print("  ESC - wyjście")
        print("="*60 + "\n")
        
        show_cam = -1  # -1 = wszystkie
        
        while True:
            frames = []
            total_pts = 0
            total_raw = 0
            total_filt = 0
            
            for i, cap in enumerate(self.caps):
                ret, frame = cap.read()
                if not ret:
                    frames.append(np.zeros((480, 640, 3), dtype=np.uint8))
                    continue
                
                display, pts, stab_raw, stab_filt = self.process_frame(frame, i)
                frames.append(display)
                total_pts += pts
                total_raw += stab_raw
                total_filt += stab_filt
            
            # Składanie obrazu
            if show_cam >= 0 and show_cam < len(frames):
                # Pojedyncza kamera (powiększona)
                final = cv2.resize(frames[show_cam], (1280, 960))
            else:
                # Wszystkie kamery
                if len(frames) == 1:
                    final = frames[0]
                elif len(frames) == 2:
                    final = np.hstack([cv2.resize(f, (640, 480)) for f in frames])
                else:
                    row1 = np.hstack([cv2.resize(frames[0], (426, 320)), 
                                      cv2.resize(frames[1], (426, 320)) if len(frames) > 1 else np.zeros((320, 426, 3), dtype=np.uint8),
                                      cv2.resize(frames[2], (426, 320)) if len(frames) > 2 else np.zeros((320, 426, 3), dtype=np.uint8)])
                    final = row1
            
            # Panel info
            avg_raw = total_raw / len(self.caps) if self.caps else 0
            avg_filt = total_filt / len(self.caps) if self.caps else 0
            
            # Panel główny
            info_h = 120
            info_panel = np.zeros((info_h, final.shape[1], 3), dtype=np.uint8)
            
            # Kolor tła zależny od stabilności filtrowanej
            if avg_filt < 0.3:
                bg_color = (0, 60, 0)  # Zielony = bardzo stabilny
            elif avg_filt < 0.8:
                bg_color = (0, 60, 60)  # Żółty = OK
            else:
                bg_color = (0, 0, 60)  # Czerwony = niestabilny
            info_panel[:] = bg_color
            
            # Linia 1: Aktualne wartości
            cv2.putText(info_panel, f"Pts:{total_pts} | RAW:{avg_raw:.2f}px | FILTERED:{avg_filt:.2f}px", 
                       (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            # Linia 2: Statystyki (jeśli zebrane)
            stats = self.get_stats_summary()
            if stats:
                improve_color = (0, 255, 0) if stats['improvement'] > 0 else (0, 0, 255)
                cv2.putText(info_panel, 
                    f"AVG: raw={stats['raw_mean']:.2f} filt={stats['filt_mean']:.2f} | "
                    f"P95: raw={stats['raw_p95']:.2f} filt={stats['filt_p95']:.2f} | "
                    f"Improve: {stats['improvement']:.0f}%", 
                    (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, improve_color, 1)
                cv2.putText(info_panel, f"[{stats['samples']} samples]", 
                    (info_panel.shape[1]-150, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1)
            
            # Linia 3: Ustawienia
            cv2.putText(info_panel, 
                f"Exp:{self.config['exposure']} Gain:{self.config['gain']} Thr:{self.config['threshold']} | "
                f"Filter: mc={self.config['filter_mincutoff']:.2f} b={self.config['filter_beta']:.3f}", 
                (10, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
            
            # Linia 4: Klawisze
            cv2.putText(info_panel, "'s'=SAVE | 't'=TEST 5s | 'c'=CLEAR stats | ESC=EXIT", 
                       (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)
            
            # Test mode indicator
            if self.test_mode:
                elapsed = time.time() - self.test_start_time
                remaining = 5.0 - elapsed
                if remaining > 0:
                    cv2.putText(info_panel, f"TESTING... {remaining:.1f}s", 
                               (info_panel.shape[1]-200, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                else:
                    self.finish_test()
            
            final = np.vstack([final, info_panel])
            
            cv2.imshow('IR Tuning', final)
            
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # ESC
                break
            elif key == ord('s'):
                self.save_config()
            elif key == ord('r'):
                self.config = DEFAULT_CONFIG.copy()
                self.setup_gui()  # Odśwież trackbary
                print("[RESET] Przywrócono domyślne wartości")
            elif key == ord('t'):
                if not self.test_mode:
                    self.start_test()
            elif key == ord('c'):
                self.clear_stats()
            elif key == ord('1'):
                show_cam = 0
            elif key == ord('2'):
                show_cam = 1
            elif key == ord('3'):
                show_cam = 2
            elif key == ord('a'):
                show_cam = -1
        
        # Cleanup
        for cap in self.caps:
            cap.release()
        cv2.destroyAllWindows()

def main():
    # Znajdź kamery
    print("Szukam kamer...")
    indices = []
    for i in [2, 3, 4, 1, 5, 0]:
        if os.path.exists(f"/dev/video{i}"):
            cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    indices.append(i)
                    print(f"  [+] Znaleziono: /dev/video{i}")
                cap.release()
        if len(indices) >= 3:
            break
    
    if not indices:
        print("[ERROR] Nie znaleziono żadnych kamer!")
        return
    
    gui = TuningGUI(indices)
    gui.run()

if __name__ == "__main__":
    main()


