import asyncio
import os
import re
from typing import Dict, List, Optional
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
from AviaxMusic.utils.youtube import download_song, download_video

# Cache storage
download_cache: Dict[str, dict] = {}
search_cache: Dict[str, dict] = {}

# Progress animations
DOWNLOAD_FRAMES = ["⬇️", "⏬", "📥", "💾"]
UPLOAD_FRAMES = ["⬆️", "⏫", "📤", "☁️"]
SEARCH_FRAMES = ["🔍", "🔎", "🔦", "🔭"]


def is_youtube_url(url: str) -> bool:
    """Validate YouTube URL"""
    youtube_regex = (
        r'(https?://)?(www\.)?'
        '(youtube|youtu|youtube-nocookie)\.(com|be)/'
        '(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    )
    return bool(re.match(youtube_regex, url))


def extract_video_id(url: str) -> Optional[str]:
    """Extract video ID from various YouTube URL formats"""
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
    """Format seconds to HH:MM:SS or MM:SS"""
    if not seconds:
        return "Unknown"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_views(views: int) -> str:
    """Format view count to readable format"""
    if not views:
        return "Unknown"
    
    if views >= 1_000_000_000:
        return f"{views / 1_000_000_000:.1f}B"
    elif views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M"
    elif views >= 1_000:
        return f"{views / 1_000:.1f}K"
    return str(views)


def format_size(bytes_size: int) -> str:
    """Format bytes to human readable size"""
    if not bytes_size:
        return "Unknown"
    
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} TB"


async def search_youtube(query: str, max_results: int = 10) -> Optional[List[dict]]:
    """Search YouTube videos using API"""
    try:
        from py_yt import VideosSearch
        
        results_search = VideosSearch(query, limit=max_results)
        results = await results_search.next()
        
        videos = []
        for video in results.get('result', []):
            videos.append({
                'video_id': video.get('id'),
                'title': video.get('title'),
                'duration': video.get('duration'),
                'duration_formatted': video.get('duration'),
                'thumbnail': video.get('thumbnails', [{}])[0].get('url', '').split('?')[0],
                'channel': video.get('channel', {}).get('name', 'Unknown'),
                'views': video.get('viewCount', {}).get('text', ''),
                'views_formatted': video.get('viewCount', {}).get('short', ''),
            })
        
        return videos
    except Exception as e:
        print(f"Search error: {e}")
        return None


async def get_video_info(video_url: str) -> Optional[dict]:
    """Get video information"""
    try:
        from py_yt import VideosSearch
        
        if "&" in video_url:
            video_url = video_url.split("&")[0]
        
        results_search = VideosSearch(video_url, limit=1)
        results = await results_search.next()
        
        if not results.get('result'):
            return None
        
        video = results['result'][0]
        
        return {
            'video_id': video.get('id'),
            'title': video.get('title'),
            'duration': video.get('duration'),
            'duration_formatted': video.get('duration'),
            'thumbnail': video.get('thumbnails', [{}])[0].get('url', '').split('?')[0],
            'channel': video.get('channel', {}).get('name', 'Unknown'),
            'views': video.get('viewCount', {}).get('text', ''),
            'views_formatted': video.get('viewCount', {}).get('short', ''),
            'formats': {
                'video': [
                    {'quality': '720p'},
                    {'quality': '480p'},
                    {'quality': '360p'},
                ],
                'audio': [
                    {'quality': '320kbps'},
                    {'quality': '192kbps'},
                    {'quality': '128kbps'},
                ]
            }
        }
    except Exception as e:
        print(f"Info fetch error: {e}")
        return None


def create_quality_keyboard(video_id: str, user_id: int, back_to_search: bool = False) -> InlineKeyboardMarkup:
    """Create keyboard with quality options"""
    buttons = []
    
    # Video formats
    buttons.append([InlineKeyboardButton("━━━━ 📹 VIDEO ━━━━", callback_data="header")])
    buttons.append([
        InlineKeyboardButton("🎬 720p", callback_data=f"dl_video_720p_{video_id}_{user_id}"),
        InlineKeyboardButton("🎬 480p", callback_data=f"dl_video_480p_{video_id}_{user_id}")
    ])
    buttons.append([
        InlineKeyboardButton("🎬 360p", callback_data=f"dl_video_360p_{video_id}_{user_id}")
    ])
    
    # Audio formats
    buttons.append([InlineKeyboardButton("━━━━ 🎵 AUDIO ━━━━", callback_data="header")])
    buttons.append([
        InlineKeyboardButton("🎧 320kbps", callback_data=f"dl_audio_320kbps_{video_id}_{user_id}"),
        InlineKeyboardButton("🎧 192kbps", callback_data=f"dl_audio_192kbps_{video_id}_{user_id}")
    ])
    buttons.append([
        InlineKeyboardButton("🎧 128kbps", callback_data=f"dl_audio_128kbps_{video_id}_{user_id}")
    ])
    
    # Navigation
    nav_buttons = []
    if back_to_search:
        nav_buttons.append(InlineKeyboardButton("◀️ Back", callback_data=f"back_search_{user_id}"))
    nav_buttons.append(InlineKeyboardButton("❌ Close", callback_data=f"close_{user_id}"))
    buttons.append(nav_buttons)
    
    return InlineKeyboardMarkup(buttons)


def create_search_keyboard(results: List[dict], user_id: int, page: int = 0) -> InlineKeyboardMarkup:
    """Create search results keyboard"""
    buttons = []
    items_per_page = 8
    start = page * items_per_page
    end = start + items_per_page
    
    for result in results[start:end]:
        video_id = result.get('video_id', '')
        title = result.get('title', 'Unknown')[:40]
        duration = result.get('duration_formatted', '')
        
        button_text = f"▶️ {title}"
        if duration:
            button_text += f" • {duration}"
        
        buttons.append([InlineKeyboardButton(
            button_text,
            callback_data=f"select_{video_id}_{user_id}"
        )])
    
    # Pagination
    total_pages = (len(results) + items_per_page - 1) // items_per_page
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️", callback_data=f"page_{page-1}_{user_id}"))
        nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="header"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("➡️", callback_data=f"page_{page+1}_{user_id}"))
        buttons.append(nav)
    
    buttons.append([InlineKeyboardButton("❌ Close", callback_data=f"close_{user_id}")])
    
    return InlineKeyboardMarkup(buttons)


async def animate_progress(message: Message, frames: List[str], text: str):
    """Animate message with frames"""
    for frame in frames * 2:
        try:
            await message.edit_text(f"{frame} {text}")
            await asyncio.sleep(0.5)
        except:
            pass


# Inline query handler
@app.on_inline_query()
async def inline_handler(client: Client, inline_query: InlineQuery):
    """Handle inline queries"""
    query = inline_query.query.strip()
    
    if not query:
        return await inline_query.answer(
            results=[InlineQueryResultArticle(
                title="🔍 YouTube Downloader",
                description="Search videos or paste YouTube URL",
                input_message_content=InputTextMessageContent(
                    "**🎵 YouTube Downloader**\n\n"
                    "**Usage:**\n"
                    "• Search: `@bot_username song name`\n"
                    "• URL: `@bot_username https://youtu.be/xxxxx`"
                ),
                thumb_url="https://i.imgur.com/7qKPdJK.png"
            )],
            cache_time=1
        )
    
    # Check if URL
    if is_youtube_url(query):
        video_info = await get_video_info(query)
        
        if not video_info:
            return await inline_query.answer(
                results=[InlineQueryResultArticle(
                    title="❌ Failed to fetch video",
                    description="Cannot get video information",
                    input_message_content=InputTextMessageContent("Failed to fetch video info")
                )],
                cache_time=1
            )
        
        video_id = extract_video_id(query)
        
        # Store in cache
        cache_key = f"{video_id}_{inline_query.from_user.id}"
        download_cache[cache_key] = {
            'url': query,
            'info': video_info,
            'user_id': inline_query.from_user.id
        }
        
        results = [InlineQueryResultPhoto(
            photo_url=video_info.get('thumbnail', 'https://i.imgur.com/7qKPdJK.png'),
            thumb_url=video_info.get('thumbnail', 'https://i.imgur.com/7qKPdJK.png'),
            title=f"📥 {video_info.get('title', 'Unknown')[:50]}",
            description=f"⏱ {video_info.get('duration_formatted', 'Unknown')} • 👤 {video_info.get('channel', 'Unknown')}",
            caption=(
                f"**📥 YouTube Downloader**\n\n"
                f"**🎵 Title:** `{video_info.get('title', 'Unknown')}`\n"
                f"**⏱ Duration:** `{video_info.get('duration_formatted', 'Unknown')}`\n"
                f"**👤 Channel:** `{video_info.get('channel', 'Unknown')}`\n\n"
                f"**Select quality below:**"
            ),
            reply_markup=create_quality_keyboard(video_id, inline_query.from_user.id)
        )]
    else:
        # Search videos
        search_results = await search_youtube(query, max_results=15)
        
        if not search_results:
            return await inline_query.answer(
                results=[InlineQueryResultArticle(
                    title="❌ No results found",
                    description=f"No videos for: {query}",
                    input_message_content=InputTextMessageContent(f"No results for: **{query}**")
                )],
                cache_time=1
            )
        
        # Store search
        search_key = f"search_{inline_query.from_user.id}"
        search_cache[search_key] = {
            'query': query,
            'results': search_results,
            'user_id': inline_query.from_user.id
        }
        
        # Store individual results
        for result in search_results:
            video_id = result.get('video_id', '')
            cache_key = f"{video_id}_{inline_query.from_user.id}"
            download_cache[cache_key] = {
                'url': f"https://youtu.be/{video_id}",
                'info': result,
                'user_id': inline_query.from_user.id,
                'from_search': True
            }
        
        results = []
        for idx, result in enumerate(search_results[:10]):
            results.append(InlineQueryResultPhoto(
                photo_url=result.get('thumbnail', 'https://i.imgur.com/7qKPdJK.png'),
                thumb_url=result.get('thumbnail', 'https://i.imgur.com/7qKPdJK.png'),
                title=f"{idx+1}. {result.get('title', 'Unknown')[:45]}",
                description=f"⏱ {result.get('duration_formatted', '')} • {result.get('channel', '')}",
                caption=(
                    f"**🎵 {result.get('title', 'Unknown')}**\n\n"
                    f"**⏱ Duration:** `{result.get('duration_formatted', 'Unknown')}`\n"
                    f"**👤 Channel:** `{result.get('channel', 'Unknown')}`\n\n"
                    f"**Select quality:**"
                ),
                reply_markup=create_quality_keyboard(
                    result.get('video_id', ''),
                    inline_query.from_user.id,
                    back_to_search=True
                )
            ))
    
    await inline_query.answer(results=results, cache_time=300)


# Callback handlers
@app.on_callback_query(filters.regex(r'^select_'))
async def select_callback(client: Client, callback: CallbackQuery):
    """Handle video selection"""
    data = callback.data.split('_')
    video_id = data[1]
    user_id = int(data[2])
    
    if callback.from_user.id != user_id:
        return await callback.answer("❌ Not for you!", show_alert=True)
    
    cache_key = f"{video_id}_{user_id}"
    cached = download_cache.get(cache_key)
    
    if not cached:
        return await callback.answer("❌ Session expired!", show_alert=True)
    
    info = cached['info']
    
    try:
        await callback.message.delete()
        await callback.message.reply_photo(
            photo=info.get('thumbnail', 'https://i.imgur.com/7qKPdJK.png'),
            caption=(
                f"**📥 YouTube Downloader**\n\n"
                f"**🎵 Title:** `{info.get('title', 'Unknown')}`\n"
                f"**⏱ Duration:** `{info.get('duration_formatted', 'Unknown')}`\n"
                f"**👤 Channel:** `{info.get('channel', 'Unknown')}`\n\n"
                f"**Select quality:**"
            ),
            reply_markup=create_quality_keyboard(video_id, user_id, back_to_search=True)
        )
        await callback.answer()
    except Exception as e:
        await callback.answer("Error loading", show_alert=True)


@app.on_callback_query(filters.regex(r'^back_search_'))
async def back_callback(client: Client, callback: CallbackQuery):
    """Back to search results"""
    user_id = int(callback.data.split('_')[2])
    
    if callback.from_user.id != user_id:
        return await callback.answer("❌ Not for you!", show_alert=True)
    
    search_key = f"search_{user_id}"
    search_data = search_cache.get(search_key)
    
    if not search_data:
        return await callback.answer("❌ Search expired!", show_alert=True)
    
    try:
        await callback.message.delete()
        await callback.message.reply_text(
            f"**🔍 Search Results:** `{search_data['query']}`\n\n"
            f"**Found {len(search_data['results'])} videos:**",
            reply_markup=create_search_keyboard(search_data['results'], user_id, 0)
        )
        await callback.answer()
    except:
        await callback.answer("Error", show_alert=True)


@app.on_callback_query(filters.regex(r'^dl_'))
async def download_callback(client: Client, callback: CallbackQuery):
    """Handle download requests"""
    data = callback.data.split('_')
    
    if len(data) < 5:
        return await callback.answer("Invalid request!", show_alert=True)
    
    format_type = data[1]  # 'video' or 'audio'
    quality = data[2]
    video_id = data[3]
    user_id = int(data[4])
    
    if callback.from_user.id != user_id:
        return await callback.answer("❌ Not for you!", show_alert=True)
    
    cache_key = f"{video_id}_{user_id}"
    cached = download_cache.get(cache_key)
    
    if not cached:
        return await callback.answer("❌ Session expired!", show_alert=True)
    
    await callback.answer(f"⏳ Downloading {quality} {format_type}...")
    
    # Update message
    status_text = f"⬇️ **Downloading {quality} {format_type}...**\n\n`Please wait...`"
    
    try:
        if callback.message.photo:
            status = await callback.message.edit_caption(status_text)
        else:
            status = await callback.message.edit_text(status_text)
    except:
        status = await callback.message.reply_text(status_text)
    
    # Animate
    async def animate():
        for _ in range(3):
            for frame in DOWNLOAD_FRAMES:
                try:
                    text = f"{frame} **Downloading {quality} {format_type}...**\n\n`Processing...`"
                    if status.photo:
                        await status.edit_caption(text)
                    else:
                        await status.edit_text(text)
                    await asyncio.sleep(0.5)
                except:
                    pass
    
    anim_task = asyncio.create_task(animate())
    
    # Download
    try:
        if format_type == 'video':
            file_path = await download_video(cached['url'])
        else:
            file_path = await download_song(cached['url'])
        
        anim_task.cancel()
        
        if not file_path or not os.path.exists(file_path):
            error_text = "❌ **Download failed!**\n\n`Please try again.`"
            try:
                if status.photo:
                    await status.edit_caption(error_text)
                else:
                    await status.edit_text(error_text)
            except:
                pass
            return
        
        # Upload
        upload_text = f"⬆️ **Uploading {quality} {format_type}...**\n\n`Almost done...`"
        try:
            if status.photo:
                await status.edit_caption(upload_text)
            else:
                await status.edit_text(upload_text)
        except:
            pass
        
        title = cached['info'].get('title', 'download')
        caption = (
            f"**✅ Download Complete!**\n\n"
            f"**🎵 Title:** `{title}`\n"
            f"**📊 Quality:** `{quality} {format_type.upper()}`\n"
            f"**📦 Size:** `{format_size(os.path.getsize(file_path))}`\n\n"
            f"**Powered by:** @{(await app.get_me()).username}"
        )
        
        if format_type == 'video':
            await callback.message.reply_video(
                video=file_path,
                caption=caption,
                supports_streaming=True
            )
        else:
            await callback.message.reply_audio(
                audio=file_path,
                caption=caption,
                title=title
            )
        
        # Success
        success_text = f"✅ **Successfully Uploaded!**\n\n`Thank you for using!`"
        try:
            if status.photo:
                await status.edit_caption(success_text)
            else:
                await status.edit_text(success_text)
        except:
            pass
        
        # Cleanup
        try:
            os.remove(file_path)
        except:
            pass
        
    except Exception as e:
        anim_task.cancel()
        print(f"Download error: {e}")
        error_text = f"❌ **Error!**\n\n`{str(e)}`"
        try:
            if status.photo:
                await status.edit_caption(error_text)
            else:
                await status.edit_text(error_text)
        except:
            pass


@app.on_callback_query(filters.regex(r'^close_'))
async def close_callback(client: Client, callback: CallbackQuery):
    """Close button"""
    user_id = int(callback.data.split('_')[1])
    
    if callback.from_user.id != user_id:
        return await callback.answer("❌ Not for you!", show_alert=True)
    
    await callback.message.delete()
    await callback.answer("✅ Closed!")


@app.on_callback_query(filters.regex(r'^header$'))
async def header_callback(client: Client, callback: CallbackQuery):
    """Header button (no action)"""
    await callback.answer()


# Commands
@app.on_message(filters.command(['download', 'dl']) & filters.private)
async def download_command(client: Client, message: Message):
    """Download command"""
    if len(message.command) < 2:
        return await message.reply_text(
            "**📥 YouTube Downloader**\n\n"
            "**Usage:**\n"
            f"`/{message.command[0]} [YouTube URL or name]`\n\n"
            "**Example:**\n"
            f"`/{message.command[0]} https://youtu.be/xxxxx`"
        )
    
    query = " ".join(message.command[1:])
    
    if is_youtube_url(query):
        status = await message.reply_text("🔍 Fetching video info...")
        
        video_info = await get_video_info(query)
        
        if not video_info:
            return await status.edit_text("❌ Failed to fetch video!")
        
        video_id = extract_video_id(query)
        
        cache_key = f"{video_id}_{message.from_user.id}"
        download_cache[cache_key] = {
            'url': query,
            'info': video_info,
            'user_id': message.from_user.id
        }
        
        await status.delete()
        
        await message.reply_photo(
            photo=video_info.get('thumbnail', 'https://i.imgur.com/7qKPdJK.png'),
            caption=(
                f"**📥 YouTube Downloader**\n\n"
                f"**🎵 Title:** `{video_info.get('title', 'Unknown')}`\n"
                f"**⏱ Duration:** `{video_info.get('duration_formatted', 'Unknown')}`\n"
                f"**👤 Channel:** `{video_info.get('channel', 'Unknown')}`\n\n"
                f"**Select quality:**"
            ),
            reply_markup=create_quality_keyboard(video_id, message.from_user.id)
        )
    else:
        status = await message.reply_text("🔍 Searching...")
        
        results = await search_youtube(query, max_results=15)
        
        if not results:
            return await status.edit_text(f"❌ No results for: **{query}**")
        
        search_key = f"search_{message.from_user.id}"
        search_cache[search_key] = {
            'query': query,
            'results': results,
            'user_id': message.from_user.id
        }
        
        for result in results:
            video_id = result.get('video_id', '')
            cache_key = f"{video_id}_{message.from_user.id}"
            download_cache[cache_key] = {
                'url': f"https://youtu.be/{video_id}",
                'info': result,
                'user_id': message.from_user.id,
                'from_search': True
            }
        
        await status.edit_text(
            f"**🔍 Search Results:** `{query}`\n\n"
            f"**Found {len(results)} videos:**",
            reply_markup=create_search_keyboard(results, message.from_user.id, 0)
        )


# Cache cleanup
async def cleanup_cache():
    """Periodic cache cleanup"""
    while True:
        await asyncio.sleep(1800)  # 30 minutes
        download_cache.clear()
        search_cache.clear()
        print("🧹 Cache cleaned")


asyncio.create_task(cleanup_cache())

print("✅ YouTube Downloader Loaded!")