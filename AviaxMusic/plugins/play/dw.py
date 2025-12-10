import asyncio
import os
import re
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    CallbackQuery,
    Message
)

import config
from AviaxMusic import app

# Store download requests temporarily
download_cache: Dict[str, dict] = {}

def is_youtube_url(url: str) -> bool:
    """Check if URL is a valid YouTube URL"""
    youtube_regex = (
        r'(https?://)?(www\.)?'
        '(youtube|youtu|youtube-nocookie)\.(com|be)/'
        '(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    )
    return bool(re.match(youtube_regex, url))

def extract_video_id(url: str) -> Optional[str]:
    """Extract video ID from YouTube URL"""
    if not url:
        return None
    
    parsed = urlparse(url)
    if parsed.hostname in ['www.youtube.com', 'youtube.com', 'm.youtube.com']:
        if parsed.path == '/watch':
            return parse_qs(parsed.query).get('v', [None])[0]
        elif parsed.path.startswith('/embed/'):
            return parsed.path.split('/')[2]
        elif parsed.path.startswith('/v/'):
            return parsed.path.split('/')[2]
    elif parsed.hostname in ['youtu.be']:
        return parsed.path[1:]
    
    return None

async def get_video_info(video_url: str) -> Optional[dict]:
    """Fetch video information from API"""
    try:
        video_id = extract_video_id(video_url)
        if not video_id:
            return None
        
        headers = {}
        if config.API_KEY:
            headers['Authorization'] = f'Bearer {config.API_KEY}'
        
        async with aiohttp.ClientSession() as session:
            # Try video API first
            async with session.get(
                f"{config.VIDEO_API_URL}/info",
                params={'url': video_url},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('status') == 'success':
                        return data.get('data')
            
            # Fallback to audio API
            async with session.get(
                f"{config.API_URL}/info",
                params={'url': video_url},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('status') == 'success':
                        return data.get('data')
        
        return None
    except Exception as e:
        print(f"Error fetching video info: {e}")
        return None

async def download_media(url: str, format_type: str, quality: str) -> Optional[dict]:
    """Download media from API"""
    try:
        headers = {}
        if config.API_KEY:
            headers['Authorization'] = f'Bearer {config.API_KEY}'
        
        api_url = config.VIDEO_API_URL if format_type == 'video' else config.API_URL
        
        params = {
            'url': url,
            'quality': quality
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{api_url}/download",
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=300)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('status') == 'success':
                        return data.get('data')
        
        return None
    except Exception as e:
        print(f"Error downloading media: {e}")
        return None

def create_quality_keyboard(video_id: str, user_id: int, formats: dict) -> InlineKeyboardMarkup:
    """Create inline keyboard with quality options"""
    buttons = []
    
    # Video formats
    if formats.get('video'):
        buttons.append([InlineKeyboardButton("📹 Video Formats", callback_data="header")])
        for quality in ['2160p', '1440p', '1080p', '720p', '480p', '360p']:
            if quality in [f.get('quality') for f in formats['video']]:
                buttons.append([
                    InlineKeyboardButton(
                        f"🎬 {quality} Video",
                        callback_data=f"dl_video_{quality}_{video_id}_{user_id}"
                    )
                ])
    
    # Audio formats
    if formats.get('audio'):
        buttons.append([InlineKeyboardButton("🎵 Audio Formats", callback_data="header")])
        for quality in ['320kbps', '256kbps', '192kbps', '128kbps']:
            if quality in [f.get('quality') for f in formats['audio']]:
                buttons.append([
                    InlineKeyboardButton(
                        f"🎧 {quality} Audio",
                        callback_data=f"dl_audio_{quality}_{video_id}_{user_id}"
                    )
                ])
    
    # Close button
    buttons.append([InlineKeyboardButton("❌ Close", callback_data=f"close_{user_id}")])
    
    return InlineKeyboardMarkup(buttons)

# Inline query handler
@app.on_inline_query(filters.regex(r'^https?://'))
async def inline_youtube_download(client: Client, inline_query: InlineQuery):
    """Handle inline queries with YouTube URLs"""
    query = inline_query.query.strip()
    
    if not is_youtube_url(query):
        return await inline_query.answer(
            results=[
                InlineQueryResultArticle(
                    title="❌ Invalid YouTube URL",
                    description="Please provide a valid YouTube URL",
                    input_message_content=InputTextMessageContent(
                        "Please provide a valid YouTube URL to download"
                    )
                )
            ],
            cache_time=1
        )
    
    # Get video info
    video_info = await get_video_info(query)
    
    if not video_info:
        return await inline_query.answer(
            results=[
                InlineQueryResultArticle(
                    title="❌ Failed to fetch video info",
                    description="Unable to retrieve video information",
                    input_message_content=InputTextMessageContent(
                        "Failed to fetch video information. Please try again."
                    )
                )
            ],
            cache_time=1
        )
    
    video_id = extract_video_id(query)
    title = video_info.get('title', 'Unknown')
    duration = video_info.get('duration', 'Unknown')
    thumbnail = video_info.get('thumbnail', '')
    
    # Store info in cache
    cache_key = f"{video_id}_{inline_query.from_user.id}"
    download_cache[cache_key] = {
        'url': query,
        'info': video_info,
        'user_id': inline_query.from_user.id
    }
    
    # Create result
    results = [
        InlineQueryResultArticle(
            title=f"📥 Download: {title[:50]}",
            description=f"Duration: {duration} | Click to select quality",
            thumb_url=thumbnail,
            input_message_content=InputTextMessageContent(
                f"**📥 YouTube Downloader**\n\n"
                f"**Title:** {title}\n"
                f"**Duration:** {duration}\n\n"
                f"Select quality from the buttons below:"
            ),
            reply_markup=create_quality_keyboard(
                video_id,
                inline_query.from_user.id,
                video_info.get('formats', {})
            )
        )
    ]
    
    await inline_query.answer(results=results, cache_time=300)

# Regular command handler
@app.on_message(filters.command(['download', 'dl', 'ytdl']) & filters.private)
async def download_command(client: Client, message: Message):
    """Handle download command"""
    if len(message.command) < 2:
        return await message.reply_text(
            "**📥 YouTube Downloader**\n\n"
            "**Usage:**\n"
            f"• `/{message.command[0]} [YouTube URL]`\n"
            "• Or use inline: `@{app.username} [YouTube URL]`\n\n"
            "**Example:**\n"
            f"`/{message.command[0]} https://youtu.be/dQw4w9WgXcQ`"
        )
    
    url = message.command[1]
    
    if not is_youtube_url(url):
        return await message.reply_text("❌ Invalid YouTube URL!")
    
    status = await message.reply_text("🔍 Fetching video information...")
    
    video_info = await get_video_info(url)
    
    if not video_info:
        return await status.edit_text("❌ Failed to fetch video information!")
    
    video_id = extract_video_id(url)
    title = video_info.get('title', 'Unknown')
    duration = video_info.get('duration', 'Unknown')
    thumbnail = video_info.get('thumbnail', '')
    
    # Store in cache
    cache_key = f"{video_id}_{message.from_user.id}"
    download_cache[cache_key] = {
        'url': url,
        'info': video_info,
        'user_id': message.from_user.id
    }
    
    # Send with keyboard
    keyboard = create_quality_keyboard(
        video_id,
        message.from_user.id,
        video_info.get('formats', {})
    )
    
    caption = (
        f"**📥 YouTube Downloader**\n\n"
        f"**Title:** {title}\n"
        f"**Duration:** {duration}\n\n"
        f"Select quality from the buttons below:"
    )
    
    await status.delete()
    
    if thumbnail:
        await message.reply_photo(
            photo=thumbnail,
            caption=caption,
            reply_markup=keyboard
        )
    else:
        await message.reply_text(caption, reply_markup=keyboard)

# Callback query handler
@app.on_callback_query(filters.regex(r'^dl_'))
async def download_callback(client: Client, callback_query: CallbackQuery):
    """Handle download button callbacks"""
    data = callback_query.data.split('_')
    
    if len(data) < 4:
        return await callback_query.answer("Invalid callback data!", show_alert=True)
    
    format_type = data[1]  # video or audio
    quality = data[2]
    video_id = data[3]
    user_id = int(data[4])
    
    # Check if user is authorized
    if callback_query.from_user.id != user_id:
        return await callback_query.answer(
            "❌ This button is not for you!",
            show_alert=True
        )
    
    cache_key = f"{video_id}_{user_id}"
    cached_data = download_cache.get(cache_key)
    
    if not cached_data:
        return await callback_query.answer(
            "❌ Session expired! Please send the URL again.",
            show_alert=True
        )
    
    await callback_query.answer("⏳ Downloading... Please wait")
    
    status = await callback_query.message.edit_caption(
        f"⏳ Downloading {quality} {format_type}...\n"
        f"Please wait, this may take a while."
    )
    
    # Download media
    download_data = await download_media(
        cached_data['url'],
        format_type,
        quality
    )
    
    if not download_data or not download_data.get('download_url'):
        return await status.edit_caption(
            "❌ Download failed! Please try again later."
        )
    
    download_url = download_data['download_url']
    title = cached_data['info'].get('title', 'download')
    
    try:
        await status.edit_caption(f"📤 Uploading {quality} {format_type}...")
        
        # Send file
        if format_type == 'video':
            await callback_query.message.reply_video(
                video=download_url,
                caption=f"**{title}**\n\n**Quality:** {quality}",
                supports_streaming=True
            )
        else:
            await callback_query.message.reply_audio(
                audio=download_url,
                caption=f"**{title}**\n\n**Quality:** {quality}",
                title=title
            )
        
        await status.edit_caption(
            f"✅ Successfully downloaded!\n\n"
            f"**Quality:** {quality} {format_type.upper()}"
        )
        
    except Exception as e:
        print(f"Upload error: {e}")
        await status.edit_caption(
            f"❌ Upload failed!\n\n"
            f"Download directly: [Click Here]({download_url})"
        )

@app.on_callback_query(filters.regex(r'^close_'))
async def close_callback(client: Client, callback_query: CallbackQuery):
    """Handle close button"""
    user_id = int(callback_query.data.split('_')[1])
    
    if callback_query.from_user.id != user_id:
        return await callback_query.answer(
            "❌ This button is not for you!",
            show_alert=True
        )
    
    await callback_query.message.delete()
    await callback_query.answer("Closed!")

@app.on_callback_query(filters.regex(r'^header$'))
async def header_callback(client: Client, callback_query: CallbackQuery):
    """Handle header button (no action)"""
    await callback_query.answer()

# Cleanup cache periodically
async def cleanup_cache():
    """Clean up old cache entries"""
    while True:
        await asyncio.sleep(1800)  # 30 minutes
        download_cache.clear()

# Start cleanup task
asyncio.create_task(cleanup_cache())