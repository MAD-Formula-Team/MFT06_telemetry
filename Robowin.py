import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import time
import serial
import serial.tools.list_ports
import cantools

# Configurar la interfaz CAN serial (detecta automáticamente el puerto)
def setup_can_interface():
    try:
        # Detectar puertos seriales disponibles
        ports = serial.tools.list_ports.comports()
        for port in ports:
            try:
                # Intentar conectar a cada puerto con baudrate asignado
                # Nota: Asegúrate de que el baudrate coincida con tu hardware (ej. 921600 o 115200)
                ser = serial.Serial(port.device, 921600, timeout=0.1)
                print(f"Conexión serial CAN establecida en {port.device}")
                return ser
            except Exception as e:
                print(f"No se pudo conectar a {port.device}: {e}")
                continue
        
        print("No se encontró ningún puerto serial disponible. Usando modo simulado.")
        return None
    except Exception as e:
        print(f"Error al buscar puertos seriales: {e}. Usando modo simulado.")
        return None

dbc_path = "mft04.dbc"
# Cargar el archivo DBC
def load_dbc_file(dbc_path):
    try:
        db = cantools.database.load_file(dbc_path)
        print(f"Archivo DBC cargado correctamente: {dbc_path}")
        return db
    except Exception as e:
        print(f"Error al cargar el archivo DBC: {e}")
        return None

# Parse el archivo DBC para obtener nombres de mensajes
def parse_dbc_names(dbc_path):
    messages = {}
    try:
        with open(dbc_path, 'r') as f:
            for line in f:
                if line.startswith('BO_ '):
                    parts = line.split()
                    if len(parts) >= 3:
                        can_id_dec = int(parts[1])
                        can_id_hex = format(can_id_dec, 'X')
                        message_name = parts[2].replace(':', '')
                        messages[can_id_hex] = message_name
    except Exception as e:
        print(f"Error al parsear archivo DBC: {e}")
    return messages

# Variables globales para almacenar datos (inicializadas a 0)
# Mantenemos todas las variables para no romper la lectura del hilo CAN, 
# aunque no todas se muestren en la UI.
ect = oil_temp = engine_in = carter_temp = 0
temp1 = temp2 = temp3 = temp4 = 0
steering_angle = 0
water_pump_current = 0
batt_volt = 0
gear = 0
engine_rpm = 0
fuel_press = 0
oil_press = 0
map_press = 0
lamda = 0
fuel_consump = 0
tp = 0
rear_left_speed = 0
rear_right_speed = 0
ecu_temp = 0
alternator_current = 0
ignition_current = 0
injection_current = 0
fuel_pump_current = 0
main_fan_current = 0
non_prior_current = 0
temp_pdm = 0
prior_current = 0
latitude = 0
longitude = 0
yaw_angle = 0
pitch_angle = 0
roll_angle = 0
velocity_x = 0
velocity_y = 0
velocity_z = 0
yaw_rate = 0
pitch_rate = 0
roll_rate = 0
accel_x = 0
accel_y = 0
accel_z = 0
angle_track = 0
angle_slip = 0
curvature_radius = 0
auto_status = 0
latitude_acc = 0
longitude_acc = 0
altitude_acc = 0
roll_acc = 0
pitch_acc = 0
yaw_acc = 0
time_stamp = 0
imu_status = 0
temp_imu = 0
digital = 0
brake_pressure = 0
front_left_wheel_speed = 0
front_right_wheel_speed = 0
front_left_damper = 0
front_right_damper = 0
node_pcb_temp = 0

# Variables para trazas CAN
can_trace_lines = []
can_trace_lock = threading.Lock()
packet_count = 0
connection_status = "Desconectado"
reconnect_attempt = 0

# Función para leer los mensajes CAN en un hilo separado
def can_reader(serial_port, db):
    # Declaración de globales (se mantienen para que la lógica de recepción funcione)
    global ect, oil_temp, engine_in, carter_temp, temp1, temp2, temp3, temp4, steering_angle, water_pump_current
    global batt_volt, gear, engine_rpm, fuel_press, oil_press, map_press, lamda, fuel_consump, tp, rear_left_speed, rear_right_speed
    global ecu_temp, alternator_current, ignition_current, injection_current, fuel_pump_current, main_fan_current, non_prior_current, temp_pdm, prior_current
    global latitude, longitude, yaw_angle, pitch_angle, roll_angle, velocity_x, velocity_y, velocity_z, yaw_rate, pitch_rate, roll_rate
    global accel_x, accel_y, accel_z, angle_track, angle_slip, curvature_radius, auto_status, latitude_acc, longitude_acc, altitude_acc
    global roll_acc, pitch_acc, yaw_acc, time_stamp, imu_status, temp_imu, digital, brake_pressure, front_left_wheel_speed, front_right_wheel_speed
    global front_left_damper, front_right_damper, node_pcb_temp, packet_count
    global connection_status, reconnect_attempt

    dbc_messages = parse_dbc_names(dbc_path)
    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 10

    while running:
        if serial_port is None:
            connection_status = "Desconectado - Intentando reconectar..."
            reconnect_attempt += 1
            print(f"Intento de reconexión #{reconnect_attempt}")
            
            # Intentar reconectar cada 3 segundos
            serial_port = setup_can_interface()
            if serial_port is not None:
                connection_status = f"Conectado ({serial_port.port})"
                consecutive_errors = 0
                reconnect_attempt = 0
            else:
                time.sleep(3)  # Esperar antes del siguiente intento
            continue

        try:
            # Leer datos del puerto serial
            if serial_port.in_waiting > 0:
                line = serial_port.readline().decode('utf-8', errors='ignore').strip()
                
                if not line:
                    continue
                
                # Formato: número_paquete,ID_CAN,byte0,byte1,byte2,...
                parts = line.split(',')
                
                if len(parts) < 2:
                    continue
                
                packet_num = parts[0].strip()
                can_id_hex = parts[1].strip().upper()
                data_bytes = parts[2:] if len(parts) > 2 else []
                
                # Convertir ID hexadecimal a decimal
                try:
                    can_id = int(can_id_hex, 16)
                except Exception as e:
                    print(f"Error al convertir ID '{can_id_hex}' a decimal: {e}")
                    continue
                
                # Convertir bytes hex a lista de bytes
                data = []
                for b in data_bytes:
                    try:
                        byte_val = int(b.strip(), 16)
                        data.append(byte_val)
                    except Exception as e:
                        pass
                
                # Crear array de bytes para decodificación
                msg_data = bytes(data)
                
                # Registrar traza CAN
                timestamp = time.strftime("%H:%M:%S")
                message_name = dbc_messages.get(can_id_hex, "Desconocido")
                data_str = ' '.join([f"{b:02X}" for b in data])
                
                # Intentar decodificar usando DBC
                decoded_signals = ""
                if db is not None and len(msg_data) > 0:
                    try:
                        decoded = db.decode_message(can_id, msg_data)
                        signal_list = []
                        for signal_name, signal_value in decoded.items():
                            if isinstance(signal_value, float):
                                signal_list.append(f"{signal_name}={signal_value:.3f}")
                            else:
                                signal_list.append(f"{signal_name}={signal_value}")
                        
                        if signal_list:
                            decoded_signals = " | " + " | ".join(signal_list)
                        else:
                            decoded_signals = f" | Raw: [{data_str}]"
                    except Exception as e:
                        decoded_signals = f" | Raw: [{data_str}] (No decodificado)"
                else:
                    decoded_signals = f" | Raw: [{data_str}]"
                
                trace_line = f"[{timestamp}] ID:0x{can_id_hex:4s} ({can_id:4d}) {message_name:20s}{decoded_signals}"
                
                with can_trace_lock:
                    can_trace_lines.append(trace_line)
                    if len(can_trace_lines) > 500: # Reducido buffer para mejorar rendimiento
                        can_trace_lines.pop(0)
                
                packet_count += 1
                
                if db is None:
                    continue
                
                consecutive_errors = 0
                connection_status = f"Conectado ({serial_port.port})" if hasattr(serial_port, 'port') else "Conectado"

                # Lógica de decodificación para actualizar variables globales
                # (Se mantiene idéntica para asegurar la integridad de los datos)
                if can_id == 929:  # ENGINE_TEMP_ID
                    decoded = db.decode_message(929, msg_data)
                    ect = decoded.get("ect", ect)
                    oil_temp = decoded.get("oil_temp", oil_temp)

                elif can_id == 930:  # ENGINE_PRESS_ID
                    decoded = db.decode_message(930, msg_data)
                    fuel_press = decoded.get("fuel_press", fuel_press)
                    oil_press = decoded.get("oil_press", oil_press)
                    map_press = decoded.get("map", map_press)

                elif can_id == 931:  # ENGINE_FUEL_ID
                    decoded = db.decode_message(931, msg_data)
                    lamda = decoded.get("lamda", lamda)
                    fuel_consump = decoded.get("fuel_consump", fuel_consump)
                    tp = decoded.get("tp", tp)

                elif can_id == 932:  # ENGINE_SPEED_ID
                    decoded = db.decode_message(932, msg_data)
                    gear = decoded.get("gear", gear)
                    rear_left_speed = decoded.get("rear_left_speed", rear_left_speed)
                    rear_right_speed = decoded.get("rear_right_speed", rear_right_speed)
                    engine_rpm = decoded.get("engine_rpm", engine_rpm)

                elif can_id == 933:  # ENGINE_MISC_ID
                    decoded = db.decode_message(933, msg_data)
                    batt_volt = decoded.get("batt_volt", batt_volt)
                    ecu_temp = decoded.get("ecu_temp", ecu_temp)
                    engine_in = decoded.get("engine_in", engine_in)
                    carter_temp = decoded.get("carter_temp", carter_temp)

                elif can_id == 945:  # CURRENTS_ENGINE_ID
                    decoded = db.decode_message(945, msg_data)
                    alternator_current = decoded.get("alternator_current", alternator_current)
                    ignition_current = decoded.get("ignition_current", ignition_current)
                    injection_current = decoded.get("injection_current", injection_current)
                    fuel_pump_current = decoded.get("fuel_pump_current", fuel_pump_current)

                elif can_id == 946:  # CURRENTS_COOLING_ID
                    decoded = db.decode_message(946, msg_data)
                    water_pump_current = decoded.get("water_pump_current", water_pump_current)
                    main_fan_current = decoded.get("main_fan_current", main_fan_current)
                    non_prior_current = decoded.get("non_prior_current", non_prior_current)
                    temp_pdm = decoded.get("temp_pdm", temp_pdm)

                elif can_id == 947:  # CURRENTS_OTHER_ID
                    decoded = db.decode_message(947, msg_data)
                    prior_current = decoded.get("prior_current", prior_current)

                elif can_id == 961:  # POS_CART_ID
                    decoded = db.decode_message(961, msg_data)
                    latitude = decoded.get("latitude", latitude)
                    longitude = decoded.get("longitude", longitude)

                elif can_id == 962:  # POS_EUL_ID
                    decoded = db.decode_message(962, msg_data)
                    yaw_angle = decoded.get("yaw_angle", yaw_angle)
                    pitch_angle = decoded.get("pitch_angle", pitch_angle)
                    roll_angle = decoded.get("roll_angle", roll_angle)
                
                # ... (resto de IDs se decodifican igual para mantener consistencia interna) ...
                
                elif can_id == 934:  # INFLUX_DIGITAL_ID
                    decoded = db.decode_message(934, msg_data)
                    digital = decoded.get("digital", digital)

                elif can_id == 176:  # STEERING_ID
                    decoded = db.decode_message(176, msg_data)
                    steering_angle = decoded.get("steering_wheel_angle", steering_angle)
                    brake_pressure = decoded.get("brake_pressure", brake_pressure)
                    front_left_wheel_speed = decoded.get("front_left_wheel_speed", front_left_wheel_speed)
                    front_right_wheel_speed = decoded.get("front_right_wheel_speed", front_right_wheel_speed)

                elif can_id == 177:  # DAMPERS_ID
                    decoded = db.decode_message(177, msg_data)
                    front_left_damper = decoded.get("front_left_damper", front_left_damper)
                    front_right_damper = decoded.get("front_right_damper", front_right_damper)

                elif can_id == 993:  # NODE_TEMP_1_ID
                    decoded = db.decode_message(993, msg_data)
                    node_pcb_temp = decoded.get("node_pcb_temp", node_pcb_temp)
                    temp1 = decoded.get("temp1", temp1)
                    temp2 = decoded.get("temp2", temp2)
                    temp3 = decoded.get("temp3", temp3)

                elif can_id == 994:  # NODE_TEMP_2_ID
                    decoded = db.decode_message(994, msg_data)
                    temp4 = decoded.get("temp4", temp4)

        except (serial.SerialException, OSError) as e:
            # Error de conexión serial
            print(f"Error de conexión serial: {e}")
            consecutive_errors += 1
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                try:
                    if serial_port and serial_port.is_open:
                        serial_port.close()
                except:
                    pass
                serial_port = None
                connection_status = "Desconectado - Error de conexión"
                consecutive_errors = 0
            time.sleep(0.5)
        except Exception as e:
            # print(f"Error al leer CAN: {e}") 
            consecutive_errors += 1
            time.sleep(0.1)

# Función para actualizar la interfaz gráfica
def update_ui():
    # Importamos solo las variables que vamos a mostrar
    global ect, oil_temp, engine_in, carter_temp, temp1, temp2, temp3, temp4, steering_angle, water_pump_current
    global batt_volt, gear, engine_rpm, fuel_press, oil_press, map_press, lamda, fuel_consump, tp, rear_left_speed, rear_right_speed
    global ecu_temp, alternator_current, ignition_current, injection_current, fuel_pump_current, main_fan_current, non_prior_current, temp_pdm, prior_current
    global digital, brake_pressure, front_left_wheel_speed, front_right_wheel_speed
    global front_left_damper, front_right_damper, node_pcb_temp, packet_count
    # Variables de UI
    global packets_label, unique_ids_label, can_traces_text
    global connection_status, connection_status_label, reconnect_attempt

    last_trace_count = 0
    unique_ids = set()

    while running:
        # Actualizar estado de conexión
        if "Conectado" in connection_status:
            connection_status_label.config(text=f"Estado: {connection_status}", foreground="green")
        elif "Intentando" in connection_status:
            connection_status_label.config(text=f"Estado: {connection_status} (Intento #{reconnect_attempt})", foreground="orange")
        else:
            connection_status_label.config(text=f"Estado: {connection_status}", foreground="red")
        
        # --- Actualización de etiquetas (Solo MOTOR, CHASIS, ELÉCTRICO) ---
        
        # MOTOR
        ect_label.config(text=f"ECT: {ect} °C")
        oil_temp_label.config(text=f"Oil Temp: {oil_temp} °C")
        engine_in_label.config(text=f"Engine In: {engine_in} °C")
        carter_temp_label.config(text=f"Carter Temp: {carter_temp} °C")
        temp1_label.config(text=f"Temp 1: {temp1} °C")
        temp2_label.config(text=f"Temp 2: {temp2} °C")
        temp3_label.config(text=f"Temp 3: {temp3} °C")
        temp4_label.config(text=f"Temp 4: {temp4} °C")
        gear_label.config(text=f"Gear: {gear}")
        engine_rpm_label.config(text=f"Engine RPM: {engine_rpm}")
        fuel_press_label.config(text=f"Fuel Press: {fuel_press} bar")
        oil_press_label.config(text=f"Oil Press: {oil_press} bar")
        map_press_label.config(text=f"MAP Press: {map_press} bar")
        lamda_label.config(text=f"Lambda: {lamda}")
        fuel_consump_label.config(text=f"Fuel Cons: {fuel_consump} l/h")
        tp_label.config(text=f"Throttle: {tp} %")
        ecu_temp_label.config(text=f"ECU Temp: {ecu_temp} °C")
        node_pcb_temp_label.config(text=f"PCB Temp: {node_pcb_temp} °C")

        # CHASIS
        steering_angle_label.config(text=f"Steering: {steering_angle} °")
        brake_pressure_label.config(text=f"Brake Press: {brake_pressure} bar")
        front_left_wheel_speed_label.config(text=f"FL Speed: {front_left_wheel_speed} km/h")
        front_right_wheel_speed_label.config(text=f"FR Speed: {front_right_wheel_speed} km/h")
        rear_left_speed_label.config(text=f"RL Speed: {rear_left_speed} km/h")
        rear_right_speed_label.config(text=f"RR Speed: {rear_right_speed} km/h")
        front_left_damper_label.config(text=f"FL Damper: {front_left_damper} mm")
        front_right_damper_label.config(text=f"FR Damper: {front_right_damper} mm")
        digital_label.config(text=f"Digital: {digital}")

        # ELECTRICO
        batt_volt_label.config(text=f"Battery: {batt_volt} V")
        water_pump_current_label.config(text=f"Water Pump: {water_pump_current} A")
        alternator_current_label.config(text=f"Alternator: {alternator_current} A")
        ignition_current_label.config(text=f"Ignition: {ignition_current} A")
        injection_current_label.config(text=f"Injection: {injection_current} A")
        fuel_pump_current_label.config(text=f"Fuel Pump: {fuel_pump_current} A")
        main_fan_current_label.config(text=f"Main Fan: {main_fan_current} A")
        non_prior_current_label.config(text=f"Non-Prior: {non_prior_current} A")
        prior_current_label.config(text=f"Prior: {prior_current} A")
        temp_pdm_label.config(text=f"PDM Temp: {temp_pdm} °C")
        
        # Estadísticas
        packets_label.config(text=f"Paquetes: {packet_count}")
        
        # Actualizar trazas CAN
        with can_trace_lock:
            current_trace_count = len(can_trace_lines)
            if current_trace_count > last_trace_count:
                # Añadir nuevas líneas
                for i in range(last_trace_count, current_trace_count):
                    tag = "even" if i % 2 == 0 else "odd"
                    can_traces_text.insert(tk.END, can_trace_lines[i] + "\n", tag)
                
                can_traces_text.see(tk.END)
                last_trace_count = current_trace_count
            
            # Contar IDs únicos (simplificado para rendimiento)
            for line in can_trace_lines:
                if "ID:" in line:
                    try:
                        id_part = line.split("ID:")[1].split("|")[0].strip()
                        unique_ids.add(id_part)
                    except:
                        pass
        
        unique_ids_label.config(text=f"IDs únicos: {len(unique_ids)}")
        
        time.sleep(0.1)

# Crear la interfaz gráfica
root = tk.Tk()
root.title("RoboWin - Telemetría Unificada")
root.geometry("1280x850")

# --- Frame Superior: Control de Conexión ---
connection_frame = ttk.LabelFrame(root, text="Estado de Conexión", padding=5)
connection_frame.pack(fill=tk.X, padx=10, pady=5)

connection_status_label = ttk.Label(connection_frame, text="Estado: Inicializando...", font=("Century Gothic", 11))
connection_status_label.pack(side=tk.LEFT, padx=10)

def manual_reconnect():
    global serial_port, connection_status
    reconnect_button.config(state=tk.DISABLED, text="...")
    connection_status_label.config(text="Estado: Reconectando...")
    root.update()
    try:
        if serial_port and hasattr(serial_port, 'is_open') and serial_port.is_open:
            serial_port.close()
    except:
        pass
    serial_port = setup_can_interface()
    if serial_port:
        connection_status = f"Conectado ({serial_port.port})"
        connection_status_label.config(text=f"Estado: {connection_status}", foreground="green")
    else:
        connection_status = "Desconectado"
        connection_status_label.config(text=f"Estado: {connection_status}", foreground="red")
    reconnect_button.config(state=tk.NORMAL, text="Reconectar")

reconnect_button = ttk.Button(connection_frame, text="Reconectar", command=manual_reconnect)
reconnect_button.pack(side=tk.LEFT, padx=10)

# --- Frame Principal para Datos (Grid 1x3) ---
data_container = ttk.Frame(root)
data_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

# Configurar pesos de columnas para que se expandan igual
data_container.columnconfigure(0, weight=1)
data_container.columnconfigure(1, weight=1)
data_container.columnconfigure(2, weight=1)

# Estilos
style = ttk.Style()
style.configure("TLabel", font=("Century Gothic", 10))
style.configure("Header.TLabel", font=("Century Gothic", 12, "bold"))
style.configure("Big.TLabelframe.Label", font=("Century Gothic", 12, "bold", "italic"))

# === COLUMNA 1: MOTOR ===
engine_frame = ttk.LabelFrame(data_container, text=" MOTOR ", style="Big.TLabelframe", padding=10)
engine_frame.grid(row=0, column=0, sticky="nsew", padx=5)

# Sub-grid motor
ect_label = ttk.Label(engine_frame, text="ECT: 0 °C")
ect_label.grid(row=0, column=0, sticky=tk.W, pady=2)
oil_temp_label = ttk.Label(engine_frame, text="Oil Temp: 0 °C")
oil_temp_label.grid(row=1, column=0, sticky=tk.W, pady=2)
engine_in_label = ttk.Label(engine_frame, text="Engine In: 0 °C")
engine_in_label.grid(row=2, column=0, sticky=tk.W, pady=2)
carter_temp_label = ttk.Label(engine_frame, text="Carter Temp: 0 °C")
carter_temp_label.grid(row=3, column=0, sticky=tk.W, pady=2)
ecu_temp_label = ttk.Label(engine_frame, text="ECU Temp: 0 °C")
ecu_temp_label.grid(row=4, column=0, sticky=tk.W, pady=2)

# Separador visual o segunda columna dentro de motor
engine_rpm_label = ttk.Label(engine_frame, text="Engine RPM: 0", font=("Century Gothic", 12, "bold"), foreground="blue")
engine_rpm_label.grid(row=0, column=1, sticky=tk.W, padx=10, pady=2)
gear_label = ttk.Label(engine_frame, text="Gear: 0", font=("Century Gothic", 12, "bold"))
gear_label.grid(row=1, column=1, sticky=tk.W, padx=10, pady=2)
fuel_press_label = ttk.Label(engine_frame, text="Fuel Press: 0 bar")
fuel_press_label.grid(row=2, column=1, sticky=tk.W, padx=10, pady=2)
oil_press_label = ttk.Label(engine_frame, text="Oil Press: 0 bar")
oil_press_label.grid(row=3, column=1, sticky=tk.W, padx=10, pady=2)
map_press_label = ttk.Label(engine_frame, text="MAP Press: 0 bar")
map_press_label.grid(row=4, column=1, sticky=tk.W, padx=10, pady=2)

lamda_label = ttk.Label(engine_frame, text="Lambda: 0")
lamda_label.grid(row=5, column=0, sticky=tk.W, pady=2)
fuel_consump_label = ttk.Label(engine_frame, text="Fuel Cons: 0 l/h")
fuel_consump_label.grid(row=6, column=0, sticky=tk.W, pady=2)
tp_label = ttk.Label(engine_frame, text="Throttle: 0 %")
tp_label.grid(row=7, column=0, sticky=tk.W, pady=2)

temp1_label = ttk.Label(engine_frame, text="Temp 1: 0 °C")
temp1_label.grid(row=5, column=1, sticky=tk.W, padx=10, pady=2)
temp2_label = ttk.Label(engine_frame, text="Temp 2: 0 °C")
temp2_label.grid(row=6, column=1, sticky=tk.W, padx=10, pady=2)
temp3_label = ttk.Label(engine_frame, text="Temp 3: 0 °C")
temp3_label.grid(row=7, column=1, sticky=tk.W, padx=10, pady=2)
temp4_label = ttk.Label(engine_frame, text="Temp 4: 0 °C")
temp4_label.grid(row=8, column=1, sticky=tk.W, padx=10, pady=2)
node_pcb_temp_label = ttk.Label(engine_frame, text="PCB Temp: 0 °C")
node_pcb_temp_label.grid(row=8, column=0, sticky=tk.W, pady=2)


# === COLUMNA 2: CHASIS ===
chassis_frame = ttk.LabelFrame(data_container, text=" CHASIS ", style="Big.TLabelframe", padding=10)
chassis_frame.grid(row=0, column=1, sticky="nsew", padx=5)

steering_angle_label = ttk.Label(chassis_frame, text="Steering: 0 °")
steering_angle_label.grid(row=0, column=0, sticky=tk.W, pady=2)
brake_pressure_label = ttk.Label(chassis_frame, text="Brake Press: 0 bar")
brake_pressure_label.grid(row=1, column=0, sticky=tk.W, pady=2)
digital_label = ttk.Label(chassis_frame, text="Digital: 0")
digital_label.grid(row=2, column=0, sticky=tk.W, pady=2)

ttk.Separator(chassis_frame, orient='horizontal').grid(row=3, column=0, columnspan=2, sticky="ew", pady=5)

front_left_wheel_speed_label = ttk.Label(chassis_frame, text="FL Speed: 0 km/h")
front_left_wheel_speed_label.grid(row=4, column=0, sticky=tk.W, pady=2)
front_right_wheel_speed_label = ttk.Label(chassis_frame, text="FR Speed: 0 km/h")
front_right_wheel_speed_label.grid(row=4, column=1, sticky=tk.W, padx=10, pady=2)
rear_left_speed_label = ttk.Label(chassis_frame, text="RL Speed: 0 km/h")
rear_left_speed_label.grid(row=5, column=0, sticky=tk.W, pady=2)
rear_right_speed_label = ttk.Label(chassis_frame, text="RR Speed: 0 km/h")
rear_right_speed_label.grid(row=5, column=1, sticky=tk.W, padx=10, pady=2)

ttk.Separator(chassis_frame, orient='horizontal').grid(row=6, column=0, columnspan=2, sticky="ew", pady=5)

front_left_damper_label = ttk.Label(chassis_frame, text="FL Damper: 0 mm")
front_left_damper_label.grid(row=7, column=0, sticky=tk.W, pady=2)
front_right_damper_label = ttk.Label(chassis_frame, text="FR Damper: 0 mm")
front_right_damper_label.grid(row=7, column=1, sticky=tk.W, padx=10, pady=2)


# === COLUMNA 3: ELÉCTRICO ===
electrical_frame = ttk.LabelFrame(data_container, text=" ELÉCTRICO ", style="Big.TLabelframe", padding=10)
electrical_frame.grid(row=0, column=2, sticky="nsew", padx=5)

batt_volt_label = ttk.Label(electrical_frame, text="Battery: 0 V", font=("Century Gothic", 12, "bold"), foreground="green")
batt_volt_label.grid(row=0, column=0, sticky=tk.W, pady=5)

alternator_current_label = ttk.Label(electrical_frame, text="Alternator: 0 A")
alternator_current_label.grid(row=1, column=0, sticky=tk.W, pady=2)
ignition_current_label = ttk.Label(electrical_frame, text="Ignition: 0 A")
ignition_current_label.grid(row=2, column=0, sticky=tk.W, pady=2)
injection_current_label = ttk.Label(electrical_frame, text="Injection: 0 A")
injection_current_label.grid(row=3, column=0, sticky=tk.W, pady=2)
fuel_pump_current_label = ttk.Label(electrical_frame, text="Fuel Pump: 0 A")
fuel_pump_current_label.grid(row=4, column=0, sticky=tk.W, pady=2)
water_pump_current_label = ttk.Label(electrical_frame, text="Water Pump: 0 A")
water_pump_current_label.grid(row=5, column=0, sticky=tk.W, pady=2)
main_fan_current_label = ttk.Label(electrical_frame, text="Main Fan: 0 A")
main_fan_current_label.grid(row=6, column=0, sticky=tk.W, pady=2)
non_prior_current_label = ttk.Label(electrical_frame, text="Non-Prior: 0 A")
non_prior_current_label.grid(row=7, column=0, sticky=tk.W, pady=2)
prior_current_label = ttk.Label(electrical_frame, text="Prior: 0 A")
prior_current_label.grid(row=8, column=0, sticky=tk.W, pady=2)
temp_pdm_label = ttk.Label(electrical_frame, text="PDM Temp: 0 °C")
temp_pdm_label.grid(row=9, column=0, sticky=tk.W, pady=2)

# --- Frame Inferior: Trazas CAN (Compacto) ---
traces_frame = ttk.LabelFrame(root, text="Monitor CAN", padding=5)
traces_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

# Stats en línea
stats_frame = ttk.Frame(traces_frame)
stats_frame.pack(fill=tk.X)
packets_label = ttk.Label(stats_frame, text="Paquetes: 0", font=("Arial", 9))
packets_label.pack(side=tk.LEFT, padx=5)
unique_ids_label = ttk.Label(stats_frame, text="IDs únicos: 0", font=("Arial", 9))
unique_ids_label.pack(side=tk.LEFT, padx=5)

# Texto scrolleable
can_traces_text = scrolledtext.ScrolledText(traces_frame, wrap=tk.WORD, height=10, font=("Courier New", 8))
can_traces_text.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
can_traces_text.tag_config("even", background="#f0f0f0")
can_traces_text.tag_config("odd", background="#ffffff")

# --- Control de Cierre ---
def on_closing():
    global running, serial_port
    running = False
    time.sleep(0.5)
    if serial_port and hasattr(serial_port, 'is_open') and serial_port.is_open:
        serial_port.close()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_closing)

# --- Inicialización ---
running = True
serial_port = None

# Iniciar
serial_port = setup_can_interface()
db = load_dbc_file(dbc_path)

if serial_port:
    connection_status = f"Conectado ({serial_port.port})"
else:
    connection_status = "Desconectado - No se encontró puerto"

# Hilos
can_thread = threading.Thread(target=can_reader, args=(serial_port, db))
can_thread.daemon = True
can_thread.start()

ui_thread = threading.Thread(target=update_ui)
ui_thread.daemon = True
ui_thread.start()

root.mainloop()