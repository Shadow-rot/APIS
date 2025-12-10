import asyncio
import os
import re
from typing import Dict, Optional
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

# Cache
cache: Dict[str, dict] = {}

def extract_video_id(url: str) -> Optional[str]:
    """Extract video ID from YouTube URL"""
    if not url:
        return None
    match = re.search(r'(?:v=|/)([0-9A-Za-z_-]{11})', url)
    return match.group(1) if match else None

def format_size(size: int) -> str:
    """Format bytes"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"

async def search_youtube(query: str, limit: int = 10):
    """Search YouTube"""
    try:
        from py_yt import VideosSearch
        search = VideosSearch(query, limit=limit)
        results = await search.next()
        videos = []
        for v in results.get('result', []):
            videos.append({
                'id': v.get('id'),
                'title': v.get('title'),
                'duration': v.get('duration'),
                'thumb': v.get('thumbnails', [{}])[0].get('url', '').split('?')[0],
                'channel': v.get('channel', {}).get('name', 'Unknown'),
            })
        return videos
    except:
        return None

async def get_video_info(url: str):
    """Get video info"""
    try:
        from py_yt import VideosSearch
        search = VideosSearch(url.split("&")[0], limit=1)
        results = await search.next()
        if not results.get('result'):
            return None
        v = results['result'][0]
        return {
            'id': v.get('id'),
            'title': v.get('title'),
            'duration': v.get('duration'),
            'thumb': v.get('thumbnails', [{}])[0].get('url', '').split('?')[0],
            'channel': v.get('channel', {}).get('name', 'Unknown'),
        }
    except:
        return None

async def download_file(video_id: str, is_video: bool = False) -> Optional[str]:
    """Download from API"""
    try:
        media = "video" if is_video else "song"
        api_url = getattr(config, 'VIDEO_API_URL' if is_video else 'API_URL', config.API_URL)
        api_key = getattr(config, 'API_KEY', '')
        
        url = f"{api_url}/{media}/{video_id}"
        if api_key:
            url += f"?api={api_key}"
        
        os.makedirs("downloads", exist_ok=True)
        
        # Check existing
        for ext in ['mp3', 'm4a', 'mp4', 'webm']:
            path = f"downloads/{video_id}.{ext}"
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return path
        
        async with aiohttp.ClientSession() as session:
            for _ in range(12):
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=25)) as resp:
                        if resp.status != 200:
                            await asyncio.sleep(2)
                            continue
                        
                        data = await resp.json()
                        status = data.get("status", "").lower()
                        
                        if status in ["done", "success"]:
                            dl_url = data.get("link") or data.get("download_url") or data.get("url")
                            if not dl_url:
                                return None
                            
                            fmt = data.get("format", "mp3" if not is_video else "mp4")
                            path = f"downloads/{video_id}.{fmt}"
                            
                            async with session.get(dl_url, timeout=aiohttp.ClientTimeout(total=500)) as file_resp:
                                if file_resp.status == 200:
                                    with open(path, 'wb') as f:
                                        async for chunk in file_resp.content.iter_chunked(16384):
                                            f.write(chunk)
                                    
                                    if os.path.exists(path) and os.path.getsize(path) > 0:
                                        return path
                            return None
                        
                        elif status in ["downloading", "processing"]:
                            await asyncio.sleep(2)
                        elif status in ["error", "failed"]:
                            return None
                        else:
                            await asyncio.sleep(2)
                except:
                    await asyncio.sleep(2)
        return None
    except:
        return None

def make_buttons(video_id: str, user_id: int, back: bool = False):
    """Create buttons"""
    btns = [
        [InlineKeyboardButton("🎧 Audio", callback_data=f"audio_{video_id}_{user_id}")],
        [InlineKeyboardButton("🎬 720p", callback_data=f"video_720_{video_id}_{user_id}"),
         InlineKeyboardButton("🎬 480p", callback_data=f"video_480_{video_id}_{user_id}")],
        [InlineKeyboardButton("🎬 360p", callback_data=f"video_360_{video_id}_{user_id}")]
    ]
    nav = []
    if back:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"back_{user_id}"))
    nav.append(InlineKeyboardButton("✖️", callback_data=f"close_{user_id}"))
    btns.append(nav)
    return InlineKeyboardMarkup(btns)

def make_search_buttons(results, user_id: int, page: int = 0):
    """Create search buttons"""
    btns = []
    per_page = 8
    start = page * per_page
    end = start + per_page
    
    for r in results[start:end]:
        vid = r.get('id', '')
        title = r.get('title', 'Unknown')[:35]
        dur = r.get('duration', '')
        text = f"▶️ {title}"
        if dur:
            text += f" • {dur}"
        btns.append([InlineKeyboardButton(text, callback_data=f"sel_{vid}_{user_id}")])
    
    total = (len(results) + per_page - 1) // per_page
    if total > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️", callback_data=f"pg_{page-1}_{user_id}"))
        nav.append(InlineKeyboardButton(f"{page+1}/{total}", callback_data="x"))
        if page < total - 1:
            nav.append(InlineKeyboardButton("➡️", callback_data=f"pg_{page+1}_{user_id}"))
        btns.append(nav)
    
    btns.append([InlineKeyboardButton("✖️", callback_data=f"close_{user_id}")])
    return InlineKeyboardMarkup(btns)

@app.on_inline_query()
async def inline_handler(client: Client, query: InlineQuery):
    """Handle inline"""
    q = query.query.strip()
    
    if not q:
        return await query.answer(
            results=[InlineQueryResultArticle(
                title="🔍 YouTube Downloader",
                description="Search or paste URL",
                input_message_content=InputTextMessageContent(
                    "**🎵 YouTube Downloader**\n\n"
                    "Search: `@bot song name`\n"
                    "URL: `@bot https://youtu.be/xxxxx`"
                ),
                thumb_url="https://i.imgur.com/7qKPdJK.png"
            )],
            cache_time=1
        )
    
    # URL
    if 'youtu' in q:
        info = await get_video_info(q)
        if not info:
            return await query.answer(
                results=[InlineQueryResultArticle(
                    title="❌ Failed",
                    description="Cannot get video",
                    input_message_content=InputTextMessageContent("❌ Failed")
                )],
                cache_time=1
            )
        
        vid = extract_video_id(q)
        cache[f"{vid}_{query.from_user.id}"] = {'info': info, 'uid': query.from_user.id}
        
        return await query.answer([InlineQueryResultPhoto(
            photo_url=info.get('thumb', 'https://i.imgur.com/7qKPdJK.png'),
            thumb_url=info.get('thumb', 'https://i.imgur.com/7qKPdJK.png'),
            title=f"📥 {info.get('title', 'Unknown')[:50]}",
            description=f"⏱ {info.get('duration', '')} • {info.get('channel', '')}",
            caption=f"**📥 {info.get('title', 'Unknown')}**\n\n**⏱** `{info.get('duration', 'Unknown')}`\n**👤** `{info.get('channel', 'Unknown')}`\n\n**Select format:**",
            reply_markup=make_buttons(vid, query.from_user.id)
        )], cache_time=300)
    
    # Search
    results = await search_youtube(q, 15)
    if not results:
        return await query.answer(
            results=[InlineQueryResultArticle(
                title="❌ No results",
                description=f"Nothing found for: {q}",
                input_message_content=InputTextMessageContent(f"❌ No results: **{q}**")
            )],
            cache_time=1
        )
    
    cache[f"search_{query.from_user.id}"] = {'q': q, 'results': results, 'uid': query.from_user.id}
    
    for r in results:
        vid = r.get('id', '')
        cache[f"{vid}_{query.from_user.id}"] = {'info': r, 'uid': query.from_user.id, 'search': True}
    
    out = []
    for i, r in enumerate(results[:10]):
        out.append(InlineQueryResultPhoto(
            photo_url=r.get('thumb', 'https://i.imgur.com/7qKPdJK.png'),
            thumb_url=r.get('thumb', 'https://i.imgur.com/7qKPdJK.png'),
            title=f"{i+1}. {r.get('title', 'Unknown')[:40]}",
            description=f"⏱ {r.get('duration', '')} • {r.get('channel', '')}",
            caption=f"**🎵 {r.get('title', 'Unknown')}**\n\n**⏱** `{r.get('duration', 'Unknown')}`\n**👤** `{r.get('channel', 'Unknown')}`\n\n**Select format:**",
            reply_markup=make_buttons(r.get('id', ''), query.from_user.id, True)
        ))
    
    await query.answer(out, cache_time=300)

@app.on_callback_query(filters.regex(r'^sel_'))
async def select_cb(client: Client, cb: CallbackQuery):
    """Select video"""
    _, vid, uid = cb.data.split('_')
    uid = int(uid)
    
    if cb.from_user.id != uid:
        return await cb.answer("❌ Not yours!", show_alert=True)
    
    key = f"{vid}_{uid}"
    data = cache.get(key)
    
    if not data:
        return await cb.answer("❌ Expired!", show_alert=True)
    
    info = data['info']
    
    try:
        await cb.message.delete()
        await cb.message.reply_photo(
            photo=info.get('thumb', 'https://i.imgur.com/7qKPdJK.png'),
            caption=f"**📥 {info.get('title', 'Unknown')}**\n\n**⏱** `{info.get('duration', 'Unknown')}`\n**👤** `{info.get('channel', 'Unknown')}`\n\n**Select format:**",
            reply_markup=make_buttons(vid, uid, True)
        )
        await cb.answer()
    except:
        await cb.answer("Error", show_alert=True)

@app.on_callback_query(filters.regex(r'^back_'))
async def back_cb(client: Client, cb: CallbackQuery):
    """Back to search"""
    uid = int(cb.data.split('_')[1])
    
    if cb.from_user.id != uid:
        return await cb.answer("❌ Not yours!", show_alert=True)
    
    key = f"search_{uid}"
    data = cache.get(key)
    
    if not data:
        return await cb.answer("❌ Expired!", show_alert=True)
    
    try:
        await cb.message.delete()
        await cb.message.reply_text(
            f"**🔍 Results:** `{data['q']}`\n\n**Found {len(data['results'])} videos**",
            reply_markup=make_search_buttons(data['results'], uid, 0)
        )
        await cb.answer()
    except:
        await cb.answer("Error")

@app.on_callback_query(filters.regex(r'^pg_'))
async def page_cb(client: Client, cb: CallbackQuery):
    """Pagination"""
    _, page, uid = cb.data.split('_')
    page = int(page)
    uid = int(uid)
    
    if cb.from_user.id != uid:
        return await cb.answer("❌ Not yours!", show_alert=True)
    
    key = f"search_{uid}"
    data = cache.get(key)
    
    if not data:
        return await cb.answer("❌ Expired!", show_alert=True)
    
    try:
        await cb.message.edit_reply_markup(make_search_buttons(data['results'], uid, page))
        await cb.answer(f"Page {page + 1}")
    except:
        await cb.answer("Error")

@app.on_callback_query(filters.regex(r'^(audio|video)_'))
async def download_cb(client: Client, cb: CallbackQuery):
    """Download handler"""
    parts = cb.data.split('_')
    
    if len(parts) == 3:  # audio_vid_uid
        fmt, vid, uid = parts
        uid = int(uid)
        quality = "Best"
        is_video = False
    elif len(parts) == 4:  # video_720_vid_uid
        fmt, quality, vid, uid = parts
        uid = int(uid)
        is_video = True
    else:
        return await cb.answer("❌ Invalid!", show_alert=True)
    
    if cb.from_user.id != uid:
        return await cb.answer("❌ Not yours!", show_alert=True)
    
    key = f"{vid}_{uid}"
    data = cache.get(key)
    
    if not data:
        return await cb.answer("❌ Expired!", show_alert=True)
    
    await cb.answer(f"⏳ Downloading {quality}...")
    
    msg = None
    try:
        msg = await cb.message.reply_text(f"⬇️ **Downloading...**\n\n`Please wait...`")
    except:
        try:
            msg = await cb.message.edit_text(f"⬇️ **Downloading...**\n\n`Please wait...`")
        except:
            pass
    
    # Download
    try:
        file = await download_file(vid, is_video)
        
        if not file or not os.path.exists(file):
            if msg:
                try:
                    await msg.edit_text("❌ **Download failed!**\n\n`Try again later`")
                except:
                    pass
            return
        
        # Upload
        if msg:
            try:
                await msg.edit_text(f"⬆️ **Uploading...**\n\n`Almost done...`")
            except:
                pass
        
        title = data['info'].get('title', 'Download')
        size = os.path.getsize(file)
        
        cap = (
            f"**✅ Complete!**\n\n"
            f"**🎵** `{title}`\n"
            f"**📊** `{quality} {fmt.upper()}`\n"
            f"**📦** `{format_size(size)}`"
        )
        
        # Send file
        if is_video:
            await cb.message.reply_video(video=file, caption=cap, supports_streaming=True)
        else:
            await cb.message.reply_audio(audio=file, caption=cap, title=title)
        
        if msg:
            try:
                await msg.edit_text("✅ **Done!**")
            except:
                pass
        
        # Cleanup
        try:
            os.remove(file)
        except:
            pass
        
    except Exception as e:
        print(f"Error: {e}")
        if msg:
            try:
                await msg.edit_text(f"❌ **Error!**\n\n`{str(e)[:100]}`")
            except:
                pass

@app.on_callback_query(filters.regex(r'^close_'))
async def close_cb(client: Client, cb: CallbackQuery):
    """Close"""
    try:
        uid = int(cb.data.split('_')[1])
        if cb.from_user.id != uid:
            return await cb.answer("❌ Not yours!", show_alert=True)
    except:
        pass
    
    try:
        await cb.message.delete()
        await cb.answer("✅ Closed")
    except Exception as e:
        print(f"Close error: {e}")
        await cb.answer("✅")

@app.on_callback_query(filters.regex(r'^x$'))
async def dummy_cb(client: Client, cb: CallbackQuery):
    """Dummy"""
    await cb.answer()

# Cleanup
async def cleanup():
    while True:
        await asyncio.sleep(1800)
        cache.clear()

asyncio.create_task(cleanup())

print("✅ YouTube Downloader Loaded!")