import cv2
import numpy as np
from picamera2 import Picamera2  # Подключаем камеру Raspberry Pi

# Загрузка и подготовка шаблонов
try:
    # Оставляем ваши пути к папке с шаблонами
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
    print(f"Ошибка загрузки шаблонов! Проверьте файлы в папке Set_znakc. {e}")
    exit()

def checkSize(w, h):
    return w * h > 1500

# --- НАСТРОЙКА КАМЕРЫ RASPBERRY PI ---
camera = Picamera2()
camera.preview_configuration.main.size = (640, 480) # Разрешение кадра
camera.preview_configuration.main.format = "RGB888"
camera.preview_configuration.main.align()
camera.configure("preview")
camera.start()
# -------------------------------------

print("Нажмите 'q' в окне трансляции для выхода из программы.")

while True:
    # Захват кадра с камеры Raspberry Pi
    im = camera.capture_array()
    
    # Конвертируем из RGB (формат Picamera2) в BGR (формат OpenCV) для корректной работы imshow и HSV
    im = cv2.cvtColor(im, cv2.COLOR_RGB2BGR)

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
            cv2.rectangle(im, (x, y), (x + w, y + h), (0, 255, 0), 2)
            
            roImg = im[y:y+h, x:x+w]
            roImg = cv2.resize(roImg, (64, 64))
            roImg = cv2.inRange(roImg, (89, 120, 74), (255, 255, 255))
            
            # Словарь для подсчета совпадений
            matches = {
                "TURN LEFT": 0,
                "TURN RIGHT": 0,
                "STOP": 0,
                "BRICK": 0,
                "FORWARD": 0
            }
            
            # Попиксельное сравнение
            for i in range(64):
                for j in range(64):
                    if roImg[i][j] == left[i][j]: matches["TURN LEFT"] += 1
                    if roImg[i][j] == right[i][j]: matches["TURN RIGHT"] += 1
                    if roImg[i][j] == stop[i][j]: matches["STOP"] += 1
                    if roImg[i][j] == brick[i][j]: matches["BRICK"] += 1
                    if roImg[i][j] == forward[i][j]: matches["FORWARD"] += 1
            
            # Вывод всех совпадений в терминал (помогает понять, какой знак ближе к истине)
            print(f"L:{matches['TURN LEFT']} | R:{matches['TURN RIGHT']} | S:{matches['STOP']} | B:{matches['BRICK']} | F:{matches['FORWARD']}")
            
            # Находим знак, набравший больше всего совпадений
            best_sign = max(matches, key=matches.get)
            max_value = matches[best_sign]
            
            # Минимальный порог (например, 2600 пикселей для стабильного срабатывания)
            MIN_THRESHOLD = 2600 
            
            if max_value > MIN_THRESHOLD:
                detected_action = f"{best_sign} ({max_value})"
            else:
                detected_action = "Unknown Sign"

    # Вывод текста на экран
    cv2.putText(im, detected_action, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
    cv2.imshow("Raspberry Pi Vision", im)
    
    if cv2.waitKey(1) == ord('q'):
        break

# Правильное закрытие камеры и окон на Pi
camera.stop()
cv2.destroyAllWindows()
