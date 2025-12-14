import asyncio
import random
import json
import os
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from pyrogram import filters
from pyrogram.types import Message
from pyrogram.enums import ChatAction
from AviaxMusic import app

@dataclass
class ChatMessage:
    role: str
    text: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

@dataclass
class UserProfile:
    name: str = "Friend"
    messages: List[ChatMessage] = field(default_factory=list)
    count: int = 0
    first_seen: str = field(default_factory=lambda: datetime.now().isoformat())
    last_seen: str = field(default_factory=lambda: datetime.now().isoformat())

class Config:
    GEMINI_API_KEY = "AIzaSyAT_aXQqEDrySmB6V0Y-sEqBnKCxWHymrQ"
    ENABLE_AI = True
    ENABLE_VOICE = False
    TYPING_DELAY = 1
    DATA_FILE = "chatbot_users.json"
    MAX_HISTORY = 20

class UserDatabase:
    def __init__(self):
        self.users: Dict[int, UserProfile] = {}
        self.load()
    
    def load(self):
        try:
            if os.path.exists(Config.DATA_FILE):
                with open(Config.DATA_FILE, 'r') as f:
                    data = json.load(f)
                    for uid, udata in data.items():
                        msgs = [ChatMessage(**m) for m in udata.get('messages', [])]
                        self.users[int(uid)] = UserProfile(
                            name=udata['name'],
                            messages=msgs,
                            count=udata['count'],
                            first_seen=udata['first_seen'],
                            last_seen=udata['last_seen']
                        )
        except:
            pass
    
    def save(self):
        try:
            data = {}
            for uid, user in self.users.items():
                user_dict = asdict(user)
                data[str(uid)] = user_dict
            with open(Config.DATA_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except:
            pass
    
    def get_user(self, user_id: int) -> UserProfile:
        if user_id not in self.users:
            self.users[user_id] = UserProfile()
        return self.users[user_id]
    
    def update_user(self, user_id: int, name: str):
        user = self.get_user(user_id)
        user.name = name
        user.last_seen = datetime.now().isoformat()
        user.count += 1
        self.save()
    
    def add_message(self, user_id: int, role: str, text: str):
        user = self.get_user(user_id)
        user.messages.append(ChatMessage(role=role, text=text))
        if len(user.messages) > Config.MAX_HISTORY:
            user.messages = user.messages[-Config.MAX_HISTORY:]
        self.save()

class AIEngine:
    def __init__(self):
        self.available = self.init_ai()
    
    def init_ai(self):
        if not Config.ENABLE_AI or Config.GEMINI_API_KEY == "YOUR_API_KEY_HERE":
            return False
        try:
            import google.generativeai as genai
            genai.configure(api_key=Config.GEMINI_API_KEY)
            self.model = genai.GenerativeModel('gemini-pro')
            return True
        except:
            return False
    
    async def generate(self, name: str, message: str, history: List[ChatMessage]) -> str:
        if not self.available:
            return self.fallback(message)
        
        try:
            context = f"You are a friendly Indian chatbot talking to {name}. Be natural and conversational.\n\n"
            
            if history:
                context += "Recent chat:\n"
                for msg in history[-6:]:
                    context += f"{msg.role}: {msg.text}\n"
            
            prompt = f"{context}\nUser: {message}\nYou:"
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return response.text
        except:
            return self.fallback(message)
    
    def fallback(self, message: str) -> str:
        msg = message.lower()
        
        if any(w in msg for w in ['hi', 'hello', 'hey']):
            return random.choice([
                "Hey! How's it going? 😊",
                "Hello! What's up? 👋",
                "Hi there! 😄"
            ])
        
        if any(w in msg for w in ['how are you', 'wassup']):
            return random.choice([
                "I'm great! How about you? 😊",
                "All good! What's new? 💫"
            ])
        
        if any(w in msg for w in ['thanks', 'thank you']):
            return random.choice([
                "You're welcome! 😊",
                "Happy to help! 💙"
            ])
        
        if any(w in msg for w in ['bye', 'goodbye']):
            return random.choice([
                "See you! 👋",
                "Bye! Take care! 💫"
            ])
        
        return random.choice([
            "Interesting! Tell me more 😊",
            "I see! Go on... 💭",
            "Cool! 🌟"
        ])

class MediaHandler:
    stickers = {
        "happy": "CAACAgIAAxkBAAEM4hhmVy",
        "sad": "CAACAgQAAxkBAAEM4jhm",
        "love": "CAACAgIAAxkBAAEM4khm",
        "laugh": "CAACAgIAAxkBAAEM4mhm"
    }
    
    @staticmethod
    def detect_emotion(text: str) -> Optional[str]:
        text = text.lower()
        if any(w in text for w in ['haha', 'lol', '😂', 'funny']):
            return "laugh"
        if any(w in text for w in ['sad', '😢', 'crying']):
            return "sad"
        if any(w in text for w in ['love', '❤️', 'amazing']):
            return "love"
        if any(w in text for w in ['happy', '😊', 'great']):
            return "happy"
        return None
    
    @staticmethod
    async def create_voice(text: str, user_id: int) -> Optional[str]:
        if not Config.ENABLE_VOICE:
            return None
        try:
            from gtts import gTTS
            clean = text.replace('*', '').replace('_', '')[:200]
            filename = f"voice_{user_id}_{int(datetime.now().timestamp())}.mp3"
            tts = gTTS(text=clean, lang='hi', tld='co.in', slow=False)
            await asyncio.to_thread(tts.save, filename)
            return filename
        except:
            return None

class Chatbot:
    def __init__(self):
        self.db = UserDatabase()
        self.ai = AIEngine()
        self.media = MediaHandler()
    
    async def handle_text(self, message: Message):
        try:
            user_id = message.from_user.id
            user_name = message.from_user.first_name or "Friend"
            
            self.db.update_user(user_id, user_name)
            self.db.add_message(user_id, "User", message.text)
            
            await message._client.send_chat_action(message.chat.id, ChatAction.TYPING)
            await asyncio.sleep(Config.TYPING_DELAY)
            
            user = self.db.get_user(user_id)
            response = await self.ai.generate(user_name, message.text, user.messages)
            
            self.db.add_message(user_id, "Bot", response)
            
            await message.reply_text(response)
            
            if random.random() > 0.7:
                emotion = self.media.detect_emotion(message.text)
                if emotion and emotion in self.media.stickers:
                    try:
                        await message.reply_sticker(self.media.stickers[emotion])
                    except:
                        pass
            
            if Config.ENABLE_VOICE and len(response) > 100 and random.random() > 0.95:
                voice = await self.media.create_voice(response, user_id)
                if voice and os.path.exists(voice):
                    try:
                        await message.reply_voice(voice)
                        os.remove(voice)
                    except:
                        if os.path.exists(voice):
                            os.remove(voice)
        except Exception as e:
            print(f"Error: {e}")
            try:
                await message.reply_text("Oops! Something went wrong 😅")
            except:
                pass
    
    async def handle_media(self, message: Message):
        try:
            responses = {
                "sticker": ["Nice sticker! 😄", "Cool! 🔥"],
                "photo": ["Great pic! 📸", "Nice! ✨"],
                "video": ["Cool video! 🎥"],
                "voice": ["Got it! 🎤"],
            }
            
            msg_type = None
            if message.sticker:
                msg_type = "sticker"
            elif message.photo:
                msg_type = "photo"
            elif message.video:
                msg_type = "video"
            elif message.voice:
                msg_type = "voice"
            
            if msg_type and msg_type in responses:
                await message.reply_text(random.choice(responses[msg_type]))
        except:
            pass

bot = Chatbot()

@app.on_message(filters.private & filters.text & ~filters.bot & ~filters.service)
async def private_text_handler(client, message: Message):
    await bot.handle_text(message)

@app.on_message(filters.private & ~filters.text & ~filters.bot & ~filters.service)
async def private_media_handler(client, message: Message):
    await bot.handle_media(message)

@app.on_message(filters.group & filters.mentioned & filters.text & ~filters.bot)
async def group_mention_handler(client, message: Message):
    await bot.handle_text(message)