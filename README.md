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