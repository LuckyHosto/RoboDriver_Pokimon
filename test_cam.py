import cv2
from picamera2 import Picamera2

picam2 = Picamera2()

# ������� ���� ������� ������ RGB888
config = picam2.create_video_configuration(main={"format": "RGB888", "size": (640, 480)})
picam2.configure(config)
picam2.start()

print("Starting video window... Press 'q' to exit.")

try:
    while True:
        # ����������� ������
        frame = picam2.capture_array()

        # ���� ����� ������� �� ��� �����, ���������������� ������ ����:
        # frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        cv2.imshow("Camera Fix", frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
finally:
    picam2.stop()
    cv2.destroyAllWindows()