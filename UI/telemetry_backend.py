"""Backend de telemetría: almacenamiento de datos (DataStore) y worker CAN serie.

Separado de Robowin.py para aislar la lógica de datos de la interfaz Qt.
"""
import csv
import os
import sys
import time
from collections import deque

import cantools
import serial
import serial.tools.list_ports
from PyQt6.QtCore import QMutex, QThread, pyqtSignal

# --- CONFIGURACIÓN CAN / DATOS ---
CAN_BITRATE = 1000000
CAN_INTERFACE_TYPE = 'robotell'
# Rutas: ejecutando el script, todo vive junto a él. Empaquetado con
# PyInstaller, BUNDLE_DIR es la carpeta de recursos embebidos (_MEIPASS,
# temporal) y SCRIPT_DIR pasa a ser la carpeta del .exe, que sí es escribible
# (autosave de sesiones, etc.).
IS_FROZEN = getattr(sys, 'frozen', False)
BUNDLE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
if IS_FROZEN:
    SCRIPT_DIR = os.path.dirname(sys.executable)
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# DBC: preferir uno externo junto al .exe (se puede actualizar sin recompilar);
# si no existe, usar el embebido en el paquete.
DBC_FILE = os.path.join(SCRIPT_DIR, "mft06.dbc")
if not os.path.exists(DBC_FILE):
    DBC_FILE = os.path.join(BUNDLE_DIR, "mft06.dbc")
LAPTIMER_CAN_ID = 0x777
# Vuelta mínima plausible: el sensor IR del laptimer emite dos pulsos por
# pasada del coche; cualquier "vuelta" más corta que esto es el segundo pulso
# de la misma pasada y se descarta sin mover la referencia de tiempo.
LAPTIMER_MIN_LAP_S = 3.0
# Trazas [DEBUG] por cada frame CAN: desactivadas por defecto porque imprimir en
# el bucle de lectura serie retrasa la lectura y puede perder frames a alta carga.
DEBUG_CAN = False

# Columnas de metadatos laptime del CSV combinado: no son señales de telemetría
# y deben ignorarse al recargar el CSV en el DataStore.
LAPTIME_CSV_COLUMNS = [
    'name', 'mode', 'started_at', 'ended_at', 'laps', 'total_time', 'best', 'avg',
    'last', 'consistency_ms', 'lap_number', 'lap_time_s', 'lap_time_fmt',
    'delta_s', 'delta_fmt', 'state'
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

            with open(filename, 'r', newline='') as csvfile:
                reader = csv.reader(csvfile)

                # Leer header
                header = next(reader, None)

                if not header or header[0] != 'timestamp':
                    self.lock.unlock()
                    return False, "Formato CSV inválido (falta columna timestamp)", 0, 0

                # Señales: todas las columnas excepto timestamp y metadatos laptime
                # (el CSV combinado incluye columnas de texto que no son señales).
                laptime_cols = set(LAPTIME_CSV_COLUMNS)
                signal_indices = [
                    (i, name) for i, name in enumerate(header[1:], start=1)
                    if name and name not in laptime_cols
                ]

                # Leer datos fila por fila. Cada celda se valida por separado:
                # una celda vacía o de texto no descarta el resto de la fila.
                num_rows = 0
                for row in reader:
                    if not row:
                        continue

                    try:
                        timestamp = float(row[0])
                    except (ValueError, IndexError):
                        continue  # Fila sin timestamp válido

                    row_has_data = False
                    for i, signal in signal_indices:
                        if i >= len(row):
                            continue
                        cell = row[i].strip()
                        if not cell:
                            continue
                        try:
                            value = float(cell)
                        except ValueError:
                            continue

                        if signal not in self.data:
                            # Carga offline sin límite: no descartar puntos
                            # de sesiones largas al analizar.
                            self.data[signal] = deque()
                            self.timestamps[signal] = deque()
                        self.data[signal].append(value)
                        self.timestamps[signal].append(timestamp)
                        row_has_data = True

                    if row_has_data:
                        num_rows += 1

                # Resetear start_time para que los timestamps del CSV sean relativos
                self.start_time = time.time()

                num_signals = len(self.data)
                self.lock.unlock()
                return True, "CSV cargado correctamente", num_signals, num_rows
                
        except FileNotFoundError:
            self.lock.unlock()
            return False, "Archivo no encontrado", 0, 0
        except Exception as e:
            self.lock.unlock()
            return False, f"Error al cargar CSV: {str(e)}", 0, 0
    
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
        if lap_time_s < LAPTIMER_MIN_LAP_S:
            # Segundo pulso del sensor IR en la misma pasada: ignorar SIN
            # actualizar la referencia (la vuelta se mide de primer pulso
            # a primer pulso).
            return {}

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
                                        if DEBUG_CAN:
                                            print(f"[DEBUG] ID 0x{can_id:X} -> Mensaje: {msg_name}")
                                    except KeyError:
                                        msg_name = f"ID_0x{can_id:X}"
                                        if DEBUG_CAN:
                                            print(f"[DEBUG] ID 0x{can_id:X} no encontrado en DBC")

                                    # Intentar decodificar y mezclar con señales derivadas (ej. laptimer)
                                    dbc_signals = self.db.decode_message(can_id, data_bytes)
                                    decoded_signals.update(dbc_signals)
                                    if DEBUG_CAN:
                                        print(f"[DEBUG] Señales decodificadas: {decoded_signals}")

                                except Exception as decode_err:
                                    if can_id != LAPTIMER_CAN_ID:
                                        decoded_str = f"(Decode Error: {decode_err})"
                                        if DEBUG_CAN:
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
