import asyncio
import os
import re
from typing import Dict, Optional, List

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

# Simple caches
cache: Dict[str, dict] = {}
download_cache: Dict[str, str] = {}

def extract_video_id(url: str) -> Optional[str]:
    """Extract video ID from YouTube URL"""
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

async def search_youtube(query: str, limit: int = 15) -> Optional[List[dict]]:
    """Search YouTube videos"""
    try:
        # Try using py_yt first
        from py_yt import VideosSearch
        
        search = VideosSearch(query, limit=limit)
        results = await search.next()
        
        videos = []
        for v in results.get('result', []):
            videos.append({
                'id': v.get('id'),
                'title': v.get('title', 'Unknown')[:100],
                'duration': v.get('duration', '0:00'),
                'thumb': v.get('thumbnails', [{}])[0].get('url', '').split('?')[0],
                'channel': v.get('channel', {}).get('name', 'Unknown')[:50],
            })
        return videos[:limit]
        
    except:
        # Fallback to alternative API
        try:
            api_url = f"https://www.youtube.com/results?search_query={query}"
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url) as resp:
                    html = await resp.text()
                    
                    # Extract video info from HTML
                    pattern = r'"videoId":"([A-Za-z0-9_-]{11})".*?"title":"(.*?)".*?"thumbnail":"(.*?)".*?"lengthText":"(.*?)".*?"ownerText":"(.*?)"'
                    matches = re.findall(pattern, html)
                    
                    videos = []
                    for match in matches[:limit]:
                        vid, title, thumb, duration, channel = match
                        # Clean up title
                        title = title.replace('\\', '')
                        thumb = thumb.replace('\\', '').replace('"', '')
                        
                        videos.append({
                            'id': vid,
                            'title': title[:100],
                            'duration': duration,
                            'thumb': thumb if thumb.startswith('http') else f"https://img.youtube.com/vi/{vid}/hqdefault.jpg",
                            'channel': channel[:50],
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
        
        # Check cache
        cache_key = f"info_{video_id}"
        if cache_key in cache:
            return cache[cache_key]
        
        # Try py_yt
        try:
            from py_yt import VideosSearch
            search = VideosSearch(f"https://youtu.be/{video_id}", limit=1)
            results = await search.next()
            
            if results.get('result'):
                v = results['result'][0]
                info = {
                    'id': video_id,
                    'title': v.get('title', 'Unknown')[:100],
                    'duration': v.get('duration', '0:00'),
                    'thumb': v.get('thumbnails', [{}])[0].get('url', '').split('?')[0],
                    'channel': v.get('channel', {}).get('name', 'Unknown')[:50],
                }
                cache[cache_key] = info
                return info
        except:
            pass
        
        # Fallback to oEmbed API
        try:
            async with aiohttp.ClientSession() as session:
                oembed_url = f"https://www.youtube.com/oembed?url=https://youtu.be/{video_id}&format=json"
                async with session.get(oembed_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        info = {
                            'id': video_id,
                            'title': data.get('title', 'Unknown')[:100],
                            'duration': 'Unknown',
                            'thumb': f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
                            'channel': data.get('author_name', 'Unknown')[:50],
                        }
                        cache[cache_key] = info
                        return info
        except:
            pass
        
        return None
        
    except Exception as e:
        print(f"Video info error: {e}")
        return None

async def download_from_api(video_id: str, is_video: bool = False, quality: str = None) -> Optional[str]:
    """Download from API service"""
    try:
        # Check if already downloaded
        ext = "mp4" if is_video else "mp3"
        quality_str = quality if quality else "audio"
        file_key = f"{video_id}_{quality_str}"
        
        if file_key in download_cache:
            filepath = download_cache[file_key]
            if os.path.exists(filepath):
                return filepath
        
        # Use config API
        media_type = "video" if is_video else "song"
        api_url = getattr(config, 'VIDEO_API_URL' if is_video else 'API_URL', config.API_URL)
        api_key = getattr(config, 'API_KEY', '')
        
        url = f"{api_url}/{media_type}/{video_id}"
        if api_key:
            url += f"?api={api_key}"
        
        # Create downloads directory
        os.makedirs("downloads", exist_ok=True)
        
        # Try to download
        async with aiohttp.ClientSession() as session:
            for attempt in range(3):
                try:
                    async with session.get(url, timeout=30) as resp:
                        if resp.status != 200:
                            await asyncio.sleep(2)
                            continue
                        
                        data = await resp.json()
                        status = data.get("status", "").lower()
                        
                        if status in ["done", "success", "completed"]:
                            # Get download link
                            dl_url = data.get("link") or data.get("download_url") or data.get("url")
                            if not dl_url:
                                return None
                            
                            # Download file
                            filename = f"{video_id}_{quality_str}.{ext}"
                            filepath = f"downloads/{filename}"
                            
                            async with session.get(dl_url, timeout=300) as file_resp:
                                if file_resp.status == 200:
                                    with open(filepath, 'wb') as f:
                                        async for chunk in file_resp.content.iter_chunked(8192):
                                            f.write(chunk)
                                    
                                    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                                        download_cache[file_key] = filepath
                                        return filepath
                            
                        elif status in ["downloading", "processing", "converting"]:
                            await asyncio.sleep(3)
                        else:
                            await asyncio.sleep(2)
                            
                except Exception as e:
                    print(f"Download attempt {attempt + 1} failed: {e}")
                    await asyncio.sleep(2)
        
        return None
        
    except Exception as e:
        print(f"API download error: {e}")
        return None

def create_buttons(video_id: str, user_id: int, from_search: bool = False):
    """Create format selection buttons"""
    buttons = [
        [InlineKeyboardButton("🎧 Audio MP3", callback_data=f"audio_{video_id}_{user_id}")],
        [
            InlineKeyboardButton("🎬 720p", callback_data=f"video_720_{video_id}_{user_id}"),
            InlineKeyboardButton("🎬 480p", callback_data=f"video_480_{video_id}_{user_id}")
        ],
        [
            InlineKeyboardButton("🎬 360p", callback_data=f"video_360_{video_id}_{user_id}"),
            InlineKeyboardButton("🎬 240p", callback_data=f"video_240_{video_id}_{user_id}")
        ]
    ]
    
    if from_search:
        buttons.append([
            InlineKeyboardButton("🔙 Back to Results", callback_data=f"back_{user_id}")
        ])
    
    buttons.append([
        InlineKeyboardButton("❌ Close", callback_data=f"close_{user_id}")
    ])
    
    return InlineKeyboardMarkup(buttons)

def create_search_buttons(results: List[dict], user_id: int, page: int = 0):
    """Create search result buttons"""
    buttons = []
    per_page = 8
    start = page * per_page
    end = start + per_page
    
    for result in results[start:end]:
        title = result['title']
        if len(title) > 35:
            title = title[:32] + "..."
        dur = result['duration']
        btn_text = f"🎵 {title} ({dur})"
        buttons.append([
            InlineKeyboardButton(
                btn_text,
                callback_data=f"sel_{result['id']}_{user_id}"
            )
        ])
    
    # Navigation
    total_pages = (len(results) + per_page - 1) // per_page
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️", callback_data=f"page_{page-1}_{user_id}"))
        
        nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
        
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("▶️", callback_data=f"page_{page+1}_{user_id}"))
        
        buttons.append(nav_buttons)
    
    buttons.append([
        InlineKeyboardButton("❌ Close", callback_data=f"close_{user_id}")
    ])
    
    return InlineKeyboardMarkup(buttons)

@app.on_inline_query()
async def inline_handler(client: Client, query: InlineQuery):
    """Handle inline queries"""
    try:
        q = query.query.strip()
        
        if not q:
            # Show help
            await query.answer(
                results=[
                    InlineQueryResultArticle(
                        title="🎵 YouTube Downloader",
                        description="Search songs or paste YouTube URL",
                        input_message_content=InputTextMessageContent(
                            "**🎵 YouTube Downloader**\n\n"
                            "Search songs: `@bot song name`\n"
                            "Download from URL: `@bot https://youtube.com/...`\n\n"
                            "Don't forget to visit @AviaxOfficial"
                        ),
                        thumb_url="https://i.imgur.com/7qKPdJK.png",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("📢 Channel", url="https://t.me/AviaxOfficial")]
                        ])
                    )
                ],
                cache_time=300
            )
            return
        
        # Check if it's a URL
        if 'youtu' in q:
            # Get video info
            info = await get_video_info(q)
            if not info:
                await query.answer(
                    results=[],
                    cache_time=1,
                    switch_pm_text="Video not found",
                    switch_pm_parameter="help"
                )
                return
            
            # Store in cache
            cache[f"{info['id']}_{query.from_user.id}"] = {
                'info': info,
                'type': 'direct'
            }
            
            # Return result
            await query.answer(
                results=[
                    InlineQueryResultPhoto(
                        photo_url=info['thumb'],
                        thumb_url=info['thumb'],
                        title=f"📥 {info['title'][:50]}",
                        description=f"⏱ {info['duration']} • {info['channel'][:30]}",
                        caption=(
                            f"**📥 {info['title']}**\n\n"
                            f"**⏱ Duration:** `{info['duration']}`\n"
                            f"**👤 Channel:** `{info['channel']}`\n\n"
                            f"**Select format below:**\n\n"
                            f"Don't forget to visit @AviaxOfficial"
                        ),
                        reply_markup=create_buttons(info['id'], query.from_user.id)
                    )
                ],
                cache_time=300
            )
            
        else:
            # Search query
            results = await search_youtube(q, 20)
            if not results:
                await query.answer(
                    results=[],
                    cache_time=1,
                    switch_pm_text="No results found",
                    switch_pm_parameter="help"
                )
                return
            
            # Cache search results
            cache[f"search_{query.from_user.id}"] = {
                'query': q,
                'results': results,
                'page': 0
            }
            
            # Cache each video info
            for r in results:
                cache[f"{r['id']}_{query.from_user.id}"] = {
                    'info': r,
                    'type': 'search'
                }
            
            # Create inline results
            inline_results = []
            for result in results[:10]:
                inline_results.append(
                    InlineQueryResultPhoto(
                        photo_url=result['thumb'],
                        thumb_url=result['thumb'],
                        title=f"🎵 {result['title'][:40]}",
                        description=f"⏱ {result['duration']} • {result['channel'][:30]}",
                        caption=(
                            f"**🎵 {result['title']}**\n\n"
                            f"**⏱ Duration:** `{result['duration']}`\n"
                            f"**👤 Channel:** `{result['channel']}`\n\n"
                            f"**Select format below:**\n\n"
                            f"Don't forget to visit @AviaxOfficial"
                        ),
                        reply_markup=create_buttons(result['id'], query.from_user.id, from_search=True)
                    )
                )
            
            await query.answer(
                inline_results,
                cache_time=300
            )
            
    except Exception as e:
        print(f"Inline error: {e}")
        await query.answer(
            results=[],
            cache_time=1,
            switch_pm_text="Error occurred",
            switch_pm_parameter="help"
        )

@app.on_callback_query(filters.regex(r'^sel_'))
async def select_video(client: Client, callback: CallbackQuery):
    """Select video from search results"""
    try:
        _, video_id, user_id = callback.data.split('_')
        user_id = int(user_id)
        
        if callback.from_user.id != user_id:
            await callback.answer("❌ Not yours!", show_alert=True)
            return
        
        # Get video info from cache
        key = f"{video_id}_{user_id}"
        data = cache.get(key)
        
        if not data:
            await callback.answer("❌ Expired! Search again.", show_alert=True)
            return
        
        info = data['info']
        
        # Edit the message
        if hasattr(callback.message, 'photo') and callback.message.photo:
            await callback.message.edit_caption(
                caption=(
                    f"**📥 {info['title']}**\n\n"
                    f"**⏱ Duration:** `{info['duration']}`\n"
                    f"**👤 Channel:** `{info['channel']}`\n\n"
                    f"**Select format below:**\n\n"
                    f"Don't forget to visit @AviaxOfficial"
                ),
                reply_markup=create_buttons(video_id, user_id, from_search=True)
            )
        else:
            await callback.message.edit_text(
                text=(
                    f"**📥 {info['title']}**\n\n"
                    f"**⏱ Duration:** `{info['duration']}`\n"
                    f"**👤 Channel:** `{info['channel']}`\n\n"
                    f"**Select format below:**\n\n"
                    f"Don't forget to visit @AviaxOfficial"
                ),
                reply_markup=create_buttons(video_id, user_id, from_search=True)
            )
        
        await callback.answer()
        
    except Exception as e:
        print(f"Select error: {e}")
        await callback.answer("❌ Error occurred!", show_alert=True)

@app.on_callback_query(filters.regex(r'^(audio|video)_'))
async def download_handler(client: Client, callback: CallbackQuery):
    """Handle download requests"""
    try:
        parts = callback.data.split('_')
        
        if len(parts) == 3:  # audio_vid_user
            fmt, video_id, user_id = parts
            user_id = int(user_id)
            is_video = False
            quality = "320kbps"
        elif len(parts) == 4:  # video_quality_vid_user
            fmt, quality, video_id, user_id = parts
            user_id = int(user_id)
            is_video = True
        else:
            await callback.answer("❌ Invalid request!", show_alert=True)
            return
        
        if callback.from_user.id != user_id:
            await callback.answer("❌ Not yours!", show_alert=True)
            return
        
        # Get video info
        key = f"{video_id}_{user_id}"
        data = cache.get(key)
        
        if not data:
            await callback.answer("❌ Expired! Search again.", show_alert=True)
            return
        
        info = data['info']
        
        # Update message to show downloading
        await callback.answer(f"⏳ Downloading {quality}...")
        
        try:
            if hasattr(callback.message, 'photo') and callback.message.photo:
                await callback.message.edit_caption(
                    caption=(
                        f"**⬇️ Downloading...**\n\n"
                        f"**Title:** `{info['title'][:50]}`\n"
                        f"**Format:** `{'Video' if is_video else 'Audio'} {quality}`\n\n"
                        f"⏳ Please wait...\n\n"
                        f"Don't forget to visit @AviaxOfficial"
                    ),
                    reply_markup=None
                )
            else:
                await callback.message.edit_text(
                    text=(
                        f"**⬇️ Downloading...**\n\n"
                        f"**Title:** `{info['title'][:50]}`\n"
                        f"**Format:** `{'Video' if is_video else 'Audio'} {quality}`\n\n"
                        f"⏳ Please wait...\n\n"
                        f"Don't forget to visit @AviaxOfficial"
                    ),
                    reply_markup=None
                )
        except:
            pass
        
        # Download file
        file_path = await download_from_api(video_id, is_video, quality if is_video else None)
        
        if not file_path or not os.path.exists(file_path):
            # Show error
            try:
                if hasattr(callback.message, 'photo') and callback.message.photo:
                    await callback.message.edit_caption(
                        caption=(
                            f"**❌ Download Failed!**\n\n"
                            f"**Title:** `{info['title'][:50]}`\n\n"
                            f"Try again or select another format.\n\n"
                            f"Don't forget to visit @AviaxOfficial"
                        ),
                        reply_markup=create_buttons(video_id, user_id, from_search=True)
                    )
                else:
                    await callback.message.edit_text(
                        text=(
                            f"**❌ Download Failed!**\n\n"
                            f"**Title:** `{info['title'][:50]}`\n\n"
                            f"Try again or select another format.\n\n"
                            f"Don't forget to visit @AviaxOfficial"
                        ),
                        reply_markup=create_buttons(video_id, user_id, from_search=True)
                    )
            except:
                pass
            return
        
        # Get file size
        file_size = os.path.getsize(file_path)
        
        # Update message to show uploading
        try:
            if hasattr(callback.message, 'photo') and callback.message.photo:
                await callback.message.edit_caption(
                    caption=(
                        f"**⬆️ Uploading...**\n\n"
                        f"**Title:** `{info['title'][:50]}`\n"
                        f"**Format:** `{'Video' if is_video else 'Audio'} {quality}`\n"
                        f"**Size:** `{format_size(file_size)}`\n\n"
                        f"⏳ Please wait...\n\n"
                        f"Don't forget to visit @AviaxOfficial"
                    ),
                    reply_markup=None
                )
            else:
                await callback.message.edit_text(
                    text=(
                        f"**⬆️ Uploading...**\n\n"
                        f"**Title:** `{info['title'][:50]}`\n"
                        f"**Format:** `{'Video' if is_video else 'Audio'} {quality}`\n"
                        f"**Size:** `{format_size(file_size)}`\n\n"
                        f"⏳ Please wait...\n\n"
                        f"Don't forget to visit @AviaxOfficial"
                    ),
                    reply_markup=None
                )
        except:
            pass
        
        # Send the file
        try:
            if is_video:
                await client.send_video(
                    chat_id=callback.message.chat.id,
                    video=file_path,
                    caption=(
                        f"**✅ Download Complete!**\n\n"
                        f"**🎬 Title:** `{info['title']}`\n"
                        f"**📊 Quality:** `{quality}`\n"
                        f"**📦 Size:** `{format_size(file_size)}`\n"
                        f"**⏱ Duration:** `{info['duration']}`\n\n"
                        f"Don't forget to visit @AviaxOfficial"
                    ),
                    supports_streaming=True,
                    reply_to_message_id=callback.message.id
                )
            else:
                await client.send_audio(
                    chat_id=callback.message.chat.id,
                    audio=file_path,
                    caption=(
                        f"**✅ Download Complete!**\n\n"
                        f"**🎵 Title:** `{info['title']}`\n"
                        f"**📊 Quality:** `{quality}`\n"
                        f"**📦 Size:** `{format_size(file_size)}`\n"
                        f"**⏱ Duration:** `{info['duration']}`\n\n"
                        f"Don't forget to visit @AviaxOfficial"
                    ),
                    title=info['title'][:64],
                    performer=info['channel'][:32],
                    reply_to_message_id=callback.message.id
                )
            
            # Update original message to show success
            try:
                if hasattr(callback.message, 'photo') and callback.message.photo:
                    await callback.message.edit_caption(
                        caption=(
                            f"**✅ Download Complete!**\n\n"
                            f"**Title:** `{info['title'][:50]}`\n"
                            f"**Format:** `{'Video' if is_video else 'Audio'} {quality}`\n"
                            f"**Size:** `{format_size(file_size)}`\n\n"
                            f"✅ File sent successfully!\n\n"
                            f"Don't forget to visit @AviaxOfficial"
                        ),
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("📢 Channel", url="https://t.me/AviaxOfficial")],
                            [InlineKeyboardButton("🔄 Download More", switch_inline_query_current_chat="")]
                        ])
                    )
                else:
                    await callback.message.edit_text(
                        text=(
                            f"**✅ Download Complete!**\n\n"
                            f"**Title:** `{info['title'][:50]}`\n"
                            f"**Format:** `{'Video' if is_video else 'Audio'} {quality}`\n"
                            f"**Size:** `{format_size(file_size)}`\n\n"
                            f"✅ File sent successfully!\n\n"
                            f"Don't forget to visit @AviaxOfficial"
                        ),
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("📢 Channel", url="https://t.me/AviaxOfficial")],
                            [InlineKeyboardButton("🔄 Download More", switch_inline_query_current_chat="")]
                        ])
                    )
            except:
                pass
            
        except Exception as e:
            print(f"Upload error: {e}")
            try:
                if hasattr(callback.message, 'photo') and callback.message.photo:
                    await callback.message.edit_caption(
                        caption=(
                            f"**❌ Upload Failed!**\n\n"
                            f"**Title:** `{info['title'][:50]}`\n\n"
                            f"Error: `{str(e)[:100]}`\n\n"
                            f"Try again later.\n\n"
                            f"Don't forget to visit @AviaxOfficial"
                        ),
                        reply_markup=create_buttons(video_id, user_id, from_search=True)
                    )
                else:
                    await callback.message.edit_text(
                        text=(
                            f"**❌ Upload Failed!**\n\n"
                            f"**Title:** `{info['title'][:50]}`\n\n"
                            f"Error: `{str(e)[:100]}`\n\n"
                            f"Try again later.\n\n"
                            f"Don't forget to visit @AviaxOfficial"
                        ),
                        reply_markup=create_buttons(video_id, user_id, from_search=True)
                    )
            except:
                pass
        
        # Cleanup file
        try:
            os.remove(file_path)
        except:
            pass
        
    except Exception as e:
        print(f"Download handler error: {e}")
        await callback.answer("❌ Error occurred!", show_alert=True)

@app.on_callback_query(filters.regex(r'^back_'))
async def back_to_search(client: Client, callback: CallbackQuery):
    """Go back to search results"""
    try:
        user_id = int(callback.data.split('_')[1])
        
        if callback.from_user.id != user_id:
            await callback.answer("❌ Not yours!", show_alert=True)
            return
        
        # Get search results from cache
        key = f"search_{user_id}"
        data = cache.get(key)
        
        if not data:
            await callback.answer("❌ Search expired!", show_alert=True)
            return
        
        # Show search results
        if hasattr(callback.message, 'photo') and callback.message.photo:
            await callback.message.edit_caption(
                caption=(
                    f"**🔍 Search Results**\n\n"
                    f"**Query:** `{data['query']}`\n"
                    f"**Results:** `{len(data['results'])} videos found`\n\n"
                    f"Select a video to download:\n\n"
                    f"Don't forget to visit @AviaxOfficial"
                ),
                reply_markup=create_search_buttons(data['results'], user_id, data['page'])
            )
        else:
            await callback.message.edit_text(
                text=(
                    f"**🔍 Search Results**\n\n"
                    f"**Query:** `{data['query']}`\n"
                    f"**Results:** `{len(data['results'])} videos found`\n\n"
                    f"Select a video to download:\n\n"
                    f"Don't forget to visit @AviaxOfficial"
                ),
                reply_markup=create_search_buttons(data['results'], user_id, data['page'])
            )
        
        await callback.answer()
        
    except Exception as e:
        print(f"Back error: {e}")
        await callback.answer("❌ Error occurred!", show_alert=True)

@app.on_callback_query(filters.regex(r'^page_'))
async def page_handler(client: Client, callback: CallbackQuery):
    """Handle pagination"""
    try:
        _, page, user_id = callback.data.split('_')
        page = int(page)
        user_id = int(user_id)
        
        if callback.from_user.id != user_id:
            await callback.answer("❌ Not yours!", show_alert=True)
            return
        
        # Get search results from cache
        key = f"search_{user_id}"
        data = cache.get(key)
        
        if not data:
            await callback.answer("❌ Search expired!", show_alert=True)
            return
        
        # Update page in cache
        data['page'] = page
        cache[key] = data
        
        # Update message with new page
        await callback.message.edit_reply_markup(
            create_search_buttons(data['results'], user_id, page)
        )
        
        await callback.answer(f"Page {page + 1}")
        
    except Exception as e:
        print(f"Page error: {e}")
        await callback.answer("❌ Error occurred!", show_alert=True)

@app.on_callback_query(filters.regex(r'^close_'))
async def close_handler(client: Client, callback: CallbackQuery):
    """Close the message"""
    try:
        user_id = int(callback.data.split('_')[1])
        
        if callback.from_user.id != user_id:
            await callback.answer("❌ Not yours!", show_alert=True)
            return
        
        await callback.message.delete()
        await callback.answer("✅ Closed")
        
    except Exception as e:
        print(f"Close error: {e}")
        await callback.answer("✅")

@app.on_callback_query(filters.regex(r'^noop$'))
async def noop_handler(client: Client, callback: CallbackQuery):
    """Handle no-operation button"""
    await callback.answer()

print("✅ YouTube Downloader Inline System Loaded!")