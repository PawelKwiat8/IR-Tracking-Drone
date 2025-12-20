import pygame
import serial
import time

# ==============================================================================
# ===                            SEKCJA KONFIGURACJI                           ===
# === TUTAJ WPROWADŹ ZMIANY ZGODNIE ZE SWOIMI POTRZEBAMI                      ===
# ==============================================================================

# Ustaw poprawny port COM dla Nadajnika ESP32
ESP32_COM_PORT = 'COM20' 
BAUD_RATE = 115200

# --- KALIBRACJA DRĄŻKÓW (Wartości do odjęcia od wyniku 1000-2000) ---
# Jeśli Roll w centrum pokazuje 1506, wpisz 6. Jeśli 1498, wpisz -2.
ROLL_OFFSET = 6
PITCH_OFFSET = 0
THROTTLE_OFFSET = 0
YAW_OFFSET = 0

# --- MAPOWANIE OSI DRĄŻKÓW ---
# Numery osi, które odpowiadają za drążki
AXIS_ROLL = 0
AXIS_PITCH = 1
AXIS_THROTTLE = 2
AXIS_YAW = 3

# --- MAPOWANIE PRZEŁĄCZNIKA ARM (działającego jako oś) ---
# Numer osi, która odpowiada za przełącznik ARM
ARM_SWITCH_AXIS = 4
# Próg, po którym przełącznik jest "włączony" (gdy oś > 0.0)
ARM_SWITCH_AXIS_THRESHOLD = 0.0
# Na którym kanale AUX ma być wysyłany sygnał ARM (indeks 4 = AUX1)
ARM_SWITCH_CHANNEL = 4

# ==============================================================================
# ===                        KONIEC SEKCJI KONFIGURACJI                      ===
# ==============================================================================


# Inicjalizacja Pygame i Joysticka
pygame.init()
pygame.joystick.init()
if pygame.joystick.get_count() == 0:
    print("BŁĄD: Nie znaleziono żadnego joysticka (radia)! Podłącz RadioMaster.")
    exit()
joystick = pygame.joystick.Joystick(0)
joystick.init()
print(f"Znaleziono joystick: {joystick.get_name()}")

# Inicjalizacja Portu Szeregowego
try:
    ser = serial.Serial(ESP32_COM_PORT, BAUD_RATE, timeout=1)
    print(f"Połączono z ESP32 na porcie {ESP32_COM_PORT}")
except serial.SerialException as e:
    print(f"BŁĄD: Nie można otworzyć portu {ESP32_COM_PORT}. Sprawdź numer portu.")
    exit()

time.sleep(2)

# Funkcje mapujące
def map_axis(value):
    """Mapuje wartość osi centrującej (-1.0 do 1.0) na zakres RC (1000 do 2000)"""
    return int(1500 + value * 500)

def map_throttle(value):
    """Mapuje wartość osi przepustnicy (-1.0 do 1.0) na zakres RC (1000 do 2000)"""
    return int(1000 + (value + 1) * 500)

# Główna pętla
try:
    print("Rozpoczęto wysyłanie danych... Naciśnij Ctrl+C aby zakończyć.")
    voltage_display = "?.?V" # Inicjalizacja zmiennej przed pętlą
    
    while True:
        pygame.event.pump()

        # Tworzymy listę 16 kanałów, domyślnie ustawioną na środek
        channels = [1500] * 16
        
        # --- ZMODYFIKOWANA LOGIKA ODCZYTU KANAŁÓW ---
        
        # 1. Odczyt i mapowanie głównych osi z uwzględnieniem kalibracji
        channels[0] = map_axis(joystick.get_axis(AXIS_ROLL)) - ROLL_OFFSET
        channels[1] = map_axis(joystick.get_axis(AXIS_PITCH)) - PITCH_OFFSET
        channels[2] = map_throttle(joystick.get_axis(AXIS_THROTTLE)) - THROTTLE_OFFSET
        channels[3] = map_axis(joystick.get_axis(AXIS_YAW)) - YAW_OFFSET

        # 2. Odczyt przełącznika ARM (działającego jako oś)
        is_armed = joystick.get_axis(ARM_SWITCH_AXIS) > ARM_SWITCH_AXIS_THRESHOLD
        channels[ARM_SWITCH_CHANNEL] = 2000 if is_armed else 1000
        
        # Konwersja na string i wysyłka do ESP32
        data_string = ",".join(map(str, channels)) + '\n'
        ser.write(data_string.encode('utf-8'))
        
        # 3. Odczyt telemetrii z ESP32 (jeśli dostępna)
        # Nie resetujemy voltage_display w każdej pętli, żeby nie migało
        while ser.in_waiting > 0:
            try:
                # Czytamy linię
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line.startswith("TLM:"):
                    voltage_display = line.split(":")[1] + "V"
            except Exception:
                pass

        # 4. Ulepszone wyświetlanie statusu w terminalu
        arm_status = "ARMED" if is_armed else "DISARMED"
        print(f"R:{channels[0]} P:{channels[1]} T:{channels[2]} Y:{channels[3]} | AUX1({arm_status}) | BAT: {voltage_display}   ", end='\r')
        
        time.sleep(0.02)

except KeyboardInterrupt:
    print("\nZamykanie programu.")
finally:
    joystick.quit()
    ser.close()