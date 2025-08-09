# jarvis.py
import os
import time
import json
import threading
import queue
import speech_recognition as sr
import pyttsx3
import openai
import wikipedia
import re
import requests
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ========== CONFIGURATION ==========

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

# -- Text2Num (simple example) --

def text2num(text: str):
    # Simplified text to number conversion
    # For demo: handles zero to ten only, extend as needed
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

# -- Welcome Message Identifier --

def welcome_message():
    return "Hello! I am Jarvis, your personal assistant. How can I help you today?"

# -- Random Search (stub for more advanced later) --

def random_search():
    # placeholder for random knowledge or joke
    return "Did you know that honey never spoils? Archaeologists have found edible honey in ancient tombs."

# -- Main ChatGPT interaction via GPT-4o chat API --

def openai_chat_completion(messages):
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
        return f"Sorry, I couldn't process that due to an error: {str(e)}"

# ========== MAIN LISTEN & RESPOND LOOP ==========

def listen_for_wake_word():
    with microphone as source:
        recognizer.adjust_for_ambient_noise(source, duration=1)
        print(f"Listening for wake word '{WAKE_WORD}'...")
        while True:
            try:
                audio = recognizer.listen(source, phrase_time_limit=4)
                transcription = recognizer.recognize_google(audio).lower()
                print(f"Heard: {transcription}")
                if WAKE_WORD in transcription:
                    return True
            except sr.UnknownValueError:
                pass
            except sr.RequestError:
                speak("Speech recognition service unavailable.")
                time.sleep(5)
            except KeyboardInterrupt:
                print("\nExiting...")
                exit(0)

def listen_for_command():
    with microphone as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
        print("Listening for command...")
        try:
            audio = recognizer.listen(source, phrase_time_limit=8)
            command = recognizer.recognize_google(audio).lower()
            print(f"Command heard: {command}")
            return command
        except sr.UnknownValueError:
            speak("Sorry, I did not catch that.")
            return None
        except sr.RequestError:
            speak("Speech recognition service unavailable.")
            return None

def process_command(command: str):
    if not command:
        return
    # Check for training command: "train: phrase => response"
    train_match = re.match(r"train\s*:\s*(.+?)\s*=>\s*(.+)", command)
    if train_match:
        phrase = train_match.group(1).strip()
        response = train_match.group(2).strip()
        reply = trainer.train(phrase, response)
        speak(reply)
        return

    # Check if trainer has a custom response
    custom_response = trainer.get_response(command)
    if custom_response:
        speak(custom_response)
        return

    # Identify command and run associated function
    func, arg = command_identifier.identify_command(command)
    if func:
        try:
            reply = func(arg)
            speak(reply)
            return
        except Exception as e:
            speak(f"Sorry, I failed to process that command: {str(e)}")
            return

    # If none matched, ask GPT-4o
    messages = [
        {"role": "system", "content": "You are Jarvis, a helpful AI assistant."},
        {"role": "user", "content": command},
    ]
    response = openai_chat_completion(messages)
    speak(response)

def main_loop():
    speak(welcome_message())
    while True:
        if listen_for_wake_word():
            speak("Yes?")
            command = listen_for_command()
            if command:
                process_command(command)
            else:
                speak("Please say your command again.")

if __name__ == "__main__":
    main_loop()
	
	Args:
	after_prompt: bool, whether the response comes directly
	after the user says "Hey, Jarvis!" or not
	
	"""
	# Default is don't start listening, until I tell you to
	start_listening = False

	with microphone as source:

		if after_prompt:
			recognizer.adjust_for_ambient_noise(source)
			print("Say 'Hey, Jarvis!' to start")
			audio = recognizer.listen(source, phrase_time_limit=5)
			try:
				transcription = recognizer.recognize_google(audio)
				if transcription.lower() == "hey jarvis":
					start_listening = True
				else:
					start_listening = False
			except sr.UnknownValueError:
				start_listening = False
		else:
			start_listening = True
		
		if start_listening:
			try:
				print("Listening for question...")
				audio = recognizer.record(source, duration=5)
				transcription = recognizer.recognize_google(audio)
				print(f"Input text: {transcription}")
					
				# Send the transcribed text to the ChatGPT3 API
				response = openai.Completion.create(
				engine="text-davinci-003",
				prompt=transcription,
				temperature=0.9,
				max_tokens=512,
				top_p=1,
				presence_penalty=0.6
				)

				# Get the response text from the ChatGPT3 API
				response_text = response.choices[0].text

				# Print the response from the ChatGPT3 API
				print(f"Response text: {response_text}")

				#  Say the response
				engine.say(response_text)
				engine.runAndWait()
	
			except sr.UnknownValueError:
				print("Unable to transcribe audio")


# pyttsx3 engine paramaters
engine = pyttsx3.init()
engine.setProperty('rate', 150) 
engine.setProperty('voice', 'english_north')

# My OpenAI API Key
openai.api_key = os.environ["API_KEY"]

recognizer = sr.Recognizer()
microphone = sr.Microphone()

# First question
first_question = True

# Initialize last_question_time to current time
last_question_time = time.time()

# Set threshold for time elapsed before requiring "Hey, Jarvis!" again
threshold = 60 # 1 minute

while True:
	if (first_question == True) | (time.time() - last_question_time > threshold):
		listen_and_respond(after_prompt=True)
		first_question = False
	else:
		listen_and_respond(after_prompt=False)