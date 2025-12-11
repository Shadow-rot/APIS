import asyncio
import os
from datetime import datetime, timedelta
from typing import Union

from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality

import config
from AviaxMusic import LOGGER, YouTube, app
from AviaxMusic.misc import db
from AviaxMusic.utils.database import (
    add_active_chat,
    add_active_video_chat,
    get_lang,
    get_loop,
    group_assistant,
    is_autoend,
    music_on,
    remove_active_chat,
    remove_active_video_chat,
    set_loop,
)
from AviaxMusic.utils.exceptions import AssistantErr
from AviaxMusic.utils.formatters import check_duration, seconds_to_min, speed_converter
from AviaxMusic.utils.inline.play import stream_markup
from AviaxMusic.utils.stream.autoclear import auto_clean
from AviaxMusic.utils.thumbnails import gen_thumb
from strings import get_string

autoend = {}
counter = {}


async def _clear_(chat_id):
    db[chat_id] = []
    await remove_active_video_chat(chat_id)
    await remove_active_chat(chat_id)


class Call:
    def __init__(self):
        # Initialize Pyrogram clients
        self.userbot1 = Client(
            name="AviaxAss1",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING1),
        ) if config.STRING1 else None
        
        self.userbot2 = Client(
            name="AviaxAss2",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING2),
        ) if config.STRING2 else None
        
        self.userbot3 = Client(
            name="AviaxAss3",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING3),
        ) if config.STRING3 else None
        
        self.userbot4 = Client(
            name="AviaxAss4",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING4),
        ) if config.STRING4 else None
        
        self.userbot5 = Client(
            name="AviaxAss5",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING5),
        ) if config.STRING5 else None

        # Initialize PyTgCalls instances
        self.one = PyTgCalls(self.userbot1) if self.userbot1 else None
        self.two = PyTgCalls(self.userbot2) if self.userbot2 else None
        self.three = PyTgCalls(self.userbot3) if self.userbot3 else None
        self.four = PyTgCalls(self.userbot4) if self.userbot4 else None
        self.five = PyTgCalls(self.userbot5) if self.userbot5 else None

    async def pause_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        await assistant.pause_stream(chat_id)

    async def resume_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        await assistant.resume_stream(chat_id)

    async def stop_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        try:
            await _clear_(chat_id)
            await assistant.leave_call(chat_id)
        except Exception as e:
            LOGGER(__name__).error(f"Error stopping stream: {e}")

    async def stop_stream_force(self, chat_id: int):
        """Force stop stream on all assistants"""
        for assistant in [self.one, self.two, self.three, self.four, self.five]:
            if assistant:
                try:
                    await assistant.leave_call(chat_id)
                except Exception as e:
                    LOGGER(__name__).error(f"Error in force stop: {e}")
        
        try:
            await _clear_(chat_id)
        except Exception as e:
            LOGGER(__name__).error(f"Error clearing data: {e}")

    async def speedup_stream(self, chat_id: int, file_path, speed, playing):
        assistant = await group_assistant(self, chat_id)
        
        if str(speed) != "1.0":
            base = os.path.basename(file_path)
            chatdir = os.path.join(os.getcwd(), "playback", str(speed))
            if not os.path.isdir(chatdir):
                os.makedirs(chatdir)
            out = os.path.join(chatdir, base)
            
            if not os.path.isfile(out):
                # Speed conversion mapping
                speed_map = {
                    "0.5": 2.0,
                    "0.75": 1.35,
                    "1.5": 0.68,
                    "2.0": 0.5
                }
                vs = speed_map.get(str(speed), 1.0)
                
                proc = await asyncio.create_subprocess_shell(
                    cmd=(
                        f"ffmpeg -i {file_path} "
                        f"-filter:v setpts={vs}*PTS "
                        f"-filter:a atempo={speed} "
                        f"{out}"
                    ),
                    stdin=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
        else:
            out = file_path
        
        dur = await asyncio.get_event_loop().run_in_executor(None, check_duration, out)
        dur = int(dur)
        played, con_seconds = speed_converter(playing[0]["played"], speed)
        duration = seconds_to_min(dur)
        
        if str(db[chat_id][0]["file"]) == str(file_path):
            # Use play method with MediaStream for PyTgCalls 2.x
            await assistant.play(
                chat_id,
                MediaStream(out)
            )
        else:
            raise AssistantErr("Umm")
        
        if str(db[chat_id][0]["file"]) == str(file_path):
            exis = (playing[0]).get("old_dur")
            if not exis:
                db[chat_id][0]["old_dur"] = db[chat_id][0]["dur"]
                db[chat_id][0]["old_second"] = db[chat_id][0]["seconds"]
            db[chat_id][0]["played"] = con_seconds
            db[chat_id][0]["dur"] = duration
            db[chat_id][0]["seconds"] = dur
            db[chat_id][0]["speed_path"] = out
            db[chat_id][0]["speed"] = speed

    async def force_stop_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        try:
            check = db.get(chat_id)
            if check:
                check.pop(0)
        except Exception as e:
            LOGGER(__name__).error(f"Error in force_stop_stream: {e}")
        
        await remove_active_video_chat(chat_id)
        await remove_active_chat(chat_id)
        
        try:
            await assistant.leave_call(chat_id)
        except Exception as e:
            LOGGER(__name__).error(f"Error leaving call: {e}")

    async def skip_stream(
        self,
        chat_id: int,
        link: str,
        video: Union[bool, str] = None,
        image: Union[bool, str] = None,
    ):
        assistant = await group_assistant(self, chat_id)
        
        if video:
            await assistant.play(
                chat_id,
                MediaStream(
                    link,
                    video_flags=VideoQuality.HD_720p
                )
            )
        else:
            await assistant.play(
                chat_id,
                MediaStream(link)
            )

    async def seek_stream(self, chat_id, file_path, to_seek, duration, mode):
        assistant = await group_assistant(self, chat_id)
        # PyTgCalls 2.x doesn't have built-in seek, need to restart with offset
        await assistant.play(
            chat_id,
            MediaStream(file_path)
        )

    async def stream_call(self, link):
        assistant = await group_assistant(self, config.LOG_GROUP_ID)
        await assistant.play(
            config.LOG_GROUP_ID,
            MediaStream(link)
        )
        await asyncio.sleep(0.2)
        await assistant.leave_call(config.LOG_GROUP_ID)

    async def join_call(
        self,
        chat_id: int,
        original_chat_id: int,
        link,
        video: Union[bool, str] = None,
        image: Union[bool, str] = None,
    ):
        assistant = await group_assistant(self, chat_id)
        language = await get_lang(chat_id)
        _ = get_string(language)
        
        try:
            if video:
                await assistant.play(
                    chat_id,
                    MediaStream(
                        link,
                        video_flags=VideoQuality.HD_720p,
                        audio_flags=AudioQuality.STUDIO
                    )
                )
            else:
                await assistant.play(
                    chat_id,
                    MediaStream(link)
                )
        except Exception as e:
            error_msg = str(e).lower()
            if "no active" in error_msg or "not found" in error_msg:
                raise AssistantErr(_["call_8"])
            elif "already" in error_msg or "joined" in error_msg:
                raise AssistantErr(_["call_9"])
            else:
                raise AssistantErr(_["call_10"])
        
        await add_active_chat(chat_id)
        await music_on(chat_id)
        
        if video:
            await add_active_video_chat(chat_id)
        
        if await is_autoend():
            counter[chat_id] = {}
            try:
                users = len(await assistant.get_participants(chat_id))
                if users == 1:
                    autoend[chat_id] = datetime.now() + timedelta(minutes=1)
            except Exception as e:
                LOGGER(__name__).error(f"Error getting participants: {e}")

    async def change_stream(self, client, chat_id):
        check = db.get(chat_id)
        popped = None
        loop = await get_loop(chat_id)
        
        try:
            if loop == 0:
                popped = check.pop(0)
            else:
                loop = loop - 1
                await set_loop(chat_id, loop)
            
            await auto_clean(popped)
            
            if not check:
                await _clear_(chat_id)
                return await client.leave_call(chat_id)
        except Exception as e:
            LOGGER(__name__).error(f"Error in change_stream: {e}")
            try:
                await _clear_(chat_id)
                return await client.leave_call(chat_id)
            except:
                return
        else:
            queued = check[0]["file"]
            language = await get_lang(chat_id)
            _ = get_string(language)
            title = (check[0]["title"]).title()
            user = check[0]["by"]
            original_chat_id = check[0]["chat_id"]
            streamtype = check[0]["streamtype"]
            videoid = check[0]["vidid"]
            db[chat_id][0]["played"] = 0
            
            exis = (check[0]).get("old_dur")
            if exis:
                db[chat_id][0]["dur"] = exis
                db[chat_id][0]["seconds"] = check[0]["old_second"]
                db[chat_id][0]["speed_path"] = None
                db[chat_id][0]["speed"] = 1.0
            
            video = True if str(streamtype) == "video" else False
            
            if "live_" in queued:
                n, link = await YouTube.video(videoid, True)
                if n == 0:
                    return await app.send_message(
                        original_chat_id,
                        text=_["call_6"],
                    )
                
                try:
                    if video:
                        await client.play(
                            chat_id,
                            MediaStream(
                                link,
                                video_flags=VideoQuality.HD_720p
                            )
                        )
                    else:
                        await client.play(chat_id, MediaStream(link))
                except Exception:
                    return await app.send_message(
                        original_chat_id,
                        text=_["call_6"],
                    )
                
                img = await gen_thumb(videoid)
                button = stream_markup(_, chat_id)
                run = await app.send_photo(
                    chat_id=original_chat_id,
                    photo=img,
                    caption=_["stream_1"].format(
                        f"https://t.me/{app.username}?start=info_{videoid}",
                        title[:23],
                        check[0]["dur"],
                        user,
                    ),
                    reply_markup=InlineKeyboardMarkup(button),
                )
                db[chat_id][0]["mystic"] = run
                db[chat_id][0]["markup"] = "tg"
                
            elif "vid_" in queued:
                mystic = await app.send_message(original_chat_id, _["call_7"])
                try:
                    file_path, direct = await YouTube.download(
                        videoid,
                        mystic,
                        videoid=True,
                        video=True if str(streamtype) == "video" else False,
                    )
                except:
                    return await mystic.edit_text(
                        _["call_6"], disable_web_page_preview=True
                    )
                
                try:
                    if video:
                        await client.play(
                            chat_id,
                            MediaStream(
                                file_path,
                                video_flags=VideoQuality.HD_720p
                            )
                        )
                    else:
                        await client.play(chat_id, MediaStream(file_path))
                except:
                    return await app.send_message(
                        original_chat_id,
                        text=_["call_6"],
                    )
                
                img = await gen_thumb(videoid)
                button = stream_markup(_, chat_id)
                await mystic.delete()
                run = await app.send_photo(
                    chat_id=original_chat_id,
                    photo=img,
                    caption=_["stream_1"].format(
                        f"https://t.me/{app.username}?start=info_{videoid}",
                        title[:23],
                        check[0]["dur"],
                        user,
                    ),
                    reply_markup=InlineKeyboardMarkup(button),
                )
                db[chat_id][0]["mystic"] = run
                db[chat_id][0]["markup"] = "stream"
                
            elif "index_" in queued:
                try:
                    await client.play(chat_id, MediaStream(videoid))
                except:
                    return await app.send_message(
                        original_chat_id,
                        text=_["call_6"],
                    )
                
                button = stream_markup(_, chat_id)
                run = await app.send_photo(
                    chat_id=original_chat_id,
                    photo=config.STREAM_IMG_URL,
                    caption=_["stream_2"].format(user),
                    reply_markup=InlineKeyboardMarkup(button),
                )
                db[chat_id][0]["mystic"] = run
                db[chat_id][0]["markup"] = "tg"
                
            else:
                try:
                    if video:
                        await client.play(
                            chat_id,
                            MediaStream(
                                queued,
                                video_flags=VideoQuality.HD_720p
                            )
                        )
                    else:
                        await client.play(chat_id, MediaStream(queued))
                except:
                    return await app.send_message(
                        original_chat_id,
                        text=_["call_6"],
                    )
                
                if videoid == "telegram":
                    button = stream_markup(_, chat_id)
                    run = await app.send_photo(
                        chat_id=original_chat_id,
                        photo=config.TELEGRAM_AUDIO_URL
                        if str(streamtype) == "audio"
                        else config.TELEGRAM_VIDEO_URL,
                        caption=_["stream_1"].format(
                            config.SUPPORT_GROUP, title[:23], check[0]["dur"], user
                        ),
                        reply_markup=InlineKeyboardMarkup(button),
                    )
                    db[chat_id][0]["mystic"] = run
                    db[chat_id][0]["markup"] = "tg"
                elif videoid == "soundcloud":
                    button = stream_markup(_, chat_id)
                    run = await app.send_photo(
                        chat_id=original_chat_id,
                        photo=config.SOUNCLOUD_IMG_URL,
                        caption=_["stream_1"].format(
                            config.SUPPORT_GROUP, title[:23], check[0]["dur"], user
                        ),
                        reply_markup=InlineKeyboardMarkup(button),
                    )
                    db[chat_id][0]["mystic"] = run
                    db[chat_id][0]["markup"] = "tg"
                else:
                    img = await gen_thumb(videoid)
                    button = stream_markup(_, chat_id)
                    run = await app.send_photo(
                        chat_id=original_chat_id,
                        photo=img,
                        caption=_["stream_1"].format(
                            f"https://t.me/{app.username}?start=info_{videoid}",
                            title[:23],
                            check[0]["dur"],
                            user,
                        ),
                        reply_markup=InlineKeyboardMarkup(button),
                    )
                    db[chat_id][0]["mystic"] = run
                    db[chat_id][0]["markup"] = "stream"

    async def ping(self):
        """Get average ping from all active PyTgCalls clients"""
        pings = []
        
        assistants = [
            (config.STRING1, self.one, "Assistant 1"),
            (config.STRING2, self.two, "Assistant 2"),
            (config.STRING3, self.three, "Assistant 3"),
            (config.STRING4, self.four, "Assistant 4"),
            (config.STRING5, self.five, "Assistant 5"),
        ]
        
        for config_string, client, name in assistants:
            if config_string and client:
                try:
                    # ping is a property in PyTgCalls 2.x, not a coroutine
                    ping_value = client.ping
                    if ping_value and ping_value > 0:
                        pings.append(ping_value)
                except Exception as e:
                    LOGGER(__name__).warning(f"{name} ping error: {e}")
                    continue
        
        if not pings:
            return "0.0"
        
        avg_ping = sum(pings) / len(pings)
        return str(round(avg_ping, 3))

    async def start(self):
        """Start all PyTgCalls clients"""
        LOGGER(__name__).info("Starting PyTgCalls Clients...\n")
        
        clients = [
            (config.STRING1, self.one, "Assistant 1"),
            (config.STRING2, self.two, "Assistant 2"),
            (config.STRING3, self.three, "Assistant 3"),
            (config.STRING4, self.four, "Assistant 4"),
            (config.STRING5, self.five, "Assistant 5"),
        ]
        
        for config_string, client, name in clients:
            if config_string and client:
                try:
                    await client.start()
                    LOGGER(__name__).info(f"{name} started successfully")
                except Exception as e:
                    LOGGER(__name__).error(f"Failed to start {name}: {e}")

    async def decorators(self):
        """
        PyTgCalls 2.x uses different event handling.
        You should handle stream_end events manually through decorators
        or by registering handlers after initialization.
        """
        pass


Aviax = Call()