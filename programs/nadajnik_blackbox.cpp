#include <Arduino.h>
#include <esp_now.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <SPI.h>
#include <SD.h>

// --- KONFIGURACJA KARTY SD ---
#define SD_CS 4
#define SD_MOSI 23
#define SD_MISO 19
#define SD_SCK 18

// --- KONFIGURACJA WIFI ---
#define WIFI_CHANNEL 1

// ADRES MAC ODBIORNIKA (Ten sam co w nadajnik copy.cpp)
uint8_t receiverAddress[] = {0x78, 0x42, 0x1C, 0x68, 0x74, 0xF0};

// Struktura danych sterowania (Nadajnik -> Odbiornik)
typedef struct struct_control {
  uint16_t channels[16];
} struct_control;

struct_control controlData;

// Struktura danych Blackbox (Odbiornik -> Nadajnik)
// Max payload ESP-NOW to 250 bajtów.
typedef struct struct_blackbox {
  uint8_t buffer[200];
  uint8_t len;
} struct_blackbox;

struct_blackbox blackboxData;

File logFile;
unsigned long lastFlushTime = 0;

// Callback po wysłaniu danych sterowania
void OnDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
  // Opcjonalnie: obsługa błędów wysyłania
}

// Callback po odebraniu danych (Blackbox z Odbiornika)
void OnDataRecv(const uint8_t * mac, const uint8_t *incomingData, int len) {
  // Sprawdzamy czy rozmiar danych pasuje do struktury Blackbox
  if (len == sizeof(struct_blackbox)) {
    memcpy(&blackboxData, incomingData, sizeof(blackboxData));
    
    // Jeśli są dane i plik jest otwarty, zapisz na kartę SD
    if (blackboxData.len > 0 && logFile) {
      logFile.write(blackboxData.buffer, blackboxData.len);
      
      // Flush co jakiś czas, żeby nie stracić danych przy awarii, 
      // ale nie za często żeby nie zatykać zapisu.
      // Tutaj dla bezpieczeństwa testu robimy flush często.
      if (millis() - lastFlushTime > 1000) {
        logFile.flush();
        lastFlushTime = millis();
        // Mignięcie diodą lub log na Serial dla potwierdzenia zapisu
        // Serial.println("Zapisano pakiet blackbox"); 
      }
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("--- NADAJNIK BLACKBOX ---");

  // Inicjalizacja SD
  SPI.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);
  if (!SD.begin(SD_CS)) {
    Serial.println("Błąd montowania karty SD!");
  } else {
    Serial.println("Karta SD zamontowana.");
    // Otwieramy plik w trybie dopisywania (FILE_APPEND)
    // Używamy rozszerzenia .bbl (standard Betaflight Blackbox) lub .txt
    logFile = SD.open("/blackbox.bbl", FILE_APPEND);
    if (!logFile) {
      logFile = SD.open("/blackbox.bbl", FILE_WRITE);
    }
    
    if (logFile) {
      Serial.println("Plik blackbox.bbl otwarty do zapisu.");
    } else {
      Serial.println("Nie udało się otworzyć pliku!");
    }
  }

  // Inicjalizacja WiFi
  WiFi.mode(WIFI_STA);
  esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);

  // Inicjalizacja ESP-NOW
  if (esp_now_init() != ESP_OK) {
    Serial.println("Błąd inicjalizacji ESP-NOW");
    return;
  }

  esp_now_register_send_cb(OnDataSent);
  esp_now_register_recv_cb(OnDataRecv);
  
  // Rejestracja Odbiornika jako partnera
  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, receiverAddress, 6);
  peerInfo.channel = WIFI_CHANNEL;
  peerInfo.encrypt = false;
  peerInfo.ifidx = WIFI_IF_STA;
  
  if (esp_now_add_peer(&peerInfo) != ESP_OK){
    Serial.println("Nie udało się dodać partnera (Odbiornika)");
    return;
  }
  
  Serial.println("Gotowy. Oczekiwanie na dane z PC i Blackbox z drona...");
}

void loop() {
  // Obsługa danych z PC (Joystick) - tak jak w oryginalnym nadajnik copy.cpp
  if (Serial.available() > 0) {
    String incomingString = Serial.readStringUntil('\n');
    
    int channel_index = 0;
    int last_index = 0;
    for (int i = 0; i < incomingString.length(); i++) {
      if (incomingString.charAt(i) == ',') {
        if (channel_index < 16) {
          String valStr = incomingString.substring(last_index, i);
          controlData.channels[channel_index] = valStr.toInt();
          channel_index++;
          last_index = i + 1;
        }
      }
    }
    // Wyślij dane sterowania do Odbiornika
    esp_now_send(receiverAddress, (uint8_t *) &controlData, sizeof(controlData));
  }
  
  // Małe opóźnienie dla stabilności
  delay(1);
}
