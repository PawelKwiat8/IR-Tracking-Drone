#include <Arduino.h>
#include <esp_now.h>
#include <WiFi.h>
#include <esp_wifi.h>

// === KONFIGURACJA PINÓW ===
// Piny do komunikacji z kontrolerem lotu drona (MSP)
#define RX_PIN_MSP 4
#define TX_PIN_MSP 5

// Definiujemy własny obiekt Serial dla MSP
HardwareSerial SerialMSP(1);

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
  SerialMSP.write('$');
  SerialMSP.write('M');
  SerialMSP.write('<');
  SerialMSP.write(payload_size);
  SerialMSP.write(command_id);
  uint8_t checksum = 0;
  checksum ^= payload_size;
  checksum ^= command_id;
  for (int i = 0; i < 16; i++) {
    uint8_t lsb = channels[i] & 0xFF;
    uint8_t msb = (channels[i] >> 8) & 0xFF;
    SerialMSP.write(lsb);
    SerialMSP.write(msb);
    checksum ^= lsb;
    checksum ^= msb;
  }
  SerialMSP.write(checksum);
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
           
           // Debug: Pokaż napięcie w Serial Monitorze
           Serial.print("MSP Voltage: ");
           Serial.println(telemetryData.voltage);

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

unsigned long lastMspRequest = 0;
unsigned long lastHeartbeat = 0;

void request_msp_analog() {
  uint8_t payload_size = 0;
  uint8_t command_id = 110; // MSP_ANALOG
  uint8_t checksum = payload_size ^ command_id;

  SerialMSP.write('$');
  SerialMSP.write('M');
  SerialMSP.write('<');
  SerialMSP.write(payload_size);
  SerialMSP.write(command_id);
  SerialMSP.write(checksum);
}

// Callback - funkcja, która uruchomi się, gdy otrzymamy dane z ESP-NOW
void OnDataRecv(const uint8_t * mac, const uint8_t *incomingData, int len) {
  // Zapisz adres nadajnika, jeśli jeszcze go nie znamy
  if (!transmitterKnown) {
    memcpy(transmitterMac, mac, 6);
    transmitterKnown = true;
    
    // Rejestracja peer-a (nadajnika)
    esp_now_peer_info_t peerInfo = {};
    memcpy(peerInfo.peer_addr, transmitterMac, 6);
    peerInfo.channel = WIFI_CHANNEL;
    peerInfo.encrypt = false;
    if (esp_now_add_peer(&peerInfo) != ESP_OK){
      transmitterKnown = false; 
    }
  }

  // Kopiujemy odebrane dane do naszej struktury
  if (len == sizeof(struct_message)) {
      memcpy(&receivedData, incomingData, sizeof(receivedData));
      // Wysyłamy odebrane kanały do drona
      send_msp_rc_channels(receivedData.channels);
  }
}

void setup() {
  Serial.begin(115200);
  delay(2000); // Dłuższe opóźnienie na start Seriala
  Serial.println("--- START SYSTEMU ---");
  Serial.print("Adres MAC Odbiornika: ");
  Serial.println(WiFi.macAddress());
  Serial.println("--- ODBIORNIK DLA DRONA (MSP + TELEMETRIA) ---");

  // Inicjalizacja SerialMSP dla MSP
  // Upewniamy się, że piny są poprawnie przypisane
  SerialMSP.begin(115200, SERIAL_8N1, RX_PIN_MSP, TX_PIN_MSP);
  Serial.println("Port SerialMSP (MSP) skonfigurowany na pinach 4(RX) i 5(TX).");
  
  WiFi.mode(WIFI_STA);
  esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);

  if (esp_now_init() != ESP_OK) {
    Serial.println("Blad inicjalizacji ESP-NOW");
    return;
  }
  
  esp_now_register_recv_cb(OnDataRecv);
  Serial.println("ESP-NOW gotowy. Oczekiwanie na dane...");
}

void loop() {
  // 0. Heartbeat - aby widzieć czy pętla żyje
  if (millis() - lastHeartbeat > 2000) {
    Serial.print("Loop running... MAC: ");
    Serial.println(WiFi.macAddress());
    lastHeartbeat = millis();
  }

  // 1. Wysyłaj zapytanie o telemetrię (MSP_ANALOG) co 100ms
  if (millis() - lastMspRequest > 100) {
    request_msp_analog();
    lastMspRequest = millis();
  }

  // 2. Odczytuj odpowiedź z FC bajt po bajcie
  while (SerialMSP.available() > 0) {
    uint8_t c = SerialMSP.read();
    process_msp_byte(c);
  }
}