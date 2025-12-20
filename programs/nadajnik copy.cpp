#include <Arduino.h>
#include <esp_now.h>
#include <WiFi.h>
#include <esp_wifi.h> // <-- DODANY BRAKUJĄCY PLIK NAGŁÓWKOWY

// Ustawiamy sztywny kanał Wi-Fi dla komunikacji. Musi być taki sam na odbiorniku.
#define WIFI_CHANNEL 1

// ADRES MAC TWOJEGO ODBIORNIKA
uint8_t broadcastAddress[] = {0xB8, 0xF8, 0x62, 0x04, 0x74, 0x50};

typedef struct struct_message {
  uint16_t channels[16];
} struct_message;

// Struktura danych do odebrania (Telemetria)
typedef struct telemetry_message {
  float voltage;
} telemetry_message;

struct_message myData;
telemetry_message receivedTelemetry;

void OnDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
  if (status != ESP_NOW_SEND_SUCCESS) {
    Serial.println("Blad wysylania danych!");
  }
}

void OnDataRecv(const uint8_t * mac, const uint8_t *incomingData, int len) {
  if (len == sizeof(telemetry_message)) {
    memcpy(&receivedTelemetry, incomingData, sizeof(receivedTelemetry));
    // Wysyłamy sformatowany ciąg do PC przez Serial
    Serial.print("TLM:");
    Serial.println(receivedTelemetry.voltage);
  }
}
 
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("--- NADAJNIK ESP-NOW ---");

  WiFi.mode(WIFI_STA);

  // Ustawienie kanału Wi-Fi na sztywno
  esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);
  
  // Inicjalizacja ESP-NOW
  if (esp_now_init() != ESP_OK) {
    Serial.println("Blad inicjalizacji ESP-NOW");
    return;
  }

  esp_now_register_send_cb(OnDataSent);
  esp_now_register_recv_cb(OnDataRecv);
  
  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, broadcastAddress, 6);
  peerInfo.channel = WIFI_CHANNEL;
  peerInfo.encrypt = false;
  peerInfo.ifidx = WIFI_IF_STA;
  
  if (esp_now_add_peer(&peerInfo) != ESP_OK){
    Serial.println("Nie udalo sie dodac partnera");
    return;
  }
  
  Serial.println("Partner dodany poprawnie. Oczekiwanie na dane z PC...");
}

void loop() {
  if (Serial.available() > 0) {
    String incomingString = Serial.readStringUntil('\n');
    
    int channel_index = 0;
    int last_index = 0;
    for (int i = 0; i < incomingString.length(); i++) {
      if (incomingString.charAt(i) == ',') {
        if (channel_index < 16) {
          String valStr = incomingString.substring(last_index, i);
          myData.channels[channel_index] = valStr.toInt();
          channel_index++;
          last_index = i + 1;
        }
      }
    }
    esp_now_send(broadcastAddress, (uint8_t *) &myData, sizeof(myData));
  }
  delay(5);
}