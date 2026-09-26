"""
Edge Impulse Data Collector & Forwarder cho SmartBand S3 (ESP32-S3)
Tự động thu thập dữ liệu gia tốc 50Hz từ COM11 và lưu thành các tệp CSV 
sẵn sàng tải lên Edge Impulse Studio (Mục Data Acquisition -> Upload Data).
"""

import os
import sys
import time
import serial
import serial.tools.list_ports

PORT = "COM11"
BAUD = 115200
SAMPLE_RATE_HZ = 50
DURATION_SEC = 2.0  # Mỗi mẫu thu thập 2 giây (100 mẫu @ 50Hz) chuẩn cho thao tác té ngã
DATA_DIR = "edge_impulse_dataset"

def find_esp32_port():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    if PORT in ports:
        return PORT
    for p in serial.tools.list_ports.comports():
        if "USB" in p.description or "Serial" in p.description:
            return p.device
    return PORT

def collect_sample(ser, label, sample_id):
    os.makedirs(DATA_DIR, exist_ok=True)
    filename = os.path.join(DATA_DIR, f"{label}.{int(time.time())}_{sample_id}.csv")
    
    print(f"\n[CHUẨN BỊ] Thu thập mẫu '{label}' #{sample_id}...")
    print("3... ", end="", flush=True)
    time.sleep(0.6)
    print("2... ", end="", flush=True)
    time.sleep(0.6)
    print("1... BẮT ĐẦU!", flush=True)
    
    # Xóa bộ đệm cũ
    ser.reset_input_buffer()
    
    lines = ["timestamp,accX,accY,accZ"]
    start_time = time.time()
    t_ms = 0
    interval_ms = int(1000 / SAMPLE_RATE_HZ)
    
    while (time.time() - start_time) < DURATION_SEC:
        if ser.in_waiting:
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                # Định dạng mong đợi: ax,ay,az (hoặc [EI] ax,ay,az)
                if line.startswith("[EI]"):
                    line = line.replace("[EI]", "").strip()
                parts = line.split(',')
                if len(parts) >= 3:
                    try:
                        ax = float(parts[0])
                        ay = float(parts[1])
                        az = float(parts[2])
                        lines.append(f"{t_ms},{ax:.2f},{ay:.2f},{az:.2f}")
                        t_ms += interval_ms
                    except ValueError:
                        continue
            except Exception:
                pass
        time.sleep(0.002)
        
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        
    print(f"[THÀNH CÔNG] Đã ghi {len(lines) - 1} mẫu vào tệp: {filename}")

def main():
    port = find_esp32_port()
    print("=" * 60)
    print("  EDGE IMPULSE DATA COLLECTOR - SMARTBAND S3 (ESP32-S3)")
    print("=" * 60)
    print(f"[*] Đang kết nối cổng Serial: {port} @ {BAUD} baud...")
    
    try:
        ser = serial.Serial(port, BAUD, timeout=1)
        time.sleep(1.5)
        print("[+] Đã kết nối cổng Serial thành công!")
    except Exception as e:
        print(f"[-] Không thể mở cổng {port}: {e}")
        print("Vui lòng kiểm tra cáp USB và đảm bảo không có Serial Monitor nào đang chạy.")
        return

    print("\nHướng dẫn sử dụng:")
    print("  Nhập 'f' để thu thập mẫu TÉ NGÃ (fall)")
    print("  Nhập 'n' để thu thập mẫu VẬN ĐỘNG THƯỜNG (normal)")
    print("  Nhập 'i' để thu thập mẫu ĐỨNG YÊN (idle)")
    print("  Nhập 'q' để thoát")

    counts = {"fall": 0, "normal": 0, "idle": 0}

    try:
        while True:
            cmd = input("\nChọn thao tác [f: Fall, n: Normal, i: Idle, q: Thoát]: ").strip().lower()
            if cmd == 'q':
                break
            elif cmd == 'f':
                counts["fall"] += 1
                collect_sample(ser, "fall", counts["fall"])
            elif cmd == 'n':
                counts["normal"] += 1
                collect_sample(ser, "normal", counts["normal"])
            elif cmd == 'i':
                counts["idle"] += 1
                collect_sample(ser, "idle", counts["idle"])
            else:
                print("Lựa chọn không hợp lệ, vui lòng nhập f, n, i hoặc q.")
                
            print(f"Thống kê hiện tại: Fall: {counts['fall']} | Normal: {counts['normal']} | Idle: {counts['idle']}")
            print(f"Thư mục lưu trữ: {os.path.abspath(DATA_DIR)}")
    finally:
        ser.close()
        print("\nĐã đóng cổng Serial. Bạn có thể kéo toàn bộ thư mục 'edge_impulse_dataset' lên Edge Impulse Studio -> Data Acquisition -> Upload Data!")

if __name__ == "__main__":
    main()
