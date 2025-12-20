#include <Arduino.h>
#include <esp_now.h>
#include <WiFi.h>
#include <esp_wifi.h>

#define WIFI_CHANNEL 1

// Adres Broadcast - wysyłamy do wszystkich (w tym do Nadajnika)
// Można tu wpisać konkretny adres MAC Nadajnika, jeśli jest znany.
uint8_t broadcastAddress[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

// Struktura danych sterowania (Odbierana z Nadajnika)
typedef struct struct_control {
  uint16_t channels[16];
} struct_control;

struct_control controlData;

// Struktura danych Blackbox (Wysyłana do Nadajnika)
typedef struct struct_blackbox {
  uint8_t buffer[200];
  uint8_t len;
} struct_blackbox;

struct_blackbox blackboxData;

// Callback po odebraniu danych sterowania z Nadajnika
void OnDataRecv(const uint8_t * mac, const uint8_t *incomingData, int len) {
  if (len == sizeof(struct_control)) {
    memcpy(&controlData, incomingData, sizeof(controlData));

    // Tutaj normalnie przekazujemy dane do FC (np. generując sygnał PPM, SBUS lub PWM)
    // W oryginalnym kodzie było tylko wypisywanie na Serial.
    // UWAGA: Jeśli Serial jest zajęty przez Blackbox (RX), to pisanie na TX (Serial.print)
    // może zakłócać komunikację, jeśli FC nie spodziewa się danych tekstowych.
    // Dla bezpieczeństwa testu Blackbox, zakomentuję wypisywanie debugowania na Serial,
    // chyba że jest to absolutnie konieczne do sterowania (np. MSP RX).
    
    // Serial.print("Odebrano! R: "); ... 
  }
}

// Callback po wysłaniu danych (Blackbox)
void OnDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
  // status check
}
 
void setup() {
  // Prędkość Serial musi być taka sama jak ustawiona w Betaflight w zakładce Ports dla Blackbox
  // Standardowo 115200 lub 250000. Dla testu ESP-NOW bezpieczniej 115200.
  Serial.begin(115200);
  
  WiFi.mode(WIFI_STA);
  esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);

  if (esp_now_init() != ESP_OK) {
    return;
  }
  
  esp_now_register_recv_cb(OnDataRecv);
  esp_now_register_send_cb(OnDataSent);

  // Rejestracja partnera (Broadcast)
  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, broadcastAddress, 6);
  peerInfo.channel = WIFI_CHANNEL;  
  peerInfo.encrypt = false;
  peerInfo.ifidx = WIFI_IF_STA;
  
  if (esp_now_add_peer(&peerInfo) != ESP_OK){
    return;
  }
}
 
void loop() {
  // Odczyt danych z portu Serial (dane Blackbox z FC)
  int available = Serial.available();
  
  if (available > 0) {
    // Czytamy paczkę danych
    int toRead = available;
    // Ograniczamy do rozmiaru bufora w strukturze (200 bajtów)
    if (toRead > 200) toRead = 200;
    
    blackboxData.len = Serial.readBytes(blackboxData.buffer, toRead);
    
    // Wysyłamy paczkę do Nadajnika
    esp_now_send(broadcastAddress, (uint8_t *) &blackboxData, sizeof(blackboxData));
  }
  
  // Brak delay() lub bardzo mały, żeby nie gubić danych z Seriala
}
