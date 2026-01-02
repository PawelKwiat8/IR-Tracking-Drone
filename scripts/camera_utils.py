import os
import glob
import json
import time

# Plik przechowujący aktualne mapowanie: ID Kamery (np. "1") -> Ścieżka (np. "/dev/video2")
CAMERA_MAP_FILE = "camera_map.json"

def load_camera_map():
    if os.path.exists(CAMERA_MAP_FILE):
        try:
            with open(CAMERA_MAP_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def get_camera_id(video_dev_path):
    """
    Zwraca logiczne ID kamery (np. "cam_1") na podstawie mapowania stworzonego przez setup_cameras.py.
    Jeśli kamera nie jest zmapowana, zwraca fallback oparty na ścieżce USB.
    """
    real_path = os.path.realpath(video_dev_path)
    mapping = load_camera_map()
    
    # 1. Sprawdź czy ta ścieżka jest przypisana do jakiegoś logicznego ID
    for cam_id, map_path in mapping.items():
        if os.path.exists(map_path) and os.path.realpath(map_path) == real_path:
            return cam_id
            
    # 2. Fallback: Jeśli nie zmapowano, użyj ścieżki by-path (dla kompatybilności)
    try:
        for path in glob.glob("/dev/v4l/by-path/*"):
            if os.path.realpath(path) == real_path:
                return os.path.basename(path)
    except:
        pass
        
    return f"unknown_{os.path.basename(video_dev_path)}"
