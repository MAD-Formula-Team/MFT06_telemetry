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
                             QButtonGroup)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QMutex
from PyQt6.QtGui import QFont, QColor

# --- CONFIGURACIÓN ---
CAN_BITRATE = 1000000
# Ruta del DBC relativa al script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DBC_FILE = os.path.join(SCRIPT_DIR, "mft04.dbc")
CAN_INTERFACE_TYPE = 'robotell' 
REFRESH_RATE_MS = 1000  # Actualización sincronizada cada 1 segundo 

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
                                    
                                    # Guardar en DataStore persistente
                                    for key, value in decoded_signals.items():
                                        if isinstance(value, (int, float)):
                                            self.data_store.add_sample(key, value)

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

# --- Widget de Gráfica Individual ---
class IndividualPlotWidget(QWidget):
    """Widget para una gráfica individual con su título y crosshair"""
    
    # Señal para sincronizar crosshair entre gráficas
    crosshair_moved = pyqtSignal(float)  # Emite posición X del mouse
    
    def __init__(self, signal_name, color, data_store, sliding_window=True, window_duration=15.0):
        super().__init__()
        self.signal_name = signal_name
        self.data_store = data_store
        self.color = color
        self.sliding_window = sliding_window
        self.window_duration = window_duration  # Duración de ventana deslizante en segundos
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.setLayout(layout)
        
        # Título con valor actual
        self.title_label = QLabel(f"<b>{signal_name}</b>: ---")
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
            self.title_label.setText(f"<b>{self.signal_name}</b>: {value:.2f} @ {timestamp:.2f}s")
    
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
        self.title_label.setText(f"<b>{self.signal_name}</b>: ---")
    
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
            
            # Aplicar sliding window si está habilitado
            if self.sliding_window and timestamps:
                max_time = max(timestamps)
                min_time = max(0, max_time - self.window_duration)
                self.plot_widget.setXRange(min_time, max_time, padding=0)
    
    def get_view_box(self):
        """Retorna el ViewBox para sincronización"""
        return self.plot_widget.getViewBox()

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

        # Barra de estado con toggle popup
        status_bar_layout = QHBoxLayout()
        
        self.status_label = QLabel("Iniciando sistema...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("background-color: #333; color: white; padding: 5px; border-radius: 3px;")
        status_bar_layout.addWidget(self.status_label, stretch=1)
        
        # Botón toggle popup
        self.popup_toggle_btn = QPushButton("💬 Popup: OFF")
        self.popup_toggle_btn.setStyleSheet("background-color: #555; color: #aaa; padding: 5px 15px; border-radius: 3px; font-weight: bold;")
        self.popup_toggle_btn.setMaximumWidth(150)
        self.popup_toggle_btn.clicked.connect(self.toggle_popup)
        self.popup_toggle_btn.setToolTip("Toggle popup de valores (Atajo: F2)")
        status_bar_layout.addWidget(self.popup_toggle_btn)
        
        main_layout.addLayout(status_bar_layout)

        self.main_tabs = QTabWidget()
        main_layout.addWidget(self.main_tabs)

        self.ui_labels = {} 
        self.checkboxes = {} 
        self.plot_widgets = {}  # Diccionario de gráficas individuales
        self.color_assignment = {}  # Asignación de colores por señal
        
        # DataStore compartido
        self.data_store = TelemetryDataStore(max_points=10000)
        
        # Estado del popup (toggle con F2)
        self.popup_enabled = False
        
        # Modo de ventana temporal actual (15s por defecto)
        self.current_window_mode = 'sliding'
        self.current_window_duration = 15.0
        
        # Popup flotante para valores
        self.value_popup = QLabel(self)
        self.value_popup.setStyleSheet("""
            QLabel {
                background-color: rgba(40, 40, 40, 230);
                color: white;
                border: 2px solid #00e676;
                border-radius: 5px;
                padding: 10px;
                font-family: 'Consolas', monospace;
                font-size: 10pt;
            }
        """)
        self.value_popup.setVisible(False)
        self.value_popup.setWordWrap(False)
        self.value_popup.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # --- TAB 1: DASHBOARD ---
        self.dashboard_tab = QWidget()
        self.setup_dashboard_ui()
        self.main_tabs.addTab(self.dashboard_tab, "Dashboard Principal")

        # --- TAB 2: TRAZAS CAN ---
        self.traces_tab = QWidget()
        self.setup_traces_ui()
        self.main_tabs.addTab(self.traces_tab, "Monitor CAN")
        
        # --- TAB 3: ANÁLISIS OFFLINE ---
        self.offline_tab = QWidget()
        self.setup_offline_ui()
        self.main_tabs.addTab(self.offline_tab, "📊 Análisis Offline")

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

    def setup_dashboard_ui(self):
        # Splitter principal: PANEL CONTROL | GRÁFICAS
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.dashboard_tab.setLayout(QVBoxLayout())
        self.dashboard_tab.layout().addWidget(main_splitter)
        
        # --- PANEL IZQUIERDO: CONTROLES ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 5, 5, 5)
        
        # Botones de control
        control_group = QGroupBox("CONTROL")
        control_layout = QVBoxLayout()
        
        clear_btn = QPushButton("🗑️ Limpiar Datos")
        clear_btn.setStyleSheet("background-color: #d32f2f; color: white; padding: 8px; font-weight: bold;")
        clear_btn.clicked.connect(self.clear_all_data)
        control_layout.addWidget(clear_btn)
        
        export_btn = QPushButton("💾 Exportar CSV")
        export_btn.setStyleSheet("background-color: #388e3c; color: white; padding: 8px; font-weight: bold;")
        export_btn.clicked.connect(self.export_to_csv)
        control_layout.addWidget(export_btn)
        
        control_group.setLayout(control_layout)
        left_layout.addWidget(control_group)
        
        # Selector de ventana temporal
        window_group = QGroupBox("VENTANA TEMPORAL")
        window_layout = QVBoxLayout()
        window_layout.setSpacing(5)
        
        self.window_button_group = QButtonGroup()
        
        self.rb_15s = QRadioButton("⏱ 15 segundos")
        self.rb_15s.setChecked(True)
        self.rb_15s.toggled.connect(lambda checked: checked and self.change_window_mode('sliding', 15.0))
        window_layout.addWidget(self.rb_15s)
        self.window_button_group.addButton(self.rb_15s)
        
        self.rb_5min = QRadioButton("⏱ 5 minutos")
        self.rb_5min.toggled.connect(lambda checked: checked and self.change_window_mode('sliding', 300.0))
        window_layout.addWidget(self.rb_5min)
        self.window_button_group.addButton(self.rb_5min)
        
        self.rb_full = QRadioButton("⏱ Todo el tiempo")
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
        
        motor_group = self.create_data_group("MOTOR", [
            ("ECT", "ect", "°C"), ("Oil Temp", "oil_temp", "°C"),
            ("Oil Press", "oil_press", "bar"), ("Fuel Press", "fuel_press", "bar"),
            ("RPM", "engine_rpm", "rpm"), ("Gear", "gear", ""),
            ("Lambda", "lamda", ""), ("Throttle", "tp", "%"),
            ("Bat Volt", "batt_volt", "V")
        ])
        scroll_layout.addWidget(motor_group)

        chassis_group = self.create_data_group("CHASIS", [
            ("Steering", "steering_wheel_angle", "°"), ("Brake", "brake_pressure", "bar"),
            ("FL Speed", "front_left_wheel_speed", "km/h"), ("FR Speed", "front_right_wheel_speed", "km/h"),
            ("RL Speed", "rear_left_speed", "km/h"), ("RR Speed", "rear_right_speed", "km/h"),
            ("FL Damp", "front_left_damper", "mm"), ("FR Damp", "front_right_damper", "mm")
        ])
        scroll_layout.addWidget(chassis_group)

        elec_group = self.create_data_group("ELÉCTRICO", [
            ("Alt Curr", "alternator_current", "A"), ("Ign Curr", "ignition_current", "A"),
            ("Inj Curr", "injection_current", "A"), ("Fuel Pmp", "fuel_pump_current", "A"),
            ("Water Pmp", "water_pump_current", "A"), ("Fan Curr", "main_fan_current", "A"),
            ("PDM Temp", "temp_pdm", "°C"), ("Lat", "latitude", "°")
        ])
        scroll_layout.addWidget(elec_group)
        
        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        left_layout.addWidget(scroll_area)
        
        # --- PANEL DERECHO: GRÁFICAS ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # ScrollArea para gráficas
        self.plots_scroll = QScrollArea()
        self.plots_scroll.setWidgetResizable(True)
        self.plots_scroll.setStyleSheet("QScrollArea { border: 1px solid #444; background-color: #1e1e1e; }")
        
        self.plots_container = QWidget()
        self.plots_layout = QVBoxLayout(self.plots_container)
        self.plots_layout.setSpacing(10)
        self.plots_layout.addStretch()
        
        self.plots_scroll.setWidget(self.plots_container)
        right_layout.addWidget(self.plots_scroll)
        
        # Configurar splitter
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 1)  # Panel izquierdo: 1 parte
        main_splitter.setStretchFactor(1, 3)  # Panel derecho: 3 partes
        main_splitter.setSizes([350, 1000])

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
    
    def setup_offline_ui(self):
        """Tab para análisis offline de archivos CSV"""
        layout = QVBoxLayout(self.offline_tab)
        
        # Header con botón de carga
        header_layout = QHBoxLayout()
        
        info_label = QLabel("📁 Análisis Offline - Carga archivos CSV exportados para visualización")
        info_label.setStyleSheet("color: #aaa; font-style: italic; font-size: 11pt;")
        header_layout.addWidget(info_label)
        
        header_layout.addStretch()
        
        load_btn = QPushButton("📂 Cargar CSV")
        load_btn.setStyleSheet("background-color: #1976d2; color: white; padding: 10px 20px; font-weight: bold; font-size: 11pt;")
        load_btn.clicked.connect(self.load_csv_file)
        header_layout.addWidget(load_btn)
        
        layout.addLayout(header_layout)
        
        # Splitter similar al dashboard en vivo
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Panel izquierdo: controles
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        control_group = QGroupBox("CONTROL")
        control_layout = QVBoxLayout()
        
        clear_btn = QPushButton("🗑️ Limpiar")
        clear_btn.setStyleSheet("background-color: #d32f2f; color: white; padding: 8px; font-weight: bold;")
        clear_btn.clicked.connect(self.clear_all_data)
        control_layout.addWidget(clear_btn)
        
        control_group.setLayout(control_layout)
        left_layout.addWidget(control_group)
        
        # Scroll con checkboxes (se llenará dinámicamente al cargar CSV)
        self.offline_scroll = QScrollArea()
        self.offline_scroll.setWidgetResizable(True)
        self.offline_scroll.setStyleSheet("QScrollArea { border: none; }")
        
        self.offline_signals_widget = QWidget()
        self.offline_signals_layout = QVBoxLayout(self.offline_signals_widget)
        self.offline_signals_layout.addStretch()
        
        self.offline_scroll.setWidget(self.offline_signals_widget)
        left_layout.addWidget(self.offline_scroll)
        
        # Panel derecho: gráficas (reutilizamos el sistema de plots)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        self.offline_plots_scroll = QScrollArea()
        self.offline_plots_scroll.setWidgetResizable(True)
        self.offline_plots_scroll.setStyleSheet("QScrollArea { border: 1px solid #444; background-color: #1e1e1e; }")
        
        self.offline_plots_container = QWidget()
        self.offline_plots_layout = QVBoxLayout(self.offline_plots_container)
        self.offline_plots_layout.setSpacing(10)
        self.offline_plots_layout.addStretch()
        
        self.offline_plots_scroll.setWidget(self.offline_plots_container)
        right_layout.addWidget(self.offline_plots_scroll)
        
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 3)
        main_splitter.setSizes([350, 1000])
        
        layout.addWidget(main_splitter)
        
        # Diccionarios para modo offline
        self.offline_checkboxes = {}
        self.offline_plot_widgets = {}

    def create_data_group(self, title, signals):
        group = QGroupBox(title)
        layout = QGridLayout()
        layout.setColumnStretch(2, 1)
        layout.setSpacing(3)
        
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
            lbl_name.setStyleSheet("color: #aaa; font-size: 10pt;")
            layout.addWidget(lbl_name, row, 1)
            
            # 3. Valor Señal
            lbl_val = QLabel("---")
            lbl_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl_val.setFont(QFont("Segoe UI", 11))
            lbl_val.setStyleSheet("color: #555;")
            layout.addWidget(lbl_val, row, 2)
            
            # 4. Unidad
            lbl_unit = QLabel(unit)
            lbl_unit.setStyleSheet("color: #666; font-size: 9pt;")
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
        lines = [f"⏱ Tiempo: {x_pos:.2f}s", "="*30]
        
        for signal_name, plot_widget in sorted(self.plot_widgets.items()):
            value = plot_widget.get_value_at_time(x_pos)
            if value is not None:
                color = self.color_assignment.get(signal_name, '#ffffff')
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
            self.popup_toggle_btn.setText("💬 Popup: ON")
            self.popup_toggle_btn.setStyleSheet("background-color: #00e676; color: white; padding: 5px 15px; border-radius: 3px; font-weight: bold;")
            print("[UI] Popup de valores activado (F2)")
        else:
            self.popup_toggle_btn.setText("💬 Popup: OFF")
            self.popup_toggle_btn.setStyleSheet("background-color: #555; color: #aaa; padding: 5px 15px; border-radius: 3px; font-weight: bold;")
            self.hide_value_popup()
            print("[UI] Popup de valores desactivado (F2)")
    
    def activate_default_graphs(self):
        """Activa las gráficas por defecto: ECT, tp, batt_volt, engine_rpm"""
        default_signals = ['ect', 'tp', 'batt_volt', 'engine_rpm']
        
        for signal in default_signals:
            if signal in self.checkboxes:
                self.checkboxes[signal].setChecked(True)
                print(f"[UI] Gráfica activada por defecto: {signal}")
    
    def clear_all_data(self):
        """Limpia todos los datos del DataStore"""
        self.data_store.clear()
        print("[DataStore] Todos los datos limpiados")
    
    def export_to_csv(self):
        """Exporta la sesión completa a CSV"""
        # Obtener todas las señales del DBC
        all_signals_from_dbc = []
        if self.can_worker.db:
            try:
                for msg in self.can_worker.db.messages:
                    for signal in msg.signals:
                        all_signals_from_dbc.append(signal.name)
                print(f"[Export] Encontradas {len(all_signals_from_dbc)} señales en DBC")
            except Exception as e:
                print(f"[Export] Error leyendo DBC: {e}")
        
        # Diálogo para seleccionar archivo
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"telemetria_{timestamp}.csv"
        
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar Telemetría a CSV",
            default_filename,
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if not filename:
            return  # Usuario canceló
        
        # Exportar
        success, message = self.data_store.export_to_csv(filename, all_signals_from_dbc)
        
        # Mostrar resultado
        if success:
            QMessageBox.information(
                self,
                "Exportación Exitosa",
                f"✅ {message}\n\nArchivo: {os.path.basename(filename)}"
            )
            print(f"[Export] {message} -> {filename}")
        else:
            QMessageBox.critical(
                self,
                "Error de Exportación",
                f"❌ {message}"
            )
            print(f"[Export] ERROR: {message}")
    
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
            # Limpiar checkboxes antiguos
            for i in reversed(range(self.offline_signals_layout.count())):
                widget = self.offline_signals_layout.itemAt(i).widget()
                if widget:
                    widget.deleteLater()
            
            # Limpiar gráficas antiguas
            for widget in self.offline_plot_widgets.values():
                self.offline_plots_layout.removeWidget(widget)
                widget.deleteLater()
            self.offline_plot_widgets.clear()
            self.offline_checkboxes.clear()
            
            # Crear checkboxes para todas las señales del CSV
            signals = self.data_store.get_all_signals()
            
            signals_group = QGroupBox(f"SEÑALES ({len(signals)})")
            signals_layout = QVBoxLayout()
            
            color_idx = 0
            for signal in sorted(signals):
                if signal not in self.color_assignment:
                    self.color_assignment[signal] = GRAPH_COLORS[color_idx % len(GRAPH_COLORS)]
                    color_idx += 1
                
                chk = QCheckBox(signal)
                chk.setStyleSheet(f"color: {self.color_assignment[signal]}; font-size: 10pt;")
                chk.toggled.connect(lambda checked, s=signal: self.toggle_offline_graph(s, checked))
                signals_layout.addWidget(chk)
                self.offline_checkboxes[signal] = chk
            
            signals_layout.addStretch()
            signals_group.setLayout(signals_layout)
            self.offline_signals_layout.addWidget(signals_group)
            
            # Cambiar al tab de análisis offline
            self.main_tabs.setCurrentIndex(2)
            
            QMessageBox.information(
                self,
                "CSV Cargado",
                f"✅ {message}\n\n{num_signals} señales\n{num_points} puntos temporales"
            )
            print(f"[CSV Load] {message}")
        else:
            QMessageBox.critical(
                self,
                "Error al Cargar CSV",
                f"❌ {message}"
            )
            print(f"[CSV Load] ERROR: {message}")
    
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
        
        lines = [f"⏱ Tiempo: {x_pos:.2f}s", "="*30]
        
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

        # Actualizar todas las gráficas activas
        if self.main_tabs.currentIndex() == 0:
            for plot_widget in self.plot_widgets.values():
                plot_widget.update_plot()

    def keyPressEvent(self, event):
        """Manejo de teclas globales"""
        if event.key() == Qt.Key.Key_F2:
            self.toggle_popup()
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
            save_btn = msg_box.addButton("💾 Guardar y Salir", QMessageBox.ButtonRole.AcceptRole)
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