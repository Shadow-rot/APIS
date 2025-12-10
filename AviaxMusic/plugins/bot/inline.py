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
    InlineQueryResultPhoto,
    InputTextMessageContent,
    CallbackQuery,
)

import config
from AviaxMusic import app

# Cache storage
download_cache: Dict[str, dict] = {}
search_cache: Dict[str, dict] = {}

# Progress animations
FRAMES = ["⬇️", "⏬", "📥", "💾", "⬆️", "⏫", "📤", "☁️"]


def is_youtube_url(url: str) -> bool:
    """Validate YouTube URL"""
    return bool(re.match(
        r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})',
        url
    ))


def extract_video_id(url: str) -> Optional[str]:
    """Extract video ID from YouTube URL"""
    if not url:
        return None
    
    parsed = urlparse(url)
    
    if parsed.hostname in ['www.youtube.com', 'youtube.com', 'm.youtube.com']:
        if parsed.path == '/watch':
            return parse_qs(parsed.query).get('v', [None])[0]
        elif parsed.path.startswith(('/embed/', '/v/')):
            return parsed.path.split('/')[2]
    elif parsed.hostname == 'youtu.be':
        return parsed.path[1:]
    
    match = re.search(r'(?:v=|/)([0-9A-Za-z_-]{11})', url)
    return match.group(1) if match else None


def format_size(bytes_size: int) -> str:
    """Format bytes to human readable"""
    if not bytes_size:
        return "Unknown"
    
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} TB"


async def search_youtube(query: str, max_results: int = 10) -> Optional[List[dict]]:
    """Search YouTube via py_yt"""
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
                'thumbnail': video.get('thumbnails', [{}])[0].get('url', '').split('?')[0],
                'channel': video.get('channel', {}).get('name', 'Unknown'),
                'views': video.get('viewCount', {}).get('short', ''),
            })
        
        return videos
    except Exception as e:
        print(f"Search error: {e}")
        return None


async def get_video_info(video_url: str) -> Optional[dict]:
    """Get video info via py_yt"""
    try:
        from py_yt import VideosSearch
        
        video_url = video_url.split("&")[0] if "&" in video_url else video_url
        
        results_search = VideosSearch(video_url, limit=1)
        results = await results_search.next()
        
        if not results.get('result'):
            return None
        
        video = results['result'][0]
        
        return {
            'video_id': video.get('id'),
            'title': video.get('title'),
            'duration': video.get('duration'),
            'thumbnail': video.get('thumbnails', [{}])[0].get('url', '').split('?')[0],
            'channel': video.get('channel', {}).get('name', 'Unknown'),
            'views': video.get('viewCount', {}).get('short', ''),
        }
    except Exception as e:
        print(f"Info error: {e}")
        return None


async def download_from_api(video_id: str, media_type: str = "song", max_retries: int = 15) -> Optional[str]:
    """Download from API with retry logic"""
    try:
        # Get API URL and KEY from config
        base_url = getattr(config, 'VIDEO_API_URL', config.API_URL) if media_type == "video" else config.API_URL
        api_key = getattr(config, 'API_KEY', None)
        
        api_endpoint = f"{base_url}/{media_type}/{video_id}"
        if api_key:
            api_endpoint += f"?api={api_key}"
        
        download_folder = "downloads"
        os.makedirs(download_folder, exist_ok=True)
        
        # Check existing files
        for ext in ["mp3", "m4a", "webm", "mp4", "mkv"]:
            file_path = f"{download_folder}/{video_id}.{ext}"
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                return file_path
        
        async with aiohttp.ClientSession() as session:
            for attempt in range(max_retries):
                try:
                    async with session.get(api_endpoint, timeout=aiohttp.ClientTimeout(total=30)) as response:
                        if response.status != 200:
                            await asyncio.sleep(2)
                            continue
                        
                        data = await response.json()
                        status = data.get("status", "").lower()
                        
                        if status in ["done", "success"]:
                            download_url = data.get("link") or data.get("download_url") or data.get("url")
                            
                            if not download_url:
                                return None
                            
                            file_format = data.get("format", "mp3" if media_type == "song" else "mp4")
                            file_path = os.path.join(download_folder, f"{video_id}.{file_format}")
                            
                            async with session.get(download_url, timeout=aiohttp.ClientTimeout(total=600)) as file_resp:
                                if file_resp.status == 200:
                                    with open(file_path, 'wb') as f:
                                        async for chunk in file_resp.content.iter_chunked(8192):
                                            f.write(chunk)
                                    
                                    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                                        return file_path
                                return None
                        
                        elif status in ["downloading", "processing"]:
                            await asyncio.sleep(3 if media_type == "song" else 6)
                        
                        elif status in ["error", "failed"]:
                            return None
                        
                        else:
                            await asyncio.sleep(2)
                
                except asyncio.TimeoutError:
                    await asyncio.sleep(2)
                except Exception:
                    await asyncio.sleep(2)
            
            return None
    
    except Exception as e:
        print(f"Download error: {e}")
        return None


def create_quality_keyboard(video_id: str, user_id: int, back_to_search: bool = False) -> InlineKeyboardMarkup:
    """Create simplified quality selection keyboard"""
    buttons = [
        [InlineKeyboardButton("🎧 Audio (Best Quality)", callback_data=f"dl_audio_{video_id}_{user_id}")],
        [InlineKeyboardButton("🎬 Video 720p", callback_data=f"dl_video_720p_{video_id}_{user_id}")],
        [InlineKeyboardButton("🎬 Video 480p", callback_data=f"dl_video_480p_{video_id}_{user_id}")],
        [InlineKeyboardButton("🎬 Video 360p", callback_data=f"dl_video_360p_{video_id}_{user_id}")]
    ]
    
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
        duration = result.get('duration', '')
        
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


@app.on_inline_query()
async def inline_handler(client: Client, inline_query: InlineQuery):
    """Handle inline queries"""
    query = inline_query.query.strip()
    
    if not query:
        return await inline_query.answer(
            results=[InlineQueryResultArticle(
                title="🔍 YouTube Downloader",
                description="Search videos or paste URL",
                input_message_content=InputTextMessageContent(
                    "**🎵 YouTube Downloader**\n\n"
                    "**Usage:**\n"
                    "• Search: `@bot song name`\n"
                    "• URL: `@bot https://youtu.be/xxxxx`"
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
                    description="Cannot get video info",
                    input_message_content=InputTextMessageContent("❌ Failed to fetch video info")
                )],
                cache_time=1
            )
        
        video_id = extract_video_id(query)
        
        # Cache
        cache_key = f"{video_id}_{inline_query.from_user.id}"
        download_cache[cache_key] = {
            'url': f"https://www.youtube.com/watch?v={video_id}",
            'info': video_info,
            'user_id': inline_query.from_user.id
        }
        
        results = [InlineQueryResultPhoto(
            photo_url=video_info.get('thumbnail', 'https://i.imgur.com/7qKPdJK.png'),
            thumb_url=video_info.get('thumbnail', 'https://i.imgur.com/7qKPdJK.png'),
            title=f"📥 {video_info.get('title', 'Unknown')[:50]}",
            description=f"⏱ {video_info.get('duration', 'Unknown')} • {video_info.get('channel', 'Unknown')}",
            caption=(
                f"**📥 YouTube Downloader**\n\n"
                f"**🎵 Title:** `{video_info.get('title', 'Unknown')}`\n"
                f"**⏱ Duration:** `{video_info.get('duration', 'Unknown')}`\n"
                f"**👤 Channel:** `{video_info.get('channel', 'Unknown')}`\n\n"
                f"**Select format below:**"
            ),
            reply_markup=create_quality_keyboard(video_id, inline_query.from_user.id)
        )]
    else:
        # Search
        search_results = await search_youtube(query, max_results=15)
        
        if not search_results:
            return await inline_query.answer(
                results=[InlineQueryResultArticle(
                    title="❌ No results found",
                    description=f"No videos for: {query}",
                    input_message_content=InputTextMessageContent(f"❌ No results for: **{query}**")
                )],
                cache_time=1
            )
        
        # Cache search
        search_key = f"search_{inline_query.from_user.id}"
        search_cache[search_key] = {
            'query': query,
            'results': search_results,
            'user_id': inline_query.from_user.id
        }
        
        # Cache results
        for result in search_results:
            video_id = result.get('video_id', '')
            cache_key = f"{video_id}_{inline_query.from_user.id}"
            download_cache[cache_key] = {
                'url': f"https://www.youtube.com/watch?v={video_id}",
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
                description=f"⏱ {result.get('duration', '')} • {result.get('channel', '')}",
                caption=(
                    f"**🎵 {result.get('title', 'Unknown')}**\n\n"
                    f"**⏱ Duration:** `{result.get('duration', 'Unknown')}`\n"
                    f"**👤 Channel:** `{result.get('channel', 'Unknown')}`\n\n"
                    f"**Select format below:**"
                ),
                reply_markup=create_quality_keyboard(
                    result.get('video_id', ''),
                    inline_query.from_user.id,
                    back_to_search=True
                )
            ))
    
    await inline_query.answer(results=results, cache_time=300)


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
                f"**⏱ Duration:** `{info.get('duration', 'Unknown')}`\n"
                f"**👤 Channel:** `{info.get('channel', 'Unknown')}`\n\n"
                f"**Select format below:**"
            ),
            reply_markup=create_quality_keyboard(video_id, user_id, back_to_search=True)
        )
        await callback.answer()
    except Exception as e:
        await callback.answer("Error", show_alert=True)


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


@app.on_callback_query(filters.regex(r'^page_'))
async def page_callback(client: Client, callback: CallbackQuery):
    """Handle pagination"""
    data = callback.data.split('_')
    page = int(data[1])
    user_id = int(data[2])
    
    if callback.from_user.id != user_id:
        return await callback.answer("❌ Not for you!", show_alert=True)
    
    search_key = f"search_{user_id}"
    search_data = search_cache.get(search_key)
    
    if not search_data:
        return await callback.answer("❌ Search expired!", show_alert=True)
    
    try:
        await callback.message.edit_reply_markup(
            reply_markup=create_search_keyboard(search_data['results'], user_id, page)
        )
        await callback.answer(f"Page {page + 1}")
    except:
        await callback.answer("Error", show_alert=True)


@app.on_callback_query(filters.regex(r'^dl_'))
async def download_callback(client: Client, callback: CallbackQuery):
    """Handle download - FIXED"""
    data = callback.data.split('_')
    
    # Parse callback data
    if len(data) == 4:  # dl_audio_videoid_userid
        format_type = data[1]
        video_id = data[2]
        user_id = int(data[3])
        quality = "Best"
    elif len(data) == 5:  # dl_video_720p_videoid_userid
        format_type = data[1]
        quality = data[2]
        video_id = data[3]
        user_id = int(data[4])
    else:
        return await callback.answer("Invalid!", show_alert=True)
    
    if callback.from_user.id != user_id:
        return await callback.answer("❌ Not for you!", show_alert=True)
    
    cache_key = f"{video_id}_{user_id}"
    cached = download_cache.get(cache_key)
    
    if not cached:
        return await callback.answer("❌ Session expired!", show_alert=True)
    
    await callback.answer(f"⏳ Downloading {quality} {format_type}...")
    
    # Status message - FIX: Check if message exists
    status = None
    status_text = f"⬇️ **Downloading {quality} {format_type}...**\n\n`Please wait...`"
    
    try:
        if callback.message:
            if callback.message.photo:
                status = await callback.message.edit_caption(status_text)
            else:
                status = await callback.message.edit_text(status_text)
    except:
        # If edit fails, send new message
        if callback.message:
            status = await callback.message.reply_text(status_text)
    
    # Animate
    async def animate():
        for _ in range(3):
            for frame in FRAMES[:4]:
                try:
                    if status:
                        text = f"{frame} **Downloading {quality} {format_type}...**\n\n`Processing...`"
                        if hasattr(status, 'photo') and status.photo:
                            await status.edit_caption(text)
                        else:
                            await status.edit_text(text)
                    await asyncio.sleep(0.5)
                except:
                    pass
    
    anim_task = asyncio.create_task(animate())
    
    # Download
    try:
        media_type = "video" if format_type == "video" else "song"
        file_path = await download_from_api(video_id, media_type)
        
        anim_task.cancel()
        
        if not file_path or not os.path.exists(file_path):
            error_text = "❌ **Download failed!**\n\n`Please try again later.`"
            try:
                if status:
                    if hasattr(status, 'photo') and status.photo:
                        await status.edit_caption(error_text)
                    else:
                        await status.edit_text(error_text)
            except:
                pass
            return
        
        # Upload
        upload_text = f"⬆️ **Uploading {quality} {format_type}...**\n\n`Almost there...`"
        try:
            if status:
                if hasattr(status, 'photo') and status.photo:
                    await status.edit_caption(upload_text)
                else:
                    await status.edit_text(upload_text)
        except:
            pass
        
        title = cached['info'].get('title', 'download')
        file_size = os.path.getsize(file_path)
        
        caption = (
            f"**✅ Download Complete!**\n\n"
            f"**🎵 Title:** `{title}`\n"
            f"**📊 Quality:** `{quality} {format_type.upper()}`\n"
            f"**📦 Size:** `{format_size(file_size)}`\n\n"
            f"**Powered by:** @{(await app.get_me()).username}"
        )
        
        # Upload file - FIX: Check if message exists
        if callback.message:
            if format_type == "video":
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
        success_text = f"✅ **Successfully Uploaded!**\n\n`Thank you!`"
        try:
            if status:
                if hasattr(status, 'photo') and status.photo:
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
        error_text = f"❌ **Error occurred!**\n\n`{str(e)}`"
        try:
            if status:
                if hasattr(status, 'photo') and status.photo:
                    await status.edit_caption(error_text)
                else:
                    await status.edit_text(error_text)
        except:
            pass


@app.on_callback_query(filters.regex(r'^close_'))
async def close_callback(client: Client, callback: CallbackQuery):
    """Close message"""
    user_id = int(callback.data.split('_')[1])
    
    if callback.from_user.id != user_id:
        return await callback.answer("❌ Not for you!", show_alert=True)
    
    await callback.message.delete()
    await callback.answer("✅ Closed!")


@app.on_callback_query(filters.regex(r'^header$'))
async def header_callback(client: Client, callback: CallbackQuery):
    """Header button"""
    await callback.answer()


# Cache cleanup
async def cleanup_cache():
    """Clean cache every 30 minutes"""
    while True:
        await asyncio.sleep(1800)
        download_cache.clear()
        search_cache.clear()
        print("🧹 Cache cleaned")


asyncio.create_task(cleanup_cache())

print("✅ YouTube Inline Downloader Loaded!")