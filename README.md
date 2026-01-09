# Chatbot de Gemini para robot Unitree G1 EDU

TO-DO:
- [ ] Crear Clases para cada etapa del flujo del script.
- [ ] Modificar el Dockerfile para que se corra directamente el script del chatbot
- [ ] Implementar un push-to-talk con un botón del joystick. 
- [ ] Sacar el clonado de este repositorio del Dockerfile y copiar directamente los archivos `./gemini_chatbot_g1.py` y `./requirements.txt` al directorio `packages`.
- [ ] Verificar si es necesario hablarle una primera vez con `Hello robot` para que publique el audio.
- [ ] Verificar si hay que agregarse al grupo multicast manualmente para probar la recepción con `tcpdump`.
- [ ] Actualizar `requirements.txt` para que tenga las versiones de los paquetes que sabemos que funcionan en el robot.

Este asistente de voz usa el micóofono interno del G1 para capturar audio, la API de Gemini como backend para procesar el audio recibido, y el servicio de Audio desarrollado en el SDK de Unitree para controlar el parlante del robot.

## Prerequisitos
### Crear una Clave API
- Entrar a Google AI Studio
- Crear un nuevo proyecto
- Generate API Key y seleccionar el proyecto
- Una vez generado el API Key copiarlo y setearlo como una variable de entorno:

```bash
cd ~
echo export GEMINI_API_KEY="{YOUR_KEY}" >> .bashrc
```

### Poner el robot en modo "wake up"
La PC1 del robot publica el stream del microfono en el puerto udp `5555` con la dirección `239.168.123.161`. Para que iniciar el servicio, se debe poner al robot en el modo `wake up` presionando los botones  `L1+L2` en el control remoto del robot (este comando cicla entre los modos `wake up conversation mode` y `push button conversation mode`). Una vez que el robot se encuentra en `wake up` mode, se debe decir la palabra clave `HELLO ROBOT`. Así el robot ya esta configurado correctamente y debería publicar el stream del micrófono. Para verificar esto, se puede correr el siguiente comando en la PC2.

<!-- chequear este comando -->
```bash
tcpdump -ni eth0 host 239.168.123.161 and udp port 5555
``` 
Si se reciben paquetes, la configuración fue exitosa.

## Ejecutar el script del chatbot
Para correr el script `./gemini_chatbot_g1.py` se tiene un container de Docker, que se puede buildear de la siguiente manera:

```bash
docker build -t gemini-chatbot .
```

Esto crea una imagen de docker según el archivo `Dockerfile` con el nombre `gemini-chatbot`.

Para ejecutar un container con esta imagen se debe correr el siguiente comando
<!-- chequear este comando -->
```bash
docker run --rm -it --privileged --network=host -v /dev:/dev -e GEMINI_API_KEY=$GEMINI_API_KEY -t gemini-chatbot-service gemini-chatbot
```

Una vez dentro del container, ejecutar el script como: `python3 gemini_chatbot_g1.py`

Actualmente, el script considera que se tiene un teclado a la PC2 y utiliza la tecla `Enter` (toggle, no push-to-talk) para escuchar al usuario. 
