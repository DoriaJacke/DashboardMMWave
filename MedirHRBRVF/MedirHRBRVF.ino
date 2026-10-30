#include "Arduino.h"
#include <60ghzbreathheart.h>

#define RXD2 16
#define TXD2 17

BreathHeart_60GHz radar = BreathHeart_60GHz(&Serial2);

// ----------------------------------
// Apagar waveform
// ----------------------------------

void modoNormal() {

  uint8_t cmd[] = {
    0x53, 0x59,
    0x80,
    0x03,
    0x01,
    0x00,   // waveform OFF
    0x00, 0x00
  };

  Serial2.write(cmd, sizeof(cmd));

  Serial.println("Waveform DESACTIVADO");
}

void setup() {

  Serial.begin(115200);
  Serial2.begin(115200, SERIAL_8N1, RXD2, TXD2);

  delay(2000);

  modoNormal();  

  delay(1000);

  radar.ModeSelect_fuc(1);

  Serial.println("Modo normal activado");
}

void loop()
{
  radar.Breath_Heart();

  if(radar.sensor_report != 0x00){

    switch(radar.sensor_report){

      case BREATHVAL:

        Serial.print("BR,");
        Serial.println(radar.breath_rate);

        break;

      case HEARTRATEVAL:

        Serial.print("HR,");
        Serial.println(radar.heart_rate);

        break;
    }
  }

  delay(200);
}
