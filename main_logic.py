import cv2
import numpy as np
import serial  # Добавили библиотеку для связи по UART
import time

# === ИНИЦИАЛИЗАЦИЯ НАСТРОЕК SERIAL ===
try:
    # Укажи порт, к которому подключена Ардуино (/dev/ttyUSB0 или /dev/ttyACM0)
    ser = serial.Serial('/dev/ttyUSB0', 9600, timeout=0.1)
    time.sleep(2)  # Даем Ардуино время перезагрузиться после открытия порта
    print("Соединение с Arduino успешно установлено!")
except Exception as e:
    print(f"Внимание! Не удалось подключиться к Arduino: {e}")
    ser = None

# Переменная для отслеживания последней отправленной команды (защита от спама)
last_command = "NONE"

# === ЗАГРУЗКА И ПОДГОТОВКА ШАБЛОНОВ ===
try:
    left = cv2.imread("Set_znakc/left.png")
    right = cv2.imread("Set_znakc/right.jpg")
    stop = cv2.imread("Set_znakc/STOP.png")
    brick = cv2.imread("Set_znakc/brick.png")
    forward = cv2.imread("Set_znakc/forward.png")

    left = cv2.resize(left, (64, 64))
    right = cv2.resize(right, (64, 64))
    stop = cv2.resize(stop, (64, 64))
    brick = cv2.resize(brick, (64, 64))
    forward = cv2.resize(forward, (64, 64))

    left = cv2.inRange(left, (89, 91, 149), (255, 255, 255))
    right = cv2.inRange(right, (89, 91, 149), (255, 255, 255))
    stop = cv2.inRange(stop, (89, 91, 149), (255, 255, 255))
    brick = cv2.inRange(brick, (89, 91, 149), (255, 255, 255))
    forward = cv2.inRange(forward, (89, 91, 149), (255, 255, 255))

except Exception as e:
    print(f"Ошибка загрузки шаблонов! {e}")
    exit()

def checkSize(w, h):
    return w * h > 1500

# === ИНИЦИАЛИЗАЦИЯ КАМЕРЫ RASPBERRY PI ===
from picamera2 import Picamera2
picam = Picamera2()

config = picam.create_preview_configuration(main={"size": (640, 480), "format": "RGB888"})
picam.configure(config)
picam.start()

print("Нажмите 'q' на клавиатуре для выхода из программы.")

while True:
    frame_raw = picam.capture_array()
    im = cv2.cvtColor(frame_raw, cv2.COLOR_RGB2BGR)

    detected_action = "Searching..."
    cmd_to_send = None  # Сюда запишем команду для Ардуино, если знак найден

    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    thres = cv2.inRange(hsv, (0, 255, 100), (255, 255, 255))
    
    cv2.imshow("Binary Mask", thres) 

    bitwise = cv2.bitwise_and(im, im, mask=thres)
    gray = cv2.cvtColor(bitwise, cv2.COLOR_BGR2GRAY)
    
    contours, _ = cv2.findContours(gray, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    
    if len(contours) != 0:
        c = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(c)
        
        if checkSize(w, h):
            cv2.rectangle(im, (x, y), (x + w, y + h), (0, 255, 0), 2)
            
            roImg = im[y:y+h, x:x+w]
            roImg = cv2.resize(roImg, (64, 64))
            roImg = cv2.inRange(roImg, (89, 120, 74), (255, 255, 255))
            
            left_val = 0
            right_val = 0
            stop_val = 0
            brick_val = 0
            forward_val = 0
            
            for i in range(64):
                for j in range(64):
                    if roImg[i][j] == left[i][j]: left_val += 1
                    if roImg[i][j] == right[i][j]: right_val += 1
                    if roImg[i][j] == stop[i][j]: stop_val += 1
                    if roImg[i][j] == brick[i][j]: brick_val += 1
                    if roImg[i][j] == forward[i][j]: forward_val += 1
            
            # Логика определения знака и выбор команды
            if left_val > 3100:
                detected_action = f"TURN LEFT (Match: {left_val})"
                cmd_to_send = "LEFT"
            elif right_val > 2900:
                detected_action = f"TURN RIGHT (Match: {right_val})"
                cmd_to_send = "RIGHT"
            elif brick_val > 2800:
                detected_action = f"brick (Match: {brick_val})"
                cmd_to_send = "BRICK"
            elif stop_val > 2900:
                detected_action = f"STOP (Match: {stop_val})"
                cmd_to_send = "STOP"
            elif forward_val > 3100:
                detected_action = f"forward (Match: {forward_val})"
                cmd_to_send = "FORWARD"
            else:
                detected_action = "Unknown Sign"

    # === БЛОК ОТПРАВКИ КОМАНДЫ НА ARDUINO ===
    if cmd_to_send and cmd_to_send != last_command:
        if ser and ser.is_open:
            ser.write(f"{cmd_to_send}\n".encode('utf-8'))
            print(f" >>> ОТПРАВЛЕНО НА ARDUINO: {cmd_to_send}")
        last_command = cmd_to_send
    elif not cmd_to_send:
        # Если знака нет в кадре, сбрасываем флаг, чтобы робот мог среагировать на него снова
        last_command = "NONE"

    # Вывод интерфейса
    cv2.putText(im, detected_action, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
    im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
    cv2.imshow("Raspberry Pi Camera Vision", im)
    
    if cv2.waitKey(1) == ord('q'):
        break

picam.stop()
cv2.destroyAllWindows()
