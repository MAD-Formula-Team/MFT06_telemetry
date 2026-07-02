import sys
import time
import os
import csv
import bisect
from datetime import datetime
import cantools
import serial
import serial.tools.list_ports
import pyqtgraph as pg
from collections import deque
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QTabWidget, QLabel, QGridLayout, 
                             QGroupBox, QPlainTextEdit, QCheckBox, QPushButton,
                             QScrollArea, QSplitter, QFileDialog, QMessageBox, QRadioButton,
                             QButtonGroup, QTableWidget, QTableWidgetItem, QHeaderView,
                             QComboBox, QStackedWidget, QLineEdit, QFrame)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QMutex
from PyQt6.QtGui import QFont, QColor
from ui_theme import (
    APP_STYLESHEET,
    nav_button_style,
    status_label_style,
    popup_button_style,
    action_button_style,
)

# --- CONFIGURACIÓN ---
CAN_BITRATE = 1000000
# Ruta del DBC relativa al script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DBC_FILE = os.path.join(SCRIPT_DIR, "mft06.dbc")
CAN_INTERFACE_TYPE = 'robotell' 
REFRESH_RATE_MS = 50  # Refresco más fluido para cronómetro y tablas (20 FPS)
LAPTIMER_CAN_ID = 0x777
LAPTIMER_LAST_LAP_TEXT = "ULTIMA VUELTA"
LAPTIMER_EMPTY_FOOTER_TEXT = "SIN VUELTAS REGISTRADAS"

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

# --- DataStore: Almacén persistente de telemetría ---
class TelemetryDataStore:
    """Almacena todos los datos de telemetría con timestamps relativos"""
    def __init__(self, max_points=10000):
        self.data = {}  # {'rpm': deque([...]), 'ect': deque([...])}
        self.timestamps = {}  # {'rpm': deque([...])}
        self.max_points = max_points
        self.start_time = time.time()
        self.lock = QMutex()
        
    def add_sample(self, signal_name, value, timestamp=None):
        """Añade un dato con timestamp relativo"""
        if timestamp is None:
            timestamp = time.time() - self.start_time
        
        self.lock.lock()
        
        if signal_name not in self.data:
            self.data[signal_name] = deque(maxlen=self.max_points)
            self.timestamps[signal_name] = deque(maxlen=self.max_points)
        
        self.data[signal_name].append(value)
        self.timestamps[signal_name].append(timestamp)
        
        self.lock.unlock()
    
    def get_signal_data(self, signal_name):
        """Retorna (timestamps, values) para una señal"""
        self.lock.lock()
        if signal_name in self.data:
            t = list(self.timestamps[signal_name])
            v = list(self.data[signal_name])
            self.lock.unlock()
            return t, v
        self.lock.unlock()
        return [], []
    
    def get_all_signals(self):
        """Retorna lista de todas las señales disponibles"""
        self.lock.lock()
        signals = list(self.data.keys())
        self.lock.unlock()
        return signals
    
    def clear(self):
        """Limpia todos los datos"""
        self.lock.lock()
        self.data.clear()
        self.timestamps.clear()
        self.start_time = time.time()
        self.lock.unlock()
    
    def load_from_csv(self, filename):
        """Carga datos desde un archivo CSV exportado previamente
        
        Args:
            filename: Ruta del archivo CSV a cargar
            
        Returns:
            tuple: (success: bool, message: str, num_signals: int, num_points: int)
        """
        self.lock.lock()
        
        try:
            # Limpiar datos actuales
            self.data.clear()
            self.timestamps.clear()
            
            with open(filename, 'r') as csvfile:
                reader = csv.reader(csvfile)
                
                # Leer header
                header = next(reader)
                
                if not header or header[0] != 'timestamp':
                    self.lock.unlock()
                    return False, "Formato CSV inválido (falta columna timestamp)", 0, 0
                
                # Señales: todas las columnas excepto timestamp
                signal_names = header[1:]
                
                # Inicializar estructuras
                for signal in signal_names:
                    self.data[signal] = deque(maxlen=self.max_points)
                    self.timestamps[signal] = deque(maxlen=self.max_points)
                
                # Leer datos fila por fila
                num_rows = 0
                for row in reader:
                    if len(row) != len(header):
                        continue  # Saltar filas malformadas
                    
                    try:
                        timestamp = float(row[0])
                        
                        for i, signal in enumerate(signal_names):
                            value = float(row[i + 1])
                            self.data[signal].append(value)
                            self.timestamps[signal].append(timestamp)
                        
                        num_rows += 1
                    except ValueError:
                        continue  # Saltar filas con valores inválidos
                
                # Resetear start_time para que los timestamps del CSV sean relativos
                self.start_time = time.time()
                
                self.lock.unlock()
                return True, "CSV cargado correctamente", len(signal_names), num_rows
                
        except FileNotFoundError:
            self.lock.unlock()
            return False, "Archivo no encontrado", 0, 0
        except Exception as e:
            self.lock.unlock()
            return False, f"Error al cargar CSV: {str(e)}", 0, 0
    
    def export_to_csv(self, filename, all_signals_from_dbc=None):
        """Exporta todos los datos a CSV
        
        Args:
            filename: Ruta del archivo CSV a crear
            all_signals_from_dbc: Lista de todas las señales del DBC (opcional)
                                 Si se provee, las señales faltantes se rellenan con 0
        
        Returns:
            tuple: (success: bool, message: str)
        """
        self.lock.lock()
        
        try:
            # Si no hay datos, no exportar
            if not self.data:
                self.lock.unlock()
                return False, "No hay datos para exportar"
            
            # Determinar qué señales exportar
            if all_signals_from_dbc:
                # Usar TODAS las señales del DBC + las que tenemos en data
                signals_to_export = sorted(set(all_signals_from_dbc) | set(self.data.keys()))
            else:
                # Solo exportar las señales que tenemos
                signals_to_export = sorted(self.data.keys())
            
            # Crear un set unificado de todos los timestamps
            all_timestamps = set()
            for signal in self.data.keys():
                all_timestamps.update(self.timestamps[signal])
            
            # Ordenar timestamps
            sorted_timestamps = sorted(all_timestamps)
            
            # Crear diccionario de índices para búsqueda rápida
            # Para cada señal, mapear timestamp -> valor
            signal_data_map = {}
            for signal in signals_to_export:
                signal_data_map[signal] = {}
                if signal in self.data:
                    for t, v in zip(self.timestamps[signal], self.data[signal]):
                        signal_data_map[signal][t] = v
            
            # Escribir CSV
            with open(filename, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                
                # Header: timestamp + todas las señales
                header = ['timestamp'] + signals_to_export
                writer.writerow(header)
                
                # Escribir cada fila
                for ts in sorted_timestamps:
                    row = [f"{ts:.3f}"]  # Timestamp con 3 decimales
                    
                    for signal in signals_to_export:
                        # Si existe valor en ese timestamp, usarlo; sino, 0
                        value = signal_data_map[signal].get(ts, 0)
                        row.append(value)
                    
                    writer.writerow(row)
            
            num_rows = len(sorted_timestamps)
            num_signals = len(signals_to_export)
            self.lock.unlock()
            
            return True, f"Exportados {num_rows} puntos de {num_signals} señales"
            
        except Exception as e:
            self.lock.unlock()
            return False, f"Error al exportar: {str(e)}"

# --- Hilo de Trabajo CAN (Backend) ---
# --- Hilo de Trabajo CAN (Backend ESTILO ROBOWIN) ---
class CanWorker(QThread):
    connection_status = pyqtSignal(str, str)
    new_trace = pyqtSignal(str)

    def __init__(self, data_store):
        super().__init__()
        self.running = True
        self.serial = None  # Usamos serial directo, no can.Bus
        self.db = None
        self.data_lock = QMutex()
        self.latest_data = {} 
        self.last_receive_times = {}
        self.data_store = data_store  # Referencia al DataStore
        self.last_laptimer_timestamp_us = None
        self.laptimer_best_lap_s = None
        self.laptimer_lap_count = 0

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
        port_list = [port.device for port in ports]
        
        # Priorizar USB0 y USB1 (común en Linux)
        priority_ports = []
        other_ports = []
        
        for port in port_list:
            if 'USB0' in port or 'USB1' in port or 'COM0' in port or 'COM1' in port:
                priority_ports.append(port)
            else:
                other_ports.append(port)
        
        # Ordenar priority_ports para que USB0/COM0 esté primero
        priority_ports.sort()
        
        # Retornar primero los prioritarios, luego el resto
        return priority_ports + other_ports

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

    def process_laptimer_packet(self, data_bytes):
        """Decodifica paquete del laptimer (ID 0x777) y calcula tiempos por vuelta."""
        if len(data_bytes) < 8:
            return {}

        timestamp_us = int.from_bytes(data_bytes[:8], byteorder='little', signed=False)
        if self.last_laptimer_timestamp_us is None:
            self.last_laptimer_timestamp_us = timestamp_us
            return {
                'laptimer_timestamp_s': timestamp_us / 1_000_000.0,
                'laptimer_laps': self.laptimer_lap_count,
            }

        if timestamp_us <= self.last_laptimer_timestamp_us:
            return {}

        lap_time_s = (timestamp_us - self.last_laptimer_timestamp_us) / 1_000_000.0
        self.last_laptimer_timestamp_us = timestamp_us
        self.laptimer_lap_count += 1

        if (self.laptimer_best_lap_s is None) or (lap_time_s < self.laptimer_best_lap_s):
            self.laptimer_best_lap_s = lap_time_s

        return {
            'laptimer_timestamp_s': timestamp_us / 1_000_000.0,
            'laptimer_laps': self.laptimer_lap_count,
            'laptimer_last_lap_s': lap_time_s,
            'laptimer_best_lap_s': self.laptimer_best_lap_s,
        }

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
                            # --- A PARTIR DE AQUÍ, ES IGUAL QUE ANTES ---
                            current_time = time.time()
                            timestamp = time.strftime('%H:%M:%S')
                            
                            # Generar Traza
                            hex_data_view = ' '.join([f"{b:02X}" for b in data_bytes])
                            msg_name = "Unknown"
                            decoded_str = ""
                            decoded_signals = {}

                            if can_id == LAPTIMER_CAN_ID:
                                decoded_signals.update(self.process_laptimer_packet(data_bytes))
                                msg_name = "LAPTIMER"

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

                                    # Intentar decodificar y mezclar con señales derivadas (ej. laptimer)
                                    dbc_signals = self.db.decode_message(can_id, data_bytes)
                                    decoded_signals.update(dbc_signals)
                                    print(f"[DEBUG] Señales decodificadas: {decoded_signals}")
                                
                                except Exception as decode_err:
                                    if can_id != LAPTIMER_CAN_ID:
                                        decoded_str = f"(Decode Error: {decode_err})"
                                        print(f"[DEBUG] Error decodificando 0x{can_id:X}: {decode_err}")

                            # Actualizar GUI Data
                            if decoded_signals:
                                self.data_lock.lock()
                                self.latest_data.update(decoded_signals)
                                for key in decoded_signals.keys():
                                    self.last_receive_times[key] = current_time
                                self.data_lock.unlock()

                                # Guardar en DataStore persistente
                                for key, value in decoded_signals.items():
                                    if isinstance(value, (int, float)):
                                        self.data_store.add_sample(key, value)

                                # String para traza
                                parts_str = [f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}" for k, v in decoded_signals.items()]
                                decoded_str = " | ".join(parts_str)
                            elif not decoded_str:
                                decoded_str = "(Sin señales)"

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

# --- Widget de Gráfica Individual ---
class IndividualPlotWidget(QWidget):
    """Widget para una gráfica individual con su título y crosshair"""
    
    # Señal para sincronizar crosshair entre gráficas
    crosshair_moved = pyqtSignal(float)  # Emite posición X del mouse
    
    def __init__(self, signal_name, color, data_store, sliding_window=True, window_duration=15.0, display_name=None, y_range=None):
        super().__init__()
        self.signal_name = signal_name
        self.display_name = display_name or signal_name
        self.data_store = data_store
        self.color = color
        self.sliding_window = sliding_window
        self.window_duration = window_duration  # Duración de ventana deslizante en segundos
        self.y_range = y_range
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.setLayout(layout)
        
        # Título con valor actual
        self.title_label = QLabel(f"<b>{self.display_name}</b>: ---")
        self.title_label.setStyleSheet(f"color: {color}; font-size: 11pt; padding: 2px;")
        layout.addWidget(self.title_label)
        
        # Plot Widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('#1a1a1a')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.2)
        self.plot_widget.setDownsampling(mode='peak')
        self.plot_widget.setClipToView(True)
        self.plot_widget.setMinimumHeight(120)
        self.plot_widget.setMaximumHeight(200)
        
        # Configurar ejes
        self.plot_widget.setLabel('bottom', 'Tiempo', units='s')
        self.plot_widget.getAxis('bottom').setStyle(tickTextOffset=5)
        if self.y_range is not None:
            self.plot_widget.setYRange(self.y_range[0], self.y_range[1], padding=0)
        
        # Curva
        pen = pg.mkPen(color=color, width=2)
        self.curve = self.plot_widget.plot(pen=pen)
        
        # Crosshair (línea vertical)
        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('#ffff00', width=1, style=Qt.PenStyle.DashLine))
        self.vline.setVisible(False)
        self.plot_widget.addItem(self.vline)
        
        # Proxy para eventos del mouse
        self.proxy = pg.SignalProxy(self.plot_widget.scene().sigMouseMoved, rateLimit=60, slot=self.on_mouse_moved)
        
        # Conectar evento de salida del mouse
        self.plot_widget.leaveEvent = self.on_mouse_leave
        
        layout.addWidget(self.plot_widget)
        
        # Cache de datos para búsqueda rápida
        self.cached_timestamps = []
        self.cached_values = []
        
    def on_mouse_leave(self, event):
        """Callback cuando el mouse sale de la gráfica"""
        self.hide_crosshair()
        
    def on_mouse_moved(self, evt):
        """Callback cuando se mueve el mouse sobre la gráfica"""
        pos = evt[0]
        if self.plot_widget.sceneBoundingRect().contains(pos):
            mouse_point = self.plot_widget.plotItem.vb.mapSceneToView(pos)
            x = mouse_point.x()
            
            # Mostrar crosshair
            self.vline.setPos(x)
            self.vline.setVisible(True)
            
            # Emitir señal para otras gráficas
            self.crosshair_moved.emit(x)
            
            # Actualizar título con valor
            self.update_title_value(x)
    
    def update_crosshair(self, x_pos):
        """Actualiza el crosshair desde otra gráfica (sincronización)"""
        self.vline.setPos(x_pos)
        self.vline.setVisible(True)
        self.update_title_value(x_pos)
    
    def update_title_value(self, x_pos):
        """Actualiza el título con el valor en la posición X"""
        if not self.cached_timestamps or not self.cached_values:
            return
        
        # Buscar el valor más cercano al timestamp x_pos
        idx = bisect.bisect_left(self.cached_timestamps, x_pos)
        
        if idx >= len(self.cached_values):
            idx = len(self.cached_values) - 1
        elif idx > 0 and idx < len(self.cached_timestamps):
            # Elegir el más cercano
            if abs(self.cached_timestamps[idx - 1] - x_pos) < abs(self.cached_timestamps[idx] - x_pos):
                idx = idx - 1
        
        if 0 <= idx < len(self.cached_values):
            value = self.cached_values[idx]
            timestamp = self.cached_timestamps[idx]
            self.title_label.setText(f"<b>{self.display_name}</b>: {value:.2f} @ {timestamp:.2f}s")
    
    def get_value_at_time(self, x_pos):
        """Retorna el valor en un timestamp específico (para popup)"""
        if not self.cached_timestamps or not self.cached_values:
            return None
        
        idx = bisect.bisect_left(self.cached_timestamps, x_pos)
        
        if idx >= len(self.cached_values):
            idx = len(self.cached_values) - 1
        elif idx > 0 and idx < len(self.cached_timestamps):
            if abs(self.cached_timestamps[idx - 1] - x_pos) < abs(self.cached_timestamps[idx] - x_pos):
                idx = idx - 1
        
        if 0 <= idx < len(self.cached_values):
            return self.cached_values[idx]
        return None
    
    def hide_crosshair(self):
        """Oculta el crosshair"""
        self.vline.setVisible(False)
        self.title_label.setText(f"<b>{self.display_name}</b>: ---")
    
    def set_window_mode(self, mode, duration=None):
        """Cambia el modo de ventana temporal
        
        Args:
            mode: 'sliding' o 'full'
            duration: duración en segundos (solo para modo sliding)
        """
        if mode == 'sliding':
            self.sliding_window = True
            if duration is not None:
                self.window_duration = duration
        else:
            self.sliding_window = False
        
    def update_plot(self):
        """Actualiza la gráfica desde el DataStore"""
        timestamps, values = self.data_store.get_signal_data(self.signal_name)
        if timestamps and values:
            self.curve.setData(timestamps, values)
            # Cachear para búsqueda rápida
            self.cached_timestamps = timestamps
            self.cached_values = values

            if self.y_range is not None:
                self.plot_widget.setYRange(self.y_range[0], self.y_range[1], padding=0)
            
            # Aplicar sliding window si está habilitado
            if self.sliding_window and timestamps:
                max_time = max(timestamps)
                min_time = max(0, max_time - self.window_duration)
                self.plot_widget.setXRange(min_time, max_time, padding=0)
    
    def get_view_box(self):
        """Retorna el ViewBox para sincronización"""
        return self.plot_widget.getViewBox()

class SkidpadTrackWidget(QWidget):
    """Widget personalizado para dibujar el circuito en forma de 8 y los tiempos."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(600, 300)
        
        # Tiempos almacenados
        self.time_r1 = 0.0
        self.time_r2 = 0.0
        self.time_l1 = 0.0
        self.time_l2 = 0.0
        
        # Estado actual para resaltado visual (0=IDLE, 1=R1, 2=R2, 3=L1, 4=L2)
        self.active_section = 0
        
    def update_times(self, r1, r2, l1, l2, active_section):
        self.time_r1 = r1
        self.time_r2 = r2
        self.time_l1 = l1
        self.time_l2 = l2
        self.active_section = active_section
        self.update() # Forzar repintado
        
    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QColor, QFont, QPen
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        # Geometría básica de los círculos
        circle_radius = min(width // 4, height // 2) - 20
        center_y = height // 2
        left_center_x = width // 2 - circle_radius
        right_center_x = width // 2 + circle_radius
        
        # Estilos de dibujo
        track_pen = QPen(QColor("#11151c"), 40)
        active_pen = QPen(QColor("#00e676"), 40)
        text_pen = QPen(QColor("#ffffff"))
        font = QFont("Consolas", 12, QFont.Weight.Bold)
        painter.setFont(font)
        
        # Dibujar Círculo Izquierdo
        painter.setPen(active_pen if self.active_section in [3, 4] else track_pen)
        painter.drawEllipse(int(left_center_x - circle_radius), int(center_y - circle_radius), 
                            int(circle_radius * 2), int(circle_radius * 2))
        
        # Dibujar Círculo Derecho
        painter.setPen(active_pen if self.active_section in [1, 2] else track_pen)
        painter.drawEllipse(int(right_center_x - circle_radius), int(center_y - circle_radius), 
                            int(circle_radius * 2), int(circle_radius * 2))
        
        # Textos Izquierda
        painter.setPen(text_pen)
        l1_text = f"V1 Izq: {self.time_l1:.3f} s" if self.time_l1 > 0 else "V1 Izq: --.--- s"
        l2_text = f"V2 Izq: {self.time_l2:.3f} s" if self.time_l2 > 0 else "V2 Izq: --.--- s"
        painter.drawText(int(left_center_x - 70), int(center_y - 15), l1_text)
        painter.drawText(int(left_center_x - 70), int(center_y + 25), l2_text)
        
        # Textos Derecha
        r1_text = f"V1 Der: {self.time_r1:.3f} s" if self.time_r1 > 0 else "V1 Der: --.--- s"
        r2_text = f"V2 Der: {self.time_r2:.3f} s" if self.time_r2 > 0 else "V2 Der: --.--- s"
        painter.drawText(int(right_center_x - 70), int(center_y - 15), r1_text)
        painter.drawText(int(right_center_x - 70), int(center_y + 25), r2_text)

# --- Ventana Principal ---
class TelemetryWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ROBOWIN")
        self.resize(1366, 800)

        self.setStyleSheet(APP_STYLESHEET)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # NavBar horizontal estilo web
        navbar_layout = QHBoxLayout()
        navbar_layout.setContentsMargins(4, 4, 4, 4)
        navbar_layout.setSpacing(0)
        
        navbar_widget = QWidget()
        navbar_widget.setStyleSheet(
            "background-color: #202020; border-bottom: 1px solid #3a3a3a;"
        )
        navbar_widget.setMaximumHeight(50)
        navbar_widget.setLayout(navbar_layout)
        main_layout.addWidget(navbar_widget)
        
        # Botones de navegación
        navbar_layout.setSpacing(0)
        navbar_layout.setContentsMargins(0, 0, 0, 0)
        
        self.nav_btn_dashboard = self.create_nav_button("DASHBOARD", 0, active=True)
        navbar_layout.addWidget(self.nav_btn_dashboard)

        self.nav_btn_todo = self.create_nav_button("TODO", 1)
        navbar_layout.addWidget(self.nav_btn_todo)
        
        self.nav_btn_laptimer = self.create_nav_button("LAP TIMER", 2)
        navbar_layout.addWidget(self.nav_btn_laptimer)
        
        self.nav_btn_monitor = self.create_nav_button("Monitor CAN", 3)
        navbar_layout.addWidget(self.nav_btn_monitor)
        
        self.nav_btn_offline = self.create_nav_button("OFFLINE", 4)
        navbar_layout.addWidget(self.nav_btn_offline)
        
        navbar_layout.addStretch()
        
        # Estado y controles a la derecha
        self.status_label = QLabel("Iniciando sistema...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet(status_label_style())
        self.status_label.setMaximumWidth(300)
        navbar_layout.addWidget(self.status_label)
        
        self.popup_toggle_btn = QPushButton("POPUP OFF")
        self.popup_toggle_btn.setStyleSheet(popup_button_style(False))
        self.popup_toggle_btn.setMaximumWidth(100)
        self.popup_toggle_btn.setMaximumHeight(34)
        self.popup_toggle_btn.clicked.connect(self.toggle_popup)
        self.popup_toggle_btn.setToolTip("POPUP (F2)")
        navbar_layout.addWidget(self.popup_toggle_btn)
        
        # Stacked widget para páginas
        pages_layout = QVBoxLayout()
        pages_layout.setContentsMargins(0, 0, 0, 0)
        pages_layout.setSpacing(0)
        
        self.pages_stack = QStackedWidget()
        pages_layout.addWidget(self.pages_stack)
        main_layout.addLayout(pages_layout, 1)

        self.ui_labels = {} 
        self.checkboxes = {} 
        self.plot_widgets = {}
        self.dashboard_plot_widgets = {}
        self.dashboard_metric_labels = {}
        self.color_assignment = {}
        
        self.data_store = TelemetryDataStore(max_points=10000)
        self.signal_catalog = self.load_dbc_signal_catalog()
        self.signals_by_group = self.group_signals_by_category(self.signal_catalog)
        self.dashboard_critical_signals = self.select_dashboard_critical_signals()
        self.popup_enabled = False
        self.current_window_mode = 'sliding'
        self.current_window_duration = 15.0
        
        self.value_popup = QLabel(self)
        self.value_popup.setStyleSheet("""
            QLabel {
                background-color: rgba(40, 40, 40, 230);
                color: white;
                border: 2px solid #00e676;
                border-radius: 0px;
                padding: 6px;
                font-family: 'Consolas', monospace;
                font-size: 10pt;
            }
        """)
        self.value_popup.setVisible(False)
        self.value_popup.setWordWrap(False)
        self.value_popup.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.dashboard_tab = QWidget()
        self.setup_dashboard_ui()
        self.pages_stack.addWidget(self.dashboard_tab)

        self.todo_tab = QWidget()
        self.setup_todo_ui()
        self.pages_stack.addWidget(self.todo_tab)

        self.laptimer_tab = QWidget()
        self.setup_laptimer_ui()
        self.pages_stack.addWidget(self.laptimer_tab)

        self.traces_tab = QWidget()
        self.setup_traces_ui()
        self.pages_stack.addWidget(self.traces_tab)
        
        self.offline_tab = QWidget()
        self.setup_offline_ui()
        self.pages_stack.addWidget(self.offline_tab)

        self.switch_page(0)

        # Worker
        self.can_worker = CanWorker(self.data_store)
        self.can_worker.connection_status.connect(self.update_status)
        self.can_worker.new_trace.connect(self.append_trace)
        self.can_worker.start()

        # Timer
        self.timer = QTimer()
        self.timer.setInterval(REFRESH_RATE_MS) 
        self.timer.timeout.connect(self.update_ui_tick)
        self.timer.start()
        
        # Activar gráficas por defecto después de que se cree la UI
        QTimer.singleShot(100, self.activate_default_graphs)

    def create_nav_button(self, label, page_index, active=False):
        button = QPushButton(label)
        button.setStyleSheet(nav_button_style(active))
        button.setMaximumHeight(34)
        button.clicked.connect(lambda: self.switch_page(page_index))
        return button

    def classify_signal_group(self, message_name):
        name = (message_name or "").lower()
        if name.startswith("engine"):
            return "MOTOR"
        if name.startswith("currents"):
            return "ELECTRICO"
        if name in {"steering", "dampers"}:
            return "CHASIS"
        return "OTROS"

    def load_dbc_signal_catalog(self):
        catalog = []
        try:
            db = cantools.database.load_file(DBC_FILE)
        except Exception as exc:
            print(f"[DBC] No se pudo cargar catálogo UI desde DBC: {exc}")
            return catalog

        for message in db.messages:
            group = self.classify_signal_group(getattr(message, "name", ""))
            for signal in message.signals:
                minimum = signal.minimum
                maximum = signal.maximum
                y_range = None
                if minimum is not None and maximum is not None and minimum < maximum:
                    y_range = (minimum, maximum)

                label = signal.name.replace("_", " ").upper()
                catalog.append({
                    "key": signal.name,
                    "label": label,
                    "unit": signal.unit or "",
                    "group": group,
                    "message": getattr(message, "name", ""),
                    "y_range": y_range,
                })

        return catalog

    def group_signals_by_category(self, catalog):
        grouped = {"MOTOR": [], "CHASIS": [], "ELECTRICO": [], "OTROS": []}
        for signal in catalog:
            grouped.setdefault(signal["group"], []).append(signal)
        return grouped

    def select_dashboard_critical_signals(self):
        preferred_keys = ["ect", "oil_temp", "batt_volt"]
        by_key = {sig["key"]: sig for sig in self.signal_catalog}

        selected = [by_key[key] for key in preferred_keys if key in by_key]
        if len(selected) == len(preferred_keys):
            return selected

        # Fallback seguro si faltara alguna señal en el DBC
        motor_signals = list(self.signals_by_group.get("MOTOR", []))
        if len(motor_signals) >= 3:
            return motor_signals[:3]

        return list(self.signal_catalog)[:3]

    def setup_dashboard_ui(self):
        layout = QHBoxLayout(self.dashboard_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter)

        # --- COLUMNA 1: LAPTIME ---
        laptime_panel = QWidget()
        laptime_layout = QVBoxLayout(laptime_panel)
        laptime_layout.setContentsMargins(6, 6, 6, 6)
        laptime_layout.setSpacing(8)

        laptime_group = QGroupBox("LAPTIME")
        laptime_group_layout = QVBoxLayout(laptime_group)
        laptime_group_layout.setContentsMargins(8, 8, 8, 8)
        laptime_group_layout.setSpacing(8)

        self.dashboard_session_mode_label = QLabel("SESION ACTUAL: --")
        self.dashboard_session_mode_label.setStyleSheet("color: #ffd166; font-size: 12pt; font-weight: 700;")
        laptime_group_layout.addWidget(self.dashboard_session_mode_label)

        self.dashboard_session_state_label = QLabel("ESTADO: --")
        self.dashboard_session_state_label.setStyleSheet("color: #dbe7f4; background-color: #1b2230; border: 1px solid #426084; border-radius: 0px; padding: 6px 10px; font-size: 10pt;")
        laptime_group_layout.addWidget(self.dashboard_session_state_label)

        self.dashboard_total_time_label = QLabel("00:00.000")
        self.dashboard_total_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dashboard_total_time_label.setStyleSheet("background-color: #0f172a; color: #7dd3fc; border: 2px solid #2563eb; border-radius: 0px; font-size: 28px; font-weight: 800; padding: 14px 12px;")
        laptime_group_layout.addWidget(self.dashboard_total_time_label)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(6)
        self.dashboard_laps_count_label = QLabel("VUELTAS: 0")
        self.dashboard_last_lap_label = QLabel("ULTIMA: --:--.---")
        for label in [self.dashboard_laps_count_label, self.dashboard_last_lap_label]:
            label.setStyleSheet("color: #f1f5f9; background-color: #252a35; border: 1px solid #3a3a3a; border-radius: 0px; padding: 6px 10px; font-size: 10pt;")
            summary_row.addWidget(label)
        laptime_group_layout.addLayout(summary_row)

        self.dashboard_laps_table = QTableWidget(0, 4)
        self.dashboard_laps_table.setHorizontalHeaderLabels(["VUELTA", "TIEMPO", "DELTA", "ESTADO"])
        self.dashboard_laps_table.verticalHeader().setVisible(False)
        self.dashboard_laps_table.setAlternatingRowColors(True)
        self.dashboard_laps_table.setStyleSheet(
            "QTableWidget {background-color: #11151c; color: #f8fafc; border: 1px solid #2f3746; gridline-color: #2f3746; font-size: 10pt;} "
            "QHeaderView::section {background-color: #1f2937; color: #e6edf7; font-weight: 700; padding: 6px; border: 1px solid #2f3746;}"
        )
        dashboard_header = self.dashboard_laps_table.horizontalHeader()
        dashboard_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        dashboard_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        dashboard_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        dashboard_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        laptime_group_layout.addWidget(self.dashboard_laps_table, 1)

        laptime_layout.addWidget(laptime_group)
        splitter.addWidget(laptime_panel)

        # --- COLUMNA 2: VARIABLES CRITICAS ---
        metrics_panel = QWidget()
        metrics_layout = QVBoxLayout(metrics_panel)
        metrics_layout.setContentsMargins(6, 6, 6, 6)
        metrics_layout.setSpacing(8)

        metrics_group = QGroupBox("VARIABLES CRITICAS")
        metrics_group_layout = QVBoxLayout(metrics_group)
        metrics_group_layout.setContentsMargins(8, 8, 8, 8)
        metrics_group_layout.setSpacing(8)

        cards_grid = QGridLayout()
        cards_grid.setHorizontalSpacing(8)
        cards_grid.setVerticalSpacing(8)
        cards = []
        for idx, signal in enumerate(self.dashboard_critical_signals):
            cards.append((signal["label"], signal["key"], signal["unit"], GRAPH_COLORS[idx % len(GRAPH_COLORS)]))

        self.dashboard_metric_labels = {}
        for index, (title_text, signal_key, unit_text, color) in enumerate(cards):
            card = QFrame()
            card.setMinimumSize(100, 110)
            card.setStyleSheet(
                f"QFrame {{ background-color: #171c24; border: 1px solid {color}; border-radius: 0px; }}"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 10, 10, 10)
            card_layout.setSpacing(4)

            card_title = QLabel(title_text)
            card_title.setStyleSheet("color: #cbd5e1; font-size: 10pt; font-weight: 700;")
            card_layout.addWidget(card_title)

            card_value = QLabel("--")
            card_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_value.setStyleSheet(f"color: {color}; font-size: 24px; font-weight: 800;")
            card_layout.addWidget(card_value, 1)

            card_unit = QLabel(unit_text)
            card_unit.setAlignment(Qt.AlignmentFlag.AlignRight)
            card_unit.setStyleSheet("color: #9fb3c8; font-size: 9pt;")
            card_layout.addWidget(card_unit)

            if signal_key is not None:
                self.dashboard_metric_labels[signal_key] = card_value

            row = index
            col = 0
            cards_grid.addWidget(card, row, col)

        metrics_group_layout.addLayout(cards_grid)
        metrics_group_layout.addStretch()
        metrics_layout.addWidget(metrics_group)
        splitter.addWidget(metrics_panel)

        # --- COLUMNA 3: GRAFICAS ---
        plots_panel = QWidget()
        plots_layout = QVBoxLayout(plots_panel)
        plots_layout.setContentsMargins(6, 6, 6, 6)
        plots_layout.setSpacing(8)

        plots_group = QGroupBox("GRAFICAS")
        plots_group_layout = QVBoxLayout(plots_group)
        plots_group_layout.setContentsMargins(8, 8, 8, 8)
        plots_group_layout.setSpacing(8)

        self.dashboard_plot_widgets = {}
        dashboard_plots = []
        for idx, signal in enumerate(self.dashboard_critical_signals):
            dashboard_plots.append((
                signal["key"],
                signal["label"],
                GRAPH_COLORS[idx % len(GRAPH_COLORS)],
                signal.get("y_range"),
            ))

        for signal_name, display_name, color, y_range in dashboard_plots:
            plot_widget = IndividualPlotWidget(
                signal_name,
                color,
                self.data_store,
                sliding_window=True,
                window_duration=15.0,
                display_name=display_name,
                y_range=y_range,
            )
            plot_widget.setMinimumHeight(150)
            plot_widget.setMaximumHeight(220)
            self.dashboard_plot_widgets[signal_name] = plot_widget
            plots_group_layout.addWidget(plot_widget)

        plots_group_layout.addStretch()

        self.dashboard_plots_scroll = QScrollArea()
        self.dashboard_plots_scroll.setWidgetResizable(True)
        self.dashboard_plots_scroll.setStyleSheet("QScrollArea { border: 1px solid #444; background-color: #1e1e1e; }")
        self.dashboard_plots_container = QWidget()
        self.dashboard_plots_container_layout = QVBoxLayout(self.dashboard_plots_container)
        self.dashboard_plots_container_layout.setContentsMargins(0, 0, 0, 0)
        self.dashboard_plots_container_layout.setSpacing(8)
        self.dashboard_plots_container_layout.addWidget(plots_group)
        self.dashboard_plots_container_layout.addStretch()
        self.dashboard_plots_scroll.setWidget(self.dashboard_plots_container)
        plots_layout.addWidget(self.dashboard_plots_scroll)
        splitter.addWidget(plots_panel)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 5)
        splitter.setSizes([320, 160, 800])

    def update_dashboard_view(self, data_snapshot, times_snapshot):
        session_mode = self.session_mode.upper() if self.session_mode else "--"
        if self.session_running and not self.session_paused:
            state_text = "EN CURSO"
        elif self.session_paused:
            state_text = "EN PAUSA"
        elif self.session_laps:
            state_text = "DETENIDO"
        else:
            state_text = "LISTO"

        self.dashboard_session_mode_label.setText(f"SESION ACTUAL: {session_mode}")
        self.dashboard_session_state_label.setText(f"ESTADO: {state_text}")

        stopwatch_s = self.get_laptimer_stopwatch_seconds()
        self.dashboard_total_time_label.setText(self.format_lap_time(stopwatch_s))
        self.dashboard_laps_count_label.setText(f"VUELTAS: {len(self.session_laps)}")
        last_lap = self.session_laps[-1] if self.session_laps else None
        self.dashboard_last_lap_label.setText(f"ULTIMA: {self.format_lap_time(last_lap)}" if last_lap is not None else "ULTIMA: --:--.---")

        best_lap = min(self.session_laps) if self.session_laps else None
        table = self.dashboard_laps_table
        table.setRowCount(len(self.session_laps))
        for idx, lap_time in enumerate(self.session_laps):
            delta = 0.0 if best_lap is None else lap_time - best_lap
            if best_lap is not None and abs(delta) < 1e-9:
                state = "BEST"
            elif idx == len(self.session_laps) - 1:
                state = "LAST"
            else:
                state = ""

            values = [
                str(idx + 1),
                self.format_lap_time(lap_time),
                f"+{delta:.3f}s" if delta > 0 else "0.000s",
                state,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                table.setItem(idx, col, item)

        if not self.session_laps:
            table.setRowCount(0)

        for signal_name, label_widget in self.dashboard_metric_labels.items():
            if signal_name not in data_snapshot:
                label_widget.setText("--")
                continue

            value = data_snapshot[signal_name]
            if isinstance(value, float):
                label_widget.setText(f"{value:.2f}")
            else:
                label_widget.setText(str(value))

        for plot_widget in self.dashboard_plot_widgets.values():
            plot_widget.update_plot()

    def setup_todo_ui(self):
        # Splitter principal: PANEL CONTROL | GRÁFICAS
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setHandleWidth(1)
        main_splitter.setChildrenCollapsible(False)
        self.todo_tab.setLayout(QVBoxLayout())
        self.todo_tab.layout().setContentsMargins(0, 0, 0, 0)
        self.todo_tab.layout().setSpacing(0)
        self.todo_tab.layout().addWidget(main_splitter)
        
        # --- PANEL IZQUIERDO: CONTROLES ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(8)
        
        # Botones de control
        control_group = QGroupBox("CONTROL")
        control_layout = QVBoxLayout()
        control_layout.setContentsMargins(6, 6, 6, 6)
        control_layout.setSpacing(6)
        
        export_btn = QPushButton("EXPORTAR DATOS")
        export_btn.setStyleSheet(action_button_style("#388e3c", font_size_pt=9))
        export_btn.clicked.connect(self.export_to_csv)
        control_layout.addWidget(export_btn)
        
        control_group.setLayout(control_layout)
        left_layout.addWidget(control_group)
        
        # Selector de ventana temporal
        window_group = QGroupBox("VENTANA TEMPORAL")
        window_layout = QVBoxLayout()
        window_layout.setContentsMargins(6, 6, 6, 6)
        window_layout.setSpacing(6)
        
        self.window_button_group = QButtonGroup()
        
        self.rb_15s = QRadioButton("15 SEGUNDOS")
        self.rb_15s.setChecked(True)
        self.rb_15s.toggled.connect(lambda checked: checked and self.change_window_mode('sliding', 15.0))
        window_layout.addWidget(self.rb_15s)
        self.window_button_group.addButton(self.rb_15s)
        
        self.rb_5min = QRadioButton("5 MINUTOS")
        self.rb_5min.toggled.connect(lambda checked: checked and self.change_window_mode('sliding', 300.0))
        window_layout.addWidget(self.rb_5min)
        self.window_button_group.addButton(self.rb_5min)
        
        self.rb_full = QRadioButton("TODO EL TIEMPO")
        self.rb_full.toggled.connect(lambda checked: checked and self.change_window_mode('full', None))
        window_layout.addWidget(self.rb_full)
        self.window_button_group.addButton(self.rb_full)
        
        window_group.setLayout(window_layout)
        left_layout.addWidget(window_group)
        
        # Grupos de señales con checkboxes
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; }")
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(6)
        
        for group_name in ["MOTOR", "CHASIS", "ELECTRICO", "OTROS"]:
            group_signals = self.signals_by_group.get(group_name, [])
            if not group_signals:
                continue

            signals = [(sig["label"], sig["key"], sig["unit"]) for sig in group_signals]
            if group_name == "MOTOR":
                group_widget = self.create_data_group(group_name, signals, font_size=12, prominent=True)
            else:
                group_widget = self.create_data_group(group_name, signals)
            scroll_layout.addWidget(group_widget)
        
        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        left_layout.addWidget(scroll_area)
        
        # --- PANEL DERECHO: GRÁFICAS ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(8)
        
        # ScrollArea para gráficas
        self.plots_scroll = QScrollArea()
        self.plots_scroll.setWidgetResizable(True)
        self.plots_scroll.setStyleSheet("QScrollArea { border: 1px solid #444; background-color: #1e1e1e; }")
        
        self.plots_container = QWidget()
        self.plots_layout = QVBoxLayout(self.plots_container)
        self.plots_layout.setContentsMargins(0, 0, 0, 0)
        self.plots_layout.setSpacing(0)
        self.plots_layout.addStretch()
        
        self.plots_scroll.setWidget(self.plots_container)
        right_layout.addWidget(self.plots_scroll)
        
        # Configurar splitter
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 1)  # Panel izquierdo: 1 parte
        main_splitter.setStretchFactor(1, 5)  # Panel derecho: 5 partes (más ancho para gráficas)
        main_splitter.setSizes([220, 1130])

    def setup_traces_ui(self):
        layout = QVBoxLayout(self.traces_tab)
        info_label = QLabel("Monitor CAN en tiempo real: Muestra datos en bruto")
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
    
    def setup_offline_ui(self):
        """Tab para análisis offline de archivos CSV"""
        layout = QVBoxLayout(self.offline_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Splitter similar al dashboard en vivo
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setHandleWidth(1)
        main_splitter.setChildrenCollapsible(False)
        
        # Panel izquierdo: controles
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(8)
        
        control_group = QGroupBox("CONTROL")
        control_layout = QVBoxLayout()
        control_layout.setContentsMargins(6, 6, 6, 6)
        control_layout.setSpacing(6)
        
        load_csv_btn = QPushButton("CARGAR CSV")
        load_csv_btn.setStyleSheet(action_button_style("#455a64", font_size_pt=9))
        load_csv_btn.clicked.connect(self.load_csv_file)
        control_layout.addWidget(load_csv_btn)
        
        control_group.setLayout(control_layout)
        left_layout.addWidget(control_group)

        sessions_group = QGroupBox("SESIONES LAPTIMER")
        sessions_layout = QVBoxLayout()
        sessions_layout.setContentsMargins(6, 6, 6, 6)
        sessions_layout.setSpacing(6)

        self.offline_session_selector = QComboBox()
        self.offline_session_selector.setStyleSheet(
            "QComboBox {background-color: #1d2735; color: #e8f0ff; border: 1px solid #426084; "
            "border-radius: 0px; padding: 6px 10px; font-size: 10pt;}"
        )
        self.offline_session_selector.addItem("SIN SESIONES CARGADAS")
        self.offline_session_selector.currentIndexChanged.connect(self.on_offline_session_selected)
        sessions_layout.addWidget(self.offline_session_selector)

        self.offline_select_session_btn = QPushButton("SELECCIONAR SESION")
        self.offline_select_session_btn.setStyleSheet(action_button_style("#2e7d32", font_size_pt=9))
        self.offline_select_session_btn.clicked.connect(self.select_offline_session)
        sessions_layout.addWidget(self.offline_select_session_btn)

        self.offline_session_summary = QLabel("CARGA UN CSV DE SESIONES PARA ANALIZAR VUELTAS.")
        self.offline_session_summary.setStyleSheet(
            "color: #9fb3c8; background-color: #1b2230; border: 1px solid #3a3a3a; "
            "border-radius: 0px; padding: 8px 10px; font-size: 10pt;"
        )
        self.offline_session_summary.setWordWrap(True)
        sessions_layout.addWidget(self.offline_session_summary)

        sessions_group.setLayout(sessions_layout)
        left_layout.addWidget(sessions_group)

        self.offline_session_laps_table = QTableWidget(0, 4)
        self.offline_session_laps_table.setHorizontalHeaderLabels(["Vuelta", "Tiempo", "Delta", "Estado"])
        self.offline_session_laps_table.verticalHeader().setVisible(False)
        self.offline_session_laps_table.setAlternatingRowColors(True)
        self.offline_session_laps_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.offline_session_laps_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.offline_session_laps_table.setStyleSheet(
            "QTableWidget {background-color: #101722; color: #f8fafc; border: 1px solid #2f3746; "
            "gridline-color: #2f3746; font-size: 10pt;} "
            "QHeaderView::section {background-color: #1f2937; color: #e6edf7; font-weight: 700; padding: 6px; border: 1px solid #2f3746;}"
        )
        session_table_header = self.offline_session_laps_table.horizontalHeader()
        session_table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        session_table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        session_table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        session_table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.offline_session_laps_table.currentCellChanged.connect(self.on_offline_session_lap_row_changed)
        left_layout.addWidget(self.offline_session_laps_table, 1)
        
        # Panel derecho: gráficas (telemetría + sesiones)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        self.offline_right_tabs = QTabWidget()
        self.offline_right_tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #2f3746; background-color: #0f141c; }"
            "QTabBar::tab { background: #202b39; color: #9fb3c8; padding: 6px 14px; border: 1px solid #2f3746; border-radius: 0px; }"
            "QTabBar::tab:selected { background: #2e3f56; color: #ffffff; border-bottom: 1px solid #00e676; }"
        )

        telemetry_page = QWidget()
        telemetry_layout = QVBoxLayout(telemetry_page)
        telemetry_layout.setContentsMargins(0, 0, 0, 0)

        self.offline_combined_hint = QLabel("VISTA COMBINADA: TELEMETRIA Y EVENTOS LAPTIME SINCRONIZADOS POR TIMESTAMP")
        self.offline_combined_hint.setStyleSheet("color: #9fb3c8; font-size: 10pt;")
        telemetry_layout.addWidget(self.offline_combined_hint)

        self.offline_plots_scroll = QScrollArea()
        self.offline_plots_scroll.setWidgetResizable(True)
        self.offline_plots_scroll.setStyleSheet("QScrollArea { border: 1px solid #444; background-color: #1e1e1e; }")
        
        self.offline_plots_container = QWidget()
        self.offline_plots_layout = QVBoxLayout(self.offline_plots_container)
        self.offline_plots_layout.setSpacing(10)
        self.offline_plots_layout.addStretch()
        
        self.offline_plots_scroll.setWidget(self.offline_plots_container)
        telemetry_layout.addWidget(self.offline_plots_scroll, 3)

        combined_group = QGroupBox("Eventos Laptime sincronizados")
        combined_layout = QVBoxLayout(combined_group)

        self.offline_combined_laps_table = QTableWidget(0, 7)
        self.offline_combined_laps_table.setHorizontalHeaderLabels(["t(s)", "Sesión", "Modo", "Vuelta", "Tiempo", "Delta", "Estado"])
        self.offline_combined_laps_table.verticalHeader().setVisible(False)
        self.offline_combined_laps_table.setAlternatingRowColors(True)
        self.offline_combined_laps_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.offline_combined_laps_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.offline_combined_laps_table.currentCellChanged.connect(self.on_offline_combined_lap_row_changed)
        self.offline_combined_laps_table.setStyleSheet(
            "QTableWidget {background-color: #101722; color: #f8fafc; border: 1px solid #2f3746; "
            "gridline-color: #2f3746; font-size: 10pt;} "
            "QHeaderView::section {background-color: #1f2937; color: #e6edf7; font-weight: 700; padding: 6px; border: 0;}"
        )

        filters_row = QHBoxLayout()
        filters_row.addWidget(QLabel("Filtrar sesión:"))
        self.offline_combined_session_filter = QComboBox()
        self.offline_combined_session_filter.addItem("Todas")
        self.offline_combined_session_filter.currentIndexChanged.connect(self.on_offline_combined_filter_changed)
        filters_row.addWidget(self.offline_combined_session_filter)
        filters_row.addWidget(QLabel("Modo:"))
        self.offline_combined_mode_filter = QComboBox()
        self.offline_combined_mode_filter.addItem("Todos")
        self.offline_combined_mode_filter.currentIndexChanged.connect(self.on_offline_combined_filter_changed)
        filters_row.addWidget(self.offline_combined_mode_filter)
        self.offline_jump_lap_btn = QPushButton("VER VUELTA")
        self.offline_jump_lap_btn.setStyleSheet(action_button_style("#455a64", font_size_pt=9))
        self.offline_jump_lap_btn.clicked.connect(self.show_selected_offline_combined_lap)
        filters_row.addWidget(self.offline_jump_lap_btn)
        filters_row.addStretch()
        combined_layout.addLayout(filters_row)

        combined_header = self.offline_combined_laps_table.horizontalHeader()
        combined_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        combined_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        combined_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        combined_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        combined_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        combined_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        combined_header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        combined_layout.addWidget(self.offline_combined_laps_table)

        telemetry_layout.addWidget(combined_group, 2)

        sessions_page = QWidget()
        sessions_layout_right = QVBoxLayout(sessions_page)
        sessions_layout_right.setContentsMargins(0, 0, 0, 0)

        self.offline_session_plot = pg.PlotWidget()
        self.offline_session_plot.setBackground('#11151c')
        self.offline_session_plot.showGrid(x=True, y=True, alpha=0.25)
        self.offline_session_plot.setLabel('left', 'Tiempo vuelta', units='s', color='#e2e8f0')
        self.offline_session_plot.setLabel('bottom', 'Núm. vuelta', color='#e2e8f0')
        self.offline_session_plot.setTitle('Vuelta por vuelta', color='#ffd166', size='12pt')
        sessions_layout_right.addWidget(self.offline_session_plot)

        self.offline_session_plot_hint = QLabel("Selecciona una sesión para visualizar la evolución de vueltas")
        self.offline_session_plot_hint.setStyleSheet("color: #9fb3c8; font-size: 10pt;")
        sessions_layout_right.addWidget(self.offline_session_plot_hint)

        self.offline_right_tabs.addTab(telemetry_page, "Telemetría")
        self.offline_right_tabs.addTab(sessions_page, "Sesiones")
        right_layout.addWidget(self.offline_right_tabs)
        
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 3)
        main_splitter.setSizes([350, 1000])
        
        layout.addWidget(main_splitter)
        
        # Diccionarios para modo offline
        self.offline_checkboxes = {}
        self.offline_plot_widgets = {}
        self.offline_loaded_sessions = []
        self.offline_selected_session_index = -1
        self.offline_session_marker = None
        self.offline_unified_laptime_rows = []
        self.offline_filtered_laptime_rows = []
        self.offline_current_session_rows = []

    def setup_laptimer_ui(self):
        """Tab dedicado a LapTimer con métricas destacadas y tabla histórica."""
        layout = QVBoxLayout(self.laptimer_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.session_mode = "Skidpad"
        self.session_running = False
        self.session_paused = False
        self.session_elapsed_before_pause = 0.0
        self.session_started_at = None
        self.session_started_wallclock = None
        self.session_first_lt_ts = None
        self.session_last_lt_ts = None
        self.session_laps = []
        self.session_lt_cursor = 0
        self.session_last_lap_armed = False
        self.completed_sessions = []
        self.laptimer_panel_widgets = {}

        # Franja superior horizontal compacta
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)

        header = QLabel("LAP TIMER")
        header.setStyleSheet("color: #ffd166; font-size: 22px; font-weight: 700;")
        top_row.addWidget(header)

        subheader = QLabel("RESOLUCION: MS")
        subheader.setStyleSheet("color: #9fb3c8; font-size: 10pt;")
        top_row.addWidget(subheader)

        self.session_status_label = QLabel("ESTADO: SKIDPAD LISTO, PENDIENTE DE INICIAR")
        self.session_status_label.setStyleSheet(
            "color: #dbe7f4; background-color: #1b2230; border: 1px solid #426084; "
            "border-radius: 0px; padding: 4px 8px; font-size: 10pt;"
        )
        top_row.addWidget(self.session_status_label, 1)

        top_row.addStretch()

        # Resumen rápido alineado en la franja superior
        self.laps_count_label = QLabel("VUELTAS: 0")
        self.last_lap_label = QLabel("ULTIMA: --:--.---")
        self.total_time_label = QLabel("TOTAL: --:--.---")
        self.stopwatch_label = QLabel("CRONO: --:--.---")

        for lbl in [self.laps_count_label, self.last_lap_label, self.total_time_label, self.stopwatch_label]:
            lbl.setStyleSheet("color: #f1f5f9; background-color: #252a35; border: 1px solid #3a3a3a; border-radius: 0px; padding: 6px 10px; font-size: 10pt;")
            top_row.addWidget(lbl)

        layout.addLayout(top_row)

        # Parte inferior: dos columnas al 50% para aprovechar pantalla
        laptimer_splitter = QSplitter(Qt.Orientation.Horizontal)
        laptimer_splitter.setHandleWidth(1)
        laptimer_splitter.setChildrenCollapsible(False)
        layout.addWidget(laptimer_splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(8)

        session_box = QGroupBox("CONTROL DE SESION")
        session_box_layout = QGridLayout(session_box)
        session_box_layout.setContentsMargins(6, 6, 6, 6)
        session_box_layout.setHorizontalSpacing(6)
        session_box_layout.setVerticalSpacing(6)

        mode_lbl = QLabel("SESION")
        mode_lbl.setStyleSheet("color: #dbe7f4; font-size: 10pt; font-weight: 700;")
        session_box_layout.addWidget(mode_lbl, 0, 0)

        self.session_selector = QComboBox()
        self.session_selector.addItems(["SKIDPAD", "AUTOCROSS", "ENDURANCE"])
        self.session_selector.setStyleSheet(
            "QComboBox {background-color: #1d2735; color: #e8f0ff; border: 1px solid #426084; "
            "border-radius: 0px; padding: 6px 10px; font-size: 10pt;}"
        )
        self.session_selector.currentTextChanged.connect(self.on_session_mode_changed)
        session_box_layout.addWidget(self.session_selector, 0, 1)

        name_lbl = QLabel("NOMBRE")
        name_lbl.setStyleSheet("color: #dbe7f4; font-size: 10pt; font-weight: 700;")
        session_box_layout.addWidget(name_lbl, 0, 2)

        self.session_name_input = QLineEdit()
        self.session_name_input.setPlaceholderText("EJ: TEST")
        self.session_name_input.setStyleSheet(
            "QLineEdit {background-color: #1d2735; color: #e8f0ff; border: 1px solid #426084; "
            "border-radius: 0px; padding: 6px 10px; font-size: 10pt;}"
        )
        session_box_layout.addWidget(self.session_name_input, 0, 3)

        self.start_session_btn = QPushButton("INICIAR")
        self.start_session_btn.setStyleSheet("background-color: #1b7a4a; color: white; padding: 8px 12px; border: 1px solid #3a3a3a; border-radius: 0px; font-weight: 700;")
        self.start_session_btn.clicked.connect(self.start_session)
        session_box_layout.addWidget(self.start_session_btn, 1, 0)

        self.pause_session_btn = QPushButton("PAUSAR")
        self.pause_session_btn.setStyleSheet("background-color: #915f00; color: white; padding: 8px 12px; border: 1px solid #3a3a3a; border-radius: 0px; font-weight: 700;")
        self.pause_session_btn.clicked.connect(self.toggle_pause_session)
        self.pause_session_btn.setEnabled(False)
        session_box_layout.addWidget(self.pause_session_btn, 1, 1)

        self.stop_session_btn = QPushButton("DETENER")
        self.stop_session_btn.setStyleSheet("background-color: #8f2c2c; color: white; padding: 8px 12px; border: 1px solid #3a3a3a; border-radius: 0px; font-weight: 700;")
        self.stop_session_btn.clicked.connect(self.stop_session)
        self.stop_session_btn.setEnabled(False)
        session_box_layout.addWidget(self.stop_session_btn, 1, 2)

        self.last_lap_btn = QPushButton(LAPTIMER_LAST_LAP_TEXT)
        self.last_lap_btn.setStyleSheet("background-color: #5c4b00; color: white; padding: 8px 12px; border: 1px solid #3a3a3a; border-radius: 0px; font-weight: 700;")
        self.last_lap_btn.clicked.connect(self.arm_last_lap)
        self.last_lap_btn.setEnabled(False)
        session_box_layout.addWidget(self.last_lap_btn, 1, 3)

        session_box_layout.setColumnStretch(1, 1)
        session_box_layout.setColumnStretch(3, 2)
        left_layout.addWidget(session_box)

        self.mode_stack = QStackedWidget()

        self.skidpad_panel = self.create_laptimer_mode_panel(
            "Skidpad",
            "Enfoque en referencia de giro y mejor vuelta.",
            layout_variant="skidpad",
        )
        self.autocross_panel = self.create_laptimer_mode_panel(
            "Autocross",
            "Tiempo total de sesión + tabla de vueltas.",
            layout_variant="autocross",
        )
        self.endurance_panel = self.create_laptimer_mode_panel(
            "Endurance",
            "Tiempo total de sesión + consistencia de vueltas.",
            layout_variant="endurance",
        )

        self.mode_stack.addWidget(self.skidpad_panel)
        self.mode_stack.addWidget(self.autocross_panel)
        self.mode_stack.addWidget(self.endurance_panel)
        left_layout.addWidget(self.mode_stack, 1)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(8)

        self.laptimer_history_table = QTableWidget(0, 7)
        self.laptimer_history_table.setHorizontalHeaderLabels(["#", "NOMBRE", "MODO", "INICIO", "FIN", "VUELTAS", "RESUMEN"])
        self.laptimer_history_table.verticalHeader().setVisible(False)
        self.laptimer_history_table.setAlternatingRowColors(True)
        self.laptimer_history_table.setMinimumHeight(230)
        self.laptimer_history_table.setStyleSheet(
            "QTableWidget {background-color: #11151c; color: #f8fafc; border: 1px solid #2f3746; "
            "gridline-color: #2f3746; font-size: 10pt;} "
            "QHeaderView::section {background-color: #1f2937; color: #e6edf7; font-weight: 700; padding: 6px; border: 1px solid #2f3746;}"
        )

        history_header = self.laptimer_history_table.horizontalHeader()
        history_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        history_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        history_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        history_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        history_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        history_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        history_header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)

        history_box = QGroupBox("HISTORIAL DE SESIONES")
        history_layout = QVBoxLayout(history_box)
        history_layout.setContentsMargins(6, 6, 6, 6)
        history_layout.setSpacing(8)

        history_controls = QHBoxLayout()
        history_controls.setContentsMargins(0, 0, 0, 0)
        history_controls.setSpacing(6)
        history_controls.addWidget(QLabel("SESION GUARDADA:"))

        self.saved_session_selector = QComboBox()
        self.saved_session_selector.setStyleSheet(
            "QComboBox {background-color: #1d2735; color: #e8f0ff; border: 1px solid #426084; "
            "border-radius: 0px; padding: 6px 10px; font-size: 10pt;}"
        )
        self.saved_session_selector.currentIndexChanged.connect(self.on_saved_session_selected)
        history_controls.addWidget(self.saved_session_selector, 1)



        history_layout.addLayout(history_controls)

        self.saved_session_details = QLabel("SIN SESIONES GUARDADAS")
        self.saved_session_details.setStyleSheet("color: #9fb3c8; background-color: #1b2230; border: 1px solid #3a3a3a; border-radius: 0px; padding: 8px 10px; font-size: 10pt;")
        history_layout.addWidget(self.saved_session_details)

        self.saved_session_laps_table = QTableWidget(0, 4)
        self.saved_session_laps_table.setHorizontalHeaderLabels(["Vuelta", "Tiempo", "Delta", "Estado"])
        self.saved_session_laps_table.verticalHeader().setVisible(False)
        self.saved_session_laps_table.setAlternatingRowColors(True)
        self.saved_session_laps_table.setMinimumHeight(180)
        self.saved_session_laps_table.setStyleSheet(
            "QTableWidget {background-color: #101722; color: #f8fafc; border: 1px solid #2f3746; "
            "gridline-color: #2f3746; font-size: 10pt;} "
            "QHeaderView::section {background-color: #1f2937; color: #e6edf7; font-weight: 700; padding: 6px; border: 1px solid #2f3746;}"
        )
        laps_header = self.saved_session_laps_table.horizontalHeader()
        laps_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        laps_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        laps_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        laps_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        history_layout.addWidget(self.saved_session_laps_table)

        history_layout.addWidget(self.laptimer_history_table, 1)
        right_layout.addWidget(history_box, 1)

        laptimer_splitter.addWidget(left_panel)
        laptimer_splitter.addWidget(right_panel)
        laptimer_splitter.setStretchFactor(0, 1)
        laptimer_splitter.setStretchFactor(1, 1)
        laptimer_splitter.setSizes([700, 700])

        self.laptimer_session_counter = 0
        self.session_summary_popup = None
        self.update_session_interface()
        self.reset_laptimer_view()
        self.update_saved_session_selector()

    def create_laptimer_mode_panel(self, title, subtitle, layout_variant="autocross"):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setStyleSheet("color: #ffd166; font-size: 14px; font-weight: 800;")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setStyleSheet("color: #9fb3c8; font-size: 9pt;")

        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)

        mini_row = QHBoxLayout()
        mini_row.setSpacing(6)

        session_time_label = QLabel("00:00.000")
        session_time_label.setObjectName(f"{title}_session_time")
        session_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        session_time_label.setStyleSheet(
            "background-color: #0f172a; color: #7dd3fc; border: 2px solid #2563eb; "
            "border-radius: 0px; font-size: 24px; font-weight: 800; padding: 12px 14px;"
        )

        total_time_card = QLabel("--:--.---")
        total_time_card.setObjectName(f"{title}_total_time")
        total_time_card.setAlignment(Qt.AlignmentFlag.AlignCenter)
        total_time_card.setStyleSheet(
            "background-color: #1a2433; color: #f9fafb; border: 2px solid #44546a; "
            "border-radius: 0px; font-size: 18px; font-weight: 700; padding: 10px 12px;"
        )

        best_time_card = QLabel("--:--.---")
        best_time_card.setObjectName(f"{title}_best_time")
        best_time_card.setAlignment(Qt.AlignmentFlag.AlignCenter)
        best_time_card.setStyleSheet(
            "background-color: #072b1f; color: #39ff9b; border: 2px solid #1aff8c; "
            "border-radius: 0px; font-size: 18px; font-weight: 800; padding: 10px 12px;"
        )

        avg_time_card = QLabel("--:--.---")
        avg_time_card.setObjectName(f"{title}_avg_time")
        avg_time_card.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avg_time_card.setStyleSheet(
            "background-color: #1f2233; color: #8fc1ff; border: 2px solid #4f7ddb; "
            "border-radius: 0px; font-size: 18px; font-weight: 700; padding: 10px 12px;"
        )

        def pack_with_label(widget, text):
            container = QWidget()
            vbox = QVBoxLayout(container)
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.setSpacing(2)
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #8fa0b5; font-size: 9pt; font-weight: bold;")
            vbox.addWidget(lbl)
            vbox.addWidget(widget)
            return container

        mini_row.addWidget(pack_with_label(session_time_label, "TIEMPO EN VIVO"), 2)
        if layout_variant == "skidpad":
            mini_row.addWidget(pack_with_label(best_time_card, "MEJOR VUELTA"), 1)
            mini_row.addWidget(pack_with_label(avg_time_card, "MEDIA VUELTAS"), 1)
            mini_row.addWidget(pack_with_label(total_time_card, "SKIDPAD FS (MEDIA)"), 1)
        elif layout_variant == "endurance":
            mini_row.addWidget(pack_with_label(total_time_card, "TIEMPO TOTAL"), 1)
            mini_row.addWidget(pack_with_label(avg_time_card, "TIEMPO MEDIO"), 1)
            mini_row.addWidget(pack_with_label(best_time_card, "MEJOR VUELTA"), 1)
        else:
            mini_row.addWidget(pack_with_label(total_time_card, "TIEMPO TOTAL"), 1)
            mini_row.addWidget(pack_with_label(best_time_card, "MEJOR VUELTA"), 1)
            mini_row.addWidget(pack_with_label(avg_time_card, "TIEMPO MEDIO"), 1)

        layout.addLayout(mini_row)

        session_table = QTableWidget(0, 4)
        session_table.setObjectName(f"{title}_table")
        session_table.setHorizontalHeaderLabels(["Vuelta", "Tiempo", "Delta", "Estado"])
        session_table.verticalHeader().setVisible(False)
        session_table.setAlternatingRowColors(True)
        session_table.setMinimumHeight(240)
        session_table.setStyleSheet(
            "QTableWidget {background-color: #161a22; color: #f8fafc; border: 1px solid #2f3746; "
            "gridline-color: #2f3746; font-size: 10pt;} "
            "QHeaderView::section {background-color: #222b38; color: #e6edf7; font-weight: 700; padding: 6px 8px; border: 1px solid #2f3746;}"
        )
        panel_header = session_table.horizontalHeader()
        panel_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        panel_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        panel_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        panel_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        session_table_footer = QLabel(LAPTIMER_EMPTY_FOOTER_TEXT)
        session_table_footer.setObjectName(f"{title}_footer")
        session_table_footer.setStyleSheet("color: #94a3b8; font-size: 9pt;")
        
        self.laptimer_panel_widgets[title] = {
            "session_time": session_time_label,
            "total_time": total_time_card,
            "best_time": best_time_card,
            "avg_time": avg_time_card,
            "table": session_table,
            "footer": session_table_footer,
            "track_widget": None
        }

        # Adaptar layout del widget de circuito en Skidpad
        if layout_variant == "skidpad":
            track_widget = SkidpadTrackWidget()
            self.laptimer_panel_widgets[title]["track_widget"] = track_widget
            layout.addWidget(track_widget, 1)
            # No agregamos la tabla al layout en skidpad
        else:
            layout.addWidget(session_table, 1)
            layout.addWidget(session_table_footer)

        return panel

    def create_data_group(self, title, signals, font_size=10, prominent=False):
        group = QGroupBox(title)
        layout = QGridLayout()
        layout.setColumnStretch(2, 1)
        layout.setSpacing(3)
        
        # Si es prominente (MOTOR), aumentar padding y espaciado
        if prominent:
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(6)
        
        row = 0
        color_idx = len(self.color_assignment)  # Continuar desde el último color asignado
        
        for label_text, key, unit in signals:
            # Asignar color si no lo tiene
            if key not in self.color_assignment:
                self.color_assignment[key] = GRAPH_COLORS[color_idx % len(GRAPH_COLORS)]
                color_idx += 1
            
            # 1. Checkbox para graficar
            chk = QCheckBox()
            chk.toggled.connect(lambda checked, k=key: self.toggle_graph(k, checked))
            layout.addWidget(chk, row, 0)
            self.checkboxes[key] = chk

            # 2. Nombre Señal
            lbl_name = QLabel(label_text)
            name_font_size = font_size if prominent else 10
            lbl_name.setStyleSheet(f"color: #aaa; font-size: {name_font_size}pt;")
            layout.addWidget(lbl_name, row, 1)
            
            # 3. Valor Señal
            lbl_val = QLabel("---")
            lbl_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            val_font_size = font_size + 1 if prominent else 11
            lbl_val.setFont(QFont("Segoe UI", val_font_size, QFont.Weight.Bold if prominent else QFont.Weight.Normal))
            lbl_val.setStyleSheet("color: #555;")
            layout.addWidget(lbl_val, row, 2)
            
            # 4. Unidad
            lbl_unit = QLabel(unit)
            lbl_unit.setStyleSheet(f"color: #666; font-size: {font_size - 1}pt;")
            layout.addWidget(lbl_unit, row, 3)
            
            self.ui_labels[key] = lbl_val 
            row += 1
            
        group.setLayout(layout)
        return group

    def toggle_graph(self, key, checked):
        """Muestra u oculta una gráfica individual"""
        if checked:
            # Crear gráfica individual con modo de ventana actual
            color = self.color_assignment.get(key, '#00e676')
            is_sliding = (self.current_window_mode == 'sliding')
            plot_widget = IndividualPlotWidget(key, color, self.data_store, 
                                              sliding_window=is_sliding, 
                                              window_duration=self.current_window_duration)
            
            # Conectar señal de crosshair a otras gráficas y popup
            plot_widget.crosshair_moved.connect(self.sync_crosshair)
            plot_widget.crosshair_moved.connect(self.update_value_popup)
            
            # Insertar antes del stretch
            self.plots_layout.insertWidget(self.plots_layout.count() - 1, plot_widget)
            self.plot_widgets[key] = plot_widget
            
        else:
            # Eliminar gráfica
            if key in self.plot_widgets:
                widget = self.plot_widgets[key]
                self.plots_layout.removeWidget(widget)
                widget.deleteLater()
                del self.plot_widgets[key]
    
    def change_window_mode(self, mode, duration):
        """Cambia el modo de ventana temporal para todas las gráficas activas
        
        Args:
            mode: 'sliding' (ventana deslizante) o 'full' (todo el tiempo)
            duration: duración en segundos (None para modo full)
        """
        self.current_window_mode = mode
        if duration is not None:
            self.current_window_duration = duration
        
        # Aplicar a todas las gráficas activas
        for plot_widget in self.plot_widgets.values():
            plot_widget.set_window_mode(mode, duration)
        
        mode_name = f"{duration}s" if mode == 'sliding' else "Todo"
        print(f"[UI] Ventana temporal cambiada a: {mode_name}")
    
    def sync_crosshair(self, x_pos):
        """Sincroniza el crosshair entre todas las gráficas activas"""
        sender = self.sender()
        for plot_widget in self.plot_widgets.values():
            if plot_widget != sender:
                plot_widget.update_crosshair(x_pos)
    
    def update_value_popup(self, x_pos):
        """Actualiza el popup con los valores de todas las gráficas activas"""
        # Solo mostrar si está habilitado
        if not self.popup_enabled or not self.plot_widgets:
            return
        
        # Recopilar valores de todas las gráficas activas
        lines = [f"TIEMPO: {x_pos:.2f}s", "="*30]
        
        for signal_name, plot_widget in sorted(self.plot_widgets.items()):
            value = plot_widget.get_value_at_time(x_pos)
            if value is not None:
                lines.append(f"{signal_name}: {value:.2f}")
        
        if len(lines) > 2:  # Hay valores para mostrar
            self.value_popup.setText("\n".join(lines))
            self.value_popup.adjustSize()
            
            # Posicionar el popup cerca del cursor (esquina superior derecha)
            cursor_pos = self.mapFromGlobal(self.cursor().pos())
            popup_x = min(cursor_pos.x() + 20, self.width() - self.value_popup.width() - 10)
            popup_y = max(cursor_pos.y() - self.value_popup.height() - 20, 50)
            
            self.value_popup.move(popup_x, popup_y)
            self.value_popup.setVisible(True)
            self.value_popup.raise_()
    
    def hide_value_popup(self):
        """Oculta el popup de valores"""
        self.value_popup.setVisible(False)
    
    def toggle_popup(self):
        """Activa/desactiva el popup de valores"""
        self.popup_enabled = not self.popup_enabled
        
        if self.popup_enabled:
            self.popup_toggle_btn.setText("POPUP ON")
            self.popup_toggle_btn.setStyleSheet(popup_button_style(True))
            self.popup_toggle_btn.setToolTip("POPUP ON (F2)")
            print("[UI] Popup de valores activado (F2)")
        else:
            self.popup_toggle_btn.setText("POPUP OFF")
            self.popup_toggle_btn.setStyleSheet(popup_button_style(False))
            self.popup_toggle_btn.setToolTip("POPUP OFF (F2)")
            self.hide_value_popup()
            print("[UI] Popup de valores desactivado (F2)")
    
    def switch_page(self, page_index):
        """Cambia la página activa y actualiza estilo navbar"""
        self.pages_stack.setCurrentIndex(page_index)
        
        # Restablecer todos los botones a estado inactivo
        for btn in [self.nav_btn_dashboard, self.nav_btn_todo, self.nav_btn_laptimer, self.nav_btn_monitor, self.nav_btn_offline]:
            btn.setStyleSheet(nav_button_style(False))
        
        # Activar el botón seleccionado
        buttons = [self.nav_btn_dashboard, self.nav_btn_todo, self.nav_btn_laptimer, self.nav_btn_monitor, self.nav_btn_offline]
        if page_index < len(buttons):
            buttons[page_index].setStyleSheet(nav_button_style(True))
    
    def activate_default_graphs(self):
        """Activa gráficas por defecto basadas en las señales del DBC."""
        default_signals = [sig["key"] for sig in self.signals_by_group.get("MOTOR", [])[:4]]
        
        for signal in default_signals:
            if signal in self.checkboxes:
                self.checkboxes[signal].setChecked(True)
                print(f"[UI] Gráfica activada por defecto: {signal}")
    
    def clear_all_data(self):
        """Limpia todos los datos del DataStore"""
        self.data_store.clear()
        self.reset_laptimer_view()
        print("[DataStore] Todos los datos limpiados")

    def get_active_laptimer_widgets(self):
        return self.laptimer_panel_widgets.get(self.session_mode, next(iter(self.laptimer_panel_widgets.values())))

    def reset_laptimer_view(self):
        self.update_session_interface()
        widgets = self.get_active_laptimer_widgets()
        widgets["table"].setRowCount(0)
        widgets["footer"].setText(LAPTIMER_EMPTY_FOOTER_TEXT)
        self.laptimer_history_table.setRowCount(len(self.completed_sessions))
        self.laptimer_rows_rendered = 0
        widgets["session_time"].setText("00:00.000")
        widgets["total_time"].setText("--:--.---")
        widgets["best_time"].setText("--:--.---")
        widgets["avg_time"].setText("--:--.---")
        self.laps_count_label.setText("VUELTAS: 0")
        self.last_lap_label.setText("ULTIMA: --:--.---")
        self.total_time_label.setText("TOTAL: --:--.---")
        self.stopwatch_label.setText("CRONO: --:--.---")

    def on_session_mode_changed(self, mode):
        mode_map = {
            "SKIDPAD": "Skidpad",
            "AUTOCROSS": "Autocross",
            "ENDURANCE": "Endurance",
        }
        self.session_mode = mode_map.get(mode.upper(), mode)
        self.update_session_interface()
        self.stop_session(clear_table=True, finalize=False)
        self.session_status_label.setText(f"ESTADO: {self.session_mode.upper()} LISTO, PENDIENTE DE INICIAR")

    def start_session(self):
        if self.session_running and self.session_paused:
            self.toggle_pause_session()
            return

        self.update_session_interface()
        self.session_running = True
        self.session_paused = False
        self.session_elapsed_before_pause = 0.0
        # El cronómetro no arranca hasta la primera señal LT.
        self.session_started_at = None
        self.session_started_wallclock = None
        self.session_first_lt_ts = None
        self.session_last_lt_ts = None
        self.session_laps = []
        self.session_last_lap_armed = False
        self.reset_laptimer_view()

        _, ts_values = self.data_store.get_signal_data('laptimer_timestamp_s')
        self.session_lt_cursor = len(ts_values)

        self.pause_session_btn.setEnabled(True)
        self.stop_session_btn.setEnabled(True)
        self.last_lap_btn.setEnabled(True)
        self.pause_session_btn.setText("PAUSAR")
        self.last_lap_btn.setText(LAPTIMER_LAST_LAP_TEXT)
        self.session_status_label.setText(f"ESTADO: {self.session_mode.upper()} EN CURSO")

    def arm_last_lap(self):
        if not self.session_running or self.session_paused:
            return
        self.session_last_lap_armed = True
        self.last_lap_btn.setText("ULTIMA VUELTA: ARMADA")
        self.last_lap_btn.setStyleSheet("background-color: #9a5e00; color: white; padding: 8px 14px; border: 1px solid #3a3a3a; border-radius: 0px; font-weight: 700;")
        self.session_status_label.setText(f"ESTADO: {self.session_mode.upper()} - ULTIMA VUELTA ARMADA")

    def toggle_pause_session(self):
        if not self.session_running:
            return

        if not self.session_paused:
            elapsed_now = max(0.0, time.time() - self.session_started_at)
            self.session_elapsed_before_pause += elapsed_now
            self.session_paused = True
            self.pause_session_btn.setText("REANUDAR")
            self.session_status_label.setText(f"ESTADO: {self.session_mode.upper()} EN PAUSA")
            return

        self.session_paused = False
        self.session_started_at = time.time()
        self.pause_session_btn.setText("PAUSAR")
        self.session_status_label.setText(f"ESTADO: {self.session_mode.upper()} EN CURSO")

    def stop_session(self, clear_table=False, finalize=True):
        if finalize and (self.session_running or self.session_laps or self.session_first_lt_ts is not None):
            self.finalize_laptimer_session()
            return

        self.session_running = False
        self.session_paused = False
        
        if clear_table:
            self.session_elapsed_before_pause = 0.0
            self.session_started_at = None
            self.session_started_wallclock = None
            self.session_first_lt_ts = None
            self.session_last_lt_ts = None
            self.session_laps = []

        _, ts_values = self.data_store.get_signal_data('laptimer_timestamp_s')
        self.session_lt_cursor = len(ts_values)

        self.pause_session_btn.setEnabled(False)
        self.stop_session_btn.setEnabled(False)
        self.last_lap_btn.setEnabled(False)
        self.pause_session_btn.setText("PAUSAR")
        self.last_lap_btn.setText(LAPTIMER_LAST_LAP_TEXT)
        self.last_lap_btn.setStyleSheet("background-color: #5c4b00; color: white; padding: 8px 14px; border: 1px solid #3a3a3a; border-radius: 0px; font-weight: 700;")

        if clear_table:
            self.reset_laptimer_view()

        self.session_status_label.setText(f"ESTADO: {self.session_mode.upper()} DETENIDO")

    def format_lap_time(self, seconds):
        if seconds is None:
            return "--:--.---"
        total_ms = int(round(seconds * 1000.0))
        mins = total_ms // 60000
        secs = (total_ms % 60000) // 1000
        millis = total_ms % 1000
        return f"{mins:02d}:{secs:02d}.{millis:03d}"

    def get_laptimer_stopwatch_seconds(self):
        elapsed = self.session_elapsed_before_pause
        if self.session_running and not self.session_paused and self.session_started_at is not None:
            elapsed += max(0.0, time.time() - self.session_started_at)
        return elapsed

    def consume_laptimer_timestamps(self):
        _, timestamp_values = self.data_store.get_signal_data('laptimer_timestamp_s')
        should_finalize = False

        while self.session_lt_cursor < len(timestamp_values):
            ts = timestamp_values[self.session_lt_cursor]
            self.session_lt_cursor += 1

            if self.session_first_lt_ts is None:
                self.session_first_lt_ts = ts
                self.session_last_lt_ts = ts

                # Primera señal LT: iniciar cronómetro real de sesión.
                if self.session_started_at is None:
                    self.session_started_at = time.time()
                    self.session_started_wallclock = datetime.now()
                continue

            if ts <= self.session_last_lt_ts:
                continue

            lap_s = ts - self.session_last_lt_ts
            self.session_last_lt_ts = ts
            self.session_laps.append(lap_s)

            if self.session_last_lap_armed or (self.session_mode.upper() == "SKIDPAD" and len(self.session_laps) >= 4):
                should_finalize = True
                break

        return should_finalize

    def update_laptimer_panel_values(self, widgets, stopwatch_s):
        widgets["session_time"].setText(self.format_lap_time(stopwatch_s))
        
        # Si es Skidpad FS válido, fijar el total con su nota oficial, sino el stopwatch
        if self.session_mode.upper() == "SKIDPAD" and len(self.session_laps) == 4:
            skidpad_avg = (min(self.session_laps[0:2]) + min(self.session_laps[2:4])) / 2.0
            widgets["total_time"].setText(self.format_lap_time(skidpad_avg))
            self.total_time_label.setText(f"TOTAL: {self.format_lap_time(skidpad_avg)}")
        else:
            widgets["total_time"].setText(self.format_lap_time(stopwatch_s))
            self.total_time_label.setText(f"TOTAL: {self.format_lap_time(stopwatch_s)}")
            
        self.stopwatch_label.setText(f"CRONO: {self.format_lap_time(stopwatch_s)}")

        # Actualizar visualmente el circuito de Skidpad en vivo
        if self.session_mode.upper() == "SKIDPAD" and "track_widget" in widgets and widgets["track_widget"]:
            track_widget = widgets["track_widget"]
            r1 = self.session_laps[0] if len(self.session_laps) > 0 else 0.0
            r2 = self.session_laps[1] if len(self.session_laps) > 1 else 0.0
            l1 = self.session_laps[2] if len(self.session_laps) > 2 else 0.0
            l2 = self.session_laps[3] if len(self.session_laps) > 3 else 0.0
            
            active_section = len(self.session_laps) + 1
            if not self.session_running or self.session_paused:
                active_section = 0
            elif active_section > 4:
                active_section = 0
                
            # Asignar tiempo en vivo a la sección activa
            if active_section > 0 and self.session_started_at is not None:
                live_lap_time = max(0.0, stopwatch_s - sum(self.session_laps))
                if active_section == 1:
                    r1 = live_lap_time
                elif active_section == 2:
                    r2 = live_lap_time
                elif active_section == 3:
                    l1 = live_lap_time
                elif active_section == 4:
                    l2 = live_lap_time
                
            track_widget.update_times(r1, r2, l1, l2, active_section)

    def refresh_laptimer_statistics(self, widgets):
        if not self.session_laps:
            widgets["best_time"].setText("--:--.---")
            widgets["avg_time"].setText("--:--.---")
            self.laps_count_label.setText("VUELTAS: 0")
            self.last_lap_label.setText("ULTIMA: --:--.---")
            widgets["footer"].setText(LAPTIMER_EMPTY_FOOTER_TEXT)
            widgets["table"].setRowCount(0)
            return

        best = min(self.session_laps)
        avg = sum(self.session_laps) / len(self.session_laps)
        last_lap = self.session_laps[-1]

        widgets["best_time"].setText(self.format_lap_time(best))
        widgets["avg_time"].setText(self.format_lap_time(avg))
        self.last_lap_label.setText(f"ULTIMA: {self.format_lap_time(last_lap)}")
        self.laps_count_label.setText(f"VUELTAS: {len(self.session_laps)}")
        widgets["footer"].setText(f"{len(self.session_laps)} VUELTAS REGISTRADAS")

        table = widgets["table"]
        table.setRowCount(len(self.session_laps))
        for idx, lap_time in enumerate(self.session_laps):
            delta = lap_time - best
            if abs(delta) < 1e-9:
                state = "BEST"
            elif idx == len(self.session_laps) - 1:
                state = "LAST"
            else:
                state = ""

            lap_item = QTableWidgetItem(str(idx + 1))
            time_item = QTableWidgetItem(self.format_lap_time(lap_time))
            delta_item = QTableWidgetItem(f"+{delta:.3f}s" if delta > 0 else "0.000s")
            state_item = QTableWidgetItem(state)

            if abs(delta) < 1e-9:
                time_item.setForeground(QColor("#39ff9b"))
                time_item.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
                delta_item.setForeground(QColor("#39ff9b"))
                state_item.setForeground(QColor("#39ff9b"))
            else:
                delta_item.setForeground(QColor("#ffad66"))
                state_item.setForeground(QColor("#e2e8f0"))

            table.setItem(idx, 0, lap_item)
            table.setItem(idx, 1, time_item)
            table.setItem(idx, 2, delta_item)
            table.setItem(idx, 3, state_item)

        table.scrollToBottom()

    def get_session_interface_index(self):
        return {"SKIDPAD": 0, "AUTOCROSS": 1, "ENDURANCE": 2}.get(self.session_mode.upper(), 0)

    def update_session_interface(self):
        self.mode_stack.setCurrentIndex(self.get_session_interface_index())
        if not self.laptimer_panel_widgets:
            return

        widgets = self.get_active_laptimer_widgets()
        self.session_time_label = widgets["session_time"]
        self.total_time_card = widgets["total_time"]
        self.best_time_card = widgets["best_time"]
        self.avg_time_card = widgets["avg_time"]
        self.session_table = widgets["table"]
        self.session_table_footer = widgets["footer"]
        self.laptimer_table = self.session_table

    def build_laptimer_summary(self, stopwatch_s):
        best = min(self.session_laps) if self.session_laps else None
        avg = (sum(self.session_laps) / len(self.session_laps)) if self.session_laps else None
        last_lap = self.session_laps[-1] if self.session_laps else None
        total_time = stopwatch_s
        
        skidpad_time_str = None
        if self.session_mode.upper() == "SKIDPAD" and len(self.session_laps) == 4:
            best_right = min(self.session_laps[0:2])
            best_left = min(self.session_laps[2:4])
            skidpad_avg = (best_right + best_left) / 2.0
            skidpad_time_str = self.format_lap_time(skidpad_avg)
            total_time = skidpad_avg

        session_name = self.session_name_input.text().strip()
        if not session_name:
            session_name = f"{self.session_mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        consistency_ms = 0.0
        if len(self.session_laps) > 1:
            mean = avg
            variance = sum((lap - mean) ** 2 for lap in self.session_laps) / len(self.session_laps)
            consistency_ms = (variance ** 0.5) * 1000.0

        started_at = self.session_started_wallclock.strftime("%H:%M:%S") if self.session_started_wallclock else datetime.now().strftime("%H:%M:%S")
        ended_at = datetime.now().strftime("%H:%M:%S")

        laps_table = []
        for idx, lap_time in enumerate(self.session_laps):
            delta = 0.0 if best is None else lap_time - best
            if best is not None and abs(delta) < 1e-9:
                state = "BEST"
            elif idx == len(self.session_laps) - 1:
                state = "LAST"
            else:
                state = ""

            laps_table.append({
                "lap_number": idx + 1,
                "lap_time_s": lap_time,
                "lap_time_fmt": self.format_lap_time(lap_time),
                "delta_s": delta,
                "delta_fmt": f"+{delta:.3f}s" if delta > 0 else "0.000s",
                "state": state,
            })

        return {
            "name": session_name,
            "mode": self.session_mode.upper(),
            "laps": len(self.session_laps),
            "started_at": started_at,
            "ended_at": ended_at,
            "total_time": self.format_lap_time(total_time) if not skidpad_time_str else skidpad_time_str,
            "stopwatch": self.format_lap_time(stopwatch_s),
            "best": self.format_lap_time(best),
            "avg": self.format_lap_time(avg),
            "last": self.format_lap_time(last_lap),
            "skidpad_time": skidpad_time_str,
            "consistency_ms": f"{consistency_ms:.1f}",
            "laps_table": laps_table,
            "resume": f"{session_name} | {self.session_mode.upper()} | {len(self.session_laps)} VUELTAS | {(skidpad_time_str if skidpad_time_str else self.format_lap_time(total_time))}",
        }

    def append_session_history(self, summary):
        self.completed_sessions.append(summary)
        row = self.laptimer_history_table.rowCount()
        self.laptimer_history_table.insertRow(row)

        values = [
            str(row + 1),
            summary["name"],
            summary["mode"],
            summary["started_at"],
            summary["ended_at"],
            str(summary["laps"]),
            summary["resume"],
        ]

        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            self.laptimer_history_table.setItem(row, col, item)

        self.update_saved_session_selector()

    def show_session_popup(self, summary):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("SESION FINALIZADA")
        msg_box.setText(f"{summary['name'].upper()} COMPLETADA")
        
        if summary['mode'] == 'SKIDPAD' and summary.get('skidpad_time'):
            msg_box.setInformativeText(
                f"MODO: {summary['mode']}\n"
                f"TIEMPO SKIDPAD (FS): {summary['skidpad_time']}\n"
                f"Media de la mejor V Derecha (1-2) y mejor V Izquierda (3-4)"
            )
        else:
            msg_box.setInformativeText(
                f"MODO: {summary['mode']}\n"
                f"VUELTAS: {summary['laps']}\n"
                f"TOTAL: {summary['total_time']}\n"
                f"CRONO: {summary['stopwatch']}\n"
                f"MEJOR: {summary['best']}\n"
                f"MEDIA: {summary['avg']}\n"
                f"CONSISTENCIA: {summary['consistency_ms']} ms"
            )
            
        msg_box.setStyleSheet(
            "QMessageBox { background-color: #161a22; }"
            "QLabel { color: #f8fafc; font-family: 'Segoe UI'; font-size: 11pt; }"
            "QPushButton { background-color: #1d2735; color: #e8f0ff; border: 1px solid #426084; border-radius: 0px; padding: 6px 12px; }"
        )
        msg_box.exec()

    def update_saved_session_selector(self):
        self.saved_session_selector.blockSignals(True)
        self.saved_session_selector.clear()
        self.saved_session_selector.addItem("SELECCIONA SESION...")
        for idx, summary in enumerate(self.completed_sessions, start=1):
            self.saved_session_selector.addItem(f"{idx}. {summary['name']} ({summary['mode']})")
        self.saved_session_selector.blockSignals(False)

    def on_saved_session_selected(self, index):
        if index <= 0 or index - 1 >= len(self.completed_sessions):
            self.saved_session_details.setText("SIN SESIONES SELECCIONADAS")
            self.saved_session_laps_table.setRowCount(0)
            return

        summary = self.completed_sessions[index - 1]
        
        if summary.get('mode') == 'SKIDPAD' and summary.get('skidpad_time'):
            self.saved_session_details.setText(
                f"<span style='color:#ffd166; font-size:14pt;'><b>SKIDPAD FINAL: {summary['skidpad_time']}</b></span><br/>"
                f"<span style='color:#a0a0a0;'>NOMBRE: {summary['name']} | INICIO: {summary['started_at']}</span><br/>"
                f"<span style='color:#a0a0a0;'>TIEMPOS: V1 Der: {summary['laps_table'][0]['lap_time_fmt']} | V2 Der: {summary['laps_table'][1]['lap_time_fmt']} | "
                f"V1 Izq: {summary['laps_table'][2]['lap_time_fmt']} | V2 Izq: {summary['laps_table'][3]['lap_time_fmt']}</span>"
            )
            self.saved_session_details.setTextFormat(Qt.TextFormat.RichText)
        else:
            self.saved_session_details.setTextFormat(Qt.TextFormat.PlainText)
            self.saved_session_details.setText(
                f"NOMBRE: {summary['name']}\n"
                f"MODO: {summary['mode']}\n"
                f"INICIO: {summary['started_at']} | FIN: {summary['ended_at']}\n"
                f"VUELTAS: {summary['laps']} | TOTAL: {summary['total_time']}\n"
                f"MEJOR: {summary['best']} | MEDIA: {summary['avg']} | CONSISTENCIA: {summary['consistency_ms']} ms"
            )

        laps_table = summary.get("laps_table", [])
        self.saved_session_laps_table.setRowCount(len(laps_table))
        for row, lap in enumerate(laps_table):
            self.saved_session_laps_table.setItem(row, 0, QTableWidgetItem(str(lap.get("lap_number", row + 1))))
            self.saved_session_laps_table.setItem(row, 1, QTableWidgetItem(lap.get("lap_time_fmt", "--:--.---")))
            self.saved_session_laps_table.setItem(row, 2, QTableWidgetItem(lap.get("delta_fmt", "0.000s")))
            self.saved_session_laps_table.setItem(row, 3, QTableWidgetItem(lap.get("state", "")))

    def export_sessions_csv(self):
        QMessageBox.information(
            self,
            "EXPORTACION UNIFICADA",
            "SE USARA UN UNICO CSV COMBINADO DE TELEMETRIA Y LAPTIME SINCRONIZADOS."
        )
        self.export_to_csv()

    def finalize_laptimer_session(self):
        if not self.session_running and not self.session_laps:
            return

        elapsed_now = self.session_elapsed_before_pause
        if self.session_running and not self.session_paused and self.session_started_at is not None:
            elapsed_now += max(0.0, time.time() - self.session_started_at)
            
        self.session_elapsed_before_pause = elapsed_now

        summary = self.build_laptimer_summary(elapsed_now)
        self.append_session_history(summary)
        self.show_session_popup(summary)
        self.stop_session(clear_table=False, finalize=False)

    def update_laptimer_view(self):
        self.update_session_interface()
        widgets = self.get_active_laptimer_widgets()
        stopwatch_s = self.get_laptimer_stopwatch_seconds()
        self.update_laptimer_panel_values(widgets, stopwatch_s)

        if self.session_running and not self.session_paused and self.consume_laptimer_timestamps():
            self.finalize_laptimer_session()
            return

        self.refresh_laptimer_statistics(widgets)
    
    def export_to_csv(self):
        """Exporta telemetría + laptime en un único CSV sincronizado por timestamp de telemetría."""
        all_signals_from_dbc = []
        if self.can_worker.db:
            try:
                for msg in self.can_worker.db.messages:
                    for signal in msg.signals:
                        all_signals_from_dbc.append(signal.name)
            except Exception as e:
                print(f"[Export] Error leyendo DBC: {e}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"telemetria_{timestamp}.csv"
        
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar Telemetría a CSV",
            default_filename,
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if not filename:
            return

        try:
            all_signals = self.data_store.get_all_signals()
            telemetry_present = [s for s in all_signals if not s.startswith('laptimer_') and not s.startswith('lt_')]

            if all_signals_from_dbc:
                telemetry_columns = sorted(set(all_signals_from_dbc) | set(telemetry_present))
            else:
                telemetry_columns = sorted(telemetry_present)

            series_map = {}
            for signal in telemetry_columns:
                if signal in all_signals:
                    ts_list, val_list = self.data_store.get_signal_data(signal)
                    series_map[signal] = (ts_list, val_list)
                else:
                    series_map[signal] = ([], [])

            telemetry_timeline = set()
            for signal in telemetry_present:
                ts_list, _ = self.data_store.get_signal_data(signal)
                telemetry_timeline.update(ts_list)

            if not telemetry_timeline:
                for signal in all_signals:
                    ts_list, _ = self.data_store.get_signal_data(signal)
                    telemetry_timeline.update(ts_list)

            timeline = sorted(telemetry_timeline)
            if not timeline:
                QMessageBox.warning(self, "Exportación", "No hay datos para exportar.")
                return

            lap_ts, lap_time_vals = self.data_store.get_signal_data('laptimer_last_lap_s')
            laptime_rows = []
            running_best = None
            cumulative = 0.0
            for idx, lap_time in enumerate(lap_time_vals):
                lap_time_f = float(lap_time)
                cumulative += lap_time_f
                running_best = lap_time_f if running_best is None else min(running_best, lap_time_f)
                delta = lap_time_f - running_best
                state = 'BEST' if abs(delta) < 1e-9 else ('LAST' if idx == len(lap_time_vals) - 1 else '')
                laptime_rows.append({
                    'timestamp': lap_ts[idx] if idx < len(lap_ts) else 0.0,
                    'lap_number': idx + 1,
                    'lap_time_s': lap_time_f,
                    'lap_time_fmt': self.format_lap_time(lap_time_f),
                    'delta_s': delta,
                    'delta_fmt': f"+{delta:.3f}s" if delta > 0 else "0.000s",
                    'state': state,
                    'total_time_s': cumulative,
                    'best_s': running_best,
                })

            active_name = self.session_name_input.text().strip() or "session"
            active_mode = self.session_mode
            started_at = self.session_started_wallclock.strftime("%H:%M:%S") if self.session_started_wallclock else ""

            laptime_columns = [
                'name', 'mode', 'started_at', 'ended_at', 'laps', 'total_time', 'best', 'avg', 'last', 'consistency_ms',
                'lap_number', 'lap_time_s', 'lap_time_fmt', 'delta_s', 'delta_fmt', 'state'
            ]

            with open(filename, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['timestamp'] + telemetry_columns + laptime_columns)

                event_idx = -1
                for ts in timeline:
                    while (event_idx + 1) < len(laptime_rows) and laptime_rows[event_idx + 1]['timestamp'] <= ts:
                        event_idx += 1

                    row = [f"{ts:.3f}"]
                    for signal in telemetry_columns:
                        ts_vals, v_vals = series_map[signal]
                        if not ts_vals:
                            row.append(0)
                            continue
                        pos = bisect.bisect_right(ts_vals, ts) - 1
                        row.append(v_vals[pos] if pos >= 0 else 0)

                    if event_idx >= 0:
                        ev = laptime_rows[event_idx]
                        laps_so_far = ev['lap_number']
                        avg_s = ev['total_time_s'] / laps_so_far if laps_so_far > 0 else 0.0
                        row.extend([
                            active_name,
                            active_mode,
                            started_at,
                            '',
                            laps_so_far,
                            self.format_lap_time(ev['total_time_s']),
                            self.format_lap_time(ev['best_s']),
                            self.format_lap_time(avg_s),
                            self.format_lap_time(ev['lap_time_s']),
                            f"{0.0:.1f}",
                            ev['lap_number'],
                            f"{ev['lap_time_s']:.6f}",
                            ev['lap_time_fmt'],
                            f"{ev['delta_s']:.6f}",
                            ev['delta_fmt'],
                            ev['state'],
                        ])
                    else:
                        row.extend(['', '', '', '', '', '', '', '', '', '', '', '', '', '', '', ''])

                    writer.writerow(row)

            QMessageBox.information(
                self,
                "EXPORTACION EXITOSA",
                f"EXPORTADO CSV COMBINADO\n\nARCHIVO: {os.path.basename(filename)}"
            )
            print(f"[Export] CSV combinado -> {filename}")
        except Exception as exc:
            QMessageBox.critical(self, "ERROR DE EXPORTACION", f"{exc}")
            print(f"[Export] ERROR combinado: {exc}")

    def parse_unified_laptime_rows_from_csv(self, filename):
        rows = []
        try:
            with open(filename, 'r', newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                required = {'timestamp', 'lap_number', 'lap_time_s', 'delta_s', 'state', 'name', 'mode'}
                if not required.issubset(set(reader.fieldnames or [])):
                    return []

                seen = set()
                for row in reader:
                    lap_text = (row.get('lap_number') or '').strip()
                    if not lap_text:
                        continue
                    try:
                        key = (int(lap_text), row.get('name', ''), row.get('mode', ''))
                        if key in seen:
                            continue
                        seen.add(key)

                        ts = float(row.get('timestamp') or 0.0)
                        lap_s = float(row.get('lap_time_s') or 0.0)
                        delta_s = float(row.get('delta_s') or 0.0)
                        rows.append({
                            'timestamp': ts,
                            'name': row.get('name', ''),
                            'mode': row.get('mode', ''),
                            'lap_number': int(lap_text),
                            'lap_time_fmt': row.get('lap_time_fmt', '--:--.---'),
                            'delta_fmt': row.get('delta_fmt', '0.000s'),
                            'state': row.get('state', ''),
                            'lap_time_s': lap_s,
                            'delta_s': delta_s,
                        })
                    except ValueError:
                        continue
            return rows
        except Exception:
            return []

    def build_offline_sessions_from_rows(self, rows):
        sessions = {}
        order = []

        for row in rows:
            key = (row.get('name', ''), row.get('mode', ''))
            if key not in sessions:
                sessions[key] = {
                    'name': row.get('name', ''),
                    'mode': row.get('mode', ''),
                    'started_at': '',
                    'ended_at': '',
                    'laps': 0,
                    'total_time': '--:--.---',
                    'best': '--:--.---',
                    'avg': '--:--.---',
                    'consistency_ms': '0',
                    'rows': [],
                }
                order.append(key)

            sessions[key]['rows'].append(row)

        built_sessions = []
        for key in order:
            sess = sessions[key]
            rows_sorted = sorted(sess['rows'], key=lambda r: r['lap_number'])
            lap_times = [r.get('lap_time_s', 0.0) for r in rows_sorted]
            total_time = sum(lap_times)
            best = min(lap_times) if lap_times else None
            avg = (sum(lap_times) / len(lap_times)) if lap_times else None
            consistency_ms = 0.0
            if len(lap_times) > 1 and avg is not None:
                variance = sum((lap - avg) ** 2 for lap in lap_times) / len(lap_times)
                consistency_ms = (variance ** 0.5) * 1000.0

            sess.update({
                'rows': rows_sorted,
                'laps': len(rows_sorted),
                'total_time': self.format_lap_time(total_time),
                'best': self.format_lap_time(best),
                'avg': self.format_lap_time(avg),
                'consistency_ms': f"{consistency_ms:.1f}",
                'resume': f"{sess['name']} | {sess['mode']} | {len(rows_sorted)} VUELTAS | {self.format_lap_time(total_time)}",
            })
            built_sessions.append(sess)

        return built_sessions

    def update_offline_session_selector(self, rows):
        self.offline_loaded_sessions = self.build_offline_sessions_from_rows(rows)

        self.offline_session_selector.blockSignals(True)
        self.offline_session_selector.clear()
        self.offline_session_selector.addItem('Selecciona sesión cargada...')
        for idx, sess in enumerate(self.offline_loaded_sessions, start=1):
            self.offline_session_selector.addItem(f"{idx}. {sess['name']} ({sess['mode']})")
        self.offline_session_selector.blockSignals(False)

        if self.offline_loaded_sessions:
            self.offline_session_selector.setCurrentIndex(1)
            self.offline_session_summary.setText(
                f"{len(self.offline_loaded_sessions)} sesiones cargadas. Usa el selector y pulsa SELECCIONAR SESION."
            )
            self.select_offline_session()
        else:
            self.offline_session_summary.setText('SIN SESIONES CARGADAS')
            self.offline_session_laps_table.setRowCount(0)
            self.offline_session_plot.clear()
            self.offline_session_plot_hint.setText('Selecciona una sesión para visualizar la evolución de vueltas')
            self.offline_selected_session_index = -1

    def select_offline_session(self):
        self.on_offline_session_selected(self.offline_session_selector.currentIndex())

    def update_offline_combined_laptime_table(self, rows):
        self.offline_unified_laptime_rows = rows
        self.update_offline_combined_filter_controls(rows)
        self.apply_offline_combined_filters()
        if not rows:
            self.offline_combined_hint.setText("Vista combinada: carga un CSV combinado para ver telemetría y laptime sincronizados")
            return
        self.offline_combined_hint.setText(f"Vista combinada: {len(rows)} vueltas laptime sincronizadas con telemetría")

    def update_offline_combined_filter_controls(self, rows):
        session_values = sorted(set(r.get('name', '') for r in rows if r.get('name', '')))
        mode_values = sorted(set(r.get('mode', '') for r in rows if r.get('mode', '')))

        self.offline_combined_session_filter.blockSignals(True)
        self.offline_combined_mode_filter.blockSignals(True)

        self.offline_combined_session_filter.clear()
        self.offline_combined_session_filter.addItem('Todas')
        for name in session_values:
            self.offline_combined_session_filter.addItem(name)

        self.offline_combined_mode_filter.clear()
        self.offline_combined_mode_filter.addItem('Todos')
        for mode in mode_values:
            self.offline_combined_mode_filter.addItem(mode)

        self.offline_combined_session_filter.blockSignals(False)
        self.offline_combined_mode_filter.blockSignals(False)

    def apply_offline_combined_filters(self):
        selected_name = self.offline_combined_session_filter.currentText()
        selected_mode = self.offline_combined_mode_filter.currentText()

        filtered = []
        for row in self.offline_unified_laptime_rows:
            if selected_name != 'Todas' and row.get('name', '') != selected_name:
                continue
            if selected_mode != 'Todos' and row.get('mode', '') != selected_mode:
                continue
            filtered.append(row)

        self.offline_filtered_laptime_rows = filtered
        self.offline_combined_laps_table.setRowCount(len(filtered))
        for row_idx, lap in enumerate(filtered):
            self.offline_combined_laps_table.setItem(row_idx, 0, QTableWidgetItem(f"{lap['timestamp']:.3f}"))
            self.offline_combined_laps_table.setItem(row_idx, 1, QTableWidgetItem(lap['name']))
            self.offline_combined_laps_table.setItem(row_idx, 2, QTableWidgetItem(lap['mode']))
            self.offline_combined_laps_table.setItem(row_idx, 3, QTableWidgetItem(str(lap['lap_number'])))
            self.offline_combined_laps_table.setItem(row_idx, 4, QTableWidgetItem(lap['lap_time_fmt']))
            self.offline_combined_laps_table.setItem(row_idx, 5, QTableWidgetItem(lap['delta_fmt']))
            self.offline_combined_laps_table.setItem(row_idx, 6, QTableWidgetItem(lap['state']))

        self.offline_combined_hint.setText(f"Vista combinada: {len(filtered)} filas visibles tras filtros")

    def on_offline_combined_filter_changed(self, index):
        self.apply_offline_combined_filters()

    def on_offline_combined_lap_row_changed(self, current_row, current_col, prev_row, prev_col):
        if current_row < 0 or current_row >= len(self.offline_filtered_laptime_rows):
            return

        row = self.offline_filtered_laptime_rows[current_row]
        ts = row.get('timestamp', 0.0)
        self.jump_offline_plots_to_timestamp(ts)

    def jump_offline_plots_to_timestamp(self, timestamp):
        if not self.offline_plot_widgets:
            return

        for plot_widget in self.offline_plot_widgets.values():
            plot_widget.update_crosshair(timestamp)
            min_x = max(0.0, timestamp - 5.0)
            max_x = timestamp + 5.0
            plot_widget.plot_widget.setXRange(min_x, max_x, padding=0)

        self.offline_right_tabs.setCurrentIndex(0)
    
    def load_csv_file(self):
        """Carga un archivo CSV para análisis offline"""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Cargar Archivo CSV de Telemetría",
            "",
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if not filename:
            return  # Usuario canceló
        
        # Cargar CSV en DataStore
        success, message, num_signals, num_points = self.data_store.load_from_csv(filename)
        
        if success:
            # Limpiar gráficas antiguas
            for widget in self.offline_plot_widgets.values():
                self.offline_plots_layout.removeWidget(widget)
                widget.deleteLater()
            self.offline_plot_widgets.clear()
            self.offline_checkboxes.clear()
            
            # Cambiar al tab de análisis offline
            self.pages_stack.setCurrentIndex(4)
            self.offline_right_tabs.setCurrentIndex(0)

            unified_rows = self.parse_unified_laptime_rows_from_csv(filename)
            self.update_offline_combined_laptime_table(unified_rows)
            self.update_offline_session_selector(unified_rows)
            
            QMessageBox.information(
                self,
                "CSV CARGADO",
                f"{message.upper()}\n\n{num_signals} SEÑALES\n{num_points} PUNTOS TEMPORALES\n{len(unified_rows)} VUELTAS LAPTIME"
            )
            print(f"[CSV Load] {message}")
        else:
            QMessageBox.critical(
                self,
                "ERROR AL CARGAR CSV",
                f"{message}"
            )
            print(f"[CSV Load] ERROR: {message}")

    def load_laptimer_sessions_csv_file(self):
        """Carga un CSV exportado de sesiones de laptimer para análisis offline."""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Cargar CSV de Sesiones Laptimer",
            "",
            "CSV Files (*.csv);;All Files (*)"
        )

        if not filename:
            return

        try:
            sessions_by_key = {}
            ordered_keys = []

            with open(filename, 'r', newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                required = {'name', 'mode', 'started_at', 'ended_at', 'laps', 'total_time', 'lap_number', 'lap_time_s', 'delta_s', 'state'}
                if not required.issubset(set(reader.fieldnames or [])):
                    raise ValueError('El CSV no tiene formato de sesiones laptimer exportadas')

                for row in reader:
                    key = (row.get('name', ''), row.get('mode', ''), row.get('started_at', ''), row.get('ended_at', ''))
                    if key not in sessions_by_key:
                        sessions_by_key[key] = {
                            'name': row.get('name', ''),
                            'mode': row.get('mode', ''),
                            'started_at': row.get('started_at', ''),
                            'ended_at': row.get('ended_at', ''),
                            'laps': row.get('laps', '0'),
                            'total_time': row.get('total_time', '--:--.---'),
                            'best': row.get('best', '--:--.---'),
                            'avg': row.get('avg', '--:--.---'),
                            'consistency_ms': row.get('consistency_ms', '0'),
                            'rows': [],
                        }
                        ordered_keys.append(key)

                    lap_number_text = (row.get('lap_number') or '').strip()
                    if not lap_number_text:
                        continue

                    lap_number = int(lap_number_text)
                    lap_time_s = float(row.get('lap_time_s') or 0.0)
                    delta_s = float(row.get('delta_s') or 0.0)
                    sessions_by_key[key]['rows'].append({
                        'lap_number': lap_number,
                        'lap_time_s': lap_time_s,
                        'lap_time_fmt': row.get('lap_time_fmt', '--:--.---'),
                        'delta_s': delta_s,
                        'delta_fmt': row.get('delta_fmt', '0.000s'),
                        'state': row.get('state', ''),
                    })

            self.offline_loaded_sessions = [sessions_by_key[k] for k in ordered_keys]

            self.offline_session_selector.blockSignals(True)
            self.offline_session_selector.clear()
            self.offline_session_selector.addItem('Selecciona sesión cargada...')
            for idx, sess in enumerate(self.offline_loaded_sessions, start=1):
                self.offline_session_selector.addItem(f"{idx}. {sess['name']} ({sess['mode']})")
            self.offline_session_selector.blockSignals(False)

            self.pages_stack.setCurrentIndex(4)
            if self.offline_loaded_sessions:
                self.offline_session_selector.setCurrentIndex(1)
            else:
                self.offline_session_laps_table.setRowCount(0)
                self.offline_session_plot.clear()
                self.offline_session_plot_hint.setText('Selecciona una sesión para ver su gráfica interactiva')
                self.offline_selected_session_index = -1

        except Exception as exc:
            QMessageBox.critical(self, 'CSV sesiones', f'Error cargando sesiones:\n{exc}')

    def on_offline_session_selected(self, index):
        if index <= 0 or index - 1 >= len(self.offline_loaded_sessions):
            self.offline_selected_session_index = -1
            self.offline_session_summary.setText('SIN SESIÓN SELECCIONADA')
            self.offline_session_laps_table.setRowCount(0)
            self.offline_current_session_rows = []
            self.offline_session_plot.clear()
            self.offline_session_plot_hint.setText('Selecciona una sesión para visualizar la evolución de vueltas')
            return

        self.offline_selected_session_index = index - 1
        sess = self.offline_loaded_sessions[self.offline_selected_session_index]
        rows = sorted(sess.get('rows', []), key=lambda r: r['lap_number'])
        self.offline_current_session_rows = rows

        self.offline_session_summary.setText(
            f"{sess['name']} | {sess['mode']} | {sess['laps']} vueltas | {sess['total_time']}"
        )

        self.offline_session_laps_table.setRowCount(len(rows))
        for row_idx, lap in enumerate(rows):
            self.offline_session_laps_table.setItem(row_idx, 0, QTableWidgetItem(str(lap['lap_number'])))
            self.offline_session_laps_table.setItem(row_idx, 1, QTableWidgetItem(lap['lap_time_fmt']))
            self.offline_session_laps_table.setItem(row_idx, 2, QTableWidgetItem(lap['delta_fmt']))
            self.offline_session_laps_table.setItem(row_idx, 3, QTableWidgetItem(lap['state']))

        self.render_offline_session_plot(rows)

    def render_offline_session_plot(self, rows):
        self.offline_session_plot.clear()
        self.offline_session_marker = None

        if not rows:
            self.offline_session_plot_hint.setText('La sesión no tiene vueltas para mostrar')
            return

        x_vals = [lap['lap_number'] for lap in rows]
        y_vals = [lap['lap_time_s'] for lap in rows]

        curve_pen = pg.mkPen(color='#61dafb', width=2)
        self.offline_session_plot.plot(x_vals, y_vals, pen=curve_pen, symbol='o', symbolSize=8, symbolBrush='#ffd166')

        best_idx = min(range(len(rows)), key=lambda idx: rows[idx]['lap_time_s'])
        best_x = x_vals[best_idx]
        best_y = y_vals[best_idx]
        self.offline_session_plot.plot([best_x], [best_y], pen=None, symbol='star', symbolSize=14, symbolBrush='#39ff9b')

        self.offline_session_marker = self.offline_session_plot.plot([best_x], [best_y], pen=None, symbol='o', symbolSize=16, symbolBrush=None, symbolPen=pg.mkPen('#ff1744', width=2))
        self.offline_session_plot_hint.setText('Haz clic en una fila de la tabla para resaltar una vuelta en la gráfica')

    def on_offline_session_lap_row_changed(self, current_row, current_col, prev_row, prev_col):
        if self.offline_selected_session_index < 0:
            return

        sess = self.offline_loaded_sessions[self.offline_selected_session_index]
        rows = sorted(sess.get('rows', []), key=lambda r: r['lap_number'])
        if current_row < 0 or current_row >= len(rows):
            return

        lap = rows[current_row]
        x = lap['lap_number']
        y = lap['lap_time_s']

        if self.offline_session_marker is not None:
            self.offline_session_marker.setData([x], [y])
        self.offline_session_plot_hint.setText(
            f"Vuelta {x}: {lap['lap_time_fmt']} ({lap['delta_fmt']}) {lap['state']}"
        )

    def compare_offline_session_laps(self):
        if not self.offline_current_session_rows:
            return

        if not hasattr(self, 'offline_compare_lap_a') or not hasattr(self, 'offline_compare_lap_b'):
            return

        lap_a_num = self.offline_compare_lap_a.currentData()
        lap_b_num = self.offline_compare_lap_b.currentData()
        if lap_a_num is None or lap_b_num is None:
            return

        lap_a = next((r for r in self.offline_current_session_rows if r['lap_number'] == lap_a_num), None)
        lap_b = next((r for r in self.offline_current_session_rows if r['lap_number'] == lap_b_num), None)
        if lap_a is None or lap_b is None:
            return

        self.render_offline_session_plot(self.offline_current_session_rows)

        self.offline_session_plot.plot([lap_a['lap_number']], [lap_a['lap_time_s']], pen=None, symbol='t', symbolSize=16, symbolBrush='#ff6b6b')
        self.offline_session_plot.plot([lap_b['lap_number']], [lap_b['lap_time_s']], pen=None, symbol='d', symbolSize=16, symbolBrush='#4dabf7')

        delta = lap_b['lap_time_s'] - lap_a['lap_time_s']
        sign = '+' if delta >= 0 else '-'
        self.offline_session_plot_hint.setText(
            f"Comparando V{lap_a_num} vs V{lap_b_num}: {lap_a['lap_time_fmt']} vs {lap_b['lap_time_fmt']} | Δ={sign}{abs(delta):.3f}s"
        )

    def show_selected_offline_combined_lap(self):
        if not self.offline_filtered_laptime_rows:
            return

        current_row = self.offline_combined_laps_table.currentRow()
        if current_row < 0 or current_row >= len(self.offline_filtered_laptime_rows):
            current_row = 0
            self.offline_combined_laps_table.selectRow(current_row)

        lap = self.offline_filtered_laptime_rows[current_row]
        self.jump_offline_plots_to_timestamp(lap.get('timestamp', 0.0))
    
    def toggle_offline_graph(self, key, checked):
        """Muestra u oculta una gráfica en modo offline"""
        if checked:
            color = self.color_assignment.get(key, '#00e676')
            # Sin sliding window para modo offline (queremos ver todo el rango)
            plot_widget = IndividualPlotWidget(key, color, self.data_store, sliding_window=False)
            
            # Conectar crosshair sincronizado
            plot_widget.crosshair_moved.connect(self.sync_offline_crosshair)
            plot_widget.crosshair_moved.connect(self.update_offline_popup)
            
            # Actualizar gráfica inmediatamente
            plot_widget.update_plot()
            
            self.offline_plots_layout.insertWidget(self.offline_plots_layout.count() - 1, plot_widget)
            self.offline_plot_widgets[key] = plot_widget
        else:
            if key in self.offline_plot_widgets:
                widget = self.offline_plot_widgets[key]
                self.offline_plots_layout.removeWidget(widget)
                widget.deleteLater()
                del self.offline_plot_widgets[key]
    
    def sync_offline_crosshair(self, x_pos):
        """Sincroniza crosshair en modo offline"""
        sender = self.sender()
        for plot_widget in self.offline_plot_widgets.values():
            if plot_widget != sender:
                plot_widget.update_crosshair(x_pos)
    
    def update_offline_popup(self, x_pos):
        """Actualiza popup en modo offline"""
        # Solo mostrar si está habilitado
        if not self.popup_enabled or not self.offline_plot_widgets:
            return
        
        lines = [f"TIEMPO: {x_pos:.2f}s", "="*30]
        
        for signal_name, plot_widget in sorted(self.offline_plot_widgets.items()):
            value = plot_widget.get_value_at_time(x_pos)
            if value is not None:
                lines.append(f"{signal_name}: {value:.2f}")
        
        if len(lines) > 2:
            self.value_popup.setText("\n".join(lines))
            self.value_popup.adjustSize()
            
            cursor_pos = self.mapFromGlobal(self.cursor().pos())
            popup_x = min(cursor_pos.x() + 20, self.width() - self.value_popup.width() - 10)
            popup_y = max(cursor_pos.y() - self.value_popup.height() - 20, 50)
            
            self.value_popup.move(popup_x, popup_y)
            self.value_popup.setVisible(True)
            self.value_popup.raise_()

    def update_status(self, msg, color_code):
        # Mostrar puerto específico en verde cuando está conectado, naranja "Buscando..." en otros casos
        if color_code == "green":
            bg_color = "#2e7d32"
            status_text = f"PUERTO: {msg.upper()}"
        else:
            # Siempre naranja para búsqueda/error
            bg_color = "#f57c00"
            status_text = "BUSCANDO..."
        
        self.status_label.setText(status_text)
        self.status_label.setStyleSheet(status_label_style(bg_color))

    def append_trace(self, text):
        if self.pages_stack.currentIndex() == 3:
            self.trace_console.appendPlainText(text)

    def update_ui_tick(self):
        self.can_worker.data_lock.lock()
        data_snapshot = self.can_worker.latest_data.copy()
        times_snapshot = self.can_worker.last_receive_times.copy()
        self.can_worker.data_lock.unlock()

        current_time = time.time()

        # Actualizar valores numéricos
        for key, label_widget in self.ui_labels.items():
            if key in data_snapshot:
                val = data_snapshot[key]
                txt = f"{val:.2f}" if isinstance(val, float) else str(val)
                label_widget.setText(txt)

                last_rx = times_snapshot.get(key, 0)
                
                # Watchdog visual (2 seg)
                if (current_time - last_rx) < 2.0:
                    label_widget.setStyleSheet("color: #00e676; font-weight: bold; font-size: 13px;") 
                else:
                    label_widget.setStyleSheet("color: #ffb74d; font-weight: normal; font-size: 11px;") 
            else:
                label_widget.setText("---")
                label_widget.setStyleSheet("color: #444; font-weight: normal; font-size: 11px;")

        # Actualizar gráficas según la página activa
        if self.pages_stack.currentIndex() == 0:
            self.update_dashboard_view(data_snapshot, times_snapshot)
        elif self.pages_stack.currentIndex() == 1:
            for plot_widget in self.plot_widgets.values():
                plot_widget.update_plot()

        self.update_laptimer_view()

    def keyPressEvent(self, event):
        """Manejo de teclas globales"""
        if event.key() == Qt.Key.Key_F2:
            self.toggle_popup()
        elif event.key() == Qt.Key.Key_Space:
            # Simular trigger óptico de laptimer
            if self.session_running and not self.session_paused:
                self.data_store.add_sample('laptimer_timestamp_s', time.time())
        else:
            super().keyPressEvent(event)
    
    def closeEvent(self, event):
        """Confirma antes de cerrar la aplicación"""
        # Verificar si hay datos para guardar
        has_data = len(self.data_store.get_all_signals()) > 0
        
        if has_data:
            # Crear diálogo personalizado con botones
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Cerrar Aplicación")
            msg_box.setText("¿Deseas guardar los datos antes de salir?")
            msg_box.setInformativeText("Tienes datos de telemetría sin guardar.")
            msg_box.setIcon(QMessageBox.Icon.Question)
            
            # Botones personalizados
            save_btn = msg_box.addButton("GUARDAR Y SALIR", QMessageBox.ButtonRole.AcceptRole)
            exit_btn = msg_box.addButton("Salir sin Guardar", QMessageBox.ButtonRole.DestructiveRole)
            cancel_btn = msg_box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
            
            msg_box.setDefaultButton(save_btn)
            
            # Mostrar diálogo
            msg_box.exec()
            clicked_button = msg_box.clickedButton()
            
            if clicked_button == save_btn:
                # Guardar CSV antes de salir
                self.export_to_csv()
                # Detener worker y timer
                self.can_worker.stop()
                self.timer.stop()
                event.accept()
                
            elif clicked_button == exit_btn:
                # Salir sin guardar
                self.can_worker.stop()
                self.timer.stop()
                event.accept()
                
            else:  # cancel_btn o cerró el diálogo
                # Cancelar cierre
                event.ignore()
        else:
            # No hay datos, cerrar directamente
            self.can_worker.stop()
            self.timer.stop()
            event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TelemetryWindow()
    window.show()
    sys.exit(app.exec())