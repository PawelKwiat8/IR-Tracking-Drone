# IR-Tracking-Drone

Projekt niestandardowego systemu sterowania dronem opartego na modułach ESP32, wykorzystujący protokół ESP-NOW do bezprzewodowej transmisji danych oraz protokół MSP do komunikacji z kontrolerem lotu.

## Główne założenia systemu

System umożliwia sterowanie dronem za pomocą kontrolera (joysticka/aparatury) podłączonego do komputera lub dedykowanego interfejsu webowego. Dane są przesyłane do drona poprzez mostek radiowy zbudowany z dwóch modułów ESP32.

### Architektura połączeń:
1.  **PC (Python Script / Web Interface)**: Odczytuje dane sterujące (np. z joysticka aparatury w trybie symulatora), mapuje je na kanały RC i przesyła do nadajnika.
2.  **Nadajnik (ESP32 TX)**: Odbiera dane z PC (przez Serial lub WebSocket) i transmituje je bezprzewodowo za pomocą niskolatencyjnego protokołu **ESP-NOW**.
3.  **Odbiornik (ESP32 RX)**: Odbiera pakiety ESP-NOW, konwertuje je na ramki protokołu **MSP (MultiWii Serial Protocol)** i przesyła bezpośrednio do kontrolera lotu (FC).
4.  **Telemetria**: System wspiera dwukierunkową komunikację – odbiornik pobiera dane o napięciu baterii z FC (komenda MSP_ANALOG) i przesyła je z powrotem do nadajnika, a następnie do PC.

## Co zostało zrealizowane

-   **Obsługa Joysticka (Python)**: Skrypt `scripts/joystick_bridge.py` wykorzystuje `pygame` do obsługi kontrolerów HID. Zawiera logikę mapowania osi na zakresy RC (1000-2000 µs) oraz obsługę przełączników (np. ARM).
-   **Komunikacja bezprzewodowa**: Implementacja stabilnego połączenia ESP-NOW z obsługą parowania adresów MAC i wymianą danych w czasie rzeczywistym.
-   **Integracja z Kontrolerem Lotu**:
    -   Implementacja maszyny stanów do obsługi protokołu **MSP**.
    -   Wysyłanie danych sterujących `MSP_SET_RAW_RC` (16 kanałów).
    -   Pobieranie i wyświetlanie telemetrii (napięcie baterii).
-   **Interfejsy alternatywne**: Dodatkowa wersja nadajnika z wbudowanym serwerem WWW i interfejsem sterowania przez WebSocket.
-   **Narzędzia diagnostyczne**: Skrypty do wykrywania podłączonych joysticków oraz obsługa przesyłania danych Blackbox przez ESP-NOW.

## Struktura projektu

-   `/scripts/`: Skrypty Python do obsługi joysticka i mostkowania danych Serial.
-   `/src/main.cpp`: Główny kod nadajnika (TX) współpracujący z PC.
-   `/programs/`: Różne wersje oprogramowania (odbiornik, wersja Blackbox, wersja Web).
-   `platformio.ini`: Konfiguracja środowiska PlatformIO dla ESP32.

## Wymagania

-   2x ESP32 (np. DevKit V1).
-   Kontroler lotu (FC) wspierający protokół MSP na wolnym porcie UART (np. Betaflight, INAV).
-   Aparatura RC lub joystick podłączony do PC (opcjonalnie dla trybu joystick_bridge).
-   Python 3.x + `pygame`, `pyserial`.

## Szybki start

1.  Zidentyfikuj adres MAC swojego odbiornika ESP32.
2.  Wprowadź adres MAC w pliku `src/main.cpp` (nadajnik).
3.  Skompiluj i wgraj oprogramowanie na oba moduły ESP32.
4.  Podłącz odbiornik do portu UART kontrolera lotu (TX->RX, RX->TX).
5.  Uruchom `scripts/joystick_bridge.py` na komputerze i rozpocznij sterowanie.
