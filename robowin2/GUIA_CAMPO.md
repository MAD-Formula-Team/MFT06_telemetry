# ROBOWIN 2 — Guía de campo

## Antes de salir al circuito

- [ ] Copia `ROBOWIN2.exe` (Windows) o `ROBOWIN2` (Linux) al portátil de pista.
      No necesita Python ni instalación.
- [ ] Linux (solo la primera vez): `sudo usermod -aG dialout $USER` y volver a
      iniciar sesión. Windows: sin drivers (USB nativo) — si el receptor usa
      CP210x y no aparece, instalar el driver de Silicon Labs.
- [ ] Prueba rápida sin coche: arranca la app y abre un log antiguo con
      ABRIR LOG para comprobar que todo pinta bien.
- [ ] Si el DBC ha cambiado: deja el `mft06.dbc` nuevo JUNTO al ejecutable
      (tiene prioridad sobre el embebido, no hace falta recompilar).

## En pista

1. Conecta el receptor por USB **antes** de abrir la app (o usa ⟳ después).
2. Elige el puerto en el desplegable: el receptor aparece **primero**, con el
   nombre del chip ("Espressif (USB nativo)" / "CP210x"). Los puertos
   Bluetooth salen los últimos: ignóralos.
3. Pulsa **CONECTAR**. El chip de estado pasa a verde al recibir el primer
   frame; la página **BUS CAN** muestra en vivo qué IDs llegan y a qué
   frecuencia (si un ID sale como DESCONOCIDO en naranja, no está en el DBC).
4. **El log crudo se graba solo** desde que conectas, en:
   - Windows: `%LOCALAPPDATA%\ROBOWIN2\robowin_AAAAMMDD.db`
   - Linux: `~/.local/share/ROBOWIN2/robowin_AAAAMMDD.db`
   No hay botón de guardar: no se puede olvidar.
5. Cronometraje: página **LAP TIMER** → modo + nombre → **INICIAR**. El
   skidpad se cierra solo a las 4 vueltas con la nota FS. Las sesiones y
   vueltas quedan en el mismo .db.

## Después

- Página **OFFLINE** → ABRIR .DB para revisar la jornada: clic en una vuelta
  para enfocar la telemetría de esa vuelta en todas las gráficas.
- EXPORTAR CSV genera el formato clásico (compatible con ROBOWIN 1 y Excel).
- Copia el .db del día a un pendrive como respaldo: es UN solo archivo.

## Problemas típicos

| Síntoma | Causa probable | Solución |
|---|---|---|
| El receptor no aparece en el desplegable | Driver ausente (CP210x) o cable solo de carga | Device Manager / `dmesg`; cambiar cable |
| Aparece pero el chip no pasa a verde | El coche no transmite o antena LoRa | Comprobar TX del coche; BUS CAN debe mostrar tráfico |
| "Permission denied" en Linux | Usuario sin grupo dialout | `sudo usermod -aG dialout $USER` + relogin |
| Puerto ocupado | Otro programa (monitor serie, ROBOWIN 1) lo tiene abierto | Cerrar el otro programa |
| Vueltas dobles | Firmware laptimer antiguo sin lockout | Reflashear `laptimer_tx`; el filtro de la app (>3 s) protege igualmente |
