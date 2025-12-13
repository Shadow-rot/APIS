"""
Advanced AI Chatbot for Telegram with Human-like Conversations
Features: Multi-language, Voice Messages, Stickers, GIFs, User Data Learning
"""

import asyncio
import random
import re
from datetime import datetime
from typing import Dict, List, Optional
import json
from collections import defaultdict

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatAction
import google.generativeai as genai
from gtts import gTTS
import os

# Configuration
class ChatbotConfig:
    # Get free Gemini API key from https://makersuite.google.com/app/apikey
    GEMINI_API_KEY = "AIzaSyAT_aXQqEDrySmB6V0Y-sEqBnKCxWHymrQ"
    
    # Voice settings
    VOICE_LANGUAGE = "hi"  # Hindi voice (Indian)
    VOICE_ACCENT = "co.in"  # Indian accent
    
    # Response settings
    MAX_HISTORY = 50
    TYPING_DELAY = 2  # seconds
    
    # Personality
    BOT_PERSONALITY = """You are a friendly, warm Indian chatbot assistant. 
    You speak naturally like a real person from India, mixing English and Hinglish when appropriate.
    You're helpful, witty, and use casual language. You remember context and user details.
    You can be funny, use emojis naturally, and relate to Indian culture.
    When users share personal info, you remember it for future conversations."""

# User data storage
class UserDatabase:
    def __init__(self):
        self.users_data: Dict[int, Dict] = defaultdict(lambda: {
            "name": "",
            "first_seen": None,
            "last_seen": None,
            "message_count": 0,
            "preferences": {},
            "conversation_history": [],
            "facts": []  # Personal facts learned about user
        })
        self.load_data()
    
    def load_data(self):
        try:
            with open("user_database.json", "r") as f:
                data = json.load(f)
                self.users_data.update(data)
        except FileNotFoundError:
            pass
    
    def save_data(self):
        with open("user_database.json", "w") as f:
            json.dump(dict(self.users_data), f, indent=2, default=str)
    
    def update_user(self, user_id: int, message: Message):
        user = self.users_data[user_id]
        
        if not user["first_seen"]:
            user["first_seen"] = datetime.now()
        
        user["last_seen"] = datetime.now()
        user["message_count"] += 1
        user["name"] = message.from_user.first_name or "Friend"
        
        # Add to conversation history
        if len(user["conversation_history"]) > ChatbotConfig.MAX_HISTORY:
            user["conversation_history"].pop(0)
        
        user["conversation_history"].append({
            "text": message.text or "[media]",
            "timestamp": datetime.now(),
            "type": "user"
        })
        
        self.save_data()
    
    def add_bot_response(self, user_id: int, response: str):
        user = self.users_data[user_id]
        user["conversation_history"].append({
            "text": response,
            "timestamp": datetime.now(),
            "type": "bot"
        })
        self.save_data()
    
    def add_user_fact(self, user_id: int, fact: str):
        user = self.users_data[user_id]
        if fact not in user["facts"]:
            user["facts"].append(fact)
            self.save_data()
    
    def get_user_context(self, user_id: int) -> str:
        user = self.users_data[user_id]
        context = f"User's name: {user['name']}\n"
        
        if user["message_count"] > 1:
            context += f"You've chatted {user['message_count']} times before.\n"
        
        if user["facts"]:
            context += f"What you know about them: {', '.join(user['facts'])}\n"
        
        # Recent conversation context
        recent = user["conversation_history"][-10:]
        if recent:
            context += "\nRecent conversation:\n"
            for msg in recent:
                role = "User" if msg["type"] == "user" else "You"
                context += f"{role}: {msg['text']}\n"
        
        return context

# AI Response Generator
class AIBrain:
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-pro')
        self.chat_sessions = {}
    
    async def generate_response(self, user_id: int, message: str, context: str) -> str:
        try:
            # Create system prompt with personality and context
            full_prompt = f"""{ChatbotConfig.BOT_PERSONALITY}

{context}

User's message: {message}

Respond naturally and warmly. Use the user's name occasionally. Be conversational."""

            response = await asyncio.to_thread(
                self.model.generate_content,
                full_prompt
            )
            
            return response.text
        except Exception as e:
            print(f"AI Error: {e}")
            return self._get_fallback_response()
    
    def _get_fallback_response(self) -> str:
        responses = [
            "Haha, sorry yaar! My brain just went blank for a sec. Say that again? 😅",
            "Oops! Can you repeat that? I got distracted 😊",
            "Wait wait, my connection glitched. What were you saying?",
            "Arre! Technical issues. Tell me again na? 🙏"
        ]
        return random.choice(responses)
    
    def extract_user_facts(self, message: str) -> List[str]:
        """Extract personal information from user messages"""
        facts = []
        
        # Pattern matching for common facts
        patterns = {
            r"my name is (\w+)": "name is {}",
            r"i am (\d+) years old": "is {} years old",
            r"i live in ([\w\s]+)": "lives in {}",
            r"i work (?:as a |as an )?(\w+)": "works as {}",
            r"i like (\w+)": "likes {}",
            r"my (?:favorite|favourite) ([\w\s]+) is ([\w\s]+)": "favorite {} is {}"
        }
        
        for pattern, template in patterns.items():
            match = re.search(pattern, message.lower())
            if match:
                facts.append(template.format(*match.groups()))
        
        return facts

# Sticker and GIF Manager
class MediaManager:
    # Popular sticker sets
    STICKER_RESPONSES = {
        "happy": ["CAACAgIAAxkBAAEBCQ5lK", "CAACAgQAAxkBAAEBCQ"],  # Happy stickers
        "sad": ["CAACAgIAAxkBAAEBCRBlK", "CAACAgQAAxkBAAEBCR"],    # Sad stickers
        "laugh": ["CAACAgIAAxkBAAEBCRJlK", "CAACAgQAAxkBAAEBCS"],  # Laughing
        "love": ["CAACAgIAAxkBAAEBCRNlK", "CAACAgQAAxkBAAEBCT"],   # Love/Heart
        "thumbsup": ["CAACAgIAAxkBAAEBCRRlK"],                      # Thumbs up
        "celebrate": ["CAACAgIAAxkBAAEBCRVlK"],                     # Party/Celebration
        "thinking": ["CAACAgIAAxkBAAEBCRZlK"],                      # Thinking
    }
    
    # GIF animations (using animation file IDs or URLs)
    GIF_RESPONSES = {
        "excited": ["https://media.giphy.com/media/excited"],
        "dancing": ["https://media.giphy.com/media/dancing"],
        "waving": ["https://media.giphy.com/media/waving"],
    }
    
    @staticmethod
    def should_send_media(message: str) -> Optional[str]:
        """Determine if message warrants a sticker/GIF response"""
        message = message.lower()
        
        if any(word in message for word in ["haha", "lol", "😂", "funny", "hilarious"]):
            return "laugh"
        elif any(word in message for word in ["sad", "😢", "upset", "crying"]):
            return "sad"
        elif any(word in message for word in ["love", "❤️", "amazing", "awesome"]):
            return "love"
        elif any(word in message for word in ["thanks", "thank you", "great", "perfect"]):
            return "thumbsup"
        elif any(word in message for word in ["yay", "woohoo", "congratulations", "party"]):
            return "celebrate"
        
        return None
    
    @staticmethod
    def get_random_sticker(emotion: str) -> Optional[str]:
        if emotion in MediaManager.STICKER_RESPONSES:
            return random.choice(MediaManager.STICKER_RESPONSES[emotion])
        return None

# Voice Message Generator
class VoiceGenerator:
    @staticmethod
    async def create_voice_message(text: str, user_id: int) -> str:
        """Generate voice message in Indian accent"""
        try:
            # Clean text for speech
            clean_text = re.sub(r'[*_`~]', '', text)
            clean_text = re.sub(r'https?://\S+', '', clean_text)
            
            # Generate voice file
            filename = f"voice_{user_id}_{datetime.now().timestamp()}.mp3"
            
            tts = gTTS(
                text=clean_text,
                lang=ChatbotConfig.VOICE_LANGUAGE,
                tld=ChatbotConfig.VOICE_ACCENT,
                slow=False
            )
            
            await asyncio.to_thread(tts.save, filename)
            return filename
        except Exception as e:
            print(f"Voice generation error: {e}")
            return None

# Main Chatbot Handler
class AdvancedChatbot:
    def __init__(self, app: Client):
        self.app = app
        self.db = UserDatabase()
        self.ai = AIBrain(ChatbotConfig.GEMINI_API_KEY)
        self.media = MediaManager()
        self.voice = VoiceGenerator()
    
    async def handle_message(self, client: Client, message: Message):
        """Main message handler"""
        try:
            user_id = message.from_user.id
            
            # Update user database
            self.db.update_user(user_id, message)
            
            # Extract and store any personal facts
            if message.text:
                facts = self.ai.extract_user_facts(message.text)
                for fact in facts:
                    self.db.add_user_fact(user_id, fact)
            
            # Show typing action for realism
            await client.send_chat_action(message.chat.id, ChatAction.TYPING)
            await asyncio.sleep(ChatbotConfig.TYPING_DELAY)
            
            # Handle different message types
            if message.text:
                await self._handle_text_message(message, user_id)
            elif message.sticker:
                await self._handle_sticker_message(message, user_id)
            elif message.photo or message.video:
                await self._handle_media_message(message, user_id)
            elif message.voice or message.audio:
                await self._handle_voice_message(message, user_id)
        
        except Exception as e:
            print(f"Error handling message: {e}")
            await message.reply_text("Oops! Something went wrong 😅")
    
    async def _handle_text_message(self, message: Message, user_id: int):
        """Handle text messages with AI response"""
        # Get user context
        context = self.db.get_user_context(user_id)
        
        # Generate AI response
        response = await self.ai.generate_response(
            user_id,
            message.text,
            context
        )
        
        # Store bot response
        self.db.add_bot_response(user_id, response)
        
        # Check if we should send a sticker too
        emotion = self.media.should_send_media(message.text)
        
        # Send response
        await message.reply_text(response)
        
        # Send sticker if appropriate
        if emotion and random.random() > 0.5:  # 50% chance
            sticker = self.media.get_random_sticker(emotion)
            if sticker:
                try:
                    await message.reply_sticker(sticker)
                except:
                    pass
        
        # Occasionally send voice message (10% chance for longer responses)
        if len(response) > 50 and random.random() > 0.9:
            voice_file = await self.voice.create_voice_message(response, user_id)
            if voice_file:
                try:
                    await message.reply_voice(voice_file)
                    os.remove(voice_file)
                except Exception as e:
                    print(f"Voice send error: {e}")
    
    async def _handle_sticker_message(self, message: Message, user_id: int):
        """Respond to stickers with text and maybe another sticker"""
        responses = [
            "Haha nice sticker! 😄",
            "Love that one! 😊",
            "That's so cute! 🥰",
            "Epic sticker bro! 🔥",
            "Lol good one! 😂"
        ]
        
        await message.reply_text(random.choice(responses))
        
        # Send a random happy sticker back
        if random.random() > 0.6:
            sticker = self.media.get_random_sticker("happy")
            if sticker:
                await message.reply_sticker(sticker)
    
    async def _handle_media_message(self, message: Message, user_id: int):
        """Handle photos/videos"""
        responses = [
            "Wow, nice pic! 📸",
            "Looking good! 😍",
            "That's awesome! ✨",
            "Beautiful! 🌟",
            "Cool photo! 📷"
        ]
        
        await message.reply_text(random.choice(responses))
    
    async def _handle_voice_message(self, message: Message, user_id: int):
        """Handle voice messages"""
        responses = [
            "Got your voice message! 🎤",
            "Listening to you! 👂",
            "Nice voice note! 🔊"
        ]
        
        await message.reply_text(random.choice(responses))

# Setup function for your bot
def setup_chatbot(app: Client):
    """Add this to your bot initialization"""
    
    chatbot = AdvancedChatbot(app)
    
    # Filter for private messages or when bot is mentioned in groups
    @app.on_message(
        filters.private | 
        filters.mentioned | 
        filters.regex(r"@YourBotUsername")
    )
    async def chat_handler(client: Client, message: Message):
        await chatbot.handle_message(client, message)
    
    print("✅ Advanced Chatbot initialized!")
    return chatbot