import sys
import time
import os
import cantools
import serial
import serial.tools.list_ports
import pyqtgraph as pg
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QTabWidget, QLabel, QGridLayout, 
                             QGroupBox, QPlainTextEdit, QCheckBox, QPushButton)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QMutex
from PyQt6.QtGui import QFont, QColor

# --- CONFIGURACIÓN ---
CAN_BITRATE = 1000000
# Ruta del DBC relativa al script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DBC_FILE = os.path.join(SCRIPT_DIR, "mft04.dbc")
CAN_INTERFACE_TYPE = 'robotell' 
REFRESH_RATE_MS = 50 

# Paleta de colores para las gráficas (se reciclan si eliges muchas señales)
GRAPH_COLORS = [
    '#00e676', # Verde Neón
    '#2979ff', # Azul Brillante
    '#ffea00', # Amarillo
    '#ff1744', # Rojo
    '#d500f9', # Violeta
    '#00b0ff', # Cyan
    '#ff9100', # Naranja
    '#ffffff', # Blanco
]

# --- Hilo de Trabajo CAN (Backend) ---
# --- Hilo de Trabajo CAN (Backend ESTILO ROBOWIN) ---
class CanWorker(QThread):
    connection_status = pyqtSignal(str, str)
    new_trace = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.serial = None  # Usamos serial directo, no can.Bus
        self.db = None
        self.data_lock = QMutex()
        self.latest_data = {} 
        self.last_receive_times = {}

        try:
            print(f"[DBC] Intentando cargar: {DBC_FILE}")
            self.db = cantools.database.load_file(DBC_FILE)
            print(f"[DBC] Cargado correctamente: {len(self.db.messages)} mensajes")
            # Mostrar algunos IDs disponibles
            available_ids = [f"0x{msg.frame_id:X}" for msg in self.db.messages[:10]]
            print(f"[DBC] Primeros IDs disponibles: {', '.join(available_ids)}")
        except Exception as e:
            print(f"[DBC] ERROR crítico cargando DBC: {e}")
            import traceback
            traceback.print_exc()

    def get_available_ports(self):
        ports = serial.tools.list_ports.comports()
        return [port.device for port in ports]

    def connect_to_port(self, port):
        try:
            # LÓGICA ROBOWIN: Conexión Serial Pura
            # DTR=False intenta evitar el reinicio en algunas placas, 
            # pero si reinicia, el timeout nos protege.
            ser = serial.Serial(port, 1000000, timeout=0.1)
            ser.dtr = False 
            ser.rts = False
            return ser
        except Exception as e:
            return None

    def run(self):
        while self.running:
            if self.serial is None:
                self.connection_status.emit("Escaneando puertos...", "orange")
                ports = self.get_available_ports()
                if not ports:
                    self.connection_status.emit("No se detectan puertos COM", "red")
                    time.sleep(1)
                    continue

                for port in ports:
                    self.connection_status.emit(f"Probando {port}...", "orange")
                    new_ser = self.connect_to_port(port)
                    if new_ser:
                        self.serial = new_ser
                        self.connection_status.emit(f"CONECTADO: {port} (Raw Serial)", "green")
                        break 
                    time.sleep(0.1)
                if self.serial is None: time.sleep(1)

            else:
                try:
                    # LÓGICA CSV: Leer línea a línea
                    if self.serial.in_waiting:
                        # Leemos hasta el salto de línea '\n' (formato CSV)
                        raw_line = self.serial.readline().decode('utf-8', errors='ignore').strip()
                        
                        if not raw_line:
                            continue

                        # --- PARSEO CSV (3B1,00,00,00,00,00,00,00,00) ---
                        try:
                            parts = raw_line.split(',')
                            
                            if len(parts) < 1:
                                continue
                            
                            # Primer elemento: CAN ID en hex
                            can_id = int(parts[0], 16)
                            
                            # Resto: datos en hex
                            data_bytes = bytes([int(b, 16) for b in parts[1:]])
                            dlc = len(data_bytes)

                            # --- A PARTIR DE AQUÍ, ES IGUAL QUE ANTES ---
                            current_time = time.time()
                            timestamp = time.strftime('%H:%M:%S')
                            
                            # Generar Traza
                            hex_data_view = ' '.join([f"{b:02X}" for b in data_bytes])
                            msg_name = "Unknown"
                            decoded_str = ""
                            decoded_signals = {}

                            if self.db:
                                try:
                                    # Intentar obtener el mensaje por ID
                                    try:
                                        msg_def = self.db.get_message_by_frame_id(can_id)
                                        msg_name = msg_def.name
                                        print(f"[DEBUG] ID 0x{can_id:X} -> Mensaje: {msg_name}")
                                    except KeyError:
                                        msg_name = f"ID_0x{can_id:X}"
                                        print(f"[DEBUG] ID 0x{can_id:X} no encontrado en DBC")

                                    # Intentar decodificar
                                    decoded_signals = self.db.decode_message(can_id, data_bytes)
                                    print(f"[DEBUG] Señales decodificadas: {decoded_signals}")
                                    
                                    # Actualizar GUI Data
                                    self.data_lock.lock()
                                    self.latest_data.update(decoded_signals)
                                    for key in decoded_signals.keys():
                                        self.last_receive_times[key] = current_time
                                    self.data_lock.unlock()

                                    # String para traza
                                    parts_str = [f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}" for k, v in decoded_signals.items()]
                                    decoded_str = " | ".join(parts_str) if parts_str else "(Sin señales)"
                                
                                except Exception as decode_err:
                                    decoded_str = f"(Decode Error: {decode_err})"
                                    print(f"[DEBUG] Error decodificando 0x{can_id:X}: {decode_err}")

                            # Emitir traza
                            trace_msg = f"[{timestamp}] {can_id:3X} ({msg_name:^15}) {decoded_str} | Raw: [{hex_data_view}]"
                            self.new_trace.emit(trace_msg)

                        except (ValueError, IndexError):
                            # Si llega basura o formato incorrecto, la ignoramos
                            pass
                        
                    else:
                        # Si no hay datos, dormimos un poco para no quemar CPU
                        time.sleep(0.001)

                except (OSError, serial.SerialException):
                    self.connection_status.emit("Conexión perdida", "red")
                    try: self.serial.close()
                    except: pass
                    self.serial = None
                    time.sleep(1)

    def stop(self):
        self.running = False
        if self.serial:
            try: self.serial.close()
            except: pass
        self.wait()
# --- Widget de Gráficos MULTIPLE ---
class MultiPlotter(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Header
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("<b>Gráfica Multiseñal</b>"))
        
        self.clear_btn = QPushButton("Limpiar Gráfica")
        self.clear_btn.setStyleSheet("background-color: #444; color: white; border: 1px solid #666; padding: 3px;")
        self.clear_btn.clicked.connect(self.clear_all_traces)
        header_layout.addWidget(self.clear_btn)
        
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Configuración pyqtgraph
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('#2b2b2b')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setDownsampling(mode='peak') 
        self.plot_widget.setClipToView(True)
        self.plot_widget.addLegend(offset=(10, 10)) # Leyenda automática
        
        layout.addWidget(self.plot_widget)

        # Estructuras de datos
        # curves = { 'rpm': PlotDataItem, 'speed': PlotDataItem }
        # buffers = { 'rpm': [1,2,3], 'speed': [4,5,6] }
        self.curves = {}
        self.buffers = {}
        self.max_points = 500
        self.color_index = 0

    def add_signal(self, key):
        if key in self.curves:
            return # Ya existe

        # Asignar color rotativo
        color = GRAPH_COLORS[self.color_index % len(GRAPH_COLORS)]
        self.color_index += 1
        
        pen = pg.mkPen(color=color, width=2)
        # Añadir curva con nombre para la leyenda
        curve = self.plot_widget.plot(name=key, pen=pen)
        
        self.curves[key] = curve
        self.buffers[key] = []

    def remove_signal(self, key):
        if key in self.curves:
            self.plot_widget.removeItem(self.curves[key])
            del self.curves[key]
            del self.buffers[key]
            # Nota: pyqtgraph no elimina automáticamente el item de la leyenda al borrar la curva
            # Por simplicidad, reconstruiremos la leyenda o la dejaremos así.
            # Para una limpieza total de leyenda, a veces es más fácil limpiar todo.

    def clear_all_traces(self):
        # Esta función es un reset manual si la gráfica se ensucia mucho
        self.plot_widget.clear()
        self.curves = {}
        self.buffers = {}
        self.color_index = 0
        # Ojo: esto desincroniza los checkbox de la UI, lo ideal es usar solo los checkboxes

    def update_data(self, full_data):
        # Recorremos solo las curvas activas
        for key in self.curves:
            if key in full_data:
                val = full_data[key]
                if isinstance(val, (int, float)):
                    self.buffers[key].append(val)
                    
                    if len(self.buffers[key]) > self.max_points:
                        self.buffers[key].pop(0)
                    
                    self.curves[key].setData(self.buffers[key])

# --- Ventana Principal ---
class TelemetryWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RoboWin - QT MultiGraph")
        self.resize(1366, 800)

        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; color: #ffffff; }
            QLabel { color: #e0e0e0; font-family: 'Segoe UI', sans-serif; }
            QGroupBox { 
                border: 1px solid #444; 
                border-radius: 5px; 
                margin-top: 10px; 
                font-weight: bold; 
                color: #00acc1;
                background-color: #252525;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
            QTabWidget::pane { border: 1px solid #444; background-color: #1e1e1e; }
            QTabBar::tab { background: #333; color: #aaa; padding: 8px 20px; }
            QTabBar::tab:selected { background: #444; color: white; border-bottom: 2px solid #00e676; }
            QCheckBox { color: #aaa; spacing: 5px; }
            QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #666; border-radius: 2px; }
            QCheckBox::indicator:checked { background-color: #00e676; border-color: #00e676; }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        self.status_label = QLabel("Iniciando sistema...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("background-color: #333; color: white; padding: 5px; border-radius: 3px;")
        main_layout.addWidget(self.status_label)

        self.main_tabs = QTabWidget()
        main_layout.addWidget(self.main_tabs)

        self.ui_labels = {} 
        self.checkboxes = {} # Para poder limpiar o gestionar checkboxes si fuera necesario

        # --- TAB 1: DASHBOARD ---
        self.dashboard_tab = QWidget()
        self.setup_dashboard_ui()
        self.main_tabs.addTab(self.dashboard_tab, "Dashboard Principal")

        # --- TAB 2: TRAZAS CAN ---
        self.traces_tab = QWidget()
        self.setup_traces_ui()
        self.main_tabs.addTab(self.traces_tab, "Monitor CAN")

        # Worker
        self.can_worker = CanWorker()
        self.can_worker.connection_status.connect(self.update_status)
        self.can_worker.new_trace.connect(self.append_trace)
        self.can_worker.start()

        # Timer
        self.timer = QTimer()
        self.timer.setInterval(REFRESH_RATE_MS) 
        self.timer.timeout.connect(self.update_ui_tick)
        self.timer.start()

    def setup_dashboard_ui(self):
        layout = QVBoxLayout(self.dashboard_tab)
        
        # --- ZONA DE DATOS (ARRIBA) ---
        columns_layout = QHBoxLayout()
        
        motor_group = self.create_data_group("MOTOR", [
            ("ECT", "ect", "°C"), ("Oil Temp", "oil_temp", "°C"),
            ("Oil Press", "oil_press", "bar"), ("Fuel Press", "fuel_press", "bar"),
            ("RPM", "engine_rpm", "rpm"), ("Gear", "gear", ""),
            ("Lambda", "lamda", ""), ("Throttle", "tp", "%"),
            ("Bat Volt", "batt_volt", "V")
        ])
        columns_layout.addWidget(motor_group)

        chassis_group = self.create_data_group("CHASIS", [
            ("Steering", "steering_wheel_angle", "°"), ("Brake", "brake_pressure", "bar"),
            ("FL Speed", "front_left_wheel_speed", "km/h"), ("FR Speed", "front_right_wheel_speed", "km/h"),
            ("RL Speed", "rear_left_speed", "km/h"), ("RR Speed", "rear_right_speed", "km/h"),
            ("FL Damp", "front_left_damper", "mm"), ("FR Damp", "front_right_damper", "mm")
        ])
        columns_layout.addWidget(chassis_group)

        elec_group = self.create_data_group("ELÉCTRICO", [
            ("Alt Curr", "alternator_current", "A"), ("Ign Curr", "ignition_current", "A"),
            ("Inj Curr", "injection_current", "A"), ("Fuel Pmp", "fuel_pump_current", "A"),
            ("Water Pmp", "water_pump_current", "A"), ("Fan Curr", "main_fan_current", "A"),
            ("PDM Temp", "temp_pdm", "°C"), ("Lat", "latitude", "°")
        ])
        columns_layout.addWidget(elec_group)

        layout.addLayout(columns_layout, stretch=1) 

        # --- ZONA DE GRÁFICA (ABAJO) ---
        self.plotter = MultiPlotter()
        self.plotter.setMinimumHeight(350)
        layout.addWidget(self.plotter, stretch=2)

    def setup_traces_ui(self):
        layout = QVBoxLayout(self.traces_tab)
        info_label = QLabel("Monitor CAN - Traducción en tiempo real")
        info_label.setStyleSheet("color: #aaa; font-style: italic;")
        layout.addWidget(info_label)

        self.trace_console = QPlainTextEdit()
        self.trace_console.setReadOnly(True)
        self.trace_console.setStyleSheet("""
            QPlainTextEdit { 
                background-color: #000000; 
                color: #00ff00; 
                font-family: 'Consolas', 'Courier New', monospace; 
                font-size: 9pt;
                border: 1px solid #555;
            }
        """)
        self.trace_console.setMaximumBlockCount(2000) 
        layout.addWidget(self.trace_console)

    def create_data_group(self, title, signals):
        group = QGroupBox(title)
        layout = QGridLayout()
        layout.setColumnStretch(2, 1) # El valor se expande
        
        row = 0
        for label_text, key, unit in signals:
            # 1. Checkbox para graficar
            chk = QCheckBox()
            # Conectamos el evento click con la función toggle_graph usando lambda para pasar la clave
            chk.toggled.connect(lambda checked, k=key: self.toggle_graph(k, checked))
            layout.addWidget(chk, row, 0)
            self.checkboxes[key] = chk

            # 2. Nombre Señal (Al hacer click en el nombre, también activamos el checkbox)
            lbl_name = QLabel(label_text)
            lbl_name.setStyleSheet("color: #aaa;")
            layout.addWidget(lbl_name, row, 1)
            
            # 3. Valor Señal
            lbl_val = QLabel("---")
            lbl_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl_val.setFont(QFont("Segoe UI", 12))
            lbl_val.setStyleSheet("color: #555;") # Gris inicial
            layout.addWidget(lbl_val, row, 2)
            
            # 4. Unidad
            lbl_unit = QLabel(unit)
            lbl_unit.setStyleSheet("color: #666; font-size: 10px;")
            layout.addWidget(lbl_unit, row, 3)
            
            self.ui_labels[key] = lbl_val 
            row += 1
            
        group.setLayout(layout)
        return group

    def toggle_graph(self, key, checked):
        if checked:
            self.plotter.add_signal(key)
        else:
            self.plotter.remove_signal(key)

    def update_status(self, msg, color_code):
        bg_color = "#333"
        if color_code == "green": bg_color = "#2e7d32"
        elif color_code == "orange": bg_color = "#f57c00"
        elif color_code == "red": bg_color = "#c62828"
        self.status_label.setText(f"ESTADO: {msg}")
        self.status_label.setStyleSheet(f"background-color: {bg_color}; color: white; padding: 5px; font-weight: bold; border-radius: 3px;")

    def append_trace(self, text):
        if self.main_tabs.currentIndex() == 1:
            self.trace_console.appendPlainText(text)

    def update_ui_tick(self):
        self.can_worker.data_lock.lock()
        data_snapshot = self.can_worker.latest_data.copy()
        times_snapshot = self.can_worker.last_receive_times.copy()
        self.can_worker.data_lock.unlock()

        current_time = time.time()

        # Actualizar valores
        for key, label_widget in self.ui_labels.items():
            if key in data_snapshot:
                val = data_snapshot[key]
                txt = f"{val:.2f}" if isinstance(val, float) else str(val)
                label_widget.setText(txt)

                last_rx = times_snapshot.get(key, 0)
                
                # Watchdog visual (2 seg)
                if (current_time - last_rx) < 2.0:
                    label_widget.setStyleSheet("color: #00e676; font-weight: bold; font-size: 14px;") 
                else:
                    label_widget.setStyleSheet("color: #ffb74d; font-weight: normal; font-size: 12px;") 
            else:
                label_widget.setText("---")
                label_widget.setStyleSheet("color: #444; font-weight: normal; font-size: 12px;")

        # Actualizar Gráfica Múltiple
        if self.main_tabs.currentIndex() == 0:
            self.plotter.update_data(data_snapshot)

    def closeEvent(self, event):
        self.can_worker.stop()
        self.timer.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TelemetryWindow()
    window.show()
    sys.exit(app.exec())