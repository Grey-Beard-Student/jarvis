"""
Jarvis Home Assistant with Wake Word & Raspberry Pi Button Integration

Features:
- Wake word "Hey Jarvis" detection
- Optional physical button activation (GPIO 17) on Raspberry Pi
- Polished voice prompts for better UX
- Flask dashboard to view logs and send manual commands
- Built-in math, Wikipedia, and web search commands
- OpenAI GPT-4o for fallback conversation

Setup:
1) Install dependencies:
   pip install openai speechrecognition pyttsx3 pyaudio flask wikipedia requests

2) For Raspberry Pi button support, install:
   pip install RPi.GPIO

3) Set environment variable API_KEY with your OpenAI key:
   export API_KEY="your_api_key_here"  (Linux/macOS)
   $env:API_KEY="your_api_key_here"   (Windows PowerShell)

4) Run:
   python jarvis.py

5) Visit dashboard at http://localhost:5000
"""

"""
Jarvis Home Assistant with Wake Word, Button, Flask Dashboard, WebSocket & Family App Backend

Features:
- Wake word ("Hey Jarvis") & Raspberry Pi button activation
- Real-time dashboard using Flask + SocketIO
- Logs commands and responses, pushes to dashboard via WebSocket
- Processes commands: math, wiki, web search, OpenAI GPT-4o fallback
- Manual command input from dashboard
"""

import os
import time
import logging
import re
import threading
import queue

from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit

import speech_recognition as sr
import pyttsx3
import openai
import wikipedia
import requests

# Attempt to import Raspberry Pi GPIO library
try:
    import RPi.GPIO as GPIO
    gpio_available = True
except ImportError:
    gpio_available = False

# ------------- Configuration -----------------
WAKE_WORD = "hey jarvis"
BUTTON_PIN = 17  # GPIO pin for button (BCM numbering)

API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise EnvironmentError("Please set your OpenAI API key in the API_KEY environment variable.")
openai.api_key = API_KEY

# Flask + SocketIO setup
app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecretkey'
socketio = SocketIO(app, cors_allowed_origins="*")

# GPIO setup for button
if gpio_available:
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# ------------- Setup Logging -----------------
logging.basicConfig(
    filename='jarvis.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# --------- Configuration --------------------
WAKE_WORD = "hey jarvis"
API_KEY = os.getenv("API_KEY")

if not API_KEY:
    raise EnvironmentError("Please set your OpenAI API key in the API_KEY environment variable.")

openai.api_key = API_KEY

# --------- Initialize Text-To-Speech Engine ---------
engine = pyttsx3.init()
engine.setProperty('rate', 150)  # Voice speed

# Pick an English voice
voices = engine.getProperty('voices')
for v in voices:
    if "english" in v.name.lower():
        engine.setProperty('voice', v.id)
        break

# --------- Initialize Speech Recognizer -------------
recognizer = sr.Recognizer()
microphone = sr.Microphone()

# ------------- Queue Setup -------------
command_log = queue.Queue(maxsize=100)
response_log = queue.Queue(maxsize=100)
status_message = queue.Queue(maxsize=1)
status_message.put("Idle, waiting for activation...")
manual_commands = queue.Queue()

# ------------- Flask Routes & WebSocket Events -------------
HTML_DASHBOARD = '''
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>Jarvis Home Dashboard</title>
<style>
  body { font-family: Arial, sans-serif; background: #121212; color: #eee; margin: 0; padding: 1rem;}
  h1 { text-align: center; }
  #status { margin-bottom: 1rem; font-weight: bold; }
  #logs { max-height: 300px; overflow-y: auto; border: 1px solid #333; padding: 1rem; background: #222; }
  input[type=text] { width: 80%; padding: 0.5rem; font-size: 1rem; margin-right: 0.5rem; }
  button { padding: 0.5rem 1rem; font-size: 1rem; cursor: pointer; }
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
</head>
<body>
<h1>Jarvis Home Dashboard</h1>
<div id="status">Status: <span id="status_text">{{status}}</span></div>

<form id="manualForm">
  <input type="text" id="manualInput" placeholder="Type command and press Send" autocomplete="off" />
  <button type="submit">Send</button>
</form>

<h2>Command & Response Log</h2>
<div id="logs"></div>

<script>
const socket = io();
const logsDiv = document.getElementById('logs');
const statusText = document.getElementById('status_text');

socket.on('connect', () => {
    addLogEntry('System', 'Connected to Jarvis');
});

socket.on('disconnect', () => {
    addLogEntry('System', 'Disconnected from Jarvis');
});

socket.on('status_update', (data) => {
    statusText.textContent = data.status;
});

socket.on('command_update', (data) => {
    addLogEntry('Command', data.command);
});

socket.on('response_update', (data) => {
    addLogEntry('Response', data.response);
});

function addLogEntry(type, text) {
    const entry = document.createElement('div');
    entry.textContent = `[${type}] ${text}`;
    logsDiv.prepend(entry);
}

document.getElementById('manualForm').onsubmit = async function(e) {
    e.preventDefault();
    const input = document.getElementById('manualInput');
    if (input.value.trim() === '') return;
    
    socket.emit('manual_command', {command: input.value});
    addLogEntry('Manual Input', input.value);
    input.value = '';
};
</script>
</body>
</html>
'''

@app.route('/')
def index():
    status = None
    try:
        status = status_message.queue[0]
    except IndexError:
        status = "Idle"
    return render_template_string(HTML_DASHBOARD, status=status)

@socketio.on('connect')
def handle_connect():
    try:
        status = status_message.queue[0]
    except IndexError:
        status = "Idle"
    emit('status_update', {'status': status})
    
    # Send current logs
    commands = list(command_log.queue)
    responses = list(response_log.queue)
    emit('initial_logs', {
        'commands': commands,
        'responses': responses
    })

@socketio.on('manual_command')
def handle_manual_command(data):
    cmd = data.get('command', '').strip()
    if cmd:
        full_cmd = f"Manual: {cmd}"
        command_log.put(full_cmd)
        manual_commands.put(cmd)
        emit('command_update', {'command': full_cmd}, broadcast=True)
        return {'status': 'Command received'}
    return {'status': 'No command received'}

def run_dashboard():
    """Run the Flask app with SocketIO support"""
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)

def emit_status_update():
    """Emit current status via WebSocket"""
    try:
        status = status_message.queue[0]
    except IndexError:
        status = "Idle"
    socketio.emit('status_update', {'status': status})

# ------------- Helper Functions --------------------

def speak(text: str):
    logging.info(f"Speaking: {text}")
    engine.say(text)
    engine.runAndWait()

# ------------ Command Processing ---------------

def process_command(command: str):
    """Process a user command and return a response."""
    if not command:
        return
    
    # First check for manual command from web dashboard
    try:
        while not manual_commands.empty():
            cmd = manual_commands.get_nowait()
            if cmd:
                command = cmd  # Override voice command with manual command
                break
    except queue.Empty:
        pass

    # Check for training command: "train: phrase => response"
    train_match = re.match(r"train\s*:\s*(.+?)\s*=>\s*(.+)", command)
    if train_match:
        phrase = train_match.group(1).strip()
        response = train_match.group(2).strip()
        reply = trainer.train(phrase, response)
        speak(reply)
        response_log.put(reply)
        return

    # Check if trainer has a custom response
    custom_response = trainer.get_response(command)
    if custom_response:
        speak(custom_response)
        response_log.put(custom_response)
        return

    # Identify command and run associated function
    func, arg = command_identifier.identify_command(command)
    if func:
        try:
            reply = func(arg)
            speak(reply)
            response_log.put(reply)
            return
        except Exception as e:
            error_msg = f"Sorry, I failed to process that command: {str(e)}"
            speak(error_msg)
            response_log.put(error_msg)
            return

    # If none matched, ask OpenAI
    messages = [
        {"role": "system", "content": "You are Jarvis, a helpful AI assistant."},
        {"role": "user", "content": command},
    ]
    response = openai_chat_completion(messages)
    speak(response)
    response_log.put(response)

def openai_chat_completion(messages):
    """Send a request to OpenAI's chat completion API."""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.9,
            max_tokens=512,
            top_p=1,
            presence_penalty=0.6,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"OpenAI API error: {e}")
        return "Sorry, I am having trouble reaching the AI service right now."

# --- Commands implementations ---

class MathExpressionCalculator:
    @staticmethod
    def calculate(expression: str):
        try:
            if re.search(r"[a-zA-Z]", expression):
                return "Invalid characters in expression."
            result = eval(expression, {"__builtins__": {}}, {})
            return f"The answer is {result}."
        except Exception as e:
            return f"Could not calculate expression. {str(e)}"

def wiki_search(query: str):
    try:
        wikipedia.set_lang("en")
        return wikipedia.summary(query, sentences=2)
    except Exception:
        return "I couldn't find anything on Wikipedia for that."

def random_web_search(query: str):
    url = f"https://api.duckduckgo.com/?q={query}&format=json&no_redirect=1&skip_disambig=1"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        abstract = data.get("AbstractText", "")
        return abstract if abstract else "No instant answer found online."
    except Exception:
        return "I couldn't perform a web search right now."

class CommandIdentifier:
    def __init__(self):
        self.commands = {
            "calculate": MathExpressionCalculator.calculate,
            "what is": wiki_search,
            "who is": wiki_search,
            "search": random_web_search,
        }
    def identify_command(self, text):
        text = text.lower()
        for cmd in self.commands:
            if text.startswith(cmd):
                arg = text[len(cmd):].strip()
                return self.commands[cmd], arg
        return None, None

class Trainer:
    def __init__(self):
        self.custom_phrases = {}
    def train(self, phrase, response):
        self.custom_phrases[phrase.lower()] = response
        return "Training saved."
    def get_response(self, phrase):
        return self.custom_phrases.get(phrase.lower())

trainer = Trainer()
command_identifier = CommandIdentifier()

# ------------- Core Functions ---------------

def speak(text: str):
    """Say text using text-to-speech."""
    logging.info(f"Speaking: {text}")
    engine.say(text)
    engine.runAndWait()

def wait_for_button_press(timeout=None):
    """Wait for button press with optional timeout."""
    if not gpio_available:
        return False
    
    logging.debug("Waiting for button press...")
    start = time.time()
    while True:
        if GPIO.input(BUTTON_PIN) == GPIO.LOW:  # Button pressed
            logging.info("Button pressed!")
            time.sleep(0.1)  # Debounce
            return True
        if timeout and (time.time() - start) > timeout:
            return False
        time.sleep(0.05)  # Reduce CPU usage

def transcribe_audio(source, timeout=5, phrase_time_limit=5):
    """Convert speech to text."""
    try:
        audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        text = recognizer.recognize_google(audio)
        logging.info(f"Transcribed text: {text}")
        return text.lower().strip()
    except sr.WaitTimeoutError:
        logging.warning("Listening timed out.")
        return None
    except sr.UnknownValueError:
        logging.warning("Speech not understood.")
        return None
    except sr.RequestError as e:
        logging.error(f"Speech recognition error: {e}")
        speak("Speech recognition service is unavailable.")
        return None

def listen_for_wake_word(timeout=5):
    """Listen for wake word with timeout."""
    with microphone as source:
        recognizer.adjust_for_ambient_noise(source, duration=1)
        logging.info(f"Listening for wake word '{WAKE_WORD}'...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                audio = recognizer.listen(source, phrase_time_limit=3)
                transcription = recognizer.recognize_google(audio).lower()
                logging.info(f"Heard: {transcription}")
                if WAKE_WORD in transcription:
                    return True
            except sr.UnknownValueError:
                pass
            except sr.RequestError:
                speak("Speech recognition service unavailable.")
                time.sleep(5)
                return False
            except KeyboardInterrupt:
                speak("Shutting down. Goodbye.")
                if gpio_available:
                    GPIO.cleanup()
                exit(0)
        return False

def listen_for_command():
    """Listen for and transcribe a command."""
    with microphone as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
        status_message.queue.clear()
        status_message.put("Active - Listening for command...")
        emit_status_update()
        
        speak("Go ahead, I'm listening.")
        try:
            audio = recognizer.listen(source, phrase_time_limit=8)
            command = recognizer.recognize_google(audio).lower()
            logging.info(f"Command received: {command}")
            command_log.put(command)
            socketio.emit('command_update', {'command': command})
            return command
        except sr.UnknownValueError:
            speak("Sorry, I didn't catch that. Could you please repeat?")
            return None
        except sr.RequestError:
            speak("Speech recognition service is unavailable.")
            return None
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.9,
            max_tokens=512,
            top_p=1,
            presence_penalty=0.6,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"OpenAI API error: {e}")
        return "Sorry, I am having trouble reaching the AI service right now."

def listen_for_wake_word():
    with microphone as source:
        recognizer.adjust_for_ambient_noise(source, duration=1)
        speak(f"Say '{WAKE_WORD}' to activate me.")
        logging.info(f"Waiting for wake word '{WAKE_WORD}'...")
        while True:
            try:
                audio = recognizer.listen(source, phrase_time_limit=4)
                transcription = recognizer.recognize_google(audio).lower()
                logging.info(f"Heard: {transcription}")
                if WAKE_WORD in transcription:
                    speak("Yes?")
                    return True
            except sr.UnknownValueError:
                pass
            except sr.RequestError:
                speak("Speech recognition service unavailable.")
                time.sleep(5)
            except KeyboardInterrupt:
                speak("Shutting down. Goodbye.")
                exit(0)

def listen_for_command():
    with microphone as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
        print("Listening for your command. Press Enter when ready to speak...")
        input()  # Simulate push-to-talk by requiring Enter key
        try:
            audio = recognizer.listen(source, phrase_time_limit=8)
            command = recognizer.recognize_google(audio).lower()
            logging.info(f"Command received: {command}")
            print(f"You said: {command}")
            return command
        except sr.UnknownValueError:
            speak("Sorry, I did not catch that. Please try again.")
            return None
        except sr.RequestError:
            speak("Speech recognition service unavailable.")
            return None

def process_command(command: str):
    if not command:
        return
    # Training
    train_match = re.match(r"train\s*:\s*(.+?)\s*=>\s*(.+)", command)
    if train_match:
        phrase = train_match.group(1).strip()
        response = train_match.group(2).strip()
        reply = trainer.train(phrase, response)
        speak(reply)
        return
    # Custom phrase
    custom_response = trainer.get_response(command)
    if custom_response:
        speak(custom_response)
        return
    # Known commands
    func, arg = command_identifier.identify_command(command)
    if func:
        try:
            reply = func(arg)
            speak(reply)
            return
        except Exception as e:
            speak(f"Sorry, I couldn't process that command: {str(e)}")
            logging.error(f"Command processing error: {e}")
            return
    # Fallback to GPT-4o
    messages = [
        {"role": "system", "content": "You are Jarvis, a helpful AI assistant."},
        {"role": "user", "content": command},
    ]
    response = openai_chat_completion(messages)
    speak(response)

def main_loop():
    speak("Jarvis starting up. Say 'Hey Jarvis' when you need me.")
    while True:
        if listen_for_wake_word():
            for _ in range(3):  # allow up to 3 attempts to get command
                command = listen_for_command()
                if command:
                    process_command(command)
                    break
                else:
                    speak("Let's try again.")
            else:
                speak("I am going back to sleep. Say 'Hey Jarvis' when you need me.")

if __name__ == "__main__":
    main_loop()

WAKE_WORD = "hey jarvis"
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise EnvironmentError("Please set your OpenAI API key in the API_KEY environment variable.")

openai.api_key = API_KEY

# ========== SPEECH ENGINE SETUP ==========

engine = pyttsx3.init()
engine.setProperty('rate', 150)
# Optional: Set your preferred voice here if you want (comment if issues)
voices = engine.getProperty('voices')
for v in voices:
    if "english" in v.name.lower():
        engine.setProperty('voice', v.id)
        break

recognizer = sr.Recognizer()
microphone = sr.Microphone()

# ========== UTILITY FUNCTIONS ==========

def speak(text: str):
    engine.say(text)
    engine.runAndWait()

def transcribe_audio(source, timeout=5, phrase_time_limit=5):
    """Listen from source and transcribe to text."""
    try:
        audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        text = recognizer.recognize_google(audio)
        return text.lower().strip()
    except sr.WaitTimeoutError:
        return None
    except sr.UnknownValueError:
        return None
    except sr.RequestError:
        speak("Speech recognition service is unavailable.")
        return None

# ========== FEATURE MODULES ==========

# -- Math Expression Calculator --

class MathExpressionCalculator:
    @staticmethod
    def calculate(expression: str):
        try:
            # Basic security check
            if re.search(r"[a-zA-Z]", expression):
                return "Invalid characters in expression."
            # Evaluate safely
            result = eval(expression, {"__builtins__": {}}, {})
            return f"The answer is {result}."
        except Exception as e:
            return f"Could not calculate expression. {str(e)}"

# -- Wikipedia Search --

def wiki_search(query: str):
    try:
        wikipedia.set_lang("en")
        summary = wikipedia.summary(query, sentences=2)
        return summary
    except Exception:
        return "I couldn't find anything on Wikipedia for that."

# -- Random Web Search (Simple Google Search Snippet) --

def random_web_search(query: str):
    # NOTE: This uses DuckDuckGo's Instant Answer API (free)
    url = f"https://api.duckduckgo.com/?q={query}&format=json&no_redirect=1&skip_disambig=1"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        abstract = data.get("AbstractText", "")
        if abstract:
            return abstract
        else:
            return "No instant answer found online."
    except Exception:
        return "I couldn't perform a web search right now."

# -- Command Identifier and Trainer --

class CommandIdentifier:
    def __init__(self):
        # example commands and their mapped functions
        self.commands = {
            "calculate": MathExpressionCalculator.calculate,
            "what is": wiki_search,
            "who is": wiki_search,
            "search": random_web_search,
            # add more mappings here
        }
    
    def identify_command(self, text):
        text = text.lower()
        for cmd in self.commands:
            if text.startswith(cmd):
                # Return function and remainder text
                arg = text[len(cmd):].strip()
                return self.commands[cmd], arg
        return None, None

class Trainer:
    def __init__(self):
        self.custom_phrases = {}  # phrase:str -> response:str
    
    def train(self, phrase, response):
        self.custom_phrases[phrase.lower()] = response
        return "Training saved."
    
    def get_response(self, phrase):
        phrase = phrase.lower()
        return self.custom_phrases.get(phrase, None)

trainer = Trainer()
command_identifier = CommandIdentifier()


	
# ------------- Command Utilities ---------------

def text2num(text: str):
    """Convert text numbers to digits."""
    numbers = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven":7, "eight": 8, "nine": 9, "ten": 10
    }
    words = text.lower().split()
    result = []
    for w in words:
        if w in numbers:
            result.append(str(numbers[w]))
        else:
            result.append(w)
    return " ".join(result)

def emit_updates(command=None, response=None, status=None):
    """Emit updates via WebSocket."""
    if command:
        socketio.emit('command_update', {'command': command})
    if response:
        socketio.emit('response_update', {'response': response})
    if status:
        status_message.queue.clear()
        status_message.put(status)
        socketio.emit('status_update', {'status': status})

# ------------- Main Program Loop ---------------

def background_status_update():
    """Background thread to periodically emit status updates"""
    while True:
        emit_status_update()
        time.sleep(2)

def run_voice_assistant():
    """Run the main voice assistant loop."""
    speak("Hello! I am Jarvis, your personal assistant.")
    status_message.queue.clear()
    status_message.put("Idle - Waiting for wake word or button press...")
    emit_status_update()

    while True:
        try:
            # Check for manual commands first
            if not manual_commands.empty():
                cmd = manual_commands.get()
                status_message.queue.clear()
                status_message.put(f"Processing manual command: {cmd}")
                emit_status_update()
                process_command(cmd)
                continue

            # Check for button press (with short timeout)
            if gpio_available:
                button_pressed = wait_for_button_press(timeout=0.1)
                if button_pressed:
                    status_message.queue.clear()
                    status_message.put("Button pressed - Listening for command")
                    emit_status_update()
                    speak("Button detected. What can I help you with?")
                    command = listen_for_command()
                    if command:
                        process_command(command)
                    continue

            # Check for wake word
            status_message.queue.clear()
            status_message.put("Listening for wake word...")
            emit_status_update()

            if listen_for_wake_word(timeout=1):
                status_message.queue.clear()
                status_message.put("Wake word detected - Listening for command")
                emit_status_update()
                speak("Yes, I'm listening.")
                command = listen_for_command()
                if command:
                    process_command(command)
                else:
                    speak("I didn't catch that. Please try again.")

            # Reset status after processing
            status_message.queue.clear()
            status_message.put("Idle - Waiting for wake word or button press...")
            emit_status_update()

        except KeyboardInterrupt:
            print("\nShutting down gracefully...")
            speak("Shutting down. Goodbye!")
            if gpio_available:
                GPIO.cleanup()
            break
        except Exception as e:
            logging.error(f"Error in main loop: {str(e)}")
            status_message.queue.clear()
            status_message.put(f"Error: {str(e)}")
            emit_status_update()
            time.sleep(5)  # Prevent rapid error loops

def main():
    """Initialize and start all components."""
    # Start background status update thread
    status_thread = threading.Thread(target=background_status_update, daemon=True)
    status_thread.start()
    
    # Start the Flask+SocketIO server in the main thread
    try:
        socketio.run(app, host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        print("\nShutting down...")
        if gpio_available:
            GPIO.cleanup()
        exit(0)

if __name__ == "__main__":
    main()