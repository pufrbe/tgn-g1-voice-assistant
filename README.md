## Pasos para generar un API request con micorfono-audio en Gemini

### Crear una Clave API
- Entrar a Google AI Studio
- Crear un nuevo proyecto
- Generate API Key y seleccionar el proyecto
- Una vez generado el API Key copiarlo y setearlo como una variable de entorno:

```bash
export GEMINI_API_KEY={your_api_key}
```

### Integración con micrófono y audio

Instalar dependencias 

```bash
sudo apt install portaudio19-dev
```

Para instalar los paquetes de python necesarios puede instalarse directamente mediante:

```bash
pip install -r requirements.txt
```

Se recomienda crear un virtual environmen (`.gemini_venv` así ya esta trackeado en el `gitignore`) 

Si no, se pueden instalar los siguientes paquetes de manera manual
### Instalar sdk de Gen AI

```bash
pip install -q -U google-genai
```

### Instalar pyaudio

Luego instalar el paquete de python
```bash
pip install pyaudio
```

Para hacer un test del microfono y audio correr el archivo: `mic_test.py`

Para listar los dispositivos de audio usar: `--list` como argumento
En mi caso el mic array es el dispositivo 24 con lo cual, para utilizarlo como input, corro el archivo de la siguiente manera:

```bash
python ./mic_test.py --in-dev 24
```

Y como ouptut usa el default seteado mediante la GUI de configuración del sistema operativo.

## Single query con microfono-audio

Para correr un único prompt que es capturado por micrófno y cuya respuesta se recibe por audio correr el script: `./geimini_one_shot_audio.py`

## Single query Push-To-Talk

Instalar el paquete para reconocer teclas del teclado
```bash
pip install pynput
```

Para correr un único prompt que es capturado por micrófno con la modalidad push-to-talk y cuya respuesta se recibe por audio correr el script: `./geimini_ptt_single_query.py`


## Loop con boton Enter

https://ai.google.dev/gemini-api/docs/live?example=mic-stream

https://ai.google.dev/gemini-api/docs/live?example=mic-stream#example-applications

El script `./gemini_toggle2audio_session.py` utiliza la tecla `ENTER` para empezar a escuchar (no push to talk, toggle) y levanta un contexto que se mantiene activo durante la duración de la ejecución del script (falta agregar un reinicio cada 15 minutos tal como recomienda Google). Se pueden realizar multiples queries en la misma ejecución.

TO-DO:

- [ ] Push to talk
- [ ] Reiniciar sesión cada 15 minutos
- [ ] Deploy a Robot
- [ ] Agregar beeps al script para notificar al usuario

https://deepwiki.com/unitreerobotics/unitree_sdk2/3.4-g1-audio-system

https://deepwiki.com/unitreerobotics/unitree_sdk2/10.5-audio-system-examples

https://deepwiki.com/unitreerobotics/unitree_sdk2_python/7.3-audio-and-media-examples


## Deploy al G1

[nodo de captura de audio](https://github.com/mgonzs13/audio_common/) -> posible utilidad
 
### Idea de flujo micG1-speakerG1

- [este ejemplo](https://deepwiki.com/unitreerobotics/unitree_sdk2/10.5-audio-system-examples) muestra que el stream del mic se envia por UDP `GROUP_IP = "239.168.123.161", PORT = 5555` -> escuchamos este puerto en python y recibimos el input del microfono. (modificamos input dev de el script `gemini_ptt2audio_session.py`)
- pasamos el input a gemini con el script actual
- para el output dev usamos `TtsMaker()` del sdk de unitree [AudioClient](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/g1/audio/g1_audio_client.py)

### Prueba previa 
- conectamos el respeaker mic a la Jetson del G1 y usamos ese input como microfono (así dejamos el desarrollo de la captura del microfno del g1 para mas adelante)
- matenemos el script del la seccion: input-procesamiento
- modificamos output para usar el speaker del g1 directamente con `TtsMaker()` y usando `output_audio_transcription()`
