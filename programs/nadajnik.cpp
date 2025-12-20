#include <WiFi.h>
#include <esp_now.h>
#include <ESPAsyncWebServer.h>

// --- KONFIGURACJA ---
// Adres MAC Twojego odbiornika ESP32
uint8_t broadcastAddress[] = {0x78, 0x42, 0x1C, 0x68, 0x74, 0xF0};

const char *ssid = "DronKontroler";
AsyncWebServer server(80);
AsyncWebSocket ws("/ws");

// Struktura danych musi być IDENTYCZNA w nadajniku i odbiorniku
typedef struct struct_message {
  uint16_t throttle;
  uint16_t yaw;
  uint16_t pitch;
  uint16_t roll;
  uint16_t aux1; // Uzbrajanie
} struct_message;

struct_message rcData;

// Strona internetowa (HTML + CSS + JavaScript) - bez zmian
const char index_html[] PROGMEM = R"rawliteral(
<!DOCTYPE HTML><html>
<head>
  <title>Sterownik Drona ESP-NOW</title>
  <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
  <style>
    body { font-family: Arial, sans-serif; text-align: center; margin: 0; padding-top: 20px; background-color: #2c3e50; color: white; -webkit-user-select: none; -ms-user-select: none; user-select: none; }
    .slider-container { display: flex; justify-content: space-around; align-items: center; margin: 20px; height: 220px; }
    .slider-vertical { writing-mode: bt-lr; -webkit-appearance: slider-vertical; width: 50px; height: 200px; padding: 0 5px; background: #34495e; border: 2px solid #7f8c8d; border-radius: 10px; }
    .slider-horizontal { width: 200px; height: 50px; background: #34495e; border: 2px solid #7f8c8d; border-radius: 10px; }
    .label { font-size: 18px; font-weight: bold; }
    .value { font-size: 16px; color: #f1c40f; }
    #arm-switch { margin-top: 20px; }
    #arm-button { padding: 15px 30px; font-size: 20px; cursor: pointer; border-radius: 10px; border: none; font-weight: bold; }
    .armed { background-color: #c0392b; color: white; }
    .disarmed { background-color: #27ae60; color: white; }
  </style>
</head>
<body>
  <h1>Sterownik Drona ESP-NOW</h1>
  <div class="slider-container">
    <div>
      <label class="label" for="throttle">Throttle</label><br>
      <input type="range" min="1000" max="2000" value="1000" class="slider-vertical" id="throttle"><br>
      <span class="value" id="throttleValue">1000</span>
    </div>
    <div>
      <label class="label" for="yaw">Yaw</label><br>
      <input type="range" min="1000" max="2000" value="1500" class="slider-vertical" id="yaw"><br>
      <span class="value" id="yawValue">1500</span>
    </div>
  </div>
  <div class="slider-container" style="height: 100px;">
     <div>
      <label class="label" for="pitch">Pitch</label><br>
      <input type="range" min="1000" max="2000" value="1500" class="slider-horizontal" id="pitch"><br>
      <span class="value" id="pitchValue">1500</span>
    </div>
     <div>
      <label class="label" for="roll">Roll</label><br>
      <input type="range" min="1000" max="2000" value="1500" class="slider-horizontal" id="roll"><br>
      <span class="value" id="rollValue">1500</span>
    </div>
  </div>
  <div id="arm-switch">
    <button id="arm-button" class="disarmed">DISARMED</button>
  </div>
<script>
  var gateway = `ws://${window.location.hostname}/ws`;
  var websocket;
  var intervalId;
  window.addEventListener('load', onload);
  function onload(event) { initWebSocket(); }
  function initWebSocket() {
    console.log('Trying to open a WebSocket connection...');
    websocket = new WebSocket(gateway);
    websocket.onopen  = onOpen;
    websocket.onclose = onClose;
  }
  function onOpen(event) {
    console.log('Connection opened');
    intervalId = setInterval(sendData, 50);
  }
  function onClose(event) {
    console.log('Connection closed');
    clearInterval(intervalId);
    setTimeout(initWebSocket, 2000);
  }
  function sendData() {
    if (websocket.readyState === WebSocket.OPEN) {
      let armValue = document.getElementById('arm-button').classList.contains('armed') ? 1500 : 1000;
      var data = [
        document.getElementById('throttle').value,
        document.getElementById('yaw').value,
        document.getElementById('pitch').value,
        document.getElementById('roll').value,
        armValue
      ].join(',');
      websocket.send(data);
    }
  }
  function updateSliderValue(sliderId, valueId) {
    document.getElementById(valueId).innerText = document.getElementById(sliderId).value;
  }
  const sliders = ['throttle', 'yaw', 'pitch', 'roll'];
  sliders.forEach(id => {
    document.getElementById(id).addEventListener('input', () => updateSliderValue(id, id + 'Value'));
    document.getElementById(id).addEventListener('touchend', () => {
        if(id === 'yaw' || id === 'pitch' || id === 'roll') {
            document.getElementById(id).value = 1500;
            updateSliderValue(id, id + 'Value');
        }
    });
  });
  document.getElementById('arm-button').addEventListener('click', function() {
    this.classList.toggle('armed');
    this.classList.toggle('disarmed');
    if (this.classList.contains('armed')) {
      this.innerText = 'ARMED';
    } else {
      this.innerText = 'DISARMED';
      document.getElementById('throttle').value = 1000;
      updateSliderValue('throttle', 'throttleValue');
    }
  });
</script>
</body>
</html>
)rawliteral";

// Funkcja onWsEvent - bez zmian
void onWsEvent(AsyncWebSocket *server, AsyncWebSocketClient *client, AwsEventType type, void *arg, uint8_t *data, size_t len) {
  if (type == WS_EVT_CONNECT) {
    Serial.println("WebSocket client connected");
  } else if (type == WS_EVT_DISCONNECT) {
    Serial.println("WebSocket client disconnected");
  } else if (type == WS_EVT_DATA) {
    char* p = (char*)data;
    rcData.throttle = atoi(strtok(p, ","));
    rcData.yaw = atoi(strtok(NULL, ","));
    rcData.pitch = atoi(strtok(NULL, ","));
    rcData.roll = atoi(strtok(NULL, ","));
    rcData.aux1 = atoi(strtok(NULL, ","));

    // --- DODAJ TĘ LINIĘ ---
    Serial.printf("Wysyłam ESP-NOW -> T: %d, Y: %d, P: %d, R: %d, ARM(AUX1): %d\n", rcData.throttle, rcData.yaw, rcData.pitch, rcData.roll, rcData.aux1);

    esp_now_send(broadcastAddress, (uint8_t *) &rcData, sizeof(rcData));
  }
}

// ==========================================================
// === TUTAJ ZNAJDUJE SIĘ POPRAWIONA FUNKCJA `setup()` ===
// ==========================================================
void setup() {
  Serial.begin(115200);

  // Krok 1: Ustaw tryb Wi-Fi i uruchom Access Point
  // Robimy to jako pierwsze, aby dać radiu czas na stabilizację.
  WiFi.mode(WIFI_AP);
  WiFi.softAP(ssid);
  Serial.print("AP IP address: ");
  Serial.println(WiFi.softAPIP());

  // Krok 2: Dopiero teraz inicjalizuj ESP-NOW
  if (esp_now_init() != ESP_OK) {
    Serial.println("Error initializing ESP-NOW");
    return;
  }

  // Krok 3: Dodaj peer'a (odbiornik)
  esp_now_peer_info_t peerInfo = {}; // Użyj {} aby wyzerować strukturę
  memcpy(peerInfo.peer_addr, broadcastAddress, 6);
  peerInfo.channel = 0; // 0 oznacza użycie aktualnego kanału Wi-Fi
  peerInfo.encrypt = false;

  if (esp_now_add_peer(&peerInfo) != ESP_OK) {
    Serial.println("Failed to add peer");
    return;
  }

  // Krok 4: Skonfiguruj i uruchom serwer WWW
  // Ten kod zostanie teraz wykonany, ponieważ błąd "Failed to add peer" nie powinien już wystąpić.
  ws.onEvent(onWsEvent);
  server.addHandler(&ws);
  server.on("/", HTTP_GET, [](AsyncWebServerRequest *request){
    request->send_P(200, "text/html", index_html);
  });

  server.begin();
  Serial.println("HTTP server started");
}

void loop() {
  ws.cleanupClients();
}