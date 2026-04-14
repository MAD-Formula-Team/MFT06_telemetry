import sys
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QLCDNumber, QFrame)
from PyQt6.QtCore import Qt, QElapsedTimer, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QBrush

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
        track_pen = QPen(QColor("#333333"), 40)
        active_pen = QPen(QColor("#00e676"), 40)
        text_pen = QPen(QColor("#ffffff"))
        font = QFont("Consolas", 14, QFont.Weight.Bold)
        painter.setFont(font)
        
        # Dibujar Círculo Izquierdo
        painter.setPen(active_pen if self.active_section in [3, 4] else track_pen)
        painter.drawEllipse(left_center_x - circle_radius, center_y - circle_radius, 
                            circle_radius * 2, circle_radius * 2)
        
        # Dibujar Círculo Derecho
        painter.setPen(active_pen if self.active_section in [1, 2] else track_pen)
        painter.drawEllipse(right_center_x - circle_radius, center_y - circle_radius, 
                            circle_radius * 2, circle_radius * 2)
        
        # Textos Izquierda
        painter.setPen(text_pen)
        l1_text = f"V1 Izq: {self.time_l1:.3f} s" if self.time_l1 > 0 else "V1 Izq: --.--- s"
        l2_text = f"V2 Izq: {self.time_l2:.3f} s" if self.time_l2 > 0 else "V2 Izq: --.--- s"
        painter.drawText(left_center_x - 80, center_y - 20, l1_text)
        painter.drawText(left_center_x - 80, center_y + 20, l2_text)
        
        # Textos Derecha
        r1_text = f"V1 Der: {self.time_r1:.3f} s" if self.time_r1 > 0 else "V1 Der: --.--- s"
        r2_text = f"V2 Der: {self.time_r2:.3f} s" if self.time_r2 > 0 else "V2 Der: --.--- s"
        painter.drawText(right_center_x - 80, center_y - 20, r1_text)
        painter.drawText(right_center_x - 80, center_y + 20, r2_text)

class SkidpadLaptimerWidget(QWidget):
    """Widget principal que integra la UI y la máquina de estados del Skidpad."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FS Skidpad Laptimer")
        self.setStyleSheet("background-color: #121212; color: #ffffff;")
        
        # Variables de estado
        self.state = 'IDLE' # Estados: IDLE, READY, R1, R2, L1, L2, FINISHED
        self.elapsed_timer = QElapsedTimer()
        self.lap_start_time = 0
        
        self.times = {'r1': 0.0, 'r2': 0.0, 'l1': 0.0, 'l2': 0.0}
        
        # Timer para actualizar la UI en vivo
        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self.update_live_ui)
        self.ui_timer.start(50)
        
        self.init_ui()
        
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        
        # --- Cabecera: Título y Status ---
        header_layout = QHBoxLayout()
        title = QLabel("SKIDPAD TELEMETRY")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffd166;")
        
        self.status_label = QLabel("ESTADO: ESPERANDO")
        self.status_label.setStyleSheet("font-size: 16px; color: #aaaaaa; background-color: #222; padding: 5px; border-radius: 5px;")
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.status_label)
        main_layout.addLayout(header_layout)
        
        # --- Display de Tiempo Total ---
        self.total_time_lcd = QLCDNumber()
        self.total_time_lcd.setDigitCount(8)
        self.total_time_lcd.setSegmentStyle(QLCDNumber.SegmentStyle.Flat)
        self.total_time_lcd.setStyleSheet("color: #00e676; background-color: #000; border: 2px solid #333;")
        self.total_time_lcd.setMinimumHeight(100)
        self.total_time_lcd.display("00.000")
        main_layout.addWidget(self.total_time_lcd)
        
        # --- Viewport del Circuito ---
        self.track_widget = SkidpadTrackWidget()
        main_layout.addWidget(self.track_widget, 1) # Expandible
        
        # --- Controles ---
        controls_layout = QHBoxLayout()
        
        self.btn_modo = QPushButton("Seleccionar Modo")
        self.btn_modo.setStyleSheet(self._button_style("#2979ff"))
        self.btn_modo.setFocusPolicy(Qt.FocusPolicy.NoFocus) # Evita que interfiera con la barra espaciadora
        
        self.btn_start = QPushButton("Iniciar (Ready)")
        self.btn_start.setStyleSheet(self._button_style("#00e676"))
        self.btn_start.clicked.connect(self.arm_system)
        self.btn_start.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        self.btn_reset = QPushButton("Reset")
        self.btn_reset.setStyleSheet(self._button_style("#ff1744"))
        self.btn_reset.clicked.connect(self.reset_system)
        self.btn_reset.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        controls_layout.addWidget(self.btn_modo)
        controls_layout.addWidget(self.btn_start)
        controls_layout.addWidget(self.btn_reset)
        main_layout.addLayout(controls_layout)
        
        # Instrucción
        info = QLabel("Pulsa [ESPACIO] para simular los triggers ópticos en pista.")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setStyleSheet("color: #777;")
        main_layout.addWidget(info)
        
    def _button_style(self, base_color):
        return f"""
            QPushButton {{
                background-color: {base_color};
                color: white;
                font-weight: bold;
                font-size: 16px;
                padding: 10px;
                border: none;
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background-color: {base_color}dd;
            }}
            QPushButton:pressed {{
                background-color: {base_color}aa;
            }}
        """
        
    def arm_system(self):
        if self.state in ['IDLE', 'FINISHED']:
            self.state = 'READY'
            self.times = {'r1': 0.0, 'r2': 0.0, 'l1': 0.0, 'l2': 0.0}
            self.status_label.setText("ESTADO: READY (Esperando Trigger 1)")
            self.status_label.setStyleSheet("font-size: 16px; color: black; background-color: #ffea00; padding: 5px;")
            self.track_widget.update_times(0, 0, 0, 0, 0)
            self.total_time_lcd.display("00.000")
            
    def reset_system(self):
        self.state = 'IDLE'
        self.times = {'r1': 0.0, 'r2': 0.0, 'l1': 0.0, 'l2': 0.0}
        self.status_label.setText("ESTADO: ESPERANDO")
        self.status_label.setStyleSheet("font-size: 16px; color: #aaaaaa; background-color: #222; padding: 5px;")
        self.track_widget.update_times(0, 0, 0, 0, 0)
        self.total_time_lcd.display("00.000")
        
    def trigger_event(self):
        """Maneja la secuencia de cruce por la línea de meta del Skidpad."""
        current_time_ms = self.elapsed_timer.elapsed() if self.elapsed_timer.isValid() else 0
        
        if self.state == 'READY':
            # Trigger 1: Inicia vuelta 1 derecha
            self.elapsed_timer.start()
            self.lap_start_time = 0
            self.state = 'R1'
            self.status_label.setText("ESTADO: CORRIENDO (V1 DERECHA)")
            self.status_label.setStyleSheet("font-size: 16px; color: black; background-color: #00e676; padding: 5px;")
            self.track_widget.active_section = 1
            
        elif self.state == 'R1':
            # Trigger 2: Cierra V1 Der, Inicia V2 Der
            lap_time = (current_time_ms - self.lap_start_time) / 1000.0
            self.times['r1'] = lap_time
            self.lap_start_time = current_time_ms
            self.state = 'R2'
            self.status_label.setText("ESTADO: CORRIENDO (V2 DERECHA)")
            self.track_widget.active_section = 2
            
        elif self.state == 'R2':
            # Trigger 3: Cierra V2 Der, Inicia transicion a Izquierda (V1 Izq)
            lap_time = (current_time_ms - self.lap_start_time) / 1000.0
            self.times['r2'] = lap_time
            self.lap_start_time = current_time_ms
            self.state = 'L1'
            self.status_label.setText("ESTADO: CORRIENDO (V1 IZQUIERDA)")
            self.track_widget.active_section = 3
            
        elif self.state == 'L1':
            # Trigger 4: Cierra V1 Izq, Inicia V2 Izq
            lap_time = (current_time_ms - self.lap_start_time) / 1000.0
            self.times['l1'] = lap_time
            self.lap_start_time = current_time_ms
            self.state = 'L2'
            self.status_label.setText("ESTADO: CORRIENDO (V2 IZQUIERDA)")
            self.track_widget.active_section = 4
            
        elif self.state == 'L2':
            # Trigger 5: Cierra V2 Izq, Finaliza prueba.
            lap_time = (current_time_ms - self.lap_start_time) / 1000.0
            self.times['l2'] = lap_time
            self.state = 'FINISHED'
            self.status_label.setText("ESTADO: FINALIZADO")
            self.status_label.setStyleSheet("font-size: 16px; color: white; background-color: #2979ff; padding: 5px;")
            self.track_widget.active_section = 0
            
            # Calcular tiempo final FS: (Media derecha + Media izquierda)
            # asumiendo las segundas vueltas o usando la fórmula específica del equipo
            total_time = (self.times['r1'] + self.times['r2'] + self.times['l1'] + self.times['l2'])
            self.total_time_lcd.display(f"{total_time:.3f}")
            
        self.update_track_widget()

    def update_track_widget(self):
        self.track_widget.update_times(
            self.times['r1'], self.times['r2'],
            self.times['l1'], self.times['l2'],
            self.track_widget.active_section
        )

    def update_live_ui(self):
        if self.state in ['R1', 'R2', 'L1', 'L2']:
            current_time_ms = self.elapsed_timer.elapsed()
            lap_live = (current_time_ms - self.lap_start_time) / 1000.0
            total_live = current_time_ms / 1000.0
            self.total_time_lcd.display(f"{total_live:.3f}")
            
            # Actualizar la vista previa de la vuelta actual temporalmente
            r1, r2, l1, l2 = self.times['r1'], self.times['r2'], self.times['l1'], self.times['l2']
            if self.state == 'R1': r1 = lap_live
            elif self.state == 'R2': r2 = lap_live
            elif self.state == 'L1': l1 = lap_live
            elif self.state == 'L2': l2 = lap_live
            
            self.track_widget.update_times(r1, r2, l1, l2, self.track_widget.active_section)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.trigger_event()
        else:
            super().keyPressEvent(event)

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    window = SkidpadLaptimerWidget()
    window.resize(800, 600)
    window.show()
    sys.exit(app.exec())
