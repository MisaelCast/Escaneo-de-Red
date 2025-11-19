import nmap
import json
import os
import time
from flask import Flask, render_template_string, request, redirect, url_for


# --- CONFIGURACIÓN GLOBAL ---

# CONFIGURACIÓN DE ARCHIVOS Y ESTADO
CONFIG_FILE = 'config_redes.txt'
STATE_FILE = 'estado_red.json'
MAX_INACTIVE_CYCLES = 2  # Ciclos para eliminar IPs (Gris -> Desaparecer)

# 1. INICIALIZACIÓN DE FLASK
app = Flask(__name__)

# 2. INICIALIZACIÓN DE NMAP
try:
    nm = nmap.PortScanner()
except nmap.nmap.PortScannerError as e:
    print("Error Crítico: No se pudo inicializar PortScanner.")
    print("Asegúrate de que 'nmap' esté instalado y el script se ejecute con 'sudo'.")
    exit()


# 3. FUNCIONES DE LÓGICA Y MANEJO DE ARCHIVOS

def load_config():
    """Carga las redes a escanear desde config_redes.txt."""
    if not os.path.exists(CONFIG_FILE):
        return ["192.168.1.0/24"]
    with open(CONFIG_FILE, 'r') as f:
        redes = [line.strip() for line in f if line.strip()]
    return redes if redes else ["192.168.1.0/24"]

def load_state():
    """Carga el estado anterior de la red desde estado_red.json."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print("Error al leer el archivo JSON. Se inicializará vacío.")
        return {}

def save_state(state):
    """Guarda el estado actual en estado_red.json."""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)

def run_scan_logic():
    """Ejecuta el escaneo de Nmap y aplica la lógica de estado."""
    
    redes = load_config()
    current_state = load_state()
    
    print(f"--- Escaneando redes: {redes} ---")
    
    # 1. Ejecutar el escaneo con argumentos mejorados para MAC y Hostname
    activas_ahora = {} 
    
    # Argumentos optimizados para Linux: -sn (Host Discovery) -R (Hostname) -T4 (Velocidad)
    nm.scan(hosts=' '.join(redes), arguments='-sn -R -T4')

    # Recorrer los hosts que respondieron
    for host in nm.all_hosts():
        if nm[host].state() == 'up': 
            
            # --- Extracción de MAC ---
            mac = nm[host]['addresses'].get('mac', 'N/A')
            
            # --- Extracción de Hostname (Lógica de Búsqueda Robusta) ---
            # Si la IP ya tiene un Hostname manual guardado, lo respetamos.
            if host in current_state and 'Hostname_Manual' in current_state[host]:
                 hostname = current_state[host]['Hostname_Manual']
            else:
                hostname = 'N/A'
                hostnames_list = nm[host].get('hostnames', [])

                # Opción 1: Intentar el nombre de host principal
                if hostnames_list:
                    hostname = hostnames_list[0].get('name', 'N/A')
                
                # Opción 2: Si el nombre sigue siendo pobre, buscar el nombre PTR (DNS inverso)
                if hostname == 'N/A' or hostname == '' or hostname.startswith('localhost'):
                    for h in hostnames_list:
                        if h.get('type') == 'ptr' and h.get('name'):
                            hostname = h.get('name')
                            break
            
            activas_ahora[host] = {'MAC': mac, 'Hostname': hostname}

    # 2. Aplicar Lógica de Estado (Verde, Gris, Eliminar)
    
    ips_to_delete = []

    for ip, data in list(current_state.items()):
        if ip in activas_ahora:
            # Caso 1: ¡Activo! (Verde) - Actualiza datos por si cambiaron
            data['Estado'] = 'Activo'
            data['Ciclos_Inactivo'] = 0
            data['MAC'] = activas_ahora[ip]['MAC'] 
            # Mantenemos el Hostname_Manual si existe, sino, usamos el nombre de Nmap
            if 'Hostname_Manual' not in data:
                 data['Hostname'] = activas_ahora[ip]['Hostname']
            else:
                # Si hay manual, lo mantenemos como Hostname principal para la tabla.
                 data['Hostname'] = data['Hostname_Manual'] 
            
            del activas_ahora[ip] 
        else:
            # Caso 2: ¡No responde! (Gris o Eliminación)
            data['Ciclos_Inactivo'] += 1
            data['Estado'] = 'Inactivo' # Color Gris
            if data['Ciclos_Inactivo'] >= MAX_INACTIVE_CYCLES:
                ips_to_delete.append(ip)

    # Procesar eliminaciones
    for ip in ips_to_delete:
        print(f"Eliminando IP inactiva: {ip}")
        del current_state[ip]

    # 3. Agregar IPs completamente Nuevas
    for ip, data in activas_ahora.items():
        print(f"Nueva IP detectada: {ip}")
        current_state[ip] = {
            'MAC': data['MAC'],
            'Hostname': data['Hostname'],
            'Estado': 'Activo',
            'Ciclos_Inactivo': 0
        }
        
    save_state(current_state)
    return current_state


# ********** ¡IMPORTANTE! Hemos quitado la llamada a run_scan_logic() aquí. **********


# --- 4. RUTAS DE FLASK Y TEMPLATE HTML ---

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Monitoreo de Red Básico</title>
    <style>
        body { font-family: sans-serif; margin: 20px; }
        h1 { color: #333; }
        .activo { color: green; font-weight: bold; }
        .inactivo { color: gray; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #f2f2f2; }
        .editable {
            cursor: pointer;
            border-bottom: 2px dashed #007bff; /* Indicador visual de edición */
        }
        .scan-btn { 
            padding: 10px 15px; 
            background-color: #dc3545; /* Rojo para Scan */
            color: white; 
            border: none; 
            cursor: pointer; 
            margin-bottom: 20px;
        }
    </style>
</head>
<body>
    <h1>Monitoreo de Red Activa</h1>
    
    <form method="POST" action="/scan">
        <button type="submit" class="scan-btn">Escanear Red Ahora</button>
    </form>
    
    <h2>Resultado del Último Escaneo</h2>
    <table>
        <tr>
            <th>IP</th>
            <th>Hostname</th>
            <th>MAC</th>
            <th>Estado</th>
        </tr>
        {% for ip, data in dispositivos.items() %}
        <tr class="{% if data.Estado == 'Activo' %}activo{% else %}inactivo{% endif %}">
            <td>{{ ip }}</td>
            <td 
                class="editable" 
                contenteditable="true" 
                data-ip="{{ ip }}"
                onkeydown="if(event.key === 'Enter') { updateHostname(this); event.preventDefault(); return false; }"
                onblur="updateHostname(this)">
                {{ data.Hostname }}
            </td>
            <td>{{ data.MAC }}</td>
            <td>{{ data.Estado }} (Ciclos fallidos: {{ data.Ciclos_Inactivo }})</td>
        </tr>
        {% endfor %}
    </table>
    
    <script>
        function updateHostname(element) {
            const ip = element.getAttribute('data-ip');
            const newHostname = element.textContent.trim();
            
            // Usamos Fetch API para enviar los datos a Flask sin recargar la página inmediatamente
            fetch('/update_hostname', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `ip=${ip}&hostname=${encodeURIComponent(newHostname)}`
            })
            .then(response => {
                // Si la actualización fue exitosa, simplemente recargamos para ver el cambio guardado
                if (response.ok) {
                    window.location.reload(); 
                } else {
                    alert('Error al guardar el nombre.');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('Fallo de conexión al servidor.');
            });
        }
    </script>
</body>
</html>
"""

# --- RUTAS DE FLASK ---

@app.route('/')
def index():
    # ********** ¡IMPORTANTE! Solo lee el estado, no escanea. **********
    dispositivos = load_state()
    config = load_config()
    return render_template_string(HTML_TEMPLATE, dispositivos=dispositivos, current_config=config)

# NUEVA RUTA: Inicia el escaneo de Nmap manualmente
@app.route('/scan', methods=['POST'])
def scan_route():
    run_scan_logic() # Ejecuta el escaneo completo
    return redirect(url_for('index'))

@app.route('/update_hostname', methods=['POST'])
def update_hostname_route():
    ip = request.form.get('ip')
    new_hostname = request.form.get('hostname')
    
    if ip and new_hostname:
        state = load_state()
        if ip in state:
            # Guardamos el nombre manual en la nueva clave Hostname_Manual
            state[ip]['Hostname_Manual'] = new_hostname
            state[ip]['Hostname'] = new_hostname # Sobrescribe el Hostname para mostrar el cambio al momento
            save_state(state)
            return "Hostname actualizado", 200
        return "IP no encontrada", 404
    return "Datos inválidos", 400

@app.route('/configurar', methods=['POST'])
def configurar():
    redes_raw = request.form['redes']
    redes_list = [line.strip() for line in redes_raw.splitlines() if line.strip()]

    with open(CONFIG_FILE, 'w') as f:
        f.write('\n'.join(redes_list))

    return redirect(url_for('index'))

# 5. INICIO DEL SERVIDOR
if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0')
