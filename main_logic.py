import cv2
import numpy as np
from picamera2 import Picamera2  # Подключаем камеру Raspberry Pi

# Загрузка и подготовка шаблонов (оригинальный блок)
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
    print(f"Ошибка загрузки шаблонов! Проверьте, лежат ли картинки рядом со скриптом. {e}")
    exit()

def checkSize(w, h):
    return w * h > 1500

# --- Инициализация камеры Raspberry Pi ---
camera = Picamera2()
camera.preview_configuration.main.size = (640, 480)
camera.preview_configuration.main.format = "RGB888"
camera.preview_configuration.main.align()
camera.configure("preview")
camera.start()
# -----------------------------------------

print("Нажмите 'q' на клавиатуре для выхода из программы.")

while True:
    # Захват кадра с камеры Raspberry Pi
    im = camera.capture_array()
    
    # Конвертируем из RGB в BGR, чтобы цвета маски и imshow отображались корректно
    im = cv2.cvtColor(im, cv2.COLOR_RGB2BGR)

    # Текущее действие для вывода на экран
    detected_action = "Searching..."

    # Преобразование в HSV и создание маски
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    thres = cv2.inRange(hsv, (89, 124, 73), (255, 255, 255))
    cv2.imshow("Бинарная маска", thres) 

    bitwise = cv2.bitwise_and(im, im, mask=thres)
    gray = cv2.cvtColor(bitwise, cv2.COLOR_BGR2GRAY)
    
    # Поиск контуров
    contours, _ = cv2.findContours(gray, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    
    if len(contours) != 0:
        c = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(c)
        
        if checkSize(w, h):
            # Рисуем зелёную рамку вокруг найденного объекта
            cv2.rectangle(im, (x, y), (x + w, y + h), (0, 255, 0), 2)
            
            # Вырезаем область знака
            roImg = im[y:y+h, x:x+w]
            roImg = cv2.resize(roImg, (64, 64))
            roImg = cv2.inRange(roImg, (89, 120, 74), (255, 255, 255))
            
            left_val = 0
            right_val = 0
            stop_val = 0
            brick_val = 0
            forward_val = 0
            
            # Попиксельное сравнение с шаблонами (твой цикл)
            for i in range(64):
                for j in range(64):
                    if roImg[i][j] == left[i][j]:
                        left_val += 1
                    if roImg[i][j] == right[i][j]:
                        right_val += 1
                    if roImg[i][j] == stop[i][j]:
                        stop_val += 1
                    if roImg[i][j] == brick[i][j]:
                        brick_val += 1
                    if roImg[i][j] == forward[i][j]:
                        forward_val += 1
            
            # Определение того, какой знак "видит" компьютер (твои оригинальные if-elif)
            if left_val > 3100:
                detected_action = f"TURN LEFT (Match: {left_val})"
            elif right_val > 3000:
                detected_action = f"TURN RIGHT (Match: {right_val})"
            elif brick_val > 2900:
                detected_action = f"brick (Match: {brick_val})"
            elif stop_val > 2900:
                detected_action = f"STOP (Match: {stop_val})"
            elif forward_val > 3100:
                detected_action = f"forward (Match: {forward_val})"
            else:
                detected_action = "Unknown Sign"

    # Вывод текста с результатом распознавания прямо на видеопоток
    cv2.putText(im, detected_action, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
    
    # Отображение главного окна с камеры
    cv2.imshow("Raspberry Pi Vision", im)
    
    # Выход по нажатию клавиши 'q'
    if cv2.waitKey(1) == ord('q'):
        break

# Правильное закрытие камеры Raspberry Pi и окон
camera.stop()
cv2.destroyAllWindows()
