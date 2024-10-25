import sys
import socket
import threading
import time
import os
from datetime import datetime
import struct
from threading import Lock
from PyQt5 import QtWidgets, QtCore
import subprocess
from datetime import timedelta

def read_settings(file_path):
    settings = {}
    print(f"---Opening settings--- {file_path}")
    if not os.path.exists(file_path):
        print(f"Error: Settings file '{file_path}' not found.")
        return settings

    with open(file_path, 'r') as file:
        for line in file:
            try:
                key, value = line.strip().split(':', 1)  # 加入最大分割次數1，防止有多個冒號的情況
                settings[key.strip()] = value.strip()
            except ValueError:
                print(f"Warning: Line '{line.strip()}' in settings file is not in the correct format.")

    return settings


def read_variable_names(file_path):
    variable_names = []
    print(f"---Opening variables--- {file_path}")
    if not os.path.exists(file_path):
        print(f"Error: Variable names file '{file_path}' not found.")
        return variable_names

    with open(file_path, 'r') as file:
        for line in file:
            name = line.strip()
            if name:  # 確保不是空行
                variable_names.append(name)
            else:
                print(f"Warning: Empty line in variable names file.")

    if not variable_names:
        print(f"Warning: No variable names found in file '{file_path}'.")

    return variable_names


class UDPReceiver(QtCore.QObject):
    def __init__(self, settings_file, variable_names_file):
        super().__init__()
        self.settings_file = settings_file
        self.variable_names_file = variable_names_file
        self.lock = Lock()
        self.stop_event = threading.Event()
        self.receive_thread = None
        self.write_thread = None
        self.recording = False  # 添加 recording
        self.start_time = None
        self.init_settings()
        print("end __init__")

    def init_settings(self):
        settings = read_settings(self.settings_file)
        self.ip_address = settings['IP']
        self.port = int(settings['Port'])
        self.settimeout = float(settings['settimeout(sec)'])
        print(f'IP: {self.ip_address}')
        print(f'Port: {self.port}')
        print(f'SetTimeout: {self.settimeout}')
        self.selected_variables = read_variable_names(self.variable_names_file)
        print(f'Variables: {self.selected_variables}')

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((self.ip_address, self.port))
        self.socket.setblocking(False)

        self.data_size = len(self.selected_variables) * 8  # 每個變數大小為8字節
        print(f'Data Size: {self.data_size}')

        self.data_buffer = {var_name: [] for var_name in self.selected_variables}
        self.data_buffer['timestamps'] = []
        self.new_data_received = False

    def create_new_csv_file(self):
        print("create_new_csv_file")
        # base_folder = 'D:\\雜物\\PlotDatabyUDP'
        base_folder = os.getcwd()
        date_str = datetime.now().strftime("%Y%m%d")  # 當天的日期
        folder_path = os.path.join(base_folder, date_str)
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)

        now = datetime.now().strftime("%Y%m%d_%H.%M.%S")  # 使用指定格式的時間戳
        self.csv_file_path = os.path.join(folder_path, f'datalog_{now}.csv')
        print(f"Creating new CSV file: {self.csv_file_path}")

        # 創建並初始化 CSV 檔案
        with open(self.csv_file_path, 'w') as file:
            file.write('timestamp,' + ','.join(self.selected_variables) + '\n')

    def start(self):
        print("start")
        self.recording = True  # 设置 recording 标志
        self.stop_event.clear()

        self.start_time = datetime.now()  # 记录开始时间
        self.receive_thread = threading.Thread(target=self.udp_receiver)
        self.write_thread = threading.Thread(target=self.write_data_to_csv)
        self.receive_thread.start()
        self.write_thread.start()
        print(f"{time.time()} self.time:", datetime.fromtimestamp(time.time()).strftime('%H:%M:%S.%f'))


    def stop(self):
        print("stop")
        self.recording = False  # 清除 recording 标志
        self.stop_event.set()
        self.receive_thread.join()
        self.write_thread.join()

    def process_data(self, data):
        # print("process_data")
        if not self.recording:
            return


        format_str = f'{len(self.selected_variables)}d'
        try:
            values = struct.unpack(format_str, data)
            timestamp = datetime.now().isoformat(timespec='milliseconds')  # 記錄接收到資料的時間
            with self.lock:
                for i, var_name in enumerate(self.selected_variables):
                    self.data_buffer[var_name].append(values[i])
                # print(f'process_data: ', len(self.data_buffer['timestamps']))
                self.data_buffer['timestamps'].append(timestamp)
                self.new_data_received = True
            # print(f'process_data: ', len(self.data_buffer['timestamps']))
        except struct.error as e:
            print(f"Data unpacking error: {e}")

    def write_data_to_csv(self):
        next_write_time = time.time() + self.settimeout
        while not self.stop_event.is_set():
            current_time = time.time()
            if current_time >= next_write_time:
                with self.lock:
                    if self.new_data_received:
                        with open(self.csv_file_path, 'a') as file:
                            for i in range(len(self.data_buffer['timestamps'])):
                                if datetime.fromisoformat(self.data_buffer['timestamps'][i]) > (self.start_time + timedelta(seconds=self.settimeout)):
                                    # print(self.data_buffer['timestamps'][i])
                                    row = [self.data_buffer['timestamps'][i]] + [self.data_buffer[var_name][i] for var_name in self.selected_variables]
                                    file.write(','.join(map(str, row)) + '\n')
                        self.new_data_received = False
                        self.data_buffer = {var_name: [] for var_name in self.selected_variables}
                        self.data_buffer['timestamps'] = []
                next_write_time = time.time() + self.settimeout
            time.sleep(0.001)  # 避免忙碌等待

    def udp_receiver(self):
        while not self.stop_event.is_set():
            try:
                if not self.recording:
                    time.sleep(0.001)
                    continue

                # print("udp_receiver")
                data, addr = self.socket.recvfrom(self.data_size)
                if len(data) == self.data_size:
                    self.process_data(data)
                else:
                    print(f"Received data size {len(data)} does not match expected size {self.data_size}")
            except socket.timeout:
                pass
            except BlockingIOError:
                pass
            except Exception as e:
                print(f"Error receiving data: {e}")
                pass


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.elapsed_time_label = QtWidgets.QLabel(self)  # 初始化 elapsed_time_label
        self.init_ui()
        self.receiver = UDPReceiver('Setting.txt', 'DataName.txt')
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_timer)
        self.start_time = None

    def init_ui(self):
        self.setWindowTitle("UDP Recorder")
        self.setGeometry(100, 100, 350, 250)

        self.record_button = QtWidgets.QPushButton("--- 已停止(AutoSave) ---", self)
        self.record_button.setGeometry(60, 40, 240, 80)
        self.record_button.setStyleSheet(
            "background-color: #089981; color: white; font-size: 20px; font-weight: bold; font-family: Arial")
        self.record_button.clicked.connect(self.toggle_recording)

        self.open_button = QtWidgets.QPushButton("開啟檔案位置", self)
        self.open_button.setGeometry(60, 140, 240, 40)
        self.open_button.setStyleSheet(
            "font-size: 16px; font-weight: bold; font-family: Arial"
        )
        self.open_button.clicked.connect(self.open_data)

        self.elapsed_time_label.setGeometry(60, 200, 240, 40)
        self.elapsed_time_label.setStyleSheet(
            "font-size: 16px; font-weight: bold; font-family: Arial"
        )

    def toggle_recording(self):
        if self.record_button.text() == "--- 已停止(AutoSave) ---":
            print("toggle_recording: 1 ")
            self.record_button.setText("--- 錄製中 ---")
            self.record_button.setStyleSheet(
                "background-color: #F23645; color: white; font-size: 20px; font-weight: bold; font-family: Arial"
            )
            self.receiver.create_new_csv_file()  # 只在这里创建新的 CSV 文件
            self.receiver.start()
            self.start_time = datetime.now()
            self.timer.start(500)  # 每0.5秒更新一次
        else:
            print("toggle_recording: 2 ")
            self.record_button.setText("--- 已停止(AutoSave) ---")
            self.record_button.setStyleSheet(
                "background-color: #089981; color: white; font-size: 20px; font-weight: bold; font-family: Arial"
            )
            self.receiver.stop()
            self.timer.stop()

    def open_data(self):
        print("---開啟檔案位置---")
        # base_folder = 'D:\\雜物\\PlotDatabyUDP'
        base_folder = os.getcwd()
        date_str = datetime.now().strftime("%Y%m%d")  # 當天的日期
        folder_path = os.path.join(base_folder, date_str)

        if not os.path.exists(folder_path):
            print(f"Error: Folder '{folder_path}' not found.")
            return

        try:
            if sys.platform == 'win32':
                os.startfile(folder_path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', folder_path])
            else:
                subprocess.Popen(['xdg-open', folder_path])
            print("打開文件位置: ", folder_path)
        except Exception as e:
            print(f"Error opening folder: {e}")

    def update_timer(self):
        elapsed_time = datetime.now() - self.start_time
        seconds = elapsed_time.total_seconds()
        formatted_time = time.strftime("%H:%M:%S", time.gmtime(seconds))
        self.elapsed_time_label.setText(f"錄製時間: {formatted_time}")


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    print("1")
    main_win = MainWindow()
    print("2")
    main_win.show()
    print("3")
    sys.exit(app.exec_())
    print("4")
