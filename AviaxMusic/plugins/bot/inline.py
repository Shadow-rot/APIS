import asyncio
import os
import re
import json
from typing import Dict, Optional, List
from urllib.parse import parse_qs, urlparse

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
    Message,
)

import config
from AviaxMusic import app

# Caches
video_cache: Dict[str, dict] = {}
search_cache: Dict[str, dict] = {}
user_cache: Dict[int, dict] = {}

# Cleanup task
cleanup_task = None

def extract_video_id(url: str) -> Optional[str]:
    """Extract video ID from YouTube URL"""
    if not url:
        return None
    patterns = [
        r'(?:v=|/)([0-9A-Za-z_-]{11})',
        r'youtu\.be/([0-9A-Za-z_-]{11})',
        r'embed/([0-9A-Za-z_-]{11})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def format_size(size: int) -> str:
    """Format bytes to human readable"""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size/1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size/(1024*1024):.1f} MB"
    else:
        return f"{size/(1024*1024*1024):.1f} GB"

async def search_youtube(query: str, limit: int = 10) -> Optional[List[dict]]:
    """Search YouTube videos"""
    try:
        from yt_dlp import YoutubeDL
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
            'force_generic_extractor': False,
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(
                ydl.extract_info,
                f"ytsearch{limit}:{query}",
                download=False
            )
            
            if not info or 'entries' not in info:
                return None
            
            videos = []
            for entry in info['entries']:
                if not entry:
                    continue
                videos.append({
                    'id': entry.get('id'),
                    'title': entry.get('title', 'Unknown'),
                    'duration': entry.get('duration_string', '0:00'),
                    'thumb': entry.get('thumbnail', ''),
                    'channel': entry.get('uploader', 'Unknown'),
                    'url': f"https://youtu.be/{entry.get('id')}",
                })
            return videos[:limit]
            
    except Exception as e:
        print(f"Search error: {e}")
        # Fallback to alternative method
        try:
            async with aiohttp.ClientSession() as session:
                search_url = f"https://www.youtube.com/results?search_query={query}&sp=EgIQAQ%253D%253D"
                async with session.get(search_url) as resp:
                    html = await resp.text()
                    
                    # Extract video IDs from search results
                    video_ids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
                    
                    videos = []
                    for vid in video_ids[:limit]:
                        # Get video info using YouTube oEmbed
                        oembed_url = f"https://www.youtube.com/oembed?url=https://youtu.be/{vid}&format=json"
                        async with session.get(oembed_url) as oembed_resp:
                            if oembed_resp.status == 200:
                                data = await oembed_resp.json()
                                videos.append({
                                    'id': vid,
                                    'title': data.get('title', 'Unknown'),
                                    'duration': 'Unknown',
                                    'thumb': f"https://img.youtube.com/vi/{vid}/hqdefault.jpg",
                                    'channel': data.get('author_name', 'Unknown'),
                                    'url': f"https://youtu.be/{vid}",
                                })
                    return videos
        except:
            return None

async def get_video_info(url: str) -> Optional[dict]:
    """Get video information"""
    try:
        video_id = extract_video_id(url)
        if not video_id:
            return None
            
        # Check cache first
        cache_key = f"info_{video_id}"
        if cache_key in video_cache:
            return video_cache[cache_key]
        
        from yt_dlp import YoutubeDL
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(
                ydl.extract_info,
                f"https://youtu.be/{video_id}",
                download=False
            )
            
            if not info:
                return None
            
            result = {
                'id': video_id,
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration_string', '0:00'),
                'thumb': info.get('thumbnail', f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg'),
                'channel': info.get('uploader', 'Unknown'),
                'url': f"https://youtu.be/{video_id}",
            }
            
            # Cache for 1 hour
            video_cache[cache_key] = result
            return result
            
    except Exception as e:
        print(f"Video info error: {e}")
        return None

async def download_media(video_id: str, is_video: bool = False, quality: str = None) -> Optional[str]:
    """Download media using yt-dlp"""
    try:
        os.makedirs("downloads", exist_ok=True)
        
        # Check existing file
        ext = "mp4" if is_video else "mp3"
        filename = f"{video_id}_{quality if quality else 'audio'}.{ext}"
        filepath = f"downloads/{filename}"
        
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            return filepath
        
        from yt_dlp import YoutubeDL
        
        ydl_opts = {
            'format': 'bestaudio/best' if not is_video else f'bestvideo[height<={quality}]+bestaudio/best' if quality else 'best',
            'outtmpl': f'downloads/%(id)s_{quality if quality else "audio"}.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }] if not is_video else [],
            'merge_output_format': 'mp4' if is_video else None,
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            await asyncio.to_thread(
                ydl.download,
                [f"https://youtu.be/{video_id}"]
            )
        
        # Find the downloaded file
        for file in os.listdir("downloads"):
            if file.startswith(f"{video_id}_{quality if quality else 'audio'}"):
                return f"downloads/{file}"
        
        return None
        
    except Exception as e:
        print(f"Download error: {e}")
        return None

def create_format_buttons(video_id: str, user_id: int, is_search: bool = False):
    """Create format selection buttons"""
    buttons = [
        [
            InlineKeyboardButton("🎧 MP3 (320kbps)", callback_data=f"dl_audio_{video_id}_{user_id}"),
        ],
        [
            InlineKeyboardButton("🎬 720p", callback_data=f"dl_video_720_{video_id}_{user_id}"),
            InlineKeyboardButton("🎬 480p", callback_data=f"dl_video_480_{video_id}_{user_id}"),
        ],
        [
            InlineKeyboardButton("🎬 360p", callback_data=f"dl_video_360_{video_id}_{user_id}"),
            InlineKeyboardButton("🎬 240p", callback_data=f"dl_video_240_{video_id}_{user_id}"),
        ]
    ]
    
    if is_search:
        buttons.append([
            InlineKeyboardButton("🔙 Back to Search", callback_data=f"back_search_{user_id}")
        ])
    
    buttons.append([
        InlineKeyboardButton("❌ Close", callback_data=f"close_{user_id}")
    ])
    
    return InlineKeyboardMarkup(buttons)

def create_search_buttons(results: List[dict], user_id: int, page: int = 0):
    """Create search result buttons"""
    buttons = []
    per_page = 8
    start_idx = page * per_page
    end_idx = start_idx + per_page
    
    for result in results[start_idx:end_idx]:
        title = result['title'][:35]
        if len(result['title']) > 35:
            title += "..."
        duration = result['duration']
        button_text = f"🎵 {title} ({duration})"
        buttons.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"select_{result['id']}_{user_id}"
            )
        ])
    
    # Navigation buttons
    nav_buttons = []
    total_pages = (len(results) + per_page - 1) // per_page
    
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton("◀️ Prev", callback_data=f"page_{page-1}_{user_id}")
        )
    
    nav_buttons.append(
        InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop")
    )
    
    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton("Next ▶️", callback_data=f"page_{page+1}_{user_id}")
        )
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([
        InlineKeyboardButton("❌ Close", callback_data=f"close_{user_id}")
    ])
    
    return InlineKeyboardMarkup(buttons)

@app.on_inline_query()
async def handle_inline_query(client: Client, query: InlineQuery):
    """Handle inline queries"""
    try:
        search_query = query.query.strip()
        
        if not search_query:
            # Show help message
            await query.answer(
                results=[
                    InlineQueryResultArticle(
                        title="🎵 YouTube Downloader",
                        description="Search songs or paste YouTube URL",
                        input_message_content=InputTextMessageContent(
                            message_text="**🎵 YouTube Downloader**\n\n"
                                        "Search songs: `@YourBot song name`\n"
                                        "Download from URL: `@YourBot https://youtube.com/...`\n\n"
                                        "Don't forget to visit @AviaxOfficial"
                        ),
                        thumb_url="https://i.ibb.co/7qKPdJK/youtube-dl.png",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("📢 Channel", url="https://t.me/AviaxOfficial")]
                        ])
                    )
                ],
                cache_time=300,
                is_gallery=False,
                is_personal=True
            )
            return
        
        # Check if it's a URL
        if 'youtu.be' in search_query or 'youtube.com' in search_query or 'youtu' in search_query:
            video_id = extract_video_id(search_query)
            if not video_id:
                await query.answer(
                    results=[],
                    cache_time=1,
                    switch_pm_text="Invalid YouTube URL",
                    switch_pm_parameter="help"
                )
                return
            
            # Get video info
            video_info = await get_video_info(search_query)
            if not video_info:
                await query.answer(
                    results=[],
                    cache_time=1,
                    switch_pm_text="Video not found",
                    switch_pm_parameter="help"
                )
                return
            
            # Cache user data
            user_cache[query.from_user.id] = {
                'type': 'video',
                'video_id': video_id,
                'video_info': video_info
            }
            
            # Create result
            await query.answer(
                results=[
                    InlineQueryResultPhoto(
                        photo_url=video_info['thumb'],
                        thumb_url=video_info['thumb'],
                        title=f"📥 {video_info['title'][:50]}",
                        description=f"⏱ {video_info['duration']} | 👤 {video_info['channel'][:30]}",
                        caption=f"**📥 {video_info['title']}**\n\n"
                               f"**⏱ Duration:** `{video_info['duration']}`\n"
                               f"**👤 Channel:** `{video_info['channel']}`\n\n"
                               f"**Select format below:**\n\n"
                               f"Don't forget to visit @AviaxOfficial",
                        reply_markup=create_format_buttons(video_id, query.from_user.id)
                    )
                ],
                cache_time=300,
                is_gallery=False
            )
            
        else:
            # It's a search query
            results = await search_youtube(search_query, limit=20)
            if not results:
                await query.answer(
                    results=[],
                    cache_time=1,
                    switch_pm_text="No results found",
                    switch_pm_parameter="help"
                )
                return
            
            # Cache search results
            search_cache_key = f"{query.from_user.id}_{hash(search_query)}"
            search_cache[search_cache_key] = {
                'query': search_query,
                'results': results,
                'timestamp': asyncio.get_event_loop().time()
            }
            
            # Store in user cache
            user_cache[query.from_user.id] = {
                'type': 'search',
                'search_key': search_cache_key,
                'page': 0
            }
            
            # Create results
            inline_results = []
            for result in results[:10]:
                inline_results.append(
                    InlineQueryResultPhoto(
                        photo_url=result['thumb'],
                        thumb_url=result['thumb'],
                        title=f"{result['title'][:50]}",
                        description=f"⏱ {result['duration']} | 👤 {result['channel'][:30]}",
                        caption=f"**🎵 {result['title']}**\n\n"
                               f"**⏱ Duration:** `{result['duration']}`\n"
                               f"**👤 Channel:** `{result['channel']}`\n\n"
                               f"**Select format below:**\n\n"
                               f"Don't forget to visit @AviaxOfficial",
                        reply_markup=create_format_buttons(result['id'], query.from_user.id, is_search=True)
                    )
                )
            
            await query.answer(
                results=inline_results,
                cache_time=300,
                is_gallery=False
            )
            
    except Exception as e:
        print(f"Inline query error: {e}")
        await query.answer(
            results=[],
            cache_time=1,
            switch_pm_text="Error occurred",
            switch_pm_parameter="help"
        )

@app.on_callback_query(filters.regex(r'^select_'))
async def handle_video_select(client: Client, callback: CallbackQuery):
    """Handle video selection from search"""
    try:
        _, video_id, user_id = callback.data.split('_')
        user_id = int(user_id)
        
        if callback.from_user.id != user_id:
            await callback.answer("❌ This is not for you!", show_alert=True)
            return
        
        # Get video info
        video_info = await get_video_info(f"https://youtu.be/{video_id}")
        if not video_info:
            await callback.answer("❌ Video not found!", show_alert=True)
            return
        
        # Update user cache
        user_cache[user_id] = {
            'type': 'video',
            'video_id': video_id,
            'video_info': video_info
        }
        
        # Edit message with format options
        await callback.message.edit_caption(
            caption=f"**📥 {video_info['title']}**\n\n"
                   f"**⏱ Duration:** `{video_info['duration']}`\n"
                   f"**👤 Channel:** `{video_info['channel']}`\n\n"
                   f"**Select format below:**\n\n"
                   f"Don't forget to visit @AviaxOfficial",
            reply_markup=create_format_buttons(video_id, user_id, is_search=True)
        )
        
        await callback.answer()
        
    except Exception as e:
        print(f"Select error: {e}")
        await callback.answer("❌ Error occurred!", show_alert=True)

@app.on_callback_query(filters.regex(r'^dl_'))
async def handle_download(client: Client, callback: CallbackQuery):
    """Handle download requests"""
    try:
        parts = callback.data.split('_')
        if len(parts) == 4:
            # audio or video with quality
            media_type, quality, video_id, user_id = parts
            user_id = int(user_id)
            is_video = media_type == 'video'
        else:
            await callback.answer("❌ Invalid request!", show_alert=True)
            return
        
        if callback.from_user.id != user_id:
            await callback.answer("❌ This is not for you!", show_alert=True)
            return
        
        # Get video info from cache or API
        video_info = None
        user_data = user_cache.get(user_id)
        
        if user_data and user_data.get('video_id') == video_id:
            video_info = user_data.get('video_info')
        
        if not video_info:
            video_info = await get_video_info(f"https://youtu.be/{video_id}")
        
        if not video_info:
            await callback.answer("❌ Video not found!", show_alert=True)
            return
        
        # Update message with downloading status
        await callback.message.edit_caption(
            caption=f"**⬇️ Downloading...**\n\n"
                   f"**Title:** `{video_info['title'][:50]}`\n"
                   f"**Format:** `{'Video' if is_video else 'Audio'} {quality if is_video else '320kbps'}`\n\n"
                   f"⏳ Please wait...\n\n"
                   f"Don't forget to visit @AviaxOfficial",
            reply_markup=None
        )
        
        await callback.answer(f"Downloading {quality if is_video else 'audio'}...")
        
        # Download the media
        file_path = await download_media(
            video_id,
            is_video=is_video,
            quality=quality if is_video else None
        )
        
        if not file_path or not os.path.exists(file_path):
            await callback.message.edit_caption(
                caption=f"**❌ Download Failed!**\n\n"
                       f"**Title:** `{video_info['title'][:50]}`\n\n"
                       f"Try again or select another format.\n\n"
                       f"Don't forget to visit @AviaxOfficial",
                reply_markup=create_format_buttons(video_id, user_id, is_search=True)
            )
            return
        
        # Get file size
        file_size = os.path.getsize(file_path)
        
        # Update message with uploading status
        await callback.message.edit_caption(
            caption=f"**⬆️ Uploading...**\n\n"
                   f"**Title:** `{video_info['title'][:50]}`\n"
                   f"**Format:** `{'Video' if is_video else 'Audio'} {quality if is_video else '320kbps'}`\n"
                   f"**Size:** `{format_size(file_size)}`\n\n"
                   f"⏳ Please wait...\n\n"
                   f"Don't forget to visit @AviaxOfficial",
            reply_markup=None
        )
        
        # Upload the file
        try:
            if is_video:
                await client.send_video(
                    chat_id=callback.message.chat.id,
                    video=file_path,
                    caption=f"**✅ Download Complete!**\n\n"
                           f"**🎬 Title:** `{video_info['title']}`\n"
                           f"**📊 Quality:** `{quality}`\n"
                           f"**📦 Size:** `{format_size(file_size)}`\n"
                           f"**⏱ Duration:** `{video_info['duration']}`\n\n"
                           f"Don't forget to visit @AviaxOfficial",
                    supports_streaming=True,
                    reply_to_message_id=callback.message.id
                )
            else:
                await client.send_audio(
                    chat_id=callback.message.chat.id,
                    audio=file_path,
                    caption=f"**✅ Download Complete!**\n\n"
                           f"**🎵 Title:** `{video_info['title']}`\n"
                           f"**📊 Quality:** `320kbps MP3`\n"
                           f"**📦 Size:** `{format_size(file_size)}`\n"
                           f"**⏱ Duration:** `{video_info['duration']}`\n\n"
                           f"Don't forget to visit @AviaxOfficial",
                    title=video_info['title'][:64],
                    performer=video_info['channel'][:32],
                    reply_to_message_id=callback.message.id
                )
            
            # Update original message
            await callback.message.edit_caption(
                caption=f"**✅ Download Complete!**\n\n"
                       f"**Title:** `{video_info['title'][:50]}`\n"
                       f"**Format:** `{'Video' if is_video else 'Audio'} {quality if is_video else '320kbps'}`\n"
                       f"**Size:** `{format_size(file_size)}`\n\n"
                       f"✅ File sent successfully!\n\n"
                       f"Don't forget to visit @AviaxOfficial",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 Channel", url="https://t.me/AviaxOfficial")],
                    [InlineKeyboardButton("🔄 Download More", switch_inline_query_current_chat="")]
                ])
            )
            
        except Exception as e:
            print(f"Upload error: {e}")
            await callback.message.edit_caption(
                caption=f"**❌ Upload Failed!**\n\n"
                       f"**Error:** `{str(e)[:100]}`\n\n"
                       f"Try again later.\n\n"
                       f"Don't forget to visit @AviaxOfficial",
                reply_markup=create_format_buttons(video_id, user_id, is_search=True)
            )
        
        # Cleanup
        try:
            os.remove(file_path)
        except:
            pass
        
    except Exception as e:
        print(f"Download handler error: {e}")
        await callback.answer("❌ Error occurred!", show_alert=True)

@app.on_callback_query(filters.regex(r'^back_search_'))
async def handle_back_search(client: Client, callback: CallbackQuery):
    """Handle back to search"""
    try:
        user_id = int(callback.data.split('_')[2])
        
        if callback.from_user.id != user_id:
            await callback.answer("❌ This is not for you!", show_alert=True)
            return
        
        user_data = user_cache.get(user_id)
        if not user_data or user_data.get('type') != 'search':
            await callback.answer("❌ Search expired!", show_alert=True)
            return
        
        search_key = user_data.get('search_key')
        search_data = search_cache.get(search_key)
        
        if not search_data:
            await callback.answer("❌ Search expired!", show_alert=True)
            return
        
        page = user_data.get('page', 0)
        
        # Show search results
        await callback.message.edit_caption(
            caption=f"**🔍 Search Results**\n\n"
                   f"**Query:** `{search_data['query']}`\n"
                   f"**Results:** `{len(search_data['results'])} videos found`\n\n"
                   f"Select a video to download:\n\n"
                   f"Don't forget to visit @AviaxOfficial",
            reply_markup=create_search_buttons(search_data['results'], user_id, page)
        )
        
        await callback.answer()
        
    except Exception as e:
        print(f"Back search error: {e}")
        await callback.answer("❌ Error occurred!", show_alert=True)

@app.on_callback_query(filters.regex(r'^page_'))
async def handle_pagination(client: Client, callback: CallbackQuery):
    """Handle search pagination"""
    try:
        _, page, user_id = callback.data.split('_')
        page = int(page)
        user_id = int(user_id)
        
        if callback.from_user.id != user_id:
            await callback.answer("❌ This is not for you!", show_alert=True)
            return
        
        user_data = user_cache.get(user_id)
        if not user_data or user_data.get('type') != 'search':
            await callback.answer("❌ Search expired!", show_alert=True)
            return
        
        # Update page in cache
        user_cache[user_id]['page'] = page
        
        search_key = user_data.get('search_key')
        search_data = search_cache.get(search_key)
        
        if not search_data:
            await callback.answer("❌ Search expired!", show_alert=True)
            return
        
        # Update message with new page
        await callback.message.edit_reply_markup(
            reply_markup=create_search_buttons(search_data['results'], user_id, page)
        )
        
        await callback.answer(f"Page {page + 1}")
        
    except Exception as e:
        print(f"Pagination error: {e}")
        await callback.answer("❌ Error occurred!", show_alert=True)

@app.on_callback_query(filters.regex(r'^close_'))
async def handle_close(client: Client, callback: CallbackQuery):
    """Handle close button"""
    try:
        user_id = int(callback.data.split('_')[1])
        
        if callback.from_user.id != user_id:
            await callback.answer("❌ This is not for you!", show_alert=True)
            return
        
        await callback.message.delete()
        await callback.answer("Closed")
        
    except Exception as e:
        print(f"Close error: {e}")
        await callback.answer("Closed")

@app.on_callback_query(filters.regex(r'^noop$'))
async def handle_noop(client: Client, callback: CallbackQuery):
    """Handle no-operation button"""
    await callback.answer()

async def cleanup_cache():
    """Regular cache cleanup"""
    while True:
        await asyncio.sleep(3600)  # Clean every hour
        current_time = asyncio.get_event_loop().time()
        
        # Clean old search cache
        expired_keys = []
        for key, data in search_cache.items():
            if current_time - data.get('timestamp', 0) > 3600:  # 1 hour
                expired_keys.append(key)
        
        for key in expired_keys:
            del search_cache[key]
        
        # Clean old user cache
        expired_users = []
        for user_id in list(user_cache.keys()):
            # Keep only recent users (last 30 minutes)
            # You might want to implement timestamp tracking for user_cache
            pass
        
        print(f"Cache cleanup: Removed {len(expired_keys)} search entries")

# Start cleanup task
async def start_cleanup():
    global cleanup_task
    cleanup_task = asyncio.create_task(cleanup_cache())

# Initialize cleanup
@app.on_startup()
async def startup():
    await start_cleanup()

@app.on_shutdown()
async def shutdown():
    if cleanup_task:
        cleanup_task.cancel()

print("✅ YouTube Downloader Inline System Loaded Successfully!")