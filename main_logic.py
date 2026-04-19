import serial
import serial.tools.list_ports
import time

port = '/dev/ttyUSB0'

try:
    ser = serial.Serial(port, 9600, timeout=1)

    time.sleep(2)
    print('yes')
    print('command [on], [off]')

    while True:
        cmd = input('>>>')

        if (cmd == 'exit'):
            break

        if cmd:
            ser.write((cmd + "\n").encode('utf-8'))
            time.sleep(0.1)

            if ser.in_waiting > 0:
                answer = ser.readline().decode('utf-8').strip()
                print('otvet', answer)
    ser.close()

except Exception as e:
    print("mistake", e)