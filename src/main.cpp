#include <Arduino.h>

int ledPin = 13;

void setup() {
  pinMode(ledPin, OUTPUT);
  Serial.begin(9600);
  Serial.setTimeout(50);
}

void loop() {
  if(Serial.available() > 0){
  String command = Serial.readStringUntil('\n');
  command.trim();

  if(command == "on"){digitalWrite(ledPin, HIGH);}
    
  else if(command == "off"){digitalWrite(ledPin, LOW);}

  else {Serial.println('lol');}
  }

}