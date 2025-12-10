import asyncio
import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timedelta

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultPhoto,
    InputTextMessageContent,
    CallbackQuery,
    Message
)

import config
from AviaxMusic import app

# Store download requests and search results
download_cache: Dict[str, dict] = {}
search_cache: Dict[str, dict] = {}

# Animation frames for progress
DOWNLOAD_FRAMES = ["⬇️", "⏬", "📥", "💾"]
UPLOAD_FRAMES = ["⬆️", "⏫", "📤", "☁️"]
SEARCH_FRAMES = ["🔍", "🔎", "🔦", "🔭"]

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

def format_duration(seconds: int) -> str:
    """Format duration in human-readable format"""
    if not seconds:
        return "Unknown"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"

def format_views(views: int) -> str:
    """Format view count"""
    if not views:
        return "Unknown"
    
    if views >= 1_000_000_000:
        return f"{views / 1_000_000_000:.1f}B"
    elif views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M"
    elif views >= 1_000:
        return f"{views / 1_000:.1f}K"
    return str(views)

async def search_youtube(query: str, max_results: int = 10) -> Optional[List[dict]]:
    """Search YouTube videos by name/query"""
    try:
        headers = {}
        if config.API_KEY:
            headers['Authorization'] = f'Bearer {config.API_KEY}'
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{config.API_URL}/search",
                params={'q': query, 'max_results': max_results},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('status') == 'success':
                        return data.get('results', [])
        
        return None
    except Exception as e:
        print(f"Error searching YouTube: {e}")
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

def create_quality_keyboard(video_id: str, user_id: int, formats: dict, back_to_search: bool = False) -> InlineKeyboardMarkup:
    """Create inline keyboard with quality options"""
    buttons = []
    
    # Video formats
    if formats.get('video'):
        video_qualities = []
        for quality in ['2160p', '1440p', '1080p', '720p', '480p', '360p']:
            if quality in [f.get('quality') for f in formats['video']]:
                video_qualities.append(quality)
        
        if video_qualities:
            buttons.append([InlineKeyboardButton("━━━━ 📹 VIDEO FORMATS ━━━━", callback_data="header")])
            # Group video qualities in pairs
            for i in range(0, len(video_qualities), 2):
                row = []
                for quality in video_qualities[i:i+2]:
                    row.append(InlineKeyboardButton(
                        f"🎬 {quality}",
                        callback_data=f"dl_video_{quality}_{video_id}_{user_id}"
                    ))
                buttons.append(row)
    
    # Audio formats
    if formats.get('audio'):
        audio_qualities = []
        for quality in ['320kbps', '256kbps', '192kbps', '128kbps']:
            if quality in [f.get('quality') for f in formats['audio']]:
                audio_qualities.append(quality)
        
        if audio_qualities:
            buttons.append([InlineKeyboardButton("━━━━ 🎵 AUDIO FORMATS ━━━━", callback_data="header")])
            # Group audio qualities in pairs
            for i in range(0, len(audio_qualities), 2):
                row = []
                for quality in audio_qualities[i:i+2]:
                    row.append(InlineKeyboardButton(
                        f"🎧 {quality}",
                        callback_data=f"dl_audio_{quality}_{video_id}_{user_id}"
                    ))
                buttons.append(row)
    
    # Navigation buttons
    nav_buttons = []
    if back_to_search:
        nav_buttons.append(InlineKeyboardButton("◀️ Back", callback_data=f"back_search_{user_id}"))
    nav_buttons.append(InlineKeyboardButton("❌ Close", callback_data=f"close_{user_id}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    return InlineKeyboardMarkup(buttons)

def create_search_results_keyboard(results: List[dict], user_id: int, page: int = 0) -> InlineKeyboardMarkup:
    """Create keyboard with search results"""
    buttons = []
    items_per_page = 8
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    
    page_results = results[start_idx:end_idx]
    
    for idx, result in enumerate(page_results):
        video_id = result.get('video_id', '')
        title = result.get('title', 'Unknown')[:35]
        duration = result.get('duration_formatted', '')
        views = result.get('views_formatted', '')
        
        button_text = f"▶️ {title}"
        if duration:
            button_text += f" • {duration}"
        
        buttons.append([InlineKeyboardButton(
            button_text,
            callback_data=f"select_video_{video_id}_{user_id}"
        )])
    
    # Pagination
    nav_buttons = []
    total_pages = (len(results) + items_per_page - 1) // items_per_page
    
    if total_pages > 1:
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"search_page_{page-1}_{user_id}"))
        
        nav_buttons.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="header"))
        
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"search_page_{page+1}_{user_id}"))
        
        buttons.append(nav_buttons)
    
    buttons.append([InlineKeyboardButton("❌ Close", callback_data=f"close_{user_id}")])
    
    return InlineKeyboardMarkup(buttons)

async def animate_progress(message: Message, frames: List[str], text_template: str, duration: float = 2.0):
    """Animate progress message"""
    interval = duration / len(frames)
    for frame in frames:
        try:
            await message.edit_text(text_template.format(frame=frame))
            await asyncio.sleep(interval)
        except:
            pass

# Inline query handler
@app.on_inline_query()
async def inline_youtube_handler(client: Client, inline_query: InlineQuery):
    """Handle inline queries for YouTube search and download"""
    query = inline_query.query.strip()
    
    if not query:
        return await inline_query.answer(
            results=[
                InlineQueryResultArticle(
                    title="🔍 Search YouTube Videos",
                    description="Type a video name or paste a YouTube URL",
                    input_message_content=InputTextMessageContent(
                        "**🎵 YouTube Downloader**\n\n"
                        "**Usage:**\n"
                        "• Search by name: `@bot_username song name`\n"
                        "• Direct URL: `@bot_username https://youtu.be/xxxxx`\n\n"
                        "**Features:**\n"
                        "✨ Search videos by name\n"
                        "📥 Download in multiple qualities\n"
                        "🎬 Video and Audio formats\n"
                        "⚡ Fast and reliable"
                    ),
                    thumb_url="https://i.imgur.com/7qKPdJK.png"
                )
            ],
            cache_time=1
        )
    
    # Check if it's a URL
    if is_youtube_url(query):
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
        duration = video_info.get('duration_formatted', video_info.get('duration', 'Unknown'))
        thumbnail = video_info.get('thumbnail', '')
        channel = video_info.get('channel', 'Unknown')
        views = video_info.get('views_formatted', '')
        
        # Store info in cache
        cache_key = f"{video_id}_{inline_query.from_user.id}"
        download_cache[cache_key] = {
            'url': query,
            'info': video_info,
            'user_id': inline_query.from_user.id
        }
        
        description_parts = [f"⏱ {duration}"]
        if channel:
            description_parts.append(f"👤 {channel}")
        if views:
            description_parts.append(f"👁 {views}")
        
        results = [
            InlineQueryResultPhoto(
                photo_url=thumbnail,
                thumb_url=thumbnail,
                title=f"📥 {title[:50]}",
                description=" • ".join(description_parts),
                caption=(
                    f"**📥 YouTube Downloader**\n\n"
                    f"**🎵 Title:** `{title}`\n"
                    f"**⏱ Duration:** `{duration}`\n"
                    f"**👤 Channel:** `{channel}`\n"
                    f"**👁 Views:** `{views}`\n\n"
                    f"**Select quality below:**"
                ),
                reply_markup=create_quality_keyboard(
                    video_id,
                    inline_query.from_user.id,
                    video_info.get('formats', {})
                )
            )
        ]
    else:
        # Search YouTube
        search_results = await search_youtube(query, max_results=15)
        
        if not search_results:
            return await inline_query.answer(
                results=[
                    InlineQueryResultArticle(
                        title="❌ No results found",
                        description=f"No videos found for: {query}",
                        input_message_content=InputTextMessageContent(
                            f"No results found for: **{query}**\n\nTry different keywords."
                        )
                    )
                ],
                cache_time=1
            )
        
        # Store search results in cache
        search_key = f"search_{inline_query.from_user.id}_{inline_query.id}"
        search_cache[search_key] = {
            'query': query,
            'results': search_results,
            'user_id': inline_query.from_user.id,
            'timestamp': datetime.now()
        }
        
        results = []
        for idx, result in enumerate(search_results[:10]):
            video_id = result.get('video_id', '')
            title = result.get('title', 'Unknown')
            duration = result.get('duration_formatted', '')
            thumbnail = result.get('thumbnail', '')
            channel = result.get('channel', 'Unknown')
            views = result.get('views_formatted', '')
            
            # Store individual result
            cache_key = f"{video_id}_{inline_query.from_user.id}"
            download_cache[cache_key] = {
                'url': f"https://youtu.be/{video_id}",
                'info': result,
                'user_id': inline_query.from_user.id,
                'from_search': True
            }
            
            description_parts = []
            if duration:
                description_parts.append(f"⏱ {duration}")
            if channel:
                description_parts.append(f"👤 {channel}")
            if views:
                description_parts.append(f"👁 {views}")
            
            results.append(
                InlineQueryResultPhoto(
                    photo_url=thumbnail if thumbnail else "https://i.imgur.com/7qKPdJK.png",
                    thumb_url=thumbnail if thumbnail else "https://i.imgur.com/7qKPdJK.png",
                    title=f"{idx + 1}. {title[:45]}",
                    description=" • ".join(description_parts) if description_parts else "Click to download",
                    caption=(
                        f"**🎵 {title}**\n\n"
                        f"**⏱ Duration:** `{duration or 'Unknown'}`\n"
                        f"**👤 Channel:** `{channel}`\n"
                        f"**👁 Views:** `{views or 'Unknown'}`\n\n"
                        f"**Select quality below:**"
                    ),
                    reply_markup=create_quality_keyboard(
                        video_id,
                        inline_query.from_user.id,
                        result.get('formats', {}),
                        back_to_search=True
                    )
                )
            )
        
    await inline_query.answer(results=results, cache_time=300)

# Regular command handlers
@app.on_message(filters.command(['download', 'dl', 'ytdl']) & filters.private)
async def download_command(client: Client, message: Message):
    """Handle download command"""
    if len(message.command) < 2:
        return await message.reply_text(
            "**📥 YouTube Downloader**\n\n"
            "**Usage:**\n"
            f"• `/{message.command[0]} [YouTube URL]`\n"
            f"• `/{message.command[0]} [Video Name]`\n"
            f"• Or use inline: `@{(await app.get_me()).username} [query]`\n\n"
            "**Examples:**\n"
            f"• `/{message.command[0]} https://youtu.be/dQw4w9WgXcQ`\n"
            f"• `/{message.command[0]} Rick Astley Never Gonna Give You Up`"
        )
    
    query = " ".join(message.command[1:])
    
    # Check if it's a URL
    if is_youtube_url(query):
        status = await message.reply_text(f"{SEARCH_FRAMES[0]} Fetching video information...")
        
        # Animate search
        asyncio.create_task(animate_progress(
            status,
            SEARCH_FRAMES,
            "{frame} Fetching video information...",
            2.0
        ))
        
        video_info = await get_video_info(query)
        
        if not video_info:
            return await status.edit_text("❌ Failed to fetch video information!")
        
        video_id = extract_video_id(query)
        title = video_info.get('title', 'Unknown')
        duration = video_info.get('duration_formatted', video_info.get('duration', 'Unknown'))
        thumbnail = video_info.get('thumbnail', '')
        channel = video_info.get('channel', 'Unknown')
        views = video_info.get('views_formatted', '')
        
        # Store in cache
        cache_key = f"{video_id}_{message.from_user.id}"
        download_cache[cache_key] = {
            'url': query,
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
            f"**🎵 Title:** `{title}`\n"
            f"**⏱ Duration:** `{duration}`\n"
            f"**👤 Channel:** `{channel}`\n"
            f"**👁 Views:** `{views}`\n\n"
            f"**Select quality below:**"
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
    else:
        # Search for videos
        status = await message.reply_text(f"{SEARCH_FRAMES[0]} Searching YouTube...")
        
        # Animate search
        asyncio.create_task(animate_progress(
            status,
            SEARCH_FRAMES,
            "{frame} Searching YouTube...",
            2.0
        ))
        
        search_results = await search_youtube(query, max_results=15)
        
        if not search_results:
            return await status.edit_text(f"❌ No results found for: **{query}**")
        
        # Store search results
        search_key = f"search_{message.from_user.id}"
        search_cache[search_key] = {
            'query': query,
            'results': search_results,
            'user_id': message.from_user.id,
            'timestamp': datetime.now()
        }
        
        # Store individual results in download cache
        for result in search_results:
            video_id = result.get('video_id', '')
            cache_key = f"{video_id}_{message.from_user.id}"
            download_cache[cache_key] = {
                'url': f"https://youtu.be/{video_id}",
                'info': result,
                'user_id': message.from_user.id,
                'from_search': True
            }
        
        keyboard = create_search_results_keyboard(
            search_results,
            message.from_user.id,
            page=0
        )
        
        result_text = f"**🔍 Search Results for:** `{query}`\n\n"
        result_text += f"**Found {len(search_results)} videos. Select one:**"
        
        await status.edit_text(result_text, reply_markup=keyboard)

# Callback query handlers
@app.on_callback_query(filters.regex(r'^select_video_'))
async def select_video_callback(client: Client, callback_query: CallbackQuery):
    """Handle video selection from search results"""
    data = callback_query.data.split('_')
    video_id = data[2]
    user_id = int(data[3])
    
    if callback_query.from_user.id != user_id:
        return await callback_query.answer("❌ This is not for you!", show_alert=True)
    
    cache_key = f"{video_id}_{user_id}"
    cached_data = download_cache.get(cache_key)
    
    if not cached_data:
        return await callback_query.answer("❌ Session expired!", show_alert=True)
    
    video_info = cached_data['info']
    title = video_info.get('title', 'Unknown')
    duration = video_info.get('duration_formatted', 'Unknown')
    channel = video_info.get('channel', 'Unknown')
    views = video_info.get('views_formatted', '')
    thumbnail = video_info.get('thumbnail', '')
    
    keyboard = create_quality_keyboard(
        video_id,
        user_id,
        video_info.get('formats', {}),
        back_to_search=True
    )
    
    caption = (
        f"**📥 YouTube Downloader**\n\n"
        f"**🎵 Title:** `{title}`\n"
        f"**⏱ Duration:** `{duration}`\n"
        f"**👤 Channel:** `{channel}`\n"
        f"**👁 Views:** `{views}`\n\n"
        f"**Select quality below:**"
    )
    
    try:
        if thumbnail:
            # Delete old message and send new one with thumbnail
            await callback_query.message.delete()
            await callback_query.message.reply_photo(
                photo=thumbnail,
                caption=caption,
                reply_markup=keyboard
            )
        else:
            await callback_query.message.edit_text(
                caption,
                reply_markup=keyboard
            )
        await callback_query.answer()
    except Exception as e:
        await callback_query.answer("Error loading video info", show_alert=True)

@app.on_callback_query(filters.regex(r'^back_search_'))
async def back_to_search_callback(client: Client, callback_query: CallbackQuery):
    """Handle back to search results"""
    user_id = int(callback_query.data.split('_')[2])
    
    if callback_query.from_user.id != user_id:
        return await callback_query.answer("❌ This is not for you!", show_alert=True)
    
    search_key = f"search_{user_id}"
    search_data = search_cache.get(search_key)
    
    if not search_data:
        return await callback_query.answer("❌ Search session expired!", show_alert=True)
    
    keyboard = create_search_results_keyboard(
        search_data['results'],
        user_id,
        page=0
    )
    
    result_text = f"**🔍 Search Results for:** `{search_data['query']}`\n\n"
    result_text += f"**Found {len(search_data['results'])} videos. Select one:**"
    
    try:
        await callback_query.message.delete()
        await callback_query.message.reply_text(result_text, reply_markup=keyboard)
        await callback_query.answer()
    except:
        await callback_query.answer("Error going back", show_alert=True)

@app.on_callback_query(filters.regex(r'^search_page_'))
async def search_page_callback(client: Client, callback_query: CallbackQuery):
    """Handle search results pagination"""
    data = callback_query.data.split('_')
    page = int(data[2])
    user_id = int(data[3])
    
    if callback_query.from_user.id != user_id:
        return await callback_query.answer("❌ This is not for you!", show_alert=True)
    
    search_key = f"search_{user_id}"
    search_data = search_cache.get(search_key)
    
    if not search_data:
        return await callback_query.answer("❌ Search session expired!", show_alert=True)
    
    keyboard = create_search_results_keyboard(
        search_data['results'],
        user_id,
        page=page
    )
    
    result_text = f"**🔍 Search Results for:** `{search_data['query']}`\n\n"
    result_text += f"**Found {len(search_data['results'])} videos. Select one:**"
    
    await callback_query.message.edit_text(result_text, reply_markup=keyboard)
    await callback_query.answer(f"Page {page + 1}")

@app.on_callback_query(filters.regex(r'^dl_'))
async def download_callback(client: Client, callback_query: CallbackQuery):
    """Handle download button callbacks"""
    data = callback_query.data.split('_')
    
    if len(data) < 5:
        return await callback_query.answer("Invalid data!", show_alert=True)
    
    format_type = data[1]
    quality = data[2]
    video_id = data[3]
    user_id = int(data[4])
    
    if callback_query.from_user.id != user_id:
        return await callback_query.answer("❌ This is not for you!", show_alert=True)
    
    cache_key = f"{video_id}_{user_id}"
    cached_data = download_cache.get(cache_key)
    
    if not cached_data:
        return await callback_query.answer("❌ Session expired!", show_alert=True)
    
    await callback_query.answer(f"⏳ Preparing {quality} {format_type}...")
    
    # Create status message
    status_text = f"{DOWNLOAD_FRAMES[0]} **Downloading {quality} {format_type}...**\n\n`Please wait...`"
    
    try:
        if callback_query.message.photo:
            status = await callback_query.message.edit_caption(status_text)
        else:
            status = await callback_query.message.edit_text(status_text)
    except:
        status = await callback_query.message.reply_text(status_text)
    
    # Animate download
    async def animate_download():
        for _ in range(3):
            for frame in DOWNLOAD_FRAMES:
                try:
                    text = f"{frame} **Downloading {quality} {format_type}...**\n\n`Processing your request...`"
                    if status.photo:
                        await status.edit_caption(text)
                    else:
                        await status.edit_text(text)
                    await asyncio.sleep(0.5)
                except:
                    pass
    
    animation_task = asyncio.create_task(animate_download())
    
    # Download media
    download_data = await download_media(
        cached_data['url'],
        format_type,
        quality
    )
    
    animation_task.cancel()
    
    if not download_data or not download_data.get('download_url'):
        error_text = "❌ **Download failed!**\n\n`Please try again later.`"
        try:
            if status.photo:
                await status.edit_caption(error_text)
            else:
                await status.edit_text(error_text)
        except:
            pass
        return
    
    download_url = download_data['download_url']
    title = cached_data['info'].get('title', 'download')
    
    try:
        # Upload animation
        upload_text = f"{UPLOAD_FRAMES[0]} **Uploading {quality} {format_type}...**\n\n`Almost there...`"
        try:
            if status.photo:
                await status.edit_caption(upload_text)
            else:
                await status.edit_text(upload_text)
        except:
            pass
        
        # Animate upload
        async def animate_upload():
            for frame in UPLOAD_FRAMES * 2:
                try:
                    text = f"{frame} **Uploading {quality} {format_type}...**\n\n`Almost there...`"
                    if status.photo:
                        await status.edit_caption(text)
                    else:
                        await status.edit_text(text)
                    await asyncio.sleep(0.5)
                except:
                    pass
        
        upload_animation = asyncio.create_task(animate_upload())
        
        # Send file
        caption_text = (
            f"**✅ Download Complete!**\n\n"
            f"**🎵 Title:** `{title}`\n"
            f"**📊 Quality:** `{quality} {format_type.upper()}`\n"
            f"**📦 Format:** `{format_type.upper()}`\n\n"
            f"**Powered by:** @{(await app.get_me()).username}"
        )
        
        if format_type == 'video':
            await callback_query.message.reply_video(
                video=download_url,
                caption=caption_text,
                supports_streaming=True,
                progress=upload_progress,
                progress_args=(status, f"Uploading {quality} video")
            )
        else:
            await callback_query.message.reply_audio(
                audio=download_url,
                caption=caption_text,
                title=title,
                progress=upload_progress,
                progress_args=(status, f"Uploading {quality} audio")
            )
        
        upload_animation.cancel()
        
        # Success message
        success_text = (
            f"✅ **Successfully Downloaded!**\n\n"
            f"**🎵 Title:** `{title}`\n"
            f"**📊 Quality:** `{quality} {format_type.upper()}`\n\n"
            f"_Thank you for using our service!_"
        )
        
        try:
            if status.photo:
                await status.edit_caption(success_text)
            else:
                await status.edit_text(success_text)
        except:
            pass
        
    except Exception as e:
        print(f"Upload error: {e}")
        error_text = (
            f"❌ **Upload Failed!**\n\n"
            f"**Download directly:** [Click Here]({download_url})\n\n"
            f"_The file might be too large for Telegram._"
        )
        try:
            if status.photo:
                await status.edit_caption(error_text)
            else:
                await status.edit_text(error_text)
        except:
            pass

async def upload_progress(current, total, status, operation):
    """Upload progress callback"""
    try:
        percent = (current / total) * 100
        bar_length = 20
        filled = int(bar_length * current / total)
        bar = "█" * filled + "░" * (bar_length - filled)
        
        text = (
            f"📤 **{operation}**\n\n"
            f"`{bar}` {percent:.1f}%\n\n"
            f"**Uploaded:** `{humanbytes(current)}`\n"
            f"**Total:** `{humanbytes(total)}`"
        )
        
        if status.photo:
            await status.edit_caption(text)
        else:
            await status.edit_text(text)
    except:
        pass

def humanbytes(size):
    """Convert bytes to human readable format"""
    if not size:
        return "0 B"
    power = 2**10
    n = 0
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    while size > power and n < len(units) - 1:
        size /= power
        n += 1
    return f"{size:.2f} {units[n]}"

@app.on_callback_query(filters.regex(r'^close_'))
async def close_callback(client: Client, callback_query: CallbackQuery):
    """Handle close button"""
    user_id = int(callback_query.data.split('_')[1])
    
    if callback_query.from_user.id != user_id:
        return await callback_query.answer("❌ This is not for you!", show_alert=True)
    
    await callback_query.message.delete()
    await callback_query.answer("✅ Closed!")

@app.on_callback_query(filters.regex(r'^header$'))
async def header_callback(client: Client, callback_query: CallbackQuery):
    """Handle header button (no action)"""
    await callback_query.answer()

# Search command
@app.on_message(filters.command(['search', 'ytsearch', 'findsong']) & filters.private)
async def search_command(client: Client, message: Message):
    """Handle search command"""
    if len(message.command) < 2:
        return await message.reply_text(
            "**🔍 YouTube Search**\n\n"
            "**Usage:**\n"
            f"• `/{message.command[0]} [song/video name]`\n\n"
            "**Example:**\n"
            f"• `/{message.command[0]} Imagine Dragons Bones`"
        )
    
    query = " ".join(message.command[1:])
    
    status = await message.reply_text(f"{SEARCH_FRAMES[0]} Searching YouTube...")
    
    # Animate search
    asyncio.create_task(animate_progress(
        status,
        SEARCH_FRAMES,
        "{frame} Searching YouTube for: " + query[:30] + "...",
        2.0
    ))
    
    search_results = await search_youtube(query, max_results=15)
    
    if not search_results:
        return await status.edit_text(f"❌ No results found for: **{query}**")
    
    # Store search results
    search_key = f"search_{message.from_user.id}"
    search_cache[search_key] = {
        'query': query,
        'results': search_results,
        'user_id': message.from_user.id,
        'timestamp': datetime.now()
    }
    
    # Store individual results
    for result in search_results:
        video_id = result.get('video_id', '')
        cache_key = f"{video_id}_{message.from_user.id}"
        download_cache[cache_key] = {
            'url': f"https://youtu.be/{video_id}",
            'info': result,
            'user_id': message.from_user.id,
            'from_search': True
        }
    
    keyboard = create_search_results_keyboard(
        search_results,
        message.from_user.id,
        page=0
    )
    
    result_text = (
        f"**🔍 Search Results**\n\n"
        f"**Query:** `{query}`\n"
        f"**Found:** `{len(search_results)} videos`\n\n"
        f"**📝 Select a video to download:**"
    )
    
    await status.edit_text(result_text, reply_markup=keyboard)

# Help command
@app.on_message(filters.command(['ythelp', 'ytdlhelp']) & filters.private)
async def help_command(client: Client, message: Message):
    """Handle help command"""
    bot_username = (await app.get_me()).username
    
    help_text = (
        "**📥 YouTube Downloader - Help Guide**\n\n"
        "**🎯 Features:**\n"
        "• 🔍 Search videos by name\n"
        "• 📥 Direct URL download\n"
        "• 🎬 Multiple video qualities (360p - 4K)\n"
        "• 🎵 Multiple audio qualities (128kbps - 320kbps)\n"
        "• ⚡ Fast and reliable\n"
        "• 📱 Inline mode support\n\n"
        
        "**💬 Commands:**\n"
        "• `/download [URL or Name]` - Download video\n"
        "• `/search [Name]` - Search videos\n"
        "• `/ythelp` - Show this help\n\n"
        
        "**🎪 Inline Mode:**\n"
        f"• `@{bot_username} [URL]` - Download from URL\n"
        f"• `@{bot_username} [Name]` - Search videos\n\n"
        
        "**📝 Examples:**\n"
        "• `/download https://youtu.be/xxxxx`\n"
        "• `/download Imagine Dragons Believer`\n"
        "• `/search Ed Sheeran Shape of You`\n"
        f"• `@{bot_username} Coldplay Viva La Vida`\n\n"
        
        "**💡 Tips:**\n"
        "• Use inline mode for quick access\n"
        "• Higher quality = larger file size\n"
        "• Audio format for music, video for clips\n"
        "• Search supports multiple keywords\n\n"
        
        "**⚠️ Note:**\n"
        "• Maximum file size: 2GB (Telegram limit)\n"
        "• Download speed depends on API server\n"
        "• Some videos may be restricted\n\n"
        
        "**🆘 Support:** @YourSupportChannel\n"
        "**👨‍💻 Developer:** @YourUsername"
    )
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Try Inline", switch_inline_query_current_chat="Imagine Dragons"),
            InlineKeyboardButton("📥 Download", switch_inline_query_current_chat="https://youtu.be/")
        ],
        [InlineKeyboardButton("❌ Close", callback_data=f"close_{message.from_user.id}")]
    ])
    
    await message.reply_text(help_text, reply_markup=keyboard)

# Stats command (admin only)
@app.on_message(filters.command(['ytstats']) & filters.private)
async def stats_command(client: Client, message: Message):
    """Show bot statistics"""
    # Check if user is admin (add your admin IDs in config)
    if message.from_user.id not in getattr(config, 'ADMIN_IDS', []):
        return await message.reply_text("❌ This command is for admins only!")
    
    stats_text = (
        f"**📊 Bot Statistics**\n\n"
        f"**💾 Cache Status:**\n"
        f"• Download Cache: `{len(download_cache)} entries`\n"
        f"• Search Cache: `{len(search_cache)} entries`\n\n"
        f"**🤖 Bot Info:**\n"
        f"• Username: `@{(await app.get_me()).username}`\n"
        f"• ID: `{(await app.get_me()).id}`\n\n"
        f"**⚙️ System:**\n"
        f"• Python: `3.x`\n"
        f"• Pyrogram: `Latest`\n"
        f"• Status: `🟢 Online`"
    )
    
    await message.reply_text(stats_text)

# Cleanup cache periodically
async def cleanup_cache():
    """Clean up old cache entries"""
    while True:
        await asyncio.sleep(1800)  # 30 minutes
        
        # Clean download cache
        download_cache.clear()
        
        # Clean old search cache (older than 1 hour)
        current_time = datetime.now()
        expired_keys = []
        
        for key, data in search_cache.items():
            if current_time - data.get('timestamp', current_time) > timedelta(hours=1):
                expired_keys.append(key)
        
        for key in expired_keys:
            search_cache.pop(key, None)
        
        print(f"🧹 Cache cleaned - Download: {len(download_cache)}, Search: {len(search_cache)}")

# Start cleanup task
asyncio.create_task(cleanup_cache())

print("✅ YouTube Downloader Module Loaded Successfully!")