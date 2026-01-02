"""
Wizualizacja 3D systemu Motion Capture używając OpenCV
Pokazuje pozycje kamer i aktualną pozycję drona w czasie rzeczywistym.
Projekcja izometryczna bez zewnętrznych bibliotek.
"""

import cv2
import numpy as np
from collections import deque
import time
import os

os.environ["QT_QPA_PLATFORM"] = "xcb"

class MocapVisualizer:
    def __init__(self, data_queue, camera_poses=None):
        self.data_queue = data_queue
        self.camera_poses = camera_poses or []
        
        # Historia pozycji drona (trajektoria)
        self.trajectory = deque(maxlen=300)
        
        # Pozycja drona
        self.drone_pos = None
        self.drone_heading = None
        
        # Rozmiar okna
        self.width = 800
        self.height = 600
        
        # Parametry projekcji izometrycznej
        self.scale = 200  # pikseli na metr
        self.center_x = self.width // 2
        self.center_y = self.height // 2 + 100
        
        # Kąty obrotu widoku (w stopniach)
        self.rot_x = 30  # pochylenie
        self.rot_z = 45  # obrót wokół osi Z
        
        # Kolory
        self.bg_color = (30, 30, 30)
        self.grid_color = (60, 60, 60)
        self.axis_colors = [(0, 0, 255), (0, 255, 0), (255, 0, 0)]  # X=czerwony, Y=zielony, Z=niebieski
        self.cam_colors = [(255, 150, 50), (50, 255, 150), (150, 50, 255)]
        self.drone_color = (0, 0, 255)
        self.trajectory_color = (100, 100, 255)
        
    def project_3d_to_2d(self, x, y, z):
        """Projekcja punktu 3D na 2D (izometryczna)"""
        # Rotacja wokół Z
        rz = np.radians(self.rot_z)
        x1 = x * np.cos(rz) - y * np.sin(rz)
        y1 = x * np.sin(rz) + y * np.cos(rz)
        z1 = z
        
        # Rotacja wokół X (pochylenie)
        rx = np.radians(self.rot_x)
        y2 = y1 * np.cos(rx) - z1 * np.sin(rx)
        z2 = y1 * np.sin(rx) + z1 * np.cos(rx)
        x2 = x1
        
        # Projekcja na ekran
        screen_x = int(self.center_x + x2 * self.scale)
        screen_y = int(self.center_y - z2 * self.scale)  # Y ekranu rośnie w dół
        
        return screen_x, screen_y
    
    def draw_grid(self, img):
        """Rysuje siatkę podłogi"""
        grid_size = 1.0  # metr
        grid_range = 2  # od -2 do 2
        
        for i in range(-grid_range, grid_range + 1):
            # Linie równoległe do X
            p1 = self.project_3d_to_2d(-grid_range * grid_size, i * grid_size, 0)
            p2 = self.project_3d_to_2d(grid_range * grid_size, i * grid_size, 0)
            cv2.line(img, p1, p2, self.grid_color, 1)
            
            # Linie równoległe do Y
            p1 = self.project_3d_to_2d(i * grid_size, -grid_range * grid_size, 0)
            p2 = self.project_3d_to_2d(i * grid_size, grid_range * grid_size, 0)
            cv2.line(img, p1, p2, self.grid_color, 1)
    
    def draw_axes(self, img):
        """Rysuje osie X, Y, Z"""
        origin = self.project_3d_to_2d(0, 0, 0)
        
        # Oś X (czerwona)
        px = self.project_3d_to_2d(0.5, 0, 0)
        cv2.arrowedLine(img, origin, px, self.axis_colors[0], 2, tipLength=0.2)
        cv2.putText(img, "X", px, cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.axis_colors[0], 1)
        
        # Oś Y (zielona)
        py = self.project_3d_to_2d(0, 0.5, 0)
        cv2.arrowedLine(img, origin, py, self.axis_colors[1], 2, tipLength=0.2)
        cv2.putText(img, "Y", py, cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.axis_colors[1], 1)
        
        # Oś Z (niebieska)
        pz = self.project_3d_to_2d(0, 0, 0.5)
        cv2.arrowedLine(img, origin, pz, self.axis_colors[2], 2, tipLength=0.2)
        cv2.putText(img, "Z", pz, cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.axis_colors[2], 1)
        
    def draw_camera(self, img, R, t, color, label):
        """Rysuje kamerę jako kropkę z kierunkiem patrzenia"""
        # Pozycja kamery w świecie
        R = np.array(R)
        t = np.array(t).flatten()
        cam_pos = -R.T @ t
        
        # Kierunek patrzenia kamery (krótka strzałka)
        view_vector = R.T @ np.array([0, 0, 1])
        cam_dir = view_vector * 0.3
        
        # Rysuj pozycję kamery
        p = self.project_3d_to_2d(*cam_pos)
        cv2.circle(img, p, 8, color, -1)
        cv2.putText(img, label, (p[0] + 15, p[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        
        # Rysuj dłuższą, cienką linię kierunku (pole widzenia)
        line_length = 3.0 # 3 metry długości
        p_far = self.project_3d_to_2d(*(cam_pos + view_vector * line_length))
        cv2.line(img, p, p_far, color, 1) # Grubość 1 dla lekkości
        
        # Rysuj krótką strzałkę kierunku
        p_dir = self.project_3d_to_2d(*(cam_pos + cam_dir))
        cv2.arrowedLine(img, p, p_dir, color, 2, tipLength=0.3)
        
    def draw_drone(self, img):
        """Rysuje drona"""
        if self.drone_pos is None:
            return
            
        p = self.project_3d_to_2d(*self.drone_pos)
        
        # Główny punkt drona
        cv2.circle(img, p, 12, self.drone_color, -1)
        cv2.circle(img, p, 14, (255, 255, 255), 2)
        
        # Kierunek (heading)
        if self.drone_heading is not None:
            dx = 0.2 * np.cos(self.drone_heading)
            dy = 0.2 * np.sin(self.drone_heading)
            p_dir = self.project_3d_to_2d(self.drone_pos[0] + dx, 
                                          self.drone_pos[1] + dy, 
                                          self.drone_pos[2])
            cv2.arrowedLine(img, p, p_dir, (0, 255, 255), 3, tipLength=0.4)
    
    def draw_trajectory(self, img):
        """Rysuje trajektorię drona"""
        if len(self.trajectory) < 2:
            return
            
        points = []
        for pos in self.trajectory:
            p = self.project_3d_to_2d(*pos)
            points.append(p)
        
        for i in range(1, len(points)):
            alpha = i / len(points)  # Starsze punkty są bardziej przezroczyste
            color = tuple(int(c * alpha) for c in self.trajectory_color)
            cv2.line(img, points[i-1], points[i], color, 1)
    
    def draw_info(self, img):
        """Rysuje informacje tekstowe"""
        y = 30
        cv2.putText(img, "WIZUALIZACJA 3D", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        y += 30
        
        if self.drone_pos is not None:
            pos_str = f"Dron: X={self.drone_pos[0]:.2f} Y={self.drone_pos[1]:.2f} Z={self.drone_pos[2]:.2f}"
            cv2.putText(img, pos_str, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            y += 25
            
            if self.drone_heading is not None:
                hdg_str = f"Heading: {np.degrees(self.drone_heading):.1f} deg"
                cv2.putText(img, hdg_str, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        else:
            cv2.putText(img, "Dron: nie wykryty", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 100), 1)
        
        # Instrukcja
        cv2.putText(img, "Q/E: obrot | W/X: pochylenie | +/-: zoom | ESC: wyjdz", 
                    (20, self.height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1)
    
    def update_from_queue(self):
        """Pobiera nowe dane z kolejki"""
        updated = False
        while not self.data_queue.empty():
            try:
                data = self.data_queue.get_nowait()
                
                if 'camera_poses' in data:
                    self.camera_poses = data['camera_poses']
                    
                if 'drone_pos' in data and data['drone_pos'] is not None:
                    self.drone_pos = np.array(data['drone_pos'])
                    self.trajectory.append(self.drone_pos.copy())
                    
                if 'drone_heading' in data:
                    self.drone_heading = data['drone_heading']
                    
                updated = True
            except:
                break
        return updated
    
    def render(self):
        """Renderuje scenę"""
        img = np.full((self.height, self.width, 3), self.bg_color, dtype=np.uint8)
        
        # Rysuj elementy (od tyłu do przodu)
        self.draw_grid(img)
        self.draw_axes(img)
        
        # Rysuj kamery
        for i, pose in enumerate(self.camera_poses):
            color = self.cam_colors[i % len(self.cam_colors)]
            self.draw_camera(img, pose['R'], pose['t'], color, f'Cam {i}')
        
        # Rysuj trajektorię i drona
        self.draw_trajectory(img)
        self.draw_drone(img)
        
        # Informacje tekstowe
        self.draw_info(img)
        
        return img
    
    def run(self):
        """Główna pętla wizualizatora"""
        print("Wizualizator 3D uruchomiony. Naciśnij ESC, aby zamknąć.")
        
        cv2.namedWindow('Wizualizacja 3D')
        
        while True:
            self.update_from_queue()
            img = self.render()
            cv2.imshow('Wizualizacja 3D', img)
            
            key = cv2.waitKey(30) & 0xFF
            if key == 27:  # ESC
                break
            elif key == ord('q'):
                self.rot_z -= 5
            elif key == ord('e'):
                self.rot_z += 5
            elif key == ord('w'):
                self.rot_x = min(89, self.rot_x + 5)
            elif key == ord('x'):
                self.rot_x = max(-89, self.rot_x - 5)
            elif key == ord('+') or key == ord('='):
                self.scale = min(500, self.scale + 20)
            elif key == ord('-'):
                self.scale = max(50, self.scale - 20)
        
        cv2.destroyWindow('Wizualizacja 3D')
        print("Wizualizator zamknięty.")


def run_visualizer(data_queue):
    """Funkcja do uruchomienia w osobnym procesie"""
    viz = MocapVisualizer(data_queue)
    viz.run()


if __name__ == "__main__":
    # Test standalone
    from multiprocessing import Queue
    
    q = Queue()
    viz = MocapVisualizer(q)
    
    # Przykładowe pozycje kamer
    viz.camera_poses = [
        {'R': np.eye(3).tolist(), 't': [[0], [0], [0]]},
        {'R': np.eye(3).tolist(), 't': [[0.5], [0], [0.3]]},
        {'R': np.eye(3).tolist(), 't': [[-0.5], [0], [0.3]]}
    ]
    
    # Symulacja ruchu drona
    t = 0
    while True:
        viz.drone_pos = np.array([0.3 * np.sin(t), 0.3 * np.cos(t), 0.3 + 0.1 * np.sin(t*2)])
        viz.drone_heading = t
        viz.trajectory.append(viz.drone_pos.copy())
        
        img = viz.render()
        cv2.imshow('Wizualizacja 3D', img)
        
        key = cv2.waitKey(30) & 0xFF
        if key == 27:
            break
        elif key == ord('q'):
            viz.rot_z -= 5
        elif key == ord('e'):
            viz.rot_z += 5
        elif key == ord('w'):
            viz.rot_x = min(89, viz.rot_x + 5)
        elif key == ord('x'):
            viz.rot_x = max(-89, viz.rot_x - 5)
            
        t += 0.05
    
    cv2.destroyAllWindows()
