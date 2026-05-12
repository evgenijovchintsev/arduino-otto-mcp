#include <Otto.h>
#include <SoftwareSerial.h>

Otto Otto;

SoftwareSerial BTserial(12, 11);

#define LeftLeg 2
#define RightLeg 3
#define LeftFoot 4
#define RightFoot 5
#define Buzzer A3

void setup() {

  Otto.init(LeftLeg, RightLeg, LeftFoot, RightFoot, true, Buzzer);

  Otto.home();

  BTserial.begin(9600);
}

void loop() {

  if (BTserial.available()) {

    char cmd = BTserial.read();

    if (cmd == 'F') {
      Otto.walk(1, 800, 1);
    }

    if (cmd == 'B') {
      Otto.walk(1, 800, -1);
    }

    if (cmd == 'L') {
      Otto.turn(1, 800, 1);
    }

    if (cmd == 'R') {
      Otto.turn(1, 800, -1);
    }

    if (cmd == 'T') {
      Otto.tiptoeSwing(1, 1000, 25);
    }

    if (cmd == 'S') {
      Otto.home();
    }
  }
}