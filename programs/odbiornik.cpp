#include <Arduino.h>
#include <esp_now.h>
#include <WiFi.h>
#include <esp_wifi.h>

// === KONFIGURACJA PINÓW ===
// Piny do komunikacji z kontrolerem lotu drona (MSP)
#define RX_PIN_MSP 25
#define TX_PIN_MSP 26

// Ustawiamy ten sam kanał Wi-Fi co na nadajniku
#define WIFI_CHANNEL 1

// Struktura danych odbieranych przez ESP-NOW
typedef struct struct_message {
  uint16_t channels[16];
} struct_message;

// Struktura danych do wysłania (Telemetria)
typedef struct telemetry_message {
  float voltage;
} telemetry_message;

// Globalna zmienna na odbierane dane
struct_message receivedData;
telemetry_message telemetryData;

uint8_t transmitterMac[6] = {0};
bool transmitterKnown = false;

// ======================================================================
// === TWOJA SPRAWDZONA FUNKCJA WYSYŁAJĄCA DANE DO KONTROLERA LOTU ===
// Została skopiowana 1:1 z Twojego działającego kodu testowego.
void send_msp_rc_channels(uint16_t channels[16]) {
  uint8_t payload_size = 32;
  uint8_t command_id = 200;
  Serial2.write('$');
  Serial2.write('M');
  Serial2.write('<');
  Serial2.write(payload_size);
  Serial2.write(command_id);
  uint8_t checksum = 0;
  checksum ^= payload_size;
  checksum ^= command_id;
  for (int i = 0; i < 16; i++) {
    uint8_t lsb = channels[i] & 0xFF;
    uint8_t msb = (channels[i] >> 8) & 0xFF;
    Serial2.write(lsb);
    Serial2.write(msb);
    checksum ^= lsb;
    checksum ^= msb;
  }
  Serial2.write(checksum);
}
// ======================================================================

// Zmienne do obsługi maszyny stanów MSP
int msp_state = 0;
uint8_t msp_checksum = 0;
uint8_t msp_cmd = 0;
uint8_t msp_size = 0;
uint8_t msp_data[32];
uint8_t msp_data_index = 0;

void process_msp_byte(uint8_t c) {
  switch (msp_state) {
    case 0: // Czekamy na '$'
      if (c == '$') msp_state = 1; 
      break;
    case 1: // Czekamy na 'M'
      if (c == 'M') msp_state = 2; 
      else msp_state = 0; 
      break;
    case 2: // Czekamy na '>'
      if (c == '>') msp_state = 3; 
      else msp_state = 0; 
      break;
    case 3: // Rozmiar danych
      msp_size = c; 
      msp_checksum = c; 
      msp_state = 4; 
      break;
    case 4: // Komenda
      msp_cmd = c; 
      msp_checksum ^= c; 
      msp_data_index = 0; 
      msp_state = (msp_size > 0) ? 5 : 6; 
      break;
    case 5: // Dane
      if (msp_data_index < sizeof(msp_data)) {
        msp_data[msp_data_index++] = c;
        msp_checksum ^= c;
      }
      if (msp_data_index == msp_size) msp_state = 6; 
      break;
    case 6: // Suma kontrolna
      if (msp_checksum == c) {
        // Prawidłowy pakiet odebrany!
        if (msp_cmd == 110) { // MSP_ANALOG
           uint8_t vbat = msp_data[0];
           telemetryData.voltage = (float)vbat / 10.0;
           
           // Wyślij do nadajnika, jeśli znamy jego adres
           if (transmitterKnown) {
             esp_now_send(transmitterMac, (uint8_t *) &telemetryData, sizeof(telemetryData));
           }
        }
      }
      msp_state = 0; 
      break;
  }
}

void loop() {
  // 1. Wysyłaj zapytanie o telemetrię (MSP_ANALOG) co 100ms
  if (millis() - lastMspRequest > 100) {
    request_msp_analog();
    lastMspRequest = millis();
  }

  // 2. Odczytuj odpowiedź z FC bajt po bajcie
  while (Serial2.available() > 0) {
    uint8_t c = Serial2.read();
    process_msp_byte(c);
  }
}